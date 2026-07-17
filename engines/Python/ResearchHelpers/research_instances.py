"""
Research Instances Engine
=======================================
A tool for creating and managing research instances.

Tools:
- create_research_instance: Create a new research instance.
- list_research_instances: List all research instances.
- delete_research_instance: Delete a research instance.
- get_research_instance: Get a research instance.
- update_research_instance: Update a research instance.

Usage:
  python engines/Python/ResearchHelpers/research_instances.py create_research_instance --name "..." --description "..."
  python engines/Python/ResearchHelpers/research_instances.py list_research_instances
  python engines/Python/ResearchHelpers/research_instances.py delete_research_instance --name "..."
  python engines/Python/ResearchHelpers/research_instances.py get_research_instance --name "..."
  python engines/Python/ResearchHelpers/research_instances.py update_research_instance --name "..." --description "..."

Data is stored in ~/.research_instances/instances.json (portable, local-first).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import ssl
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATA_DIR = Path.home() / ".research_instances"
INDEX_FILE = DATA_DIR / "instances.json"
INSTANCES_DIR = DATA_DIR / "workspaces"

STATUSES = {"active", "paused", "archived", "done"}


def _ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    INSTANCES_DIR.mkdir(parents=True, exist_ok=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# SSL / light page title fetch (optional source enrichment)
# ---------------------------------------------------------------------------

def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    try:
        import urllib.request as _ur

        ctx = ssl.create_default_context()
        _ur.urlopen("https://example.com", context=ctx, timeout=5).close()
        return ctx
    except Exception:
        pass
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


_SSL = _ssl_context()
UA = "Mozilla/5.0 (compatible; SwitchbayResearchInstances/1.0)"


def _fetch_page_title(url: str) -> Optional[str]:
    """Best-effort HTML <title> extraction. Returns None on failure."""
    try:
        req = Request(url, headers={"User-Agent": UA})
        with urlopen(req, timeout=12, context=_SSL) as resp:
            raw = resp.read(65536).decode("utf-8", errors="replace")
        match = re.search(r"<title[^>]*>(.*?)</title>", raw, re.IGNORECASE | re.DOTALL)
        if not match:
            return None
        title = re.sub(r"\s+", " ", match.group(1)).strip()
        return title[:200] or None
    except (URLError, HTTPError, TimeoutError, OSError, Exception):
        return None


# ---------------------------------------------------------------------------
# Index store
# ---------------------------------------------------------------------------

def _empty_index() -> Dict[str, Any]:
    return {"instances": [], "created_at": _now()}


def _load_index() -> Dict[str, Any]:
    if INDEX_FILE.exists():
        try:
            data = json.loads(INDEX_FILE.read_text("utf-8"))
            if isinstance(data, dict) and isinstance(data.get("instances"), list):
                return data
        except Exception:
            pass
    return _empty_index()


def _save_index(index: Dict[str, Any]) -> None:
    _ensure_dirs()
    index["updated_at"] = _now()
    INDEX_FILE.write_text(json.dumps(index, indent=2, ensure_ascii=False), "utf-8")


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return slug[:64] or "instance"


def _unique_slug(name: str, existing: List[Dict[str, Any]], exclude_id: Optional[str] = None) -> str:
    base = _slugify(name)
    slug = base
    n = 2
    taken = {
        (i.get("slug") or i.get("id"))
        for i in existing
        if i.get("id") != exclude_id
    }
    while slug in taken:
        slug = f"{base}-{n}"
        n += 1
    return slug


def _find_instance(index: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    """Find by exact name, id, or slug (case-insensitive for name/slug)."""
    key = (name or "").strip()
    if not key:
        return None
    key_l = key.lower()
    for inst in index.get("instances", []):
        if inst.get("id") == key:
            return inst
        if str(inst.get("name", "")).lower() == key_l:
            return inst
        if str(inst.get("slug", "")).lower() == key_l:
            return inst
    return None


def _parse_tags(tags: Optional[str]) -> List[str]:
    if not tags or tags in {"None", "null"}:
        return []
    # Accept JSON array or comma-separated
    raw = tags.strip()
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(t).strip() for t in parsed if str(t).strip()]
        except json.JSONDecodeError:
            pass
    return [t.strip() for t in raw.split(",") if t.strip()]


def _workspace_path(slug: str) -> Path:
    return INSTANCES_DIR / slug


def _write_workspace_readme(inst: Dict[str, Any]) -> Path:
    ws = _workspace_path(inst["slug"])
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "notes").mkdir(exist_ok=True)
    (ws / "sources").mkdir(exist_ok=True)
    (ws / "artifacts").mkdir(exist_ok=True)

    lines = [
        f"# {inst['name']}",
        "",
        f"**Status:** {inst.get('status', 'active')}  ",
        f"**Created:** {inst.get('created_at', '')}  ",
        f"**Updated:** {inst.get('updated_at', '')}  ",
        "",
        "## Description",
        inst.get("description") or "_No description._",
        "",
        "## Tags",
        ", ".join(inst.get("tags") or []) or "_None._",
        "",
        "## Notes",
    ]
    notes = inst.get("notes") or []
    if notes:
        for note in notes[-20:]:
            lines.append(f"- [{note.get('at', '')}] {note.get('text', '')}")
    else:
        lines.append("_No notes yet._")

    lines.extend(["", "## Sources"])
    sources = inst.get("sources") or []
    if sources:
        for src in sources:
            title = src.get("title") or src.get("url")
            lines.append(f"- [{title}]({src.get('url', '')})")
    else:
        lines.append("_No sources yet._")

    lines.extend(
        [
            "",
            "## Workspace layout",
            "- `notes/` — freeform note files",
            "- `sources/` — saved source snapshots",
            "- `artifacts/` — reports and deliverables",
            "",
            f"_id: `{inst['id']}` · slug: `{inst['slug']}`_",
            "",
        ]
    )
    readme = ws / "README.md"
    readme.write_text("\n".join(lines), "utf-8")
    (ws / "instance.json").write_text(json.dumps(inst, indent=2, ensure_ascii=False), "utf-8")
    return ws


def _public(inst: Dict[str, Any]) -> Dict[str, Any]:
    """Return a stable public view of an instance."""
    return {
        "id": inst.get("id"),
        "name": inst.get("name"),
        "slug": inst.get("slug"),
        "description": inst.get("description"),
        "status": inst.get("status"),
        "tags": list(inst.get("tags") or []),
        "notes": list(inst.get("notes") or []),
        "sources": list(inst.get("sources") or []),
        "note_count": len(inst.get("notes") or []),
        "source_count": len(inst.get("sources") or []),
        "workspace": str(_workspace_path(inst["slug"])),
        "created_at": inst.get("created_at"),
        "updated_at": inst.get("updated_at"),
    }


def _noneish(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if text in {"", "None", "null"}:
        return None
    return text


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def create_research_instance(
    name: str,
    description: str = "",
    tags: Optional[str] = None,
    status: str = "active",
    note: Optional[str] = None,
    source_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new research instance with a local workspace."""
    name = (name or "").strip()
    if not name:
        raise ValueError("name is required")

    status = (_noneish(status) or "active").strip().lower()
    if status not in STATUSES:
        raise ValueError(f"status must be one of: {', '.join(sorted(STATUSES))}")

    description = _noneish(description) or ""
    note = _noneish(note)
    source_url = _noneish(source_url)

    index = _load_index()
    if _find_instance(index, name):
        raise ValueError(f"research instance already exists: {name}")

    slug = _unique_slug(name, index.get("instances", []))
    slug_token = slug[:12].strip("-") or "inst"
    inst_id = f"ri_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{slug_token}"
    now = _now()

    notes: List[Dict[str, str]] = []
    if note:
        notes.append({"at": now, "text": note})

    sources: List[Dict[str, str]] = []
    if source_url:
        title = _fetch_page_title(source_url) or source_url
        sources.append({"url": source_url, "title": title, "added_at": now})

    inst: Dict[str, Any] = {
        "id": inst_id,
        "name": name,
        "slug": slug,
        "description": description,
        "status": status,
        "tags": _parse_tags(tags),
        "notes": notes,
        "sources": sources,
        "created_at": now,
        "updated_at": now,
    }

    workspace = _write_workspace_readme(inst)
    if source_url:
        src_file = workspace / "sources" / f"{_slugify(title)[:40] or 'source'}.json"
        src_file.write_text(json.dumps(sources[-1], indent=2, ensure_ascii=False), "utf-8")

    index.setdefault("instances", []).append(inst)
    _save_index(index)

    return {
        "ok": True,
        "tool": "create_research_instance",
        "instance": _public(inst),
        "index_file": str(INDEX_FILE),
    }


