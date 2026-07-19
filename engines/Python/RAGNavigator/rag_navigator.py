#!/usr/bin/env python3
"""RAG Navigator — local corpus indexing, retrieval, inspection, and context packing."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

DATA_DIR = Path.home() / ".switchbay" / "rag-navigator"
DEFAULT_EXTENSIONS = ".md,.markdown,.txt,.jsonl"
TOKEN_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_'-]*")


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


def _tokens(text: str) -> list[str]:
    return [match.group(0).lower() for match in TOKEN_RE.finditer(text)]


def _extensions(value: Any) -> set[str]:
    raw = _noneish(value) or DEFAULT_EXTENSIONS
    result = set()
    for item in raw.split(","):
        item = item.strip().lower()
        if item:
            result.add(item if item.startswith(".") else "." + item)
    return result


def _safe_root(value: Any) -> Path:
    text = _noneish(value)
    if not text:
        raise ValueError("corpus must be a directory path")
    root = Path(text).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"corpus directory does not exist: {root}")
    return root


def _default_index(root: Path) -> Path:
    digest = hashlib.sha256(str(root).encode()).hexdigest()[:12]
    return DATA_DIR / "indexes" / f"{root.name or 'corpus'}-{digest}.json"


def _index_path(value: Any, root: Path | None = None) -> Path:
    text = _noneish(value)
    if text:
        return Path(text).expanduser().resolve()
    if root is None:
        raise ValueError("index is required when corpus is omitted")
    return _default_index(root)


def _files(root: Path, extensions: set[str], max_file_bytes: int) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        try:
            resolved = path.resolve()
            resolved.relative_to(root)
        except (OSError, ValueError):
            continue
        if not path.is_file() or path.is_symlink() or path.suffix.lower() not in extensions:
            continue
        try:
            if path.stat().st_size <= max_file_bytes:
                yield path
        except OSError:
            continue


def _heading(block: str) -> str | None:
    match = re.match(r"^#{1,6}\s+(.+)$", block.strip())
    return match.group(1).strip() if match else None


def _chunk_text(text: str, target: int, overlap: int) -> list[dict[str, Any]]:
    blocks = [item.strip() for item in re.split(r"\n{2,}", text) if item.strip()]
    chunks: list[dict[str, Any]] = []
    current = ""
    section: str | None = None

    def emit(value: str, heading: str | None) -> None:
        clean = value.strip()
        if clean:
            chunks.append({"text": clean, "section": heading})

    for block in blocks:
        section = _heading(block) or section
        candidate = f"{current}\n\n{block}".strip() if current else block
        if len(candidate) <= target:
            current = candidate
            continue
        emit(current, section)
        tail = current[-overlap:] if overlap and current else ""
        if len(block) <= target:
            current = f"{tail}\n\n{block}".strip()
            continue
        step = max(1, target - overlap)
        for start in range(0, len(block), step):
            emit(block[start:start + target], section)
        current = ""
    emit(current, section)
    return chunks


def _jsonl_chunks(path: Path) -> list[dict[str, Any]] | None:
    if path.name != "chunks.jsonl":
        return None
    rows = []
    try:
        for line in path.read_text("utf-8", errors="replace").splitlines():
            item = json.loads(line)
            if isinstance(item, dict) and _noneish(item.get("text")):
                rows.append(item)
    except (OSError, json.JSONDecodeError):
        return None
    return rows


def inventory_corpus(corpus: Any, extensions: Any = None, max_file_bytes: Any = 5_000_000) -> dict[str, Any]:
    root = _safe_root(corpus)
    maximum = _parse_int(max_file_bytes, 5_000_000, 1_000, 100_000_000)
    paths = list(_files(root, _extensions(extensions), maximum))
    by_extension = Counter(path.suffix.lower() for path in paths)
    return {
        "ok": True,
        "corpus": str(root),
        "file_count": len(paths),
        "total_bytes": sum(path.stat().st_size for path in paths),
        "by_extension": dict(sorted(by_extension.items())),
        "files": [str(path.relative_to(root)) for path in paths[:200]],
        "truncated": len(paths) > 200,
    }


def index_corpus(corpus: Any, index: Any = None, extensions: Any = None, chunk_chars: Any = 3200,
                 overlap_chars: Any = 240, max_file_bytes: Any = 5_000_000) -> dict[str, Any]:
    root = _safe_root(corpus)
    target = _parse_int(chunk_chars, 3200, 400, 50_000)
    overlap = _parse_int(overlap_chars, 240, 0, min(5000, target // 2))
    maximum = _parse_int(max_file_bytes, 5_000_000, 1_000, 100_000_000)
    output = _index_path(index, root)
    chunks: list[dict[str, Any]] = []
    sources: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()

    for path in _files(root, _extensions(extensions), maximum):
        rel = str(path.relative_to(root))
        rows = _jsonl_chunks(path)
        if rows is None:
            text = path.read_text("utf-8", errors="replace")
            rows = _chunk_text(text, target, overlap)
        title = path.stem.replace("_", " ").replace("-", " ").strip()
        source_url = ""
        accepted = 0
        for ordinal, row in enumerate(rows):
            text = str(row.get("text", "")).strip()
            if not text:
                continue
            digest = str(row.get("sha256") or hashlib.sha256(text.encode()).hexdigest())
            if digest in seen:
                continue
            seen.add(digest)
            row_title = _noneish(row.get("title")) or title
            row_url = _noneish(row.get("source_url")) or ""
            title = row_title
            source_url = row_url or source_url
            counts = Counter(_tokens(f"{row_title} {row.get('section') or ''} {text}"))
            chunk_id = f"c{len(chunks) + 1:06d}"
            chunks.append({
                "id": chunk_id, "source": rel, "source_url": row_url,
                "title": row_title, "section": _noneish(row.get("section")),
                "ordinal": ordinal, "chars": len(text), "sha256": digest,
                "text": text, "terms": dict(counts), "length": sum(counts.values()),
            })
            accepted += 1
        sources[rel] = {"path": rel, "title": title, "source_url": source_url,
                        "chunks": accepted, "bytes": path.stat().st_size}

    document_frequency: Counter[str] = Counter()
    for chunk in chunks:
        document_frequency.update(chunk["terms"].keys())
    payload = {
        "schema_version": 1, "engine": "rag-navigator", "corpus": str(root),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "chunk_chars": target, "overlap_chars": overlap,
        "source_count": len(sources), "chunk_count": len(chunks),
        "average_length": (sum(item["length"] for item in chunks) / len(chunks)) if chunks else 0,
        "document_frequency": dict(document_frequency),
        "sources": list(sources.values()), "chunks": chunks,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "index": str(output), "corpus": str(root),
            "source_count": len(sources), "chunk_count": len(chunks),
            "unique_terms": len(document_frequency), "deduplicated_chunks": sum(s["chunks"] for s in sources.values()) - len(chunks)}


def _load_index(value: Any) -> tuple[Path, dict[str, Any]]:
    path = _index_path(value)
    if not path.is_file():
        raise ValueError(f"index does not exist: {path}")
    data = json.loads(path.read_text("utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("chunks"), list):
        raise ValueError("unsupported or invalid RAG Navigator index")
    return path, data


def corpus_status(index: Any) -> dict[str, Any]:
    path, data = _load_index(index)
    return {"ok": True, "index": str(path), "corpus": data["corpus"],
            "created_at": data["created_at"], "source_count": data["source_count"],
            "chunk_count": data["chunk_count"], "sources": data["sources"][:100],
            "sources_truncated": len(data["sources"]) > 100}


def _rank(data: dict[str, Any], query: str, source_filter: str | None) -> list[dict[str, Any]]:
    query_terms = _tokens(query)
    if not query_terms:
        raise ValueError("query must contain searchable terms")
    q_counts = Counter(query_terms)
    total = max(1, len(data["chunks"]))
    avg = max(1.0, float(data.get("average_length") or 1))
    df = data.get("document_frequency", {})
    phrase = query.lower().strip()
    ranked = []
    for chunk in data["chunks"]:
        if source_filter and source_filter.lower() not in chunk["source"].lower():
            continue
        score = 0.0
        length = max(1, chunk["length"])
        for term, q_weight in q_counts.items():
            frequency = chunk["terms"].get(term, 0)
            if not frequency:
                continue
            inverse = math.log(1 + (total - int(df.get(term, 0)) + 0.5) / (int(df.get(term, 0)) + 0.5))
            score += q_weight * inverse * (frequency * 2.2) / (frequency + 1.2 * (0.25 + 0.75 * length / avg))
        haystack = chunk["text"].lower()
        if phrase and phrase in haystack:
            score += 4.0
        if any(term in (chunk.get("title") or "").lower() for term in q_counts):
            score += 1.25
        if any(term in (chunk.get("section") or "").lower() for term in q_counts):
            score += 1.0
        if score > 0:
            ranked.append((score, chunk))
    ranked.sort(key=lambda item: (-item[0], item[1]["source"], item[1]["ordinal"]))
    return [{**chunk, "score": round(score, 6)} for score, chunk in ranked]


def search(index: Any, query: Any, top_k: Any = 8, source_filter: Any = None,
           include_text: Any = True) -> dict[str, Any]:
    path, data = _load_index(index)
    query_text = _noneish(query)
    if not query_text:
        raise ValueError("query must not be empty")
    limit = _parse_int(top_k, 8, 1, 50)
    matches = _rank(data, query_text, _noneish(source_filter))[:limit]
    if not _truthy(include_text, True):
        for item in matches:
            item.pop("text", None)
            item.pop("terms", None)
    else:
        for item in matches:
            item.pop("terms", None)
    return {"ok": True, "index": str(path), "query": query_text,
            "match_count": len(matches), "matches": matches}


def read_chunk(index: Any, chunk_id: Any, neighbor_window: Any = 0) -> dict[str, Any]:
    path, data = _load_index(index)
    wanted = _noneish(chunk_id)
    if not wanted:
        raise ValueError("chunk_id is required")
    lookup = {item["id"]: item for item in data["chunks"]}
    if wanted not in lookup:
        raise ValueError(f"unknown chunk_id: {wanted}")
    anchor = lookup[wanted]
    window = _parse_int(neighbor_window, 0, 0, 5)
    selected = [item for item in data["chunks"] if item["source"] == anchor["source"] and abs(item["ordinal"] - anchor["ordinal"]) <= window]
    for item in selected:
        item.pop("terms", None)
    return {"ok": True, "index": str(path), "anchor": wanted, "chunks": selected}


def build_context(index: Any, query: Any, top_k: Any = 8, neighbor_window: Any = 1,
                  max_chars: Any = 12_000, source_filter: Any = None) -> dict[str, Any]:
    path, data = _load_index(index)
    query_text = _noneish(query)
    if not query_text:
        raise ValueError("query must not be empty")
    seeds = _rank(data, query_text, _noneish(source_filter))[:_parse_int(top_k, 8, 1, 30)]
    window = _parse_int(neighbor_window, 1, 0, 3)
    budget = _parse_int(max_chars, 12_000, 500, 100_000)
    by_source: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    for item in data["chunks"]:
        by_source[item["source"]][item["ordinal"]] = item
    chosen: list[tuple[float, dict[str, Any]]] = []
    seen = set()
    for seed in seeds:
        for ordinal in range(seed["ordinal"] - window, seed["ordinal"] + window + 1):
            item = by_source[seed["source"]].get(ordinal)
            if item and item["id"] not in seen:
                seen.add(item["id"])
                chosen.append((seed["score"], item))
    chosen.sort(key=lambda pair: (-pair[0], pair[1]["source"], pair[1]["ordinal"]))
    parts, citations, used = [], [], 0
    for score, item in chosen:
        label = f"[{item['id']}] {item['title']}"
        if item.get("section"):
            label += f" — {item['section']}"
        block = f"{label}\nSource: {item.get('source_url') or item['source']}\n{item['text']}"
        if parts and used + len(block) + 2 > budget:
            continue
        if len(block) > budget and not parts:
            block = block[:budget]
        parts.append(block)
        used += len(block) + 2
        citations.append({"chunk_id": item["id"], "source": item["source"],
                          "source_url": item.get("source_url") or None, "title": item["title"],
                          "section": item.get("section"), "score": score})
        if used >= budget:
            break
    return {"ok": True, "index": str(path), "query": query_text,
            "context_chars": len("\n\n".join(parts)), "max_chars": budget,
            "citation_count": len(citations), "citations": citations,
            "context": "\n\n".join(parts)}


def status() -> dict[str, Any]:
    return {"ok": True, "engine": "rag-navigator", "data_dir": str(DATA_DIR),
            "retrieval": "local BM25-style lexical ranking with phrase, title, and section boosts",
            "dependencies": "Python standard library only", "network": "none"}


TOOLS = {"status": status, "inventory_corpus": inventory_corpus, "index_corpus": index_corpus,
         "corpus_status": corpus_status, "search": search, "read_chunk": read_chunk,
         "build_context": build_context}


def _cli() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="tool", required=True)
    sub.add_parser("status")
    p = sub.add_parser("inventory_corpus")
    p.add_argument("--corpus", required=True); p.add_argument("--extensions", default=None); p.add_argument("--max_file_bytes", default="5000000")
    p = sub.add_parser("index_corpus")
    p.add_argument("--corpus", required=True); p.add_argument("--index", default=None); p.add_argument("--extensions", default=None)
    p.add_argument("--chunk_chars", default="3200"); p.add_argument("--overlap_chars", default="240"); p.add_argument("--max_file_bytes", default="5000000")
    p = sub.add_parser("corpus_status"); p.add_argument("--index", required=True)
    p = sub.add_parser("search")
    p.add_argument("--index", required=True); p.add_argument("--query", required=True); p.add_argument("--top_k", default="8")
    p.add_argument("--source_filter", default=None); p.add_argument("--include_text", default="true")
    p = sub.add_parser("read_chunk")
    p.add_argument("--index", required=True); p.add_argument("--chunk_id", required=True); p.add_argument("--neighbor_window", default="0")
    p = sub.add_parser("build_context")
    p.add_argument("--index", required=True); p.add_argument("--query", required=True); p.add_argument("--top_k", default="8")
    p.add_argument("--neighbor_window", default="1"); p.add_argument("--max_chars", default="12000"); p.add_argument("--source_filter", default=None)
    args = parser.parse_args()
    try:
        kwargs = {key: value for key, value in vars(args).items() if key != "tool"}
        print(json.dumps(TOOLS[args.tool](**kwargs), indent=2, ensure_ascii=False))
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "tool": args.tool, "error": str(exc)}), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    _cli()
