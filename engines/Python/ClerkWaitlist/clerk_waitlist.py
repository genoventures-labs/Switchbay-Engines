"""Clerk Waitlist Engine — inspect Clerk waitlist entries through the Backend API.

Usage:
  python3 clerk_waitlist.py status
  python3 clerk_waitlist.py list_entries --status pending --limit 25
  python3 clerk_waitlist.py get_entry --entry_id waitlist_...
  python3 clerk_waitlist.py summarize --fetch_all true

Authentication:
  export CLERK_SECRET_KEY=sk_test_...
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.parse
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_BASE = "https://api.clerk.com/v1"
VALID_STATUSES = {"pending", "invited", "completed", "rejected"}
VALID_ORDER_BY = {
    "created_at", "+created_at", "-created_at",
    "invited_at", "+invited_at", "-invited_at",
    "email_address", "+email_address", "-email_address",
}


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


def _truthy(value: Any, default: bool = False) -> bool:
    text = _noneish(value)
    if text is None:
        return default
    lowered = text.lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return default


def _secret_key() -> str:
    key = _noneish(os.getenv("CLERK_SECRET_KEY"))
    if not key:
        raise RuntimeError("CLERK_SECRET_KEY is required. Create one in Clerk Dashboard > API Keys.")
    return key


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # type: ignore
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_SSL = _ssl_context()


def _request(path: str, params: Optional[Dict[str, Any]] = None, timeout: int = 30) -> Any:
    query = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})
    url = f"{API_BASE}{path}" + (f"?{query}" if query else "")
    req = Request(
        url,
        headers={
            "Authorization": f"Bearer {_secret_key()}",
            "Accept": "application/json",
            "User-Agent": "Switchbay-Clerk-Waitlist/1.0",
        },
    )
    try:
        with urlopen(req, timeout=timeout, context=_SSL) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(body)
        except json.JSONDecodeError:
            detail = body
        raise RuntimeError(f"Clerk API returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach Clerk API: {exc.reason}") from exc


def _iso_ms(value: Any) -> Optional[str]:
    if not isinstance(value, (int, float)):
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()


def _normalize_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": entry.get("id"),
        "email_address": entry.get("email_address"),
        "status": entry.get("status"),
        "created_at": entry.get("created_at"),
        "created_at_iso": _iso_ms(entry.get("created_at")),
        "updated_at": entry.get("updated_at"),
        "updated_at_iso": _iso_ms(entry.get("updated_at")),
        "is_locked": entry.get("is_locked", False),
        "invitation": entry.get("invitation"),
    }


def status() -> Dict[str, Any]:
    result = _request("/waitlist_entries", {"limit": 1, "offset": 0})
    return {
        "ok": True,
        "configured": True,
        "api_base": API_BASE,
        "total_count": result.get("total_count", 0),
        "message": "Clerk waitlist API is reachable.",
    }


def list_entries(
    status_filter: Any = None,
    query: Any = None,
    order_by: Any = None,
    limit: Any = 25,
    offset: Any = 0,
) -> Dict[str, Any]:
    status_value = _noneish(status_filter)
    query_value = _noneish(query)
    order_value = _noneish(order_by) or "-created_at"
    limit_value = _parse_int(limit, 25, 1, 500)
    offset_value = _parse_int(offset, 0, 0, 1_000_000)

    if status_value and status_value not in VALID_STATUSES:
        raise ValueError(f"status must be one of: {', '.join(sorted(VALID_STATUSES))}")
    if order_value not in VALID_ORDER_BY:
        raise ValueError("order_by must target created_at, invited_at, or email_address, optionally prefixed with + or -")

    payload = _request(
        "/waitlist_entries",
        {
            "status": status_value,
            "query": query_value,
            "order_by": order_value,
            "limit": limit_value,
            "offset": offset_value,
        },
    )
    entries = [_normalize_entry(item) for item in payload.get("data", [])]
    total = payload.get("total_count", len(entries))
    return {
        "ok": True,
        "summary": {
            "returned": len(entries),
            "total_count": total,
            "offset": offset_value,
            "limit": limit_value,
            "has_more": offset_value + len(entries) < total,
        },
        "filters": {"status": status_value, "query": query_value, "order_by": order_value},
        "data": entries,
    }


def get_entry(entry_id: Any) -> Dict[str, Any]:
    entry_value = _noneish(entry_id)
    if not entry_value:
        raise ValueError("entry_id is required")
    payload = _request("/waitlist_entries", {"query": entry_value, "limit": 100, "offset": 0})
    matches = [_normalize_entry(item) for item in payload.get("data", [])]
    exact = next((item for item in matches if item.get("id") == entry_value), None)
    if exact is None:
        raise LookupError(f"No waitlist entry found with id {entry_value}")
    return {"ok": True, "data": exact}


def summarize(fetch_all: Any = True, page_size: Any = 500) -> Dict[str, Any]:
    fetch_everything = _truthy(fetch_all, True)
    size = _parse_int(page_size, 500, 1, 500)
    offset = 0
    entries: List[Dict[str, Any]] = []
    total_count = 0

    while True:
        payload = _request("/waitlist_entries", {"limit": size, "offset": offset, "order_by": "+created_at"})
        batch = payload.get("data", [])
        total_count = payload.get("total_count", len(batch))
        entries.extend(batch)
        offset += len(batch)
        if not fetch_everything or not batch or offset >= total_count:
            break

    counts = Counter(str(item.get("status", "unknown")) for item in entries)
    created_values = [item.get("created_at") for item in entries if isinstance(item.get("created_at"), (int, float))]
    return {
        "ok": True,
        "summary": {
            "total_count": total_count,
            "fetched_count": len(entries),
            "by_status": dict(sorted(counts.items())),
            "oldest_created_at": _iso_ms(min(created_values)) if created_values else None,
            "newest_created_at": _iso_ms(max(created_values)) if created_values else None,
            "complete": len(entries) >= total_count,
        },
    }


def _cli() -> None:
    parser = argparse.ArgumentParser(description="Inspect Clerk waitlist entries through the Backend API.")
    sub = parser.add_subparsers(dest="tool", required=True)

    sub.add_parser("status")

    p = sub.add_parser("list_entries")
    p.add_argument("--status", dest="status_filter", default=None)
    p.add_argument("--query", default=None)
    p.add_argument("--order_by", default="-created_at")
    p.add_argument("--limit", default="25")
    p.add_argument("--offset", default="0")

    p = sub.add_parser("get_entry")
    p.add_argument("--entry_id", required=True)

    p = sub.add_parser("summarize")
    p.add_argument("--fetch_all", default="true")
    p.add_argument("--page_size", default="500")

    args = parser.parse_args()
    try:
        if args.tool == "status":
            result = status()
        elif args.tool == "list_entries":
            result = list_entries(args.status_filter, args.query, args.order_by, args.limit, args.offset)
        elif args.tool == "get_entry":
            result = get_entry(args.entry_id)
        elif args.tool == "summarize":
            result = summarize(args.fetch_all, args.page_size)
        else:
            raise ValueError(f"Unknown tool: {args.tool}")
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    _cli()
