"""Working memory utilities for GumOps agent.

This module provides a small persistent working-memory store used by the
agent to keep recent facts about the Gumroad store (products, sales summary,
account info, arbitrary notes). It is intentionally lightweight and file-
backed (JSON) so it can be inspected and edited by humans during development.

"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from engines.Python.Gumroad.model_tools import list_gumroad_products, gumroad_sales_summary, get_gumroad_account_info

MEMORY_DIR = Path.home() / ".gumops_working_memory"
MEMORY_FILE = MEMORY_DIR / "memory.json"

STORE_CONTEXT = """
BOUND WITH PURPOSE — STORE CONTEXT

Brand Core: Power Exchange With Purpose

Central beliefs:
- Authority without accountability is not leadership.
- Submission without agency is not trust.

The store is a practical resource library for adults building healthier structured dynamics.
Main promise: Before people go deeper, BWP helps them get clearer.

Key positioning:
- Educational, platform-safe, non-explicit, relationship-centered
- Practical guides and worksheets for consent, communication, structure, emotional safety, accountability, care

Product types:
- Free / pay-what-you-want worksheets
- Short checklists
- Beginner-friendly mini-guides
- Fillable reflection tools
- Downloadable templates
- Practical planners
- Starter packs
- Bundle packs

Tone: Mature, direct, protective, emotionally intelligent, values-driven, grounded.

Core messaging:
- Structure should make you feel safer, not smaller.
- Submission should not erase your voice.
- Dominance without accountability is just ego wearing a title.
- A collar is responsibility, not decoration.
- Healthy surrender still has a voice.
- Power without purpose becomes control.
- Care is not optional when trust is involved.
"""


@dataclass
class MemoryItem:
    key: str
    value: Any
    timestamp: str
    metadata: Dict[str, Any]


def _ensure_store() -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    if not MEMORY_FILE.exists():
        MEMORY_FILE.write_text(json.dumps({}), encoding="utf-8")


def _read_store() -> Dict[str, Any]:
    _ensure_store()
    try:
        return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_store(data: Dict[str, Any]) -> None:
    _ensure_store()
    MEMORY_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def add_memory(key: str, value: Any, metadata: Optional[Dict[str, Any]] = None) -> MemoryItem:
    """Add or update a memory entry by key."""
    store = _read_store()
    item = MemoryItem(key=key, value=value, timestamp=datetime.utcnow().isoformat() + "Z", metadata=metadata or {})
    store[key] = asdict(item)
    _write_store(store)
    return item


def get_memory(key: str) -> Optional[MemoryItem]:
    """Retrieve a memory item by key, or None if not found."""
    store = _read_store()
    raw = store.get(key)
    if not raw:
        return None
    return MemoryItem(**raw)


def list_memory_keys() -> List[str]:
    store = _read_store()
    return sorted(list(store.keys()))


def find_memory(predicate) -> List[MemoryItem]:
    """Return items matching a predicate function that accepts MemoryItem."""
    store = _read_store()
    results: List[MemoryItem] = []
    for raw in store.values():
        try:
            item = MemoryItem(**raw)
        except Exception:
            continue
        if predicate(item):
            results.append(item)
    return results


def summarize_memory(max_items: int = 20) -> str:
    """Return a short text summary of recent memory items."""
    store = _read_store()
    items = sorted(store.values(), key=lambda r: r.get("timestamp", ""), reverse=True)[:max_items]
    lines: List[str] = []
    for raw in items:
        key = raw.get("key")
        ts = raw.get("timestamp")
        val = raw.get("value")
        snippet = repr(val)
        if len(snippet) > 200:
            snippet = snippet[:197] + "..."
        lines.append(f"{ts} {key}: {snippet}")
    return "\n".join(lines) if lines else "(no memory)"


def refresh_from_gumroad() -> Dict[str, str]:
    """Fetch latest Gumroad data using project tools and store in memory.

    Returns dict of keys added/updated to their stored timestamp.
    """
    results: Dict[str, str] = {}
    try:
        products = list_gumroad_products()
        add_memory("gumroad:products", products, metadata={"source": "gumroad_api"})
        results["gumroad:products"] = datetime.utcnow().isoformat() + "Z"
    except Exception as exc:  # pragma: no cover - best-effort
        results["gumroad:products:error"] = str(exc)

    try:
        summary = gumroad_sales_summary()
        add_memory("gumroad:sales_summary", summary, metadata={"source": "gumroad_api"})
        results["gumroad:sales_summary"] = datetime.utcnow().isoformat() + "Z"
    except Exception as exc:  # pragma: no cover
        results["gumroad:sales_summary:error"] = str(exc)

    try:
        account = get_gumroad_account_info()
        add_memory("gumroad:account_info", account, metadata={"source": "gumroad_api"})
        results["gumroad:account_info"] = datetime.utcnow().isoformat() + "Z"
    except Exception as exc:  # pragma: no cover
        results["gumroad:account_info:error"] = str(exc)

    return results


__all__ = [
    "STORE_CONTEXT",
    "MemoryItem",
    "add_memory",
    "get_memory",
    "list_memory_keys",
    "find_memory",
    "summarize_memory",
    "refresh_from_gumroad",
]