def list_research_instances(
    status: Optional[str] = None,
    tag: Optional[str] = None,
    query: Optional[str] = None,
) -> Dict[str, Any]:
    """List research instances, optionally filtered."""
    status = _noneish(status)
    tag = _noneish(tag)
    query = _noneish(query)

    if status:
        status = status.lower()
        if status not in STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(STATUSES))}")

    index = _load_index()
    items = list(index.get("instances", []))

    if status:
        items = [i for i in items if i.get("status") == status]
    if tag:
        tag_l = tag.lower()
        items = [i for i in items if tag_l in [str(t).lower() for t in (i.get("tags") or [])]]
    if query:
        q = query.lower()
        items = [
            i
            for i in items
            if q in str(i.get("name", "")).lower()
            or q in str(i.get("description", "")).lower()
            or q in str(i.get("slug", "")).lower()
        ]

    # newest updated first
    items.sort(key=lambda i: i.get("updated_at") or i.get("created_at") or "", reverse=True)

    summaries = [
        {
            "id": i.get("id"),
            "name": i.get("name"),
            "slug": i.get("slug"),
            "status": i.get("status"),
            "tags": i.get("tags") or [],
            "note_count": len(i.get("notes") or []),
            "source_count": len(i.get("sources") or []),
            "updated_at": i.get("updated_at"),
            "workspace": str(_workspace_path(i["slug"])),
        }
        for i in items
    ]

    return {
        "ok": True,
        "tool": "list_research_instances",
        "count": len(summaries),
        "filters": {"status": status, "tag": tag, "query": query},
        "instances": summaries,
        "index_file": str(INDEX_FILE),
    }


