#!/usr/bin/env python3
"""Convert public HTML pages into local, RAG-friendly Markdown corpora."""
from __future__ import annotations
import argparse, hashlib, html, ipaddress, json, re, socket, sys, time
import urllib.parse, urllib.robotparser
from collections import deque
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

UA = "Switchbay-WebToMarkdown/1.0"
DATA_DIR = Path.home() / ".switchbay" / "web-corpora"
SKIP = {"script", "style", "svg", "canvas", "noscript", "template", "iframe"}
NOISE = re.compile(r"cookie|consent|banner|modal|popup|advert|promo|newsletter|social-share|breadcrumbs?", re.I)
SPACE = re.compile(r"[ \t]+")


def noneish(v: Any) -> str | None:
    if v is None: return None
    s = str(v).strip()
    return None if s.lower() in {"", "none", "null"} else s


def as_int(v: Any, default: int, lo: int, hi: int) -> int:
    try: return max(lo, min(int(float(noneish(v) or default)), hi))
    except (TypeError, ValueError): return default


def as_float(v: Any, default: float, lo: float, hi: float) -> float:
    try: return max(lo, min(float(noneish(v) or default), hi))
    except (TypeError, ValueError): return default


def as_bool(v: Any, default: bool = False) -> bool:
    s = (noneish(v) or "").lower()
    if s in {"1", "true", "yes", "on"}: return True
    if s in {"0", "false", "no", "off"}: return False
    return default


def normalize_url(raw: str, base: str | None = None) -> str:
    p = urllib.parse.urlsplit(urllib.parse.urljoin(base, raw) if base else raw.strip())
    if p.scheme.lower() not in {"http", "https"} or not p.hostname:
        raise ValueError("A complete http:// or https:// URL is required.")
    query = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
    return urllib.parse.urlunsplit((p.scheme.lower(), p.netloc.lower(), re.sub(r"/{2,}", "/", p.path or "/"), urllib.parse.urlencode(query), ""))


def assert_public(url: str, allow_private: bool) -> None:
    if allow_private: return
    host = urllib.parse.urlsplit(url).hostname or ""
    try: addresses = {x[4][0] for x in socket.getaddrinfo(host, None)}
    except socket.gaierror as exc: raise ValueError(f"Could not resolve host: {host}") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified:
            raise ValueError(f"Refusing non-public target: {address}")


def fetch_html(url: str, timeout: int, max_bytes: int, allow_private: bool) -> tuple[str, str]:
    assert_public(url, allow_private)
    req = Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"})
    with urlopen(req, timeout=timeout) as response:
        final = normalize_url(response.geturl())
        assert_public(final, allow_private)
        if response.headers.get_content_type() not in {"text/html", "application/xhtml+xml"}:
            raise ValueError(f"Unsupported content type: {response.headers.get_content_type()}")
        raw = response.read(max_bytes + 1)
        if len(raw) > max_bytes: raise ValueError(f"Response exceeded {max_bytes} bytes")
        return raw.decode(response.headers.get_content_charset() or "utf-8", "replace"), final


