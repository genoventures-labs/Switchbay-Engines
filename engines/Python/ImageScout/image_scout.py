#!/usr/bin/env python3
"""Image Scout — vision input preparation for Switchbay.

Turns a local image path or public HTTP(S) URL into reliable, model-friendly
artifacts: metadata, normalized images, overlapping detail tiles, optional OCR,
task-specific inspection prompts, and provider-native base64 payload files.

No model API is called. URL inputs are downloaded directly; private-network
targets are blocked unless explicitly allowed.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import ipaddress
import json
import math
import mimetypes
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from PIL import Image, ImageOps, ImageStat, UnidentifiedImageError
except ImportError:  # surfaced cleanly by doctor / CLI
    Image = ImageOps = ImageStat = None  # type: ignore
    UnidentifiedImageError = Exception  # type: ignore


DATA_DIR = Path(os.environ.get("SWITCHBAY_IMAGE_SCOUT_DIR", Path.home() / ".switchbay" / "image-scout"))
DOWNLOAD_DIR = DATA_DIR / "downloads"
ARTIFACT_DIR = DATA_DIR / "artifacts"
PAYLOAD_DIR = DATA_DIR / "payloads"
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
UA = "Switchbay-Image-Scout/1.0"
SUPPORTED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "BMP", "TIFF"}
OUTPUT_FORMATS = {"jpeg": ("JPEG", "image/jpeg", ".jpg"), "png": ("PNG", "image/png", ".png"), "webp": ("WEBP", "image/webp", ".webp")}


def _noneish(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return None if text.lower() in {"", "none", "null"} else text


def _parse_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    text = _noneish(value)
    if text is None:
        return default
    try:
        return max(minimum, min(int(float(text)), maximum))
    except (TypeError, ValueError):
        return default


def _parse_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    text = _noneish(value)
    if text is None:
        return default
    try:
        return max(minimum, min(float(text), maximum))
    except (TypeError, ValueError):
        return default


def _choice(value: Any, default: str, allowed: Iterable[str]) -> str:
    text = _noneish(value)
    return text if text in set(allowed) else default


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_pillow() -> None:
    if Image is None:
        raise RuntimeError("Pillow is required. Install it with: python3 -m pip install Pillow")


def _ensure_dirs() -> None:
    for directory in (DOWNLOAD_DIR, ARTIFACT_DIR, PAYLOAD_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def _json_safe(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_url(source: str) -> bool:
    return urllib.parse.urlparse(source).scheme.lower() in {"http", "https"}


def _validate_public_host(hostname: str, allow_private_url: bool) -> None:
    if allow_private_url:
        return
    if not hostname:
        raise ValueError("URL is missing a hostname.")
    if hostname.lower() == "localhost":
        raise ValueError("Private or loopback URLs are blocked. Use --allow_private_url only for trusted targets.")
    try:
        addresses = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve URL hostname: {hostname}") from exc
    for entry in addresses:
        ip = ipaddress.ip_address(entry[4][0].split("%", 1)[0])
        if not ip.is_global:
            raise ValueError(f"URL resolves to non-public address {ip}. Use --allow_private_url only for trusted targets.")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, allow_private_url: bool):
        super().__init__()
        self.allow_private_url = allow_private_url

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        parsed = urllib.parse.urlparse(newurl)
        if parsed.scheme.lower() not in {"http", "https"}:
            raise ValueError("Redirected to a non-HTTP URL.")
        _validate_public_host(parsed.hostname or "", self.allow_private_url)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download(source: str, allow_private_url: bool, max_bytes: int = MAX_DOWNLOAD_BYTES) -> Path:
    parsed = urllib.parse.urlparse(source)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("Only http:// and https:// image URLs are supported.")
    if parsed.username or parsed.password:
        raise ValueError("Credential-bearing URLs are not accepted.")
    _validate_public_host(parsed.hostname or "", allow_private_url)
    _ensure_dirs()
    request = urllib.request.Request(source, headers={"User-Agent": UA, "Accept": "image/*"})
    opener = urllib.request.build_opener(_SafeRedirect(allow_private_url))
    with opener.open(request, timeout=25) as response:
        declared = response.headers.get("Content-Length")
        if declared and int(declared) > max_bytes:
            raise ValueError(f"Remote image exceeds the {max_bytes} byte limit.")
        content_type = response.headers.get_content_type().lower()
        if not content_type.startswith("image/") and content_type != "application/octet-stream":
            raise ValueError(f"URL did not return an image content type: {content_type}")
        suffix = mimetypes.guess_extension(content_type) or Path(parsed.path).suffix or ".img"
        target = DOWNLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
        total = 0
        with target.open("wb") as output:
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    output.close()
                    target.unlink(missing_ok=True)
                    raise ValueError(f"Remote image exceeds the {max_bytes} byte limit.")
                output.write(chunk)
    return target


def _resolve_source(source: str, allow_private_url: bool = False) -> Tuple[Path, Dict[str, Any]]:
    if not source or not source.strip():
        raise ValueError("source must not be empty.")
    if _is_url(source):
        path = _download(source, allow_private_url)
        return path, {"kind": "url", "source": source, "downloaded_path": str(path)}
    path = Path(source).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")
    if not path.is_file():
        raise ValueError(f"Image source is not a file: {path}")
    return path, {"kind": "local", "source": str(path)}


def _open_image(path: Path):
    _require_pillow()
    try:
        image = Image.open(path)
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"Unsupported or invalid image: {path}") from exc
    if (image.format or "").upper() not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported image format: {image.format or 'unknown'}")
    return image


def _orientation_label(width: int, height: int) -> str:
    ratio = width / max(height, 1)
    if ratio > 1.12:
        return "landscape"
    if ratio < 0.89:
        return "portrait"
    return "square"


def _detail_advice(width: int, height: int, file_bytes: int) -> Dict[str, Any]:
    megapixels = width * height / 1_000_000
    long_edge = max(width, height)
    dense = megapixels >= 4 or long_edge >= 2600
    return {
        "suggested_detail": "high" if dense else "auto",
        "suggested_strategy": "overview_then_tiles" if dense else "single_normalized_image",
        "reason": "Large images benefit from a global pass followed by overlapping detail crops." if dense else "The full image should retain enough detail in one normalized pass.",
        "megapixels": round(megapixels, 2),
        "large_file": file_bytes > 8 * 1024 * 1024,
    }


def inspect_image(source: str, allow_private_url: bool = False, include_exif: bool = False) -> Dict[str, Any]:
    """Inspect a local or remote image without calling a model."""
    path, origin = _resolve_source(source, allow_private_url)
    image = _open_image(path)
    width, height = image.size
    frame_count = int(getattr(image, "n_frames", 1))
    exif = image.getexif()
    result: Dict[str, Any] = {
        "source": origin,
        "path": str(path),
        "format": image.format,
        "mime_type": Image.MIME.get(image.format, mimetypes.guess_type(path.name)[0] or "application/octet-stream"),
        "width": width,
        "height": height,
        "aspect_ratio": round(width / max(height, 1), 4),
        "orientation": _orientation_label(width, height),
        "mode": image.mode,
        "has_alpha": image.mode in {"RGBA", "LA"} or "transparency" in image.info,
        "animated": bool(getattr(image, "is_animated", False)),
        "frame_count": frame_count,
        "file_bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "exif_present": bool(exif),
        "advice": _detail_advice(width, height, path.stat().st_size),
    }
    if include_exif:
        result["exif"] = {str(key): _json_safe(value) for key, value in exif.items()}
    return result


def _flatten(image, background: str = "white"):
    if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
        rgba = image.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, background)
        bg.alpha_composite(rgba)
        return bg.convert("RGB")
    return image.convert("RGB")


def _save_image(image, target: Path, output_format: str, quality: int) -> None:
    fmt, _, _ = OUTPUT_FORMATS[output_format]
    target.parent.mkdir(parents=True, exist_ok=True)
    kwargs: Dict[str, Any] = {"format": fmt}
    if fmt in {"JPEG", "WEBP"}:
        kwargs.update({"quality": max(40, min(quality, 100)), "optimize": True})
    if fmt == "JPEG":
        kwargs["progressive"] = True
    image.save(target, **kwargs)


def _normalized_image(path: Path, max_edge: int, output_format: str, background: str):
    image = _open_image(path)
    image = ImageOps.exif_transpose(image)
    image.seek(0)
    image = _flatten(image, background)
    if max(image.size) > max_edge:
        image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    return image


def prepare_image(
    source: str,
    max_edge: int = 2048,
    output_format: str = "jpeg",
    quality: int = 88,
    background: str = "white",
    output_path: Optional[str] = None,
    allow_private_url: bool = False,
) -> Dict[str, Any]:
    """Normalize orientation, color mode, dimensions, and encoding."""
    if output_format not in OUTPUT_FORMATS:
        raise ValueError(f"output_format must be one of: {', '.join(OUTPUT_FORMATS)}")
    if not 256 <= max_edge <= 8192:
        raise ValueError("max_edge must be between 256 and 8192.")
    path, origin = _resolve_source(source, allow_private_url)
    image = _normalized_image(path, max_edge, output_format, background)
    _ensure_dirs()
    _, mime, suffix = OUTPUT_FORMATS[output_format]
    target = Path(output_path).expanduser().resolve() if output_path else ARTIFACT_DIR / f"normalized-{uuid.uuid4().hex}{suffix}"
    _save_image(image, target, output_format, quality)
    return {
        "status": "prepared",
        "source": origin,
        "output_path": str(target),
        "mime_type": mime,
        "width": image.width,
        "height": image.height,
        "file_bytes": target.stat().st_size,
        "sha256": _sha256(target),
        "changes": ["EXIF orientation applied", "first frame selected", "metadata stripped", f"converted to {output_format}", f"long edge capped at {max_edge}px"],
    }


def _tile_boxes(width: int, height: int, tile_size: int, overlap: float) -> Iterable[Tuple[int, int, int, int]]:
    stride = max(1, int(tile_size * (1 - overlap)))
    xs = list(range(0, max(width - tile_size, 0) + 1, stride)) or [0]
    ys = list(range(0, max(height - tile_size, 0) + 1, stride)) or [0]
    if xs[-1] + tile_size < width:
        xs.append(max(0, width - tile_size))
    if ys[-1] + tile_size < height:
        ys.append(max(0, height - tile_size))
    for y in ys:
        for x in xs:
            yield x, y, min(x + tile_size, width), min(y + tile_size, height)


def _run_ocr(path: Path, language: str) -> Dict[str, Any]:
    executable = shutil.which("tesseract")
    if not executable:
        return {"status": "unavailable", "text": "", "message": "Tesseract is not installed. On macOS: brew install tesseract"}
    proc = subprocess.run([executable, str(path), "stdout", "-l", language], capture_output=True, text=True, timeout=90)
    if proc.returncode != 0:
        return {"status": "error", "text": "", "message": proc.stderr.strip()[:500]}
    return {"status": "ok", "text": proc.stdout.strip(), "language": language}


TASK_PROTOCOLS = {
    "general": ["Describe the whole scene before details.", "Separate visible facts from uncertain inference.", "Read text exactly when legible; mark uncertain characters.", "Check each detail tile, then reconcile it with the overview."],
    "ui": ["Identify screen, product, and apparent user goal.", "Inventory navigation, controls, states, labels, and hierarchy.", "Trace likely interaction flow and flag usability or accessibility issues.", "Do not infer hidden behavior from appearance alone."],
    "document": ["Determine document type and reading order.", "Transcribe headings, labels, tables, and key values faithfully.", "Preserve relationships between captions, columns, and figures.", "Mark unreadable or ambiguous text instead of guessing."],
    "chart": ["Identify chart type, axes, units, legend, and time range.", "Extract labeled values before estimating unlabeled values.", "Describe trend, outliers, comparisons, and uncertainty.", "Do not claim precision beyond visible resolution."],
    "code": ["Identify language, file context, and visible line order.", "Transcribe code exactly where legible.", "Separate observed code from proposed fixes.", "Inspect tiles for punctuation, indentation, and truncated lines."],
    "comparison": ["Describe each image or region independently first.", "Compare composition, text, state, and meaningful visual differences.", "Ignore compression noise unless it affects interpretation.", "State which differences are certain versus probable."],
}


def build_vision_bundle(
    source: str,
    task: str = "general",
    question: str = "Analyze the image.",
    tile_size: int = 1280,
    overlap: float = 0.12,
    max_tiles: int = 12,
    ocr: bool = False,
    ocr_language: str = "eng",
    output_dir: Optional[str] = None,
    allow_private_url: bool = False,
) -> Dict[str, Any]:
    """Create overview/detail artifacts and a model-facing reasoning manifest."""
    if task not in TASK_PROTOCOLS:
        raise ValueError(f"task must be one of: {', '.join(TASK_PROTOCOLS)}")
    if not 512 <= tile_size <= 2048:
        raise ValueError("tile_size must be between 512 and 2048.")
    if not 0 <= overlap <= 0.4:
        raise ValueError("overlap must be between 0 and 0.4.")
    if not 1 <= max_tiles <= 48:
        raise ValueError("max_tiles must be between 1 and 48.")

    path, origin = _resolve_source(source, allow_private_url)
    original = _open_image(path)
    original = _flatten(ImageOps.exif_transpose(original), "white")
    _ensure_dirs()
    bundle_dir = Path(output_dir).expanduser().resolve() if output_dir else ARTIFACT_DIR / f"bundle-{uuid.uuid4().hex}"
    bundle_dir.mkdir(parents=True, exist_ok=True)

    overview = original.copy()
    if max(overview.size) > 2048:
        overview.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
    overview_path = bundle_dir / "overview.jpg"
    _save_image(overview, overview_path, "jpeg", 88)

    boxes = list(_tile_boxes(original.width, original.height, tile_size, overlap))
    use_tiles = len(boxes) > 1 and (original.width * original.height >= 2_500_000 or max(original.size) > 2200)
    if use_tiles and len(boxes) > max_tiles:
        scale = math.sqrt(len(boxes) / max_tiles)
        adjusted = min(2048, max(tile_size, int(tile_size * scale)))
        boxes = list(_tile_boxes(original.width, original.height, adjusted, overlap))
    boxes = boxes[:max_tiles] if use_tiles else []

    tiles: List[Dict[str, Any]] = []
    for index, box in enumerate(boxes, 1):
        crop = original.crop(box)
        tile_path = bundle_dir / f"tile-{index:02d}.jpg"
        _save_image(crop, tile_path, "jpeg", 90)
        x1, y1, x2, y2 = box
        tiles.append({"index": index, "path": str(tile_path), "box_px": [x1, y1, x2, y2], "position": {"left": round(x1 / original.width, 3), "top": round(y1 / original.height, 3), "right": round(x2 / original.width, 3), "bottom": round(y2 / original.height, 3)}})

    ocr_result = _run_ocr(overview_path, ocr_language) if ocr else {"status": "not_requested", "text": ""}
    manifest: Dict[str, Any] = {
        "engine": "image-scout",
        "version": "1.0.0",
        "created_at": _now(),
        "source": origin,
        "source_sha256": _sha256(path),
        "task": task,
        "question": question,
        "image": {"width": original.width, "height": original.height, "orientation": _orientation_label(original.width, original.height)},
        "overview": {"path": str(overview_path), "width": overview.width, "height": overview.height},
        "tiles": tiles,
        "reading_order": [str(overview_path)] + [tile["path"] for tile in tiles],
        "inspection_protocol": TASK_PROTOCOLS[task],
        "response_contract": {
            "visible_facts": "What is directly observable.",
            "extracted_text": "Exact text with uncertainty marked.",
            "interpretation": "Best-supported meaning or answer.",
            "uncertainties": "Occlusions, blur, ambiguity, or missing context.",
        },
        "ocr": ocr_result,
    }
    manifest_path = bundle_dir / "manifest.json"
    manifest["manifest_path"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), "utf-8")
    return manifest


def vision_prompt(task: str = "general", question: str = "Analyze the image.", has_tiles: bool = False, has_ocr: bool = False) -> Dict[str, Any]:
    """Return a compact, task-specific vision analysis prompt."""
    if task not in TASK_PROTOCOLS:
        raise ValueError(f"task must be one of: {', '.join(TASK_PROTOCOLS)}")
    lines = ["Analyze the supplied image evidence carefully."]
    if question:
        lines.append(f"Primary question: {question}")
    lines.extend(f"- {item}" for item in TASK_PROTOCOLS[task])
    if has_tiles:
        lines.append("Use the overview for global context, inspect tiles in reading order, then reconcile conflicts.")
    if has_ocr:
        lines.append("Treat OCR as a fallible hint and verify it against pixels before quoting it.")
    lines.append("Return: visible facts, extracted text, interpretation, and uncertainties. Never fill unseen gaps with guesses.")
    return {"task": task, "prompt": "\n".join(lines)}


def encode_for_provider(
    source: str,
    provider: str = "openai-responses",
    detail: str = "auto",
    max_edge: int = 2048,
    quality: int = 88,
    output_path: Optional[str] = None,
    allow_private_url: bool = False,
) -> Dict[str, Any]:
    """Normalize an image and write a provider-native base64 JSON payload."""
    providers = {"openai-responses", "openai-chat", "anthropic", "gemini", "generic"}
    if provider not in providers:
        raise ValueError(f"provider must be one of: {', '.join(sorted(providers))}")
    if detail not in {"auto", "low", "high"}:
        raise ValueError("detail must be auto, low, or high.")
    prepared = prepare_image(source, max_edge, "jpeg", quality, "white", None, allow_private_url)
    image_path = Path(prepared["output_path"])
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    mime = "image/jpeg"
    data_url = f"data:{mime};base64,{encoded}"
    if provider == "openai-responses":
        payload: Any = {"type": "input_image", "image_url": data_url, "detail": detail}
    elif provider == "openai-chat":
        payload = {"type": "image_url", "image_url": {"url": data_url, "detail": detail}}
    elif provider == "anthropic":
        payload = {"type": "image", "source": {"type": "base64", "media_type": mime, "data": encoded}}
    elif provider == "gemini":
        payload = {"inline_data": {"mime_type": mime, "data": encoded}}
    else:
        payload = {"mime_type": mime, "data_base64": encoded}
    _ensure_dirs()
    target = Path(output_path).expanduser().resolve() if output_path else PAYLOAD_DIR / f"{provider}-{uuid.uuid4().hex}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, separators=(",", ":")), "utf-8")
    return {"status": "encoded", "provider": provider, "detail": detail, "payload_path": str(target), "payload_bytes": target.stat().st_size, "image_path": str(image_path), "image_bytes": image_path.stat().st_size, "mime_type": mime, "note": "Payload data is written to disk instead of flooding tool output with base64."}


def doctor() -> Dict[str, Any]:
    """Report local dependency and capability status."""
    return {
        "engine": "image-scout",
        "version": "1.0.0",
        "python": sys.version.split()[0],
        "pillow": {"available": Image is not None, "version": getattr(Image, "__version__", None), "required": True},
        "tesseract": {"available": shutil.which("tesseract") is not None, "path": shutil.which("tesseract"), "required": False, "purpose": "optional local OCR"},
        "data_dir": str(DATA_DIR),
        "network": "Only used to download explicit http(s) image URLs. Private-network targets are blocked by default.",
        "apis": [],
    }


def _cli() -> None:
    parser = argparse.ArgumentParser(description="Image Scout — model-friendly image preparation")
    sub = parser.add_subparsers(dest="tool", required=True)

    p = sub.add_parser("inspect_image")
    p.add_argument("--source", required=True)
    p.add_argument("--allow_private_url", action="store_true")
    p.add_argument("--include_exif", action="store_true")

    p = sub.add_parser("prepare_image")
    p.add_argument("--source", required=True)
    p.add_argument("--max_edge", default=None)
    p.add_argument("--output_format", default=None)
    p.add_argument("--quality", default=None)
    p.add_argument("--background", default="white")
    p.add_argument("--output_path", default=None)
    p.add_argument("--allow_private_url", action="store_true")

    p = sub.add_parser("build_vision_bundle")
    p.add_argument("--source", required=True)
    p.add_argument("--task", default=None)
    p.add_argument("--question", default=None)
    p.add_argument("--tile_size", default=None)
    p.add_argument("--overlap", default=None)
    p.add_argument("--max_tiles", default=None)
    p.add_argument("--ocr", action="store_true")
    p.add_argument("--ocr_language", default=None)
    p.add_argument("--output_dir", default=None)
    p.add_argument("--allow_private_url", action="store_true")

    p = sub.add_parser("vision_prompt")
    p.add_argument("--task", default=None)
    p.add_argument("--question", default=None)
    p.add_argument("--has_tiles", action="store_true")
    p.add_argument("--has_ocr", action="store_true")

    p = sub.add_parser("encode_for_provider")
    p.add_argument("--source", required=True)
    p.add_argument("--provider", default=None)
    p.add_argument("--detail", default=None)
    p.add_argument("--max_edge", default=None)
    p.add_argument("--quality", default=None)
    p.add_argument("--output_path", default=None)
    p.add_argument("--allow_private_url", action="store_true")

    sub.add_parser("doctor")
    args = parser.parse_args()
    kwargs = {key: value for key, value in vars(args).items() if key != "tool"}
    if args.tool == "prepare_image":
        kwargs["max_edge"] = _parse_int(kwargs["max_edge"], 2048, 256, 8192)
        kwargs["output_format"] = _choice(kwargs["output_format"], "jpeg", OUTPUT_FORMATS)
        kwargs["quality"] = _parse_int(kwargs["quality"], 88, 40, 100)
    elif args.tool == "build_vision_bundle":
        kwargs["task"] = _choice(kwargs["task"], "general", TASK_PROTOCOLS)
        kwargs["question"] = _noneish(kwargs["question"]) or "Analyze the image."
        kwargs["tile_size"] = _parse_int(kwargs["tile_size"], 1280, 512, 2048)
        kwargs["overlap"] = _parse_float(kwargs["overlap"], 0.12, 0.0, 0.4)
        kwargs["max_tiles"] = _parse_int(kwargs["max_tiles"], 12, 1, 48)
        kwargs["ocr_language"] = _noneish(kwargs["ocr_language"]) or "eng"
    elif args.tool == "vision_prompt":
        kwargs["task"] = _choice(kwargs["task"], "general", TASK_PROTOCOLS)
        kwargs["question"] = _noneish(kwargs["question"]) or "Analyze the image."
    elif args.tool == "encode_for_provider":
        kwargs["provider"] = _choice(kwargs["provider"], "openai-responses", {"openai-responses", "openai-chat", "anthropic", "gemini", "generic"})
        kwargs["detail"] = _choice(kwargs["detail"], "auto", {"auto", "low", "high"})
        kwargs["max_edge"] = _parse_int(kwargs["max_edge"], 2048, 256, 8192)
        kwargs["quality"] = _parse_int(kwargs["quality"], 88, 40, 100)
    functions = {"inspect_image": inspect_image, "prepare_image": prepare_image, "build_vision_bundle": build_vision_bundle, "vision_prompt": vision_prompt, "encode_for_provider": encode_for_provider, "doctor": doctor}
    try:
        result = functions[args.tool](**kwargs)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc), "tool": args.tool}), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    _cli()
