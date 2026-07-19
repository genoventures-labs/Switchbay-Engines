#!/usr/bin/env python3
"""Web Ingest Engine — turn public web pages into clean Markdown and RAG chunks."""
from __future__ import annotations

import argparse
import hashlib
import html
import ipaddress
import json
import re
import socket
import sys
import time
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

DATA_DIR = Path.home() / ".switchbay" / "web-ingest"
USER_AGENT = "Mozilla/5.0 (compatible; Switchbay-WebIngest/1.0)"
BLOCK_TAGS = {"article", "aside", "blockquote", "div", "footer", "header", "main", "nav", "p", "section"}
DROP_TAGS = {"script", "style", "noscript", "svg", "canvas", "template", "iframe"}


def _noneish(value: Any) -> str | None:
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


def _truthy(value: Any, default: bool = False) -> bool:
    text = (_noneish(value) or "").lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _slug(text: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return value[:80] or "page"


def _is_public_host(hostname: str) -> bool:
    if hostname.lower() in {"localhost", "localhost.localdomain"}:
        return False
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, None)}
    except socket.gaierror:
        return False
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
        if not ip.is_global:
            return False
    return bool(addresses)


def _validate_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("url must be an absolute http:// or https:// URL")
    if not _is_public_host(parsed.hostname):
        raise ValueError("refusing localhost, private, reserved, or unresolved network targets")
    return url