class MarkdownHTML(HTMLParser):
    def __init__(self, base: str):
        super().__init__(convert_charrefs=True)
        self.base, self.parts, self.links = base, [], []
        self.title = self.description = self.canonical = self.language = ""
        self.skip = self.noise = self.pre = 0
        self.in_title = False
        self.list_stack: list[str] = []
        self.href: str | None = None

    def emit(self, s: str) -> None: self.parts.append(s)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag, a = tag.lower(), {k.lower(): v or "" for k, v in attrs}
        if tag in SKIP: self.skip += 1; return
        if self.skip: return
        if self.noise or NOISE.search(" ".join((a.get("id", ""), a.get("class", ""), a.get("role", "")))):
            self.noise += 1; return
        if tag == "html": self.language = a.get("lang", "")
        elif tag == "title": self.in_title = True
        elif tag == "meta" and (a.get("name") or a.get("property", "")).lower() in {"description", "og:description"}:
            self.description = self.description or a.get("content", "").strip()
        elif tag == "link" and "canonical" in a.get("rel", "").lower() and a.get("href"):
            try: self.canonical = normalize_url(a["href"], self.base)
            except ValueError: pass
        elif re.fullmatch(r"h[1-6]", tag): self.emit("\n\n" + "#" * int(tag[1]) + " ")
        elif tag in {"p", "div", "main", "article", "section"}: self.emit("\n\n")
        elif tag == "blockquote": self.emit("\n\n> ")
        elif tag == "br": self.emit("\n")
        elif tag == "hr": self.emit("\n\n---\n\n")
        elif tag in {"ul", "ol"}: self.list_stack.append(tag); self.emit("\n")
        elif tag == "li": self.emit("\n" + "  " * max(0, len(self.list_stack)-1) + ("1. " if self.list_stack and self.list_stack[-1] == "ol" else "- "))
        elif tag == "a":
            self.href = a.get("href") or None
            if self.href:
                try: self.links.append(normalize_url(self.href, self.base))
                except ValueError: pass
                self.emit("[")
        elif tag == "img" and a.get("alt") and a.get("src"): self.emit(f"![{a['alt']}]({urllib.parse.urljoin(self.base, a['src'])})")
        elif tag == "pre": self.pre += 1; self.emit("\n\n```\n")
        elif tag == "code" and not self.pre: self.emit("`")
        elif tag in {"strong", "b"}: self.emit("**")
        elif tag in {"em", "i"}: self.emit("*")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in SKIP and self.skip: self.skip -= 1; return
        if self.skip: return
        if self.noise: self.noise -= 1; return
        if tag == "title": self.in_title = False
        elif re.fullmatch(r"h[1-6]", tag) or tag in {"p", "div", "main", "article", "section", "blockquote"}: self.emit("\n\n")
        elif tag in {"ul", "ol"} and self.list_stack: self.list_stack.pop(); self.emit("\n")
        elif tag == "a":
            if self.href: self.emit(f"]({urllib.parse.urljoin(self.base, self.href)})")
            self.href = None
        elif tag == "pre" and self.pre: self.pre -= 1; self.emit("\n```\n\n")
        elif tag == "code" and not self.pre: self.emit("`")
        elif tag in {"strong", "b"}: self.emit("**")
        elif tag in {"em", "i"}: self.emit("*")

    def handle_data(self, data: str) -> None:
        if self.skip or self.noise: return
        if self.in_title: self.title += data; return
        self.emit(data if self.pre else SPACE.sub(" ", data))


def convert(url: str, timeout: int, max_bytes: int, allow_private: bool) -> dict[str, Any]:
    raw, final = fetch_html(url, timeout, max_bytes, allow_private)
    p = MarkdownHTML(final); p.feed(raw)
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(x.rstrip() for x in "".join(p.parts).replace("\r", "").splitlines())).strip()
    title = html.unescape(SPACE.sub(" ", p.title)).strip()
    if title and not body.startswith("# "): body = f"# {title}\n\n{body}"
    digest = hashlib.sha256(body.encode()).hexdigest()
    meta = {"title": title or final, "source_url": final, "canonical_url": p.canonical or final,
            "description": html.unescape(p.description), "language": p.language,
            "fetched_at": datetime.now(timezone.utc).isoformat(), "content_sha256": digest,
            "word_count": len(body.split()), "links_found": len(set(p.links))}
    fm = "---\n" + "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in meta.items() if v) + "\n---\n\n"
    return {"metadata": meta, "markdown": fm + body + "\n", "links": sorted(set(p.links))}


def slug(url: str) -> str:
    p = urllib.parse.urlsplit(url); raw = p.path.strip("/") or "index"
    clean = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-.") or "page"
    return clean[:120] + ("-" + hashlib.sha1(url.encode()).hexdigest()[:8] if len(clean) > 120 or p.query else "") + ".md"


def fetch_page(**a: Any) -> dict[str, Any]:
    result = convert(normalize_url(a["url"]), as_int(a["timeout"],20,3,120), as_int(a["max_bytes"],5_000_000,100_000,25_000_000), as_bool(a["allow_private"]))
    dest = noneish(a["output_path"])
    if dest:
        path = Path(dest).expanduser().resolve(); path.parent.mkdir(parents=True, exist_ok=True); path.write_text(result["markdown"], encoding="utf-8"); result["output_path"] = str(path)
    if not as_bool(a["include_markdown"], True): result.pop("markdown", None)
    return {"ok": True, **result}


