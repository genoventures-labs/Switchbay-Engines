"""Memory Search Engine

On-demand search/recall across Switchbay memory stores so models pull context
when needed instead of stuffing large memory into every turn.

Tools:
  search_memory  — Ranked hits (source, path, score, snippet)
  recall_memory  — Compact context_pack + structured facts

Stores scanned:
  Global     ~/.switchbay/context/, ~/.switchbay/sessions/
  Workspace  SWITCHBAY.md, .switchbay/memory/, knowledge, pins, plan, guides

Usage:
  python engines/Python/MemoryHelper/memory_search.py search_memory --query "..." [--workspace PATH]
  python engines/Python/MemoryHelper/memory_search.py recall_memory --query "..." [--workspace PATH]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

HOME = Path.home()
GLOBAL_DIR = Path(os.environ.get("SWITCHBAY_CONFIG_DIR", HOME / ".switchbay")).expanduser()
GLOBAL_CONTEXT = Path(os.environ.get("SWITCHBAY_CONTEXT_DIR", GLOBAL_DIR / "context")).expanduser()
GLOBAL_SESSIONS = Path(os.environ.get("SWITCHBAY_SESSION_DIR", GLOBAL_DIR / "sessions")).expanduser()

SENSITIVE_NAME_RE = re.compile(
    r"(^|[._-])(credential|secret|token|private[-_]?key|api[-_]?key)([._-]|$)",
    re.IGNORECASE,
)

STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for", "of",
    "with", "by", "from", "as", "is", "are", "was", "were", "be", "this", "that",
    "these", "those", "it", "its", "into", "about", "how", "what", "why", "when",
    "where", "which", "who", "can", "could", "should", "would", "will", "do",
    "does", "did", "my", "your", "our", "their", "me", "we", "you", "i", "please",
    "remember", "recall", "memory", "search", "find", "look", "show", "tell",
}

SOURCE_KINDS = {
    "context",
    "switchbay",
    "notes",
    "facts",
    "summary",
    "knowledge",
    "pins",
    "sessions",
    "plan",
    "guides",
}

DEFAULT_SOURCES = "context,switchbay,notes,facts,summary,knowledge,pins,sessions,plan"


# ---------------------------------------------------------------------------
# Scoring / tokenization
# ---------------------------------------------------------------------------

@dataclass
class Hit:
    source: str
    path: str
    title: str
    snippet: str
    score: float
    kind: str = "text"
    meta: Dict[str, Any] = field(default_factory=dict)


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9][a-z0-9_\-./]{1,}", (text or "").lower())


def _query_terms(query: str) -> List[str]:
    terms = [t for t in _tokenize(query) if t not in STOP_WORDS and len(t) > 1]
    # Keep original tokens if everything was stop-worded
    return terms or _tokenize(query)


def _score_text(text: str, terms: Sequence[str]) -> float:
    if not text or not terms:
        return 0.0
    lower = text.lower()
    tokens = set(_tokenize(lower))
    score = 0.0
    for term in terms:
        if term in lower:
            score += 2.0
            score += lower.count(term) * 0.15
        if term in tokens:
            score += 1.0
        # light prefix/fuzzy for compound terms
        if any(tok.startswith(term) or term.startswith(tok) for tok in tokens if len(term) >= 4):
            score += 0.25
    # Phrase bonus
    phrase = " ".join(terms)
    if len(terms) >= 2 and phrase in lower:
        score += 3.0
    return score


def _clip(text: str, limit: int = 400) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _noneish(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if text in {"", "None", "null"}:
        return None
    return text


def _parse_int(value: Any, default: int, *, minimum: int = 1, maximum: int = 100) -> int:
    """Parse CLI ints. Missing Switchbay placeholders arrive as the string 'None'."""
    if value is None:
        return default
    text = str(value).strip()
    if text in {"", "None", "null"}:
        return default
    try:
        parsed = int(float(text))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(parsed, maximum))


def _resolve_workspace(workspace: Optional[str]) -> Path:
    raw = _noneish(workspace) or os.environ.get("SWITCHBAY_WORKSPACE") or os.getcwd()
    return Path(raw).expanduser().resolve()


def _parse_sources(sources: Optional[str]) -> Set[str]:
    raw = _noneish(sources) or DEFAULT_SOURCES
    if raw.lower() in {"all", "*"}:
        return set(SOURCE_KINDS)
    chosen = {s.strip().lower() for s in raw.split(",") if s.strip()}
    unknown = chosen - SOURCE_KINDS
    if unknown:
        raise ValueError(f"unknown source(s): {', '.join(sorted(unknown))}")
    return chosen or set(SOURCE_KINDS)


def _safe_read_text(path: Path, max_bytes: int = 250_000) -> Optional[str]:
    try:
        if not path.is_file():
            return None
        if path.stat().st_size > max_bytes:
            return path.read_text("utf-8", errors="replace")[:max_bytes]
        return path.read_text("utf-8", errors="replace")
    except Exception:
        return None


def _safe_read_json(path: Path) -> Any:
    text = _safe_read_text(path)
    if text is None:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Collectors
# ---------------------------------------------------------------------------

def _collect_context(terms: Sequence[str]) -> List[Hit]:
    hits: List[Hit] = []
    if not GLOBAL_CONTEXT.is_dir():
        return hits
    for path in sorted(GLOBAL_CONTEXT.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.suffix.lower() not in {".md", ".txt", ".json"}:
            continue
        if SENSITIVE_NAME_RE.search(path.name):
            continue
        text = _safe_read_text(path, max_bytes=80_000)
        if not text:
            continue
        score = _score_text(f"{path.name}\n{text}", terms)
        if score <= 0:
            continue
        hits.append(
            Hit(
                source="context",
                path=str(path),
                title=path.name,
                snippet=_clip(text),
                score=score + 0.5,  # slight boost — personal prefs matter
                kind="user_context",
            )
        )
    return hits


def _collect_switchbay_md(workspace: Path, terms: Sequence[str]) -> List[Hit]:
    path = workspace / "SWITCHBAY.md"
    text = _safe_read_text(path)
    if not text:
        return []
    score = _score_text(text, terms)
    if score <= 0 and terms:
        # Still surface a short pointer when file exists and query is project-ish
        if any(t in {"project", "switchbay", "repo", "workspace", "instructions"} for t in terms):
            score = 1.0
        else:
            return []
    return [
        Hit(
            source="switchbay",
            path=str(path),
            title="SWITCHBAY.md",
            snippet=_clip(text, 600),
            score=score + 1.0,
            kind="project_context",
        )
    ]


def _parse_notes_md(content: str) -> List[str]:
    notes: List[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("- ", "* ")):
            notes.append(stripped[2:].strip())
        else:
            notes.append(stripped)
    return [n for n in notes if n]


def _collect_memory_notes(workspace: Path, terms: Sequence[str]) -> List[Hit]:
    hits: List[Hit] = []
    candidates = [
        workspace / ".switchbay" / "memory" / "notes.md",
        workspace / ".switchbay" / "memory" / "notes.json",
        workspace / ".switchbay" / "memory.md",
    ]
    for path in candidates:
        if not path.exists():
            continue
        if path.suffix == ".json":
            data = _safe_read_json(path)
            notes: List[str] = []
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, str):
                        notes.append(item)
                    elif isinstance(item, dict):
                        notes.append(str(item.get("text") or item.get("note") or item))
            elif isinstance(data, dict) and isinstance(data.get("notes"), list):
                notes = [str(n) for n in data["notes"]]
        else:
            text = _safe_read_text(path) or ""
            notes = _parse_notes_md(text)

        for i, note in enumerate(notes):
            score = _score_text(note, terms)
            if score <= 0:
                continue
            hits.append(
                Hit(
                    source="notes",
                    path=str(path),
                    title=f"note[{i}]",
                    snippet=_clip(note, 500),
                    score=score + 1.25,
                    kind="memory_note",
                    meta={"index": i},
                )
            )
    return hits


def _collect_facts(workspace: Path, terms: Sequence[str]) -> List[Hit]:
    path = workspace / ".switchbay" / "memory" / "facts.json"
    data = _safe_read_json(path)
    if not isinstance(data, list):
        return []
    hits: List[Hit] = []
    for fact in data:
        if not isinstance(fact, dict):
            continue
        key = str(fact.get("key", ""))
        value = str(fact.get("value", ""))
        blob = f"{key}: {value}"
        score = _score_text(blob, terms)
        if score <= 0:
            continue
        hits.append(
            Hit(
                source="facts",
                path=str(path),
                title=key or "fact",
                snippet=_clip(blob, 400),
                score=score + 1.5,
                kind="memory_fact",
                meta={"key": key, "source_field": fact.get("source")},
            )
        )
    return hits


def _collect_summary(workspace: Path, terms: Sequence[str]) -> List[Hit]:
    path = workspace / ".switchbay" / "memory" / "summary.md"
    text = _safe_read_text(path)
    if not text:
        return []
    score = _score_text(text, terms)
    if score <= 0:
        return []
    # Split into sections for tighter snippets
    sections = re.split(r"\n(?=##\s)", text)
    hits: List[Hit] = []
    for section in sections:
        sec_score = _score_text(section, terms)
        if sec_score <= 0:
            continue
        title_match = re.match(r"##\s+(.+)", section.strip())
        title = title_match.group(1).strip() if title_match else "summary"
        hits.append(
            Hit(
                source="summary",
                path=str(path),
                title=title,
                snippet=_clip(section, 500),
                score=sec_score + 0.75,
                kind="memory_summary",
            )
        )
    if not hits and score > 0:
        hits.append(
            Hit(
                source="summary",
                path=str(path),
                title="summary.md",
                snippet=_clip(text, 500),
                score=score,
                kind="memory_summary",
            )
        )
    return hits


def _collect_knowledge(workspace: Path, terms: Sequence[str], limit_scan: int = 800) -> List[Hit]:
    # Prefer real Switchbay path; also accept a flat knowledge.json if present
    candidates = [
        workspace / ".switchbay" / "knowledge" / "index.json",
        workspace / ".switchbay" / "knowledge.json",
    ]
    index = None
    index_path = None
    for path in candidates:
        data = _safe_read_json(path)
        if isinstance(data, dict) and isinstance(data.get("chunks"), list):
            index = data
            index_path = path
            break
    if not index or not index_path:
        return []

    hits: List[Hit] = []
    for chunk in index["chunks"][:limit_scan]:
        if not isinstance(chunk, dict):
            continue
        text = str(chunk.get("text") or "")
        rel = str(chunk.get("path") or "")
        blob = f"{rel}\n{text}"
        score = _score_text(blob, terms)
        if score <= 0:
            continue
        start = chunk.get("startLine")
        end = chunk.get("endLine")
        span = f":{start}-{end}" if start and end else ""
        hits.append(
            Hit(
                source="knowledge",
                path=f"{rel}{span}",
                title=rel,
                snippet=_clip(text, 450),
                score=score,
                kind=str(chunk.get("kind") or "knowledge"),
                meta={
                    "index": str(index_path),
                    "id": chunk.get("id"),
                    "startLine": start,
                    "endLine": end,
                },
            )
        )
    return hits


def _collect_pins(workspace: Path, terms: Sequence[str]) -> List[Hit]:
    path = workspace / ".switchbay" / "pins.json"
    data = _safe_read_json(path)
    if data is None:
        return []

    pin_paths: List[str] = []
    if isinstance(data, list):
        pin_paths = [str(p) for p in data]
    elif isinstance(data, dict):
        for key in ("pins", "files", "paths"):
            if isinstance(data.get(key), list):
                pin_paths = [str(p) for p in data[key]]
                break
        if not pin_paths:
            # object map path -> meta
            pin_paths = [str(k) for k in data.keys() if not str(k).startswith("_")]

    hits: List[Hit] = []
    for rel in pin_paths:
        file_path = Path(rel)
        if not file_path.is_absolute():
            file_path = workspace / rel
        text = _safe_read_text(file_path, max_bytes=60_000) or ""
        score = _score_text(f"{rel}\n{text}", terms) + 0.5
        if score <= 0.5 and terms:
            # Pins are intentional — keep a weak hit if the filename matches
            if _score_text(rel, terms) <= 0:
                continue
        hits.append(
            Hit(
                source="pins",
                path=str(file_path),
                title=rel,
                snippet=_clip(text or rel, 400),
                score=score,
                kind="pinned_file",
            )
        )
    return hits


def _iter_session_files() -> Iterable[Path]:
    # Global sessions (canonical Switchbay location)
    if GLOBAL_SESSIONS.is_dir():
        for path in GLOBAL_SESSIONS.glob("session-*.json"):
            yield path
    # Optional workspace-local sessions if present
    # (handled by caller with workspace path)


def _collect_sessions(
    workspace: Path,
    terms: Sequence[str],
    max_files: int = 40,
) -> List[Hit]:
    hits: List[Hit] = []
    files: List[Path] = []
    files.extend(list(_iter_session_files()))
    local_sessions = workspace / ".switchbay" / "sessions"
    if local_sessions.is_dir():
        files.extend(local_sessions.glob("session-*.json"))

    # Newest first
    files = sorted({p.resolve() for p in files}, key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    workspace_s = str(workspace)

    scanned = 0
    for path in files:
        if scanned >= max_files:
            break
        data = _safe_read_json(path)
        if not isinstance(data, dict):
            continue
        scanned += 1

        # Prefer sessions tied to this workspace when metadata exists
        sess_ws = None
        workspace_meta = data.get("workspace")
        if isinstance(workspace_meta, dict):
            sess_ws = workspace_meta.get("cwd")
        elif isinstance(workspace_meta, str):
            sess_ws = workspace_meta
        workspace_boost = 0.0
        if sess_ws:
            if Path(str(sess_ws)).expanduser().resolve() == workspace:
                workspace_boost = 1.5
            elif workspace_s not in str(sess_ws):
                # Different workspace — still searchable, but lower priority
                workspace_boost = -0.5

        title = str(data.get("sessionTitle") or path.stem)
        conversation = data.get("conversation") or data.get("messages") or []
        if not isinstance(conversation, list):
            continue

        # Score title + recent messages
        best_msg = ""
        best_score = _score_text(title, terms)
        for msg in conversation[-80:]:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role") or "")
            content = str(msg.get("content") or "")
            if not content or content.startswith("/"):
                continue
            # Skip huge tool dumps
            if len(content) > 4000:
                content = content[:4000]
            msg_score = _score_text(content, terms)
            if role == "user":
                msg_score += 0.35
            if msg_score > best_score:
                best_score = msg_score
                best_msg = content

        score = best_score + workspace_boost
        if score <= 0:
            continue
        hits.append(
            Hit(
                source="sessions",
                path=str(path),
                title=title,
                snippet=_clip(best_msg or title, 450),
                score=score,
                kind="session",
                meta={"session_id": path.stem.replace("session-", ""), "workspace": sess_ws},
            )
        )
    return hits


def _collect_plan(workspace: Path, terms: Sequence[str]) -> List[Hit]:
    path = workspace / ".switchbay" / "plan.json"
    data = _safe_read_json(path)
    if data is None:
        return []
    text = json.dumps(data, indent=2) if not isinstance(data, str) else data
    score = _score_text(text, terms)
    if score <= 0:
        return []
    return [
        Hit(
            source="plan",
            path=str(path),
            title="plan.json",
            snippet=_clip(text, 500),
            score=score + 0.5,
            kind="plan",
        )
    ]


def _collect_guides(workspace: Path, terms: Sequence[str]) -> List[Hit]:
    guide_dir = workspace / ".switchbay" / "runtime" / "guides"
    if not guide_dir.is_dir():
        return []
    hits: List[Hit] = []
    for path in sorted(guide_dir.glob("*.md")):
        if path.name == "INDEX.md":
            continue
        text = _safe_read_text(path, max_bytes=40_000)
        if not text:
            continue
        score = _score_text(f"{path.name}\n{text}", terms)
        if score <= 0:
            continue
        hits.append(
            Hit(
                source="guides",
                path=str(path),
                title=path.name,
                snippet=_clip(text, 400),
                score=score,
                kind="guide",
            )
        )
    return hits


def _gather_hits(
    query: str,
    workspace: Path,
    sources: Set[str],
) -> List[Hit]:
    terms = _query_terms(query)
    hits: List[Hit] = []
    if "context" in sources:
        hits.extend(_collect_context(terms))
    if "switchbay" in sources:
        hits.extend(_collect_switchbay_md(workspace, terms))
    if "notes" in sources:
        hits.extend(_collect_memory_notes(workspace, terms))
    if "facts" in sources:
        hits.extend(_collect_facts(workspace, terms))
    if "summary" in sources:
        hits.extend(_collect_summary(workspace, terms))
    if "knowledge" in sources:
        hits.extend(_collect_knowledge(workspace, terms))
    if "pins" in sources:
        hits.extend(_collect_pins(workspace, terms))
    if "sessions" in sources:
        hits.extend(_collect_sessions(workspace, terms))
    if "plan" in sources:
        hits.extend(_collect_plan(workspace, terms))
    if "guides" in sources:
        hits.extend(_collect_guides(workspace, terms))

    # Deduplicate near-identical snippets
    seen: Set[str] = set()
    unique: List[Hit] = []
    for hit in sorted(hits, key=lambda h: h.score, reverse=True):
        key = f"{hit.source}|{hit.path}|{hit.snippet[:120]}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(hit)
    return unique


def _inventory(workspace: Path) -> Dict[str, Any]:
    mem = workspace / ".switchbay" / "memory"
    return {
        "workspace": str(workspace),
        "global_context": str(GLOBAL_CONTEXT),
        "global_sessions": str(GLOBAL_SESSIONS),
        "present": {
            "SWITCHBAY.md": (workspace / "SWITCHBAY.md").is_file(),
            "memory/notes.md": (mem / "notes.md").is_file(),
            "memory/facts.json": (mem / "facts.json").is_file(),
            "memory/summary.md": (mem / "summary.md").is_file(),
            "knowledge/index.json": (workspace / ".switchbay" / "knowledge" / "index.json").is_file(),
            "pins.json": (workspace / ".switchbay" / "pins.json").is_file(),
            "plan.json": (workspace / ".switchbay" / "plan.json").is_file(),
            "user_context_dir": GLOBAL_CONTEXT.is_dir(),
            "sessions_dir": GLOBAL_SESSIONS.is_dir(),
        },
    }


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def search_memory(
    query: str,
    workspace: Optional[str] = None,
    limit: Any = 12,
    sources: Optional[str] = None,
    scope: str = "all",
) -> Dict[str, Any]:
    """Search Switchbay memory stores and return ranked hits.

    Use this to discover *where* something was remembered.
    """
    query = (query or "").strip()
    if not query or query in {"None", "null"}:
        raise ValueError("query is required")

    ws = _resolve_workspace(workspace)
    chosen = _parse_sources(sources)
    scope = (_noneish(scope) or "all").lower()
    if scope == "global":
        chosen &= {"context", "sessions"}
    elif scope == "workspace":
        chosen -= {"context"}
    elif scope != "all":
        raise ValueError("scope must be all, workspace, or global")

    limit_n = _parse_int(limit, 12, minimum=1, maximum=50)
    hits = _gather_hits(query, ws, chosen)[:limit_n]

    return {
        "ok": True,
        "tool": "search_memory",
        "query": query,
        "terms": _query_terms(query),
        "workspace": str(ws),
        "scope": scope,
        "sources": sorted(chosen),
        "count": len(hits),
        "hits": [asdict(h) for h in hits],
        "inventory": _inventory(ws),
        "hint": "Use recall_memory for a compact context pack from the best matches.",
    }


def recall_memory(
    query: str,
    workspace: Optional[str] = None,
    limit: Any = 8,
    sources: Optional[str] = None,
    scope: str = "all",
) -> Dict[str, Any]:
    """Recall the most relevant memory as a compact context pack.

    Use this when you need usable content for the current turn — not just hit metadata.
    """
    query = (query or "").strip()
    if not query or query in {"None", "null"}:
        raise ValueError("query is required")

    ws = _resolve_workspace(workspace)
    chosen = _parse_sources(sources)
    scope = (_noneish(scope) or "all").lower()
    if scope == "global":
        chosen &= {"context", "sessions"}
    elif scope == "workspace":
        chosen -= {"context"}
    elif scope != "all":
        raise ValueError("scope must be all, workspace, or global")

    limit_n = _parse_int(limit, 8, minimum=1, maximum=25)
    hits = _gather_hits(query, ws, chosen)[:limit_n]

    # Prefer durable stores in the assembled pack
    priority = {"facts": 0, "notes": 1, "switchbay": 2, "summary": 3, "context": 4, "pins": 5, "knowledge": 6, "plan": 7, "sessions": 8, "guides": 9}
    ordered = sorted(hits, key=lambda h: (priority.get(h.source, 50), -h.score))

    lines = [
        f"# Memory recall: {query}",
        f"Workspace: {ws}",
        f"Matches: {len(ordered)}",
        "",
    ]
    for i, hit in enumerate(ordered, 1):
        lines.append(f"## {i}. [{hit.source}] {hit.title}")
        lines.append(f"Path: {hit.path}")
        lines.append(hit.snippet)
        lines.append("")

    pack = "\n".join(lines).strip() + "\n"

    # Quick key/value extract from fact hits for easy consumption
    facts = [
        {"key": h.meta.get("key") or h.title, "value": h.snippet, "score": h.score}
        for h in ordered
        if h.source == "facts"
    ]

    return {
        "ok": True,
        "tool": "recall_memory",
        "query": query,
        "workspace": str(ws),
        "scope": scope,
        "sources": sorted(chosen),
        "count": len(ordered),
        "facts": facts,
        "hits": [asdict(h) for h in ordered],
        "context_pack": pack,
        "inventory": _inventory(ws),
        "usage": "Paste or cite context_pack / facts in your reasoning. Do not invent memories that are not listed.",
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli() -> None:
    parser = argparse.ArgumentParser(
        description="Memory Search Engine — on-demand Switchbay memory recall for models"
    )
    sub = parser.add_subparsers(dest="tool", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--query", required=True, help="What to search or recall")
        p.add_argument(
            "--workspace",
            default=None,
            help="Project root (defaults to SWITCHBAY_WORKSPACE or cwd)",
        )
        p.add_argument(
            "--limit",
            default=None,
            help="Max hits to return",
        )
        p.add_argument(
            "--sources",
            default=None,
            help=f"Comma-separated sources or 'all'. Default: {DEFAULT_SOURCES}",
        )
        p.add_argument(
            "--scope",
            default="all",
            help="all | workspace | global",
        )

    p = sub.add_parser("search_memory", help="Ranked search across Switchbay memory stores")
    add_common(p)
    p.set_defaults(limit="12")

    p = sub.add_parser("recall_memory", help="Compact context pack from best memory matches")
    add_common(p)
    p.set_defaults(limit="8")


    args = parser.parse_args()
    kwargs = {
        "query": args.query,
        "workspace": args.workspace,
        "limit": args.limit,
        "sources": args.sources,
        "scope": args.scope,
    }

    try:
        if args.tool == "search_memory":
            result = search_memory(**kwargs)
        elif args.tool == "recall_memory":
            result = recall_memory(**kwargs)
        else:
            raise ValueError(f"Unknown tool: {args.tool}")
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    _cli()
