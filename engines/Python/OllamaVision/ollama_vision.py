#!/usr/bin/env python3
"""Ollama Vision engine for Switchbay.

Sends images to a local Ollama VL model and returns JSON descriptions.
Supports base64-encoded images or local file paths.
Outputs JSON for agent consumption.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path


OLLAMA_BASE = "http://localhost:11434"


def result(ok: bool, action: str, **data):
    payload = {"ok": ok, "action": action, **data}
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if ok else 1


def ollama_post(endpoint: str, payload: dict) -> dict:
    url = f"{OLLAMA_BASE}{endpoint}"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ollama_get(endpoint: str) -> dict:
    url = f"{OLLAMA_BASE}{endpoint}"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def encode_image(path: str) -> str:
    """Read a local image file and return base64-encoded string."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"Image not found: {p}")
    with open(p, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_status(_args):
    try:
        data = ollama_get("/api/tags")
        models = [m["name"] for m in data.get("models", [])]
        vl_models = [m for m in models if any(k in m.lower() for k in ("vl", "vision", "qwen3.5", "qwen2.5vl"))]
        return result(
            True, "status",
            message="Ollama Vision engine ready",
            ollama_url=OLLAMA_BASE,
            available_models=models,
            vision_models=vl_models,
        )
    except Exception as e:
        return result(False, "status", message=f"Ollama not reachable: {e}", ollama_url=OLLAMA_BASE)


def cmd_list_models(_args):
    try:
        data = ollama_get("/api/tags")
        models = [m["name"] for m in data.get("models", [])]
        vl_models = [m for m in models if any(k in m.lower() for k in ("vl", "vision", "qwen3.5", "qwen2.5vl"))]
        return result(True, "list_models", models=models, vision_models=vl_models, count=len(models))
    except Exception as e:
        return result(False, "list_models", message=str(e))


def cmd_describe(args):
    """General image description."""
    try:
        if args.image_path:
            b64 = encode_image(args.image_path)
        elif args.image_base64:
            b64 = args.image_base64
        else:
            return result(False, "describe", message="Provide --image-path or --image-base64")

        prompt = args.prompt or (
            "Describe this image in detail. Include the main subject, setting, "
            "colors, composition, and any notable elements."
        )

        payload = {
            "model": args.model,
            "prompt": prompt,
            "images": [b64],
            "stream": False,
        }

        data = ollama_post("/api/generate", payload)
        description = data.get("response", "").strip()

        return result(
            True, "describe",
            model=args.model,
            description=description,
            prompt_used=prompt,
            source=args.image_path or "base64_input",
        )
    except FileNotFoundError as e:
        return result(False, "describe", message=str(e))
    except urllib.error.URLError as e:
        return result(False, "describe", message=f"Ollama request failed: {e}")
    except Exception as e:
        return result(False, "describe", message=str(e))


def cmd_describe_person(args):
    """Person-focused description tuned for LoRA training captions."""
    try:
        if args.image_path:
            b64 = encode_image(args.image_path)
        elif args.image_base64:
            b64 = args.image_base64
        else:
            return result(False, "describe_person", message="Provide --image-path or --image-base64")

        subject_hint = f" The subject is {args.subject}." if args.subject else ""

        prompt = (
            f"Focus only on the person in this image.{subject_hint} "
            "Describe their physical appearance in detail for use as a LoRA training caption. "
            "Include: face shape, facial features (eyes, nose, mouth, jawline), skin tone, "
            "hair color, hair length, hair texture and style, eyebrows, any visible facial hair, "
            "approximate age range, and build/body type if visible. "
            "Do not describe background, clothing unless asked, or unrelated objects. "
            "Be specific and factual. Output a single descriptive paragraph."
        )

        payload = {
            "model": args.model,
            "prompt": prompt,
            "images": [b64],
            "stream": False,
        }

        data = ollama_post("/api/generate", payload)
        description = data.get("response", "").strip()

        # Optional refinement pass with a text model
        refined = None
        if args.refine_model and description:
            refine_prompt = (
                f"Rewrite this person description as a clean, concise LoRA training caption. "
                f"Keep all physical details accurate. Remove any hedging language like 'appears to' or 'seems'. "
                f"Output one paragraph only.\n\nDescription:\n{description}"
            )
            refine_payload = {
                "model": args.refine_model,
                "prompt": refine_prompt,
                "stream": False,
            }
            refine_data = ollama_post("/api/generate", refine_payload)
            refined = refine_data.get("response", "").strip()

        return result(
            True, "describe_person",
            model=args.model,
            refine_model=args.refine_model or None,
            raw_description=description,
            refined_caption=refined,
            caption=refined if refined else description,
            subject=args.subject or None,
            source=args.image_path or "base64_input",
        )
    except FileNotFoundError as e:
        return result(False, "describe_person", message=str(e))
    except urllib.error.URLError as e:
        return result(False, "describe_person", message=f"Ollama request failed: {e}")
    except Exception as e:
        return result(False, "describe_person", message=str(e))


def cmd_caption(args):
    """Generate a short image caption suitable for training or alt-text."""
    try:
        if args.image_path:
            b64 = encode_image(args.image_path)
        elif args.image_base64:
            b64 = args.image_base64
        else:
            return result(False, "caption", message="Provide --image-path or --image-base64")

        style_prompts = {
            "training": (
                "Write a single concise training caption for this image. "
                "Focus on the main subject, key visual attributes, and composition. "
                "No filler words. Output one sentence only."
            ),
            "alttext": (
                "Write a concise, accurate alt-text description of this image for accessibility. "
                "One to two sentences maximum."
            ),
            "tweet": (
                "Write a short, natural caption for this image as if posting it on social media. "
                "One sentence, no hashtags."
            ),
        }

        prompt = style_prompts.get(args.style, style_prompts["training"])

        payload = {
            "model": args.model,
            "prompt": prompt,
            "images": [b64],
            "stream": False,
        }

        data = ollama_post("/api/generate", payload)
        caption = data.get("response", "").strip()

        return result(
            True, "caption",
            model=args.model,
            caption=caption,
            style=args.style,
            source=args.image_path or "base64_input",
        )
    except FileNotFoundError as e:
        return result(False, "caption", message=str(e))
    except urllib.error.URLError as e:
        return result(False, "caption", message=f"Ollama request failed: {e}")
    except Exception as e:
        return result(False, "caption", message=str(e))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Ollama Vision engine for Switchbay")
    sub = parser.add_subparsers(dest="command")

    # status
    sub.add_parser("status", help="Check Ollama connectivity and list vision models")

    # list-models
    sub.add_parser("list-models", help="List all models available in Ollama")

    # describe
    p_desc = sub.add_parser("describe", help="General image description")
    p_desc.add_argument("--model", default="qwen3.5:2b", help="Ollama VL model name")
    p_desc.add_argument("--image-path", help="Local path to image file")
    p_desc.add_argument("--image-base64", help="Base64-encoded image string")
    p_desc.add_argument("--prompt", help="Custom prompt (optional)")

    # describe-person
    p_person = sub.add_parser("describe-person", help="Person-focused description for LoRA training")
    p_person.add_argument("--model", default="qwen3.5:2b", help="Ollama VL model name")
    p_person.add_argument("--image-path", help="Local path to image file")
    p_person.add_argument("--image-base64", help="Base64-encoded image string")
    p_person.add_argument("--subject", help="Optional subject hint (e.g. 'a woman in her 30s')")
    p_person.add_argument("--refine-model", help="Optional text model for caption refinement (e.g. qwen2.5:3b)")

    # caption
    p_cap = sub.add_parser("caption", help="Short caption for training, alt-text, or social")
    p_cap.add_argument("--model", default="qwen3.5:2b", help="Ollama VL model name")
    p_cap.add_argument("--image-path", help="Local path to image file")
    p_cap.add_argument("--image-base64", help="Base64-encoded image string")
    p_cap.add_argument("--style", choices=["training", "alttext", "tweet"], default="training")

    args = parser.parse_args()

    commands = {
        "status": cmd_status,
        "list-models": cmd_list_models,
        "describe": cmd_describe,
        "describe-person": cmd_describe_person,
        "caption": cmd_caption,
    }

    if args.command not in commands:
        parser.print_help()
        sys.exit(1)

    sys.exit(commands[args.command](args))


if __name__ == "__main__":
    main()