def get_research_instance(name: str) -> Dict[str, Any]:
    """Get one research instance by name, id, or slug."""
    name = (name or "").strip()
    if not name:
        raise ValueError("name is required")

    index = _load_index()
    inst = _find_instance(index, name)
    if not inst:
        raise ValueError(f"research instance not found: {name}")

    # Refresh workspace mirror so README stays current
    workspace = _write_workspace_readme(inst)

    return {
        "ok": True,
        "tool": "get_research_instance",
        "instance": _public(inst),
        "workspace": str(workspace),
        "index_file": str(INDEX_FILE),
    }


def update_research_instance(
    name: str,
    description: Optional[str] = None,
    status: Optional[str] = None,
    tags: Optional[str] = None,
    note: Optional[str] = None,
    source_url: Optional[str] = None,
    new_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Update fields on an existing research instance.

    Pass tags as a full replacement list (comma-separated or JSON array).
    Use note / source_url to append.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("name is required")

    description = _noneish(description)
    status = _noneish(status)
    tags_raw = _noneish(tags)
    note = _noneish(note)
    source_url = _noneish(source_url)
    new_name = _noneish(new_name)

    if not any([description is not None, status, tags_raw is not None, note, source_url, new_name]):
        raise ValueError(
            "nothing to update — pass --description, --status, --tags, --note, --source_url, and/or --new_name"
        )

    if status:
        status = status.lower()
        if status not in STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(STATUSES))}")

    index = _load_index()
    inst = _find_instance(index, name)
    if not inst:
        raise ValueError(f"research instance not found: {name}")

    now = _now()
    changed: List[str] = []

    if new_name and new_name != inst["name"]:
        # Disallow colliding names
        other = _find_instance(index, new_name)
        if other and other.get("id") != inst.get("id"):
            raise ValueError(f"another instance already uses name: {new_name}")
        old_slug = inst["slug"]
        inst["name"] = new_name
        inst["slug"] = _unique_slug(new_name, index.get("instances", []), exclude_id=inst["id"])
        old_ws = _workspace_path(old_slug)
        new_ws = _workspace_path(inst["slug"])
        if old_ws.exists() and old_ws != new_ws:
            if new_ws.exists():
                raise ValueError(f"workspace already exists for slug: {inst['slug']}")
            old_ws.rename(new_ws)
        changed.append("name")

    if description is not None:
        inst["description"] = description
        changed.append("description")

    if status:
        inst["status"] = status
        changed.append("status")

    if tags_raw is not None:
        inst["tags"] = _parse_tags(tags_raw)
        changed.append("tags")

    if note:
        inst.setdefault("notes", []).append({"at": now, "text": note})
        changed.append("note")
        notes_dir = _workspace_path(inst["slug"]) / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        (notes_dir / f"note_{stamp}.md").write_text(f"# Note\n\n{note}\n", "utf-8")

    if source_url:
        # Dedup by URL
        existing_urls = {s.get("url") for s in inst.get("sources") or []}
        if source_url not in existing_urls:
            title = _fetch_page_title(source_url) or source_url
            entry = {"url": source_url, "title": title, "added_at": now}
            inst.setdefault("sources", []).append(entry)
            changed.append("source_url")
            src_dir = _workspace_path(inst["slug"]) / "sources"
            src_dir.mkdir(parents=True, exist_ok=True)
            (src_dir / f"{_slugify(title)[:40] or 'source'}.json").write_text(
                json.dumps(entry, indent=2, ensure_ascii=False),
                "utf-8",
            )
        else:
            changed.append("source_url(already_present)")

    inst["updated_at"] = now
    workspace = _write_workspace_readme(inst)
    _save_index(index)

    return {
        "ok": True,
        "tool": "update_research_instance",
        "changed": changed,
        "instance": _public(inst),
        "workspace": str(workspace),
        "index_file": str(INDEX_FILE),
    }


