"""WebSearch Engine

Guarded web search and extraction tools for Switchbay.

Tools:
  - web_search   — Query a search API (Brave, Serper, or Tavily) and return ranked results.
  - web_scrape   — Fetch a URL and extract structured content (text, tables, code blocks, links).
  - web_crawl    — Bounded domain crawl: follow links N levels deep and return page summaries.

Requires one of the following env vars set (checked in order):
  BRAVE_API_KEY, SERPER_API_KEY, TAVILY_API_KEY

Usage (called by Switchbay via CLI):
  python engines/Python/WebSearch/web_search.py web_search --query "..." [--count 10]
  python engines/Python/WebSearch/web_search.py web_scrape --url "https://..." [--extract text|table|code|links]
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
# Search backends
# ---------------------------------------------------------------------------

def _search_brave(query: str, count: int, api_key: str) -> List[Dict[str, Any]]:
    url = f"https://api.search.brave.com/res/v1/web/search?q={urllib.parse.quote(query)}&count={count}"
    raw = _http_get(url, headers={"Accept": "application/json", "X-Subscription-Token": api_key})
    data = json.loads(raw)
    results = []
    for item in data.get("web", {}).get("results", []):
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "description": item.get("description", ""),
            "source": "brave",
        })
    return results


def _search_serper(query: str, count: int, api_key: str) -> List[Dict[str, Any]]:
    raw = _http_post(
        "https://google.serper.dev/search",
        {"q": query, "num": count},
        headers={"X-API-KEY": api_key},
    )
    data = json.loads(raw)
    results = []
    for item in data.get("organic", []):
        results.append({
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "description": item.get("snippet", ""),
            "source": "serper",
        })
    return results


def _search_tavily(query: str, count: int, api_key: str) -> List[Dict[str, Any]]:
    raw = _http_post(
        "https://api.tavily.com/search",
        {"api_key": api_key, "query": query, "max_results": count},
    )
    data = json.loads(raw)
    results = []
    for item in data.get("results", []):
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "description": item.get("content", ""),
            "source": "tavily",
        })
    return results


# ---------------------------------------------------------------------------
# Public tool functions
# ---------------------------------------------------------------------------

def web_search(query: str, count: int = 10) -> Dict[str, Any]:
    """Search the web using the first available API key.

    Checks: BRAVE_API_KEY → SERPER_API_KEY → TAVILY_API_KEY.

    Returns:
        {
            "query": str,
            "provider": str,
            "count": int,
            "results": [{"title", "url", "description", "source"}, ...]
        }
    """
    if not query or not query.strip():
        raise ValueError("query must not be empty.")

    count = max(1, min(count, 20))

    brave_key = os.environ.get("BRAVE_API_KEY")
    serper_key = os.environ.get("SERPER_API_KEY")
    tavily_key = os.environ.get("TAVILY_API_KEY")

    if brave_key:
        results = _search_brave(query, count, brave_key)
        provider = "brave"
    elif serper_key:
        results = _search_serper(query, count, serper_key)
        provider = "serper"
    elif tavily_key:
        results = _search_tavily(query, count, tavily_key)
        provider = "tavily"
    else:
        raise EnvironmentError(
            "No search API key found. Set one of: BRAVE_API_KEY, SERPER_API_KEY, or TAVILY_API_KEY."
        )

    return {"query": query, "provider": provider, "count": len(results), "results": results}


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