def _fetch_static(url: str, timeout: int, max_bytes: int) -> tuple[str, str, str]:
    current = _validate_url(url)
    request = Request(current, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    with urlopen(request, timeout=timeout) as response:
        final_url = response.geturl()
        _validate_url(final_url)
        content_type = response.headers.get_content_type()
        if content_type not in {"text/html", "application/xhtml+xml"}:
            raise ValueError(f"unsupported content type: {content_type}")
        charset = response.headers.get_content_charset() or "utf-8"
        raw = response.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ValueError(f"page exceeded max_bytes={max_bytes}")
        return raw.decode(charset, errors="replace"), final_url, "static"


async def _render_playwright(url: str, timeout: int, max_bytes: int, wait_ms: int) -> tuple[str, str, str]:
    try:
        from playwright.async_api import async_playwright  # type: ignore
    except ImportError as exc:
        raise RuntimeError("render=true requires Playwright: pip install playwright && playwright install chromium") from exc
    _validate_url(url)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(user_agent=USER_AGENT)
        await page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
        if wait_ms:
            await page.wait_for_timeout(wait_ms)
        final_url = page.url
        _validate_url(final_url)
        content = await page.content()
        await browser.close()
    if len(content.encode("utf-8")) > max_bytes:
        raise ValueError(f"rendered page exceeded max_bytes={max_bytes}")
    return content, final_url, "playwright"


class MarkdownExtractor(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.parts: list[str] = []
        self.drop_depth = 0
        self.link_stack: list[str] = []
        self.list_stack: list[tuple[str, int]] = []
        self.title = ""
        self._in_title = False

    def _add(self, text: str) -> None:
        if self.drop_depth == 0:
            self.parts.append(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = dict(attrs)
        if tag in DROP_TAGS:
            self.drop_depth += 1
            return
        if self.drop_depth:
            return
        if tag == "title":
            self._in_title = True
        elif re.fullmatch(r"h[1-6]", tag):
            self._add("\n\n" + "#" * int(tag[1]) + " ")
        elif tag in BLOCK_TAGS:
            self._add("\n\n")
        elif tag == "br":
            self._add("\n")
        elif tag in {"strong", "b"}:
            self._add("**")
        elif tag in {"em", "i"}:
            self._add("*")
        elif tag == "code":
            self._add("`")
        elif tag == "pre":
            self._add("\n\n```\n")
        elif tag in {"ul", "ol"}:
            self.list_stack.append((tag, 0))
            self._add("\n")
        elif tag == "li":
            if self.list_stack:
                kind, count = self.list_stack[-1]
                count += 1
                self.list_stack[-1] = (kind, count)
                prefix = f"{count}. " if kind == "ol" else "- "
            else:
                prefix = "- "
            self._add("\n" + "  " * max(0, len(self.list_stack) - 1) + prefix)
        elif tag == "a":
            href = _noneish(attrs_map.get("href")) or ""
            self.link_stack.append(urljoin(self.base_url, href))
            self._add("[")
        elif tag == "img":
            alt = (attrs_map.get("alt") or "").strip()
            src = _noneish(attrs_map.get("src"))
            if alt and src:
                self._add(f"![{alt}]({urljoin(self.base_url, src)})")

    def handle_endtag(self, tag: str) -> None:
        if tag in DROP_TAGS:
            self.drop_depth = max(0, self.drop_depth - 1)
            return
        if self.drop_depth:
            return
        if tag == "title":
            self._in_title = False
        elif re.fullmatch(r"h[1-6]", tag) or tag in BLOCK_TAGS:
            self._add("\n\n")
        elif tag in {"strong", "b"}:
            self._add("**")
        elif tag in {"em", "i"}:
            self._add("*")
        elif tag == "code":
            self._add("`")
        elif tag == "pre":
            self._add("\n```\n\n")
        elif tag in {"ul", "ol"} and self.list_stack:
            self.list_stack.pop()
            self._add("\n")
        elif tag == "a" and self.link_stack:
            href = self.link_stack.pop()
            if href and not href.lower().startswith("javascript:"):
                self._add(f"]({href})")
            else:
                self._add("]")

    def handle_data(self, data: str) -> None:
        if self.drop_depth:
            return
        text = html.unescape(data)
        if self._in_title:
            self.title += text
            return
        self._add(text)

    def markdown(self) -> str:
        text = "".join(self.parts).replace("\xa0", " ")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r" *\n *", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"\*\*\s*\*\*", "", text)
        return text.strip() + "\n"


@dataclass
class Chunk:
    index: int
    text: str
    chars: int
    source_url: str
    title: str
    section: str | None
    sha256: str


def _chunk_markdown(markdown: str, source_url: str, title: str, chunk_chars: int, overlap_chars: int) -> list[Chunk]:
    blocks = [b.strip() for b in re.split(r"\n{2,}", markdown) if b.strip()]
    chunks: list[Chunk] = []
    current = ""
    section: str | None = None
    prior_tail = ""

    def emit(text: str, section_name: str | None) -> None:
        clean = text.strip()
        if not clean:
            return
        chunks.append(Chunk(
            index=len(chunks), text=clean, chars=len(clean), source_url=source_url,
            title=title, section=section_name,
            sha256=hashlib.sha256(clean.encode("utf-8")).hexdigest(),
        ))

    for block in blocks:
        heading = re.match(r"^#{1,6}\s+(.+)$", block)
        if heading:
            section = heading.group(1).strip()
        candidate = f"{current}\n\n{block}".strip() if current else block
        if len(candidate) <= chunk_chars:
            current = candidate
            continue
        emit((prior_tail + "\n\n" + current).strip() if prior_tail else current, section)
        prior_tail = current[-overlap_chars:] if overlap_chars else ""
        if len(block) <= chunk_chars:
            current = block
        else:
            start = 0
            while start < len(block):
                piece = block[start:start + chunk_chars]
                emit((prior_tail + "\n\n" + piece).strip() if prior_tail else piece, section)
                prior_tail = piece[-overlap_chars:] if overlap_chars else ""
                start += max(1, chunk_chars - overlap_chars)
            current = ""
    emit((prior_tail + "\n\n" + current).strip() if prior_tail else current, section)
    return chunks


def convert_html(html_text: str, source_url: str) -> tuple[str, str]:
    parser = MarkdownExtractor(source_url)
    parser.feed(html_text)
    title = re.sub(r"\s+", " ", parser.title).strip() or urlparse(source_url).netloc
    markdown = parser.markdown()
    if not markdown.startswith("# "):
        markdown = f"# {title}\n\nSource: {source_url}\n\n{markdown}"
    return title, markdown


def ingest_website(url: str, render: Any = False, output_dir: Any = None, chunk_chars: Any = 4000,
                   overlap_chars: Any = 300, timeout: Any = 25, max_bytes: Any = 5_000_000,
                   wait_ms: Any = 0, save_html: Any = False) -> dict[str, Any]:
    timeout_i = _parse_int(timeout, 25, 3, 120)
    max_bytes_i = _parse_int(max_bytes, 5_000_000, 50_000, 25_000_000)
    chunk_chars_i = _parse_int(chunk_chars, 4000, 500, 50_000)
    overlap_i = _parse_int(overlap_chars, 300, 0, min(5000, chunk_chars_i // 2))
    wait_ms_i = _parse_int(wait_ms, 0, 0, 30_000)
    use_render = _truthy(render)

    if use_render:
        import asyncio
        page_html, final_url, fetch_mode = asyncio.run(_render_playwright(url, timeout_i, max_bytes_i, wait_ms_i))
    else:
        page_html, final_url, fetch_mode = _fetch_static(url, timeout_i, max_bytes_i)

    title, markdown = convert_html(page_html, final_url)
    chunks = _chunk_markdown(markdown, final_url, title, chunk_chars_i, overlap_i)
    root = Path(_noneish(output_dir) or DATA_DIR)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    page_dir = root.expanduser() / f"{_slug(title)}-{stamp}"
    page_dir.mkdir(parents=True, exist_ok=False)
    markdown_path = page_dir / "page.md"
    chunks_path = page_dir / "chunks.jsonl"
    metadata_path = page_dir / "metadata.json"
    markdown_path.write_text(markdown, encoding="utf-8")
    with chunks_path.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")
    metadata = {
        "ok": True, "requested_url": url, "final_url": final_url, "title": title,
        "fetch_mode": fetch_mode, "markdown_chars": len(markdown), "chunk_count": len(chunks),
        "chunk_chars": chunk_chars_i, "overlap_chars": overlap_i,
        "markdown_path": str(markdown_path), "chunks_path": str(chunks_path),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if _truthy(save_html):
        html_path = page_dir / "source.html"
        html_path.write_text(page_html, encoding="utf-8")
        metadata["html_path"] = str(html_path)
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    metadata["metadata_path"] = str(metadata_path)
    metadata["preview"] = markdown[:1200]
    return metadata


def status() -> dict[str, Any]:
    try:
        import playwright  # type: ignore  # noqa: F401
        playwright_available = True
    except ImportError:
        playwright_available = False
    return {
        "ok": True,
        "engine": "web-ingest",
        "data_dir": str(DATA_DIR),
        "static_mode": "ready",
        "playwright_available": playwright_available,
        "network_policy": "public http/https only; private and localhost targets are blocked",
    }


def _cli() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="tool", required=True)
    sub.add_parser("status")
    ingest = sub.add_parser("ingest_website")
    ingest.add_argument("--url", required=True)
    ingest.add_argument("--render", default="false")
    ingest.add_argument("--output_dir", default=None)
    ingest.add_argument("--chunk_chars", default="4000")
    ingest.add_argument("--overlap_chars", default="300")
    ingest.add_argument("--timeout", default="25")
    ingest.add_argument("--max_bytes", default="5000000")
    ingest.add_argument("--wait_ms", default="0")
    ingest.add_argument("--save_html", default="false")
    args = parser.parse_args()
    try:
        result = status() if args.tool == "status" else ingest_website(**{k: v for k, v in vars(args).items() if k != "tool"})
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except (ValueError, RuntimeError, HTTPError, URLError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc), "tool": args.tool}), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    _cli()