def delete_research_instance(
    name: str,
    keep_workspace: bool = False,
) -> Dict[str, Any]:
    """Delete a research instance from the index (and optionally its workspace)."""
    name = (name or "").strip()
    if not name:
        raise ValueError("name is required")

    index = _load_index()
    inst = _find_instance(index, name)
    if not inst:
        raise ValueError(f"research instance not found: {name}")

    index["instances"] = [i for i in index.get("instances", []) if i.get("id") != inst.get("id")]
    _save_index(index)

    workspace = _workspace_path(inst["slug"])
    removed_workspace = False
    if not keep_workspace and workspace.exists():
        shutil.rmtree(workspace)
        removed_workspace = True

    return {
        "ok": True,
        "tool": "delete_research_instance",
        "deleted": {
            "id": inst.get("id"),
            "name": inst.get("name"),
            "slug": inst.get("slug"),
        },
        "workspace_removed": removed_workspace,
        "workspace": str(workspace),
        "index_file": str(INDEX_FILE),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli() -> None:
    parser = argparse.ArgumentParser(description="Research Instances Engine for Switchbay")
    sub = parser.add_subparsers(dest="tool", required=True)

    p = sub.add_parser("create_research_instance", help="Create a new research instance")
    p.add_argument("--name", required=True, help="Unique instance name")
    p.add_argument("--description", default="", help="What this research is about")
    p.add_argument("--tags", default=None, help="Comma-separated or JSON array of tags")
    p.add_argument("--status", default="active", help="active | paused | archived | done")
    p.add_argument("--note", default=None, help="Optional opening note")
    p.add_argument("--source_url", default=None, help="Optional first source URL")

    p = sub.add_parser("list_research_instances", help="List research instances")
    p.add_argument("--status", default=None, help="Filter by status")
    p.add_argument("--tag", default=None, help="Filter by tag")
    p.add_argument("--query", default=None, help="Substring search on name/description/slug")

    p = sub.add_parser("get_research_instance", help="Get one research instance")
    p.add_argument("--name", required=True, help="Name, id, or slug")

    p = sub.add_parser("update_research_instance", help="Update a research instance")
    p.add_argument("--name", required=True, help="Current name, id, or slug")
    p.add_argument("--description", default=None, help="New description")
    p.add_argument("--status", default=None, help="active | paused | archived | done")
    p.add_argument("--tags", default=None, help="Replace tags (comma-separated or JSON array)")
    p.add_argument("--note", default=None, help="Append a research note")
    p.add_argument("--source_url", default=None, help="Append a source URL")
    p.add_argument("--new_name", default=None, help="Rename the instance")

    p = sub.add_parser("delete_research_instance", help="Delete a research instance")
    p.add_argument("--name", required=True, help="Name, id, or slug")
    p.add_argument(
        "--keep_workspace",
        default="false",
        help="If true, keep ~/.research_instances/workspaces/<slug>/ (default false)",
    )

    args = parser.parse_args()
    kwargs = {k: v for k, v in vars(args).items() if k != "tool"}

    try:
        if args.tool == "create_research_instance":
            result = create_research_instance(**kwargs)
        elif args.tool == "list_research_instances":
            result = list_research_instances(**kwargs)
        elif args.tool == "get_research_instance":
            result = get_research_instance(**kwargs)
        elif args.tool == "update_research_instance":
            result = update_research_instance(**kwargs)
        elif args.tool == "delete_research_instance":
            keep_raw = str(kwargs.pop("keep_workspace", "false")).strip().lower()
            keep = keep_raw in {"1", "true", "yes", "on"}
            result = delete_research_instance(keep_workspace=keep, **kwargs)
        else:
            raise ValueError(f"Unknown tool: {args.tool}")

        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    _cli()