def crawl_site(**a: Any) -> dict[str, Any]:
    root = normalize_url(a["url"]); host = urllib.parse.urlsplit(root).hostname or "site"
    out = Path(noneish(a["output_dir"]) or DATA_DIR / f"{host}-{datetime.now():%Y%m%d-%H%M%S}").expanduser().resolve()
    pages_dir = out / "pages"; pages_dir.mkdir(parents=True, exist_ok=True)
    max_pages, max_depth = as_int(a["max_pages"],50,1,500), as_int(a["max_depth"],2,0,10)
    delay, timeout, max_bytes = as_float(a["delay"],.35,0,10), as_int(a["timeout"],20,3,120), as_int(a["max_bytes"],5_000_000,100_000,25_000_000)
    inc = re.compile(noneish(a["include"])) if noneish(a["include"]) else None
    exc = re.compile(noneish(a["exclude"])) if noneish(a["exclude"]) else None
    robots = urllib.robotparser.RobotFileParser(urllib.parse.urljoin(root, "/robots.txt")) if as_bool(a["respect_robots"], True) else None
    if robots:
        try: robots.read()
        except Exception: robots.parse([])
    q, seen, records, errors = deque([(root,0)]), set(), [], []
    while q and len(records) < max_pages:
        current, depth = q.popleft()
        if current in seen: continue
        seen.add(current)
        if robots and not robots.can_fetch(UA, current): errors.append({"url":current,"error":"blocked by robots.txt"}); continue
        try:
            page = convert(current, timeout, max_bytes, as_bool(a["allow_private"]))
            name = slug(page["metadata"]["source_url"]); path = pages_dir / name
            if path.exists(): path = pages_dir / f"{path.stem}-{hashlib.sha1(current.encode()).hexdigest()[:8]}.md"
            path.write_text(page["markdown"], encoding="utf-8")
            record = {**page["metadata"], "depth": depth, "file": f"pages/{path.name}"}; records.append(record)
            if depth < max_depth:
                for link in page["links"]:
                    lp = urllib.parse.urlsplit(link); rp = urllib.parse.urlsplit(root)
                    if (lp.scheme,lp.netloc)!=(rp.scheme,rp.netloc) or re.search(r"\.(?:png|jpe?g|gif|webp|svg|pdf|zip|css|js|json|xml|mp[34])$", lp.path, re.I): continue
                    if inc and not inc.search(link): continue
                    if exc and exc.search(link): continue
                    if link not in seen: q.append((link, depth+1))
        except (ValueError, HTTPError, URLError, OSError, TimeoutError) as e: errors.append({"url":current,"error":str(e)})
        if q and delay: time.sleep(delay)
    manifest = {"schema_version":1,"root_url":root,"created_at":datetime.now(timezone.utc).isoformat(),"pages":records,"errors":errors}
    (out/"corpus.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding="utf-8")
    with (out/"documents.jsonl").open("w",encoding="utf-8") as f:
        for r in records: f.write(json.dumps({"id":r["content_sha256"],"text":(out/r["file"]).read_text("utf-8"),"metadata":r},ensure_ascii=False)+"\n")
    return {"ok":True,"summary":{"root_url":root,"pages_written":len(records),"errors":len(errors),"output_dir":str(out)},"corpus_manifest":str(out/"corpus.json"),"documents_jsonl":str(out/"documents.jsonl"),"pages":records,"errors":errors[:25]}


def inspect_corpus(**a: Any) -> dict[str, Any]:
    path = Path(a["corpus_path"]).expanduser().resolve(); path = path/"corpus.json" if path.is_dir() else path
    if not path.exists(): raise ValueError(f"Corpus not found: {path}")
    data = json.loads(path.read_text("utf-8")); limit = as_int(a["limit"],20,1,200)
    return {"ok":True,"summary":{"root_url":data.get("root_url"),"page_count":len(data.get("pages",[])),"error_count":len(data.get("errors",[])),"created_at":data.get("created_at")},"pages":data.get("pages",[])[:limit],"errors":data.get("errors",[])[:limit],"corpus_path":str(path)}


def main() -> None:
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest="tool",required=True)
    p=sub.add_parser("fetch_page"); p.add_argument("--url",required=True); p.add_argument("--output_path",default=None); p.add_argument("--timeout",default="20"); p.add_argument("--max_bytes",default="5000000"); p.add_argument("--allow_private",default="false"); p.add_argument("--include_markdown",default="true")
    p=sub.add_parser("crawl_site"); p.add_argument("--url",required=True); p.add_argument("--output_dir",default=None); p.add_argument("--max_pages",default="50"); p.add_argument("--max_depth",default="2"); p.add_argument("--delay",default="0.35"); p.add_argument("--timeout",default="20"); p.add_argument("--max_bytes",default="5000000"); p.add_argument("--include",default=None); p.add_argument("--exclude",default=None); p.add_argument("--respect_robots",default="true"); p.add_argument("--allow_private",default="false")
    p=sub.add_parser("inspect_corpus"); p.add_argument("--corpus_path",required=True); p.add_argument("--limit",default="20")
    args=vars(ap.parse_args()); tool=args.pop("tool")
    try: result={"fetch_page":fetch_page,"crawl_site":crawl_site,"inspect_corpus":inspect_corpus}[tool](**args); print(json.dumps(result,indent=2,ensure_ascii=False))
    except Exception as e: print(json.dumps({"ok":False,"tool":tool,"error":str(e)}),file=sys.stderr); raise SystemExit(1)
if __name__ == "__main__": main()
