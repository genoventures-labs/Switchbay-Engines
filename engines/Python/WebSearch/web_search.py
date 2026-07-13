"""WebSearch Engine

Guarded web search and extraction tools for Switchbay.

Tools:
  - web_search   — Search the web via DuckDuckGo (no API key required).
  - web_scrape   — Fetch a URL and extract structured content (text, links, or all).
  - web_crawl    — Bounded domain crawl: follow links N levels deep and return page summaries.

No API keys required. DuckDuckGo HTML scraping is used for web_search.

Usage (called by Switchbay via CLI):
  python engines/Python/WebSearch/web_search.py web_search --query "..." [--count 10]
  python engines/Python/WebSearch/web_search.py web_scrape --url "https://..." [--extract text|links|all]
  python engines/Python/WebSearch/web_search.py web_crawl  --url "https://..." [--depth 2] [--max_pages 20]
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import urllib.parse
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from html.parser import HTMLParser

# macOS Python 3.x ships without a bundled CA store unless you run
# "Install Certificates.command". We probe with a real request and fall back
# gracefully: certifi > system certs > no-verify (last resort, still functional).
def _ssl_context() -> ssl.SSLContext:
    # 1. Prefer certifi if installed
    try:
        import certifi  # type: ignore
        ctx = ssl.create_default_context(cafile=certifi.where())
        return ctx
    except ImportError:
        pass

    # 2. Try the default context with a live probe
    try:
        import urllib.request as _ur
        ctx = ssl.create_default_context()
        _ur.urlopen("https://example.com", context=ctx, timeout=5).close()
        return ctx
    except Exception:
        pass

    # 3. Last resort — no cert verification (warns via stderr)
    import sys as _sys
    print(
        "WARNING: WebSearch SSL certs not found. Running without verification. "
        "Run: /Applications/Python\\ 3.*/Install\\ Certificates.command  "
        "or: pip3 install certifi",
        file=_sys.stderr,
    )
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

_SSL_CTX = _ssl_context()


# ---------------------------------------------------------------------------
# Shared HTTP helper
# ---------------------------------------------------------------------------

USER_AGENT = "Mozilla/5.0 (compatible; SwitchbayWebSearch/1.0)"


def _http_get(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 15) -> bytes:
    req = Request(url, headers={**(headers or {}), "User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
        return resp.read()


def _http_post(url: str, payload: Dict, headers: Optional[Dict[str, str]] = None, timeout: int = 15) -> bytes:
    data = json.dumps(payload).encode("utf-8")
    req = Request(
        url,
        data=data,
        headers={**(headers or {}), "User-Agent": USER_AGENT, "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
        return resp.read()


# ---------------------------------------------------------------------------
# Simple HTML text extractor
# ---------------------------------------------------------------------------

class _TextExtractor(HTMLParser):
    SKIP_TAGS = {"script", "style", "noscript", "head", "meta", "link"}

    def __init__(self):
        super().__init__()
        self._skip = False
        self._skip_tag = None
        self.text_parts: List[str] = []
        self.links: List[Dict[str, str]] = []
        self._current_href: Optional[str] = None

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self._skip = True
            self._skip_tag = tag
        if tag == "a":
            attr_dict = dict(attrs)
            self._current_href = attr_dict.get("href")

    def handle_endtag(self, tag):
        if tag == self._skip_tag:
            self._skip = False
            self._skip_tag = None
        if tag == "a":
            self._current_href = None

    def handle_data(self, data):
        if not self._skip:
            stripped = data.strip()
            if stripped:
                self.text_parts.append(stripped)
                if self._current_href:
                    self.links.append({"text": stripped, "href": self._current_href})

    def get_text(self) -> str:
        return "\n".join(self.text_parts)


def _extract_html(html: bytes, base_url: str = "") -> Dict[str, Any]:
    """Parse raw HTML into text, links, and basic metadata."""
    try:
        text = html.decode("utf-8", errors="replace")
    except Exception:
        text = html.decode("latin-1", errors="replace")

    parser = _TextExtractor()
    parser.feed(text)

    # Resolve relative links
    resolved_links = []
    for link in parser.links:
        href = link["href"]
        if href and not href.startswith(("javascript:", "mailto:", "#")):
            resolved = urllib.parse.urljoin(base_url, href)
            resolved_links.append({"text": link["text"], "url": resolved})

    return {
        "text": parser.get_text(),
        "links": resolved_links,
    }


# ---------------------------------------------------------------------------
# DuckDuckGo Lite search backend (no API key required)
# ---------------------------------------------------------------------------

class _DDGLiteParser(HTMLParser):
    """Parse DuckDuckGo Lite POST results into title/url/description triples.

    DDG Lite HTML structure:
      <a class="result-link" href="URL">Title</a>
      <td class="result-snippet">Description text</td>
    """

    def __init__(self):
        super().__init__()
        self.results: List[Dict[str, str]] = []
        self._in_link = False
        self._in_snippet = False
        self._pending_title = ""
        self._pending_url = ""
        self._pending_snippet = ""

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        classes = attr_dict.get("class", "")

        if tag == "a" and "result-link" in classes:
            self._pending_url = attr_dict.get("href", "")
            self._pending_title = ""
            self._in_link = True

        if tag == "td" and "result-snippet" in classes:
            self._pending_snippet = ""
            self._in_snippet = True

    def handle_endtag(self, tag):
        if tag == "a" and self._in_link:
            self._in_link = False
            # Don't commit yet — wait for snippet

        if tag == "td" and self._in_snippet:
            self._in_snippet = False
            # Commit result when snippet closes
            if self._pending_url and self._pending_title:
                self.results.append({
                    "title": self._pending_title.strip(),
                    "url": self._pending_url.strip(),
                    "description": self._pending_snippet.strip(),
                })
                self._pending_title = ""
                self._pending_url = ""
                self._pending_snippet = ""

    def handle_data(self, data):
        stripped = data.strip()
        if not stripped:
            return
        if self._in_link:
            self._pending_title += stripped
        elif self._in_snippet:
            self._pending_snippet += " " + stripped


def _search_ddg(query: str, count: int) -> List[Dict[str, Any]]:
    """Search via DuckDuckGo Lite (POST). No API key needed."""
    data = urllib.parse.urlencode({"q": query}).encode("utf-8")
    req = Request(
        "https://lite.duckduckgo.com/lite/",
        data=data,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.5",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://lite.duckduckgo.com/lite/",
        },
        method="POST",
    )
    with urlopen(req, timeout=15, context=_SSL_CTX) as resp:
        raw = resp.read()

    html = raw.decode("utf-8", errors="replace")
    parser = _DDGLiteParser()
    parser.feed(html)

    results = []
    for item in parser.results[:count]:
        results.append({
            "title": item.get("title", "").strip(),
            "url": item.get("url", "").strip(),
            "description": item.get("description", "").strip(),
            "source": "duckduckgo",
        })
    return results


# ---------------------------------------------------------------------------
# Public tool functions
# ---------------------------------------------------------------------------

def web_search(query: str, count: int = 10) -> Dict[str, Any]:
    """Search the web using DuckDuckGo (no API key required).

    Returns:
        {
            "query": str,
            "provider": "duckduckgo",
            "count": int,
            "results": [{"title", "url", "description", "source"}, ...]
        }
    """
    if not query or not query.strip():
        raise ValueError("query must not be empty.")

    count = max(1, min(count, 20))
    results = _search_ddg(query, count)

    return {"query": query, "provider": "duckduckgo", "count": len(results), "results": results}


def web_scrape(url: str, extract: str = "text") -> Dict[str, Any]:
    """Fetch a URL and extract structured content.

    Args:
        url:     The explicit public URL to fetch.
        extract: One of: text, links, all. Defaults to text.

    Returns:
        {
            "url": str,
            "extract": str,
            "text"?: str,
            "links"?: [{"text", "url"}, ...]
        }
    """
    if not url or not url.strip():
        raise ValueError("url must not be empty.")

    valid_modes = {"text", "links", "all"}
    if extract not in valid_modes:
        raise ValueError(f"extract must be one of: {', '.join(valid_modes)}")

    raw = _http_get(url)
    parsed = _extract_html(raw, base_url=url)

    result: Dict[str, Any] = {"url": url, "extract": extract}

    if extract in ("text", "all"):
        result["text"] = parsed["text"]
    if extract in ("links", "all"):
        result["links"] = parsed["links"]

    return result


def web_crawl(url: str, depth: int = 1, max_pages: int = 10, delay: float = 0.5) -> Dict[str, Any]:
    """Bounded domain crawl — follow links up to `depth` levels deep.

    Stays within the same domain. Returns page summaries.

    Args:
        url:       The seed URL to start from.
        depth:     How many link-hops to follow. Max 3.
        max_pages: Hard cap on total pages fetched. Max 20.
        delay:     Seconds to wait between requests (default 0.5).

    Returns:
        {
            "seed": str,
            "domain": str,
            "pages_crawled": int,
            "pages": [{"url", "summary", "link_count"}, ...]
        }
    """
    if not url or not url.strip():
        raise ValueError("url must not be empty.")

    depth = max(1, min(depth, 3))
    max_pages = max(1, min(max_pages, 20))

    parsed_seed = urllib.parse.urlparse(url)
    domain = parsed_seed.netloc

    visited: set[str] = set()
    queue: List[tuple[str, int]] = [(url, 0)]
    pages: List[Dict[str, Any]] = []

    while queue and len(pages) < max_pages:
        current_url, current_depth = queue.pop(0)

        if current_url in visited:
            continue
        visited.add(current_url)

        try:
            raw = _http_get(current_url)
            parsed = _extract_html(raw, base_url=current_url)
            text = parsed["text"]
            summary = " ".join(text.split()[:80])  # First ~80 words

            pages.append({
                "url": current_url,
                "summary": summary,
                "link_count": len(parsed["links"]),
            })

            if current_depth < depth:
                for link in parsed["links"]:
                    link_url = link["url"]
                    link_parsed = urllib.parse.urlparse(link_url)
                    if link_parsed.netloc == domain and link_url not in visited:
                        queue.append((link_url, current_depth + 1))

            if delay > 0:
                time.sleep(delay)

        except (URLError, HTTPError, Exception):
            # Skip pages that error; don't abort the whole crawl
            continue

    return {
        "seed": url,
        "domain": domain,
        "pages_crawled": len(pages),
        "pages": pages,
    }


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def _cli():
    parser = argparse.ArgumentParser(description="WebSearch Engine CLI")
    sub = parser.add_subparsers(dest="tool", required=True)

    # web_search
    p_search = sub.add_parser("web_search")
    p_search.add_argument("--query", required=True)
    p_search.add_argument("--count", type=int, default=10)

    # web_scrape
    p_scrape = sub.add_parser("web_scrape")
    p_scrape.add_argument("--url", required=True)
    p_scrape.add_argument("--extract", default="text", choices=["text", "links", "all"])

    # web_crawl
    p_crawl = sub.add_parser("web_crawl")
    p_crawl.add_argument("--url", required=True)
    p_crawl.add_argument("--depth", type=int, default=1)
    p_crawl.add_argument("--max_pages", type=int, default=10)
    p_crawl.add_argument("--delay", type=float, default=0.5)

    args = parser.parse_args()

    try:
        if args.tool == "web_search":
            result = web_search(query=args.query, count=args.count)
        elif args.tool == "web_scrape":
            result = web_scrape(url=args.url, extract=args.extract)
        elif args.tool == "web_crawl":
            result = web_crawl(url=args.url, depth=args.depth, max_pages=args.max_pages, delay=args.delay)
        else:
            raise ValueError(f"Unknown tool: {args.tool}")

        print(json.dumps(result, indent=2))

    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    _cli()
