"""PageTend Helper Engine

Read-only stats and status tools for PageTend's JSON API.
Docs: PageTend/docs/pagetend-api-integration.md

Tools:
  status          — Ping base URL + report config
  analytics       — GET /api/pagetend/analytics (richest aggregated stats)
  dashboard       — GET /api/pagetend/dashboard (safe to poll; check fallback)
  meta_live       — GET /api/meta/live (live Meta page + recent posts)
  settings        — GET /api/pagetend/settings (counts + integration health)
  signals         — GET /api/pagetend/signals (inbox-derived product signals)
  list_posts      — GET /api/pagetend/posts
  list_inbox      — GET /api/pagetend/inbox
  views_per_post  — Rolling-window posts published + views + views/post


Config (first match wins):
  1. --base_url CLI flag
  2. PAGETEND_BASE_URL env
  3. ~/.pagetend/config.json  {"base_url": "https://..."}
  4. http://localhost:3000

Usage:
  python engines/Python/PagetendHelper/pagetend_helper.py analytics
  python engines/Python/PagetendHelper/pagetend_helper.py views_per_post --days 30
  python engines/Python/PagetendHelper/pagetend_helper.py dashboard --base_url http://localhost:3000

NOTE: PageTend API has no auth. Prefer a private/local URL. This engine is
read-only by design — it does not call POST/PATCH/PUT/DELETE.
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CONFIG_DIR = Path.home() / ".pagetend"
CONFIG_FILE = CONFIG_DIR / "config.json"
DEFAULT_BASE_URL = "http://localhost:3000"
UA = "Mozilla/5.0 (compatible; SwitchbayPageTendHelper/1.0)"


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    ctx = ssl.create_default_context()
    try:
        urllib.request.urlopen("https://example.com", context=ctx, timeout=5).close()
        return ctx
    except Exception:
        pass
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


_SSL = _ssl_context()


def _noneish(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if text in {"", "None", "null"}:
        return None
    return text


def _truthy(value: Any, default: bool = False) -> bool:
    """Parse CLI/engine truthy flags. Switchbay interpolates missing args as 'None'."""
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"", "none", "null"}:
        return default
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_int(value: Any, default: int, *, minimum: int = 1, maximum: int = 365) -> int:
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


def _load_config() -> Dict[str, Any]:
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text("utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def resolve_base_url(base_url: Optional[str] = None) -> str:
    for candidate in (
        _noneish(base_url),
        _noneish(os.environ.get("PAGETEND_BASE_URL")),
        _noneish(str(_load_config().get("base_url") or "")),
        DEFAULT_BASE_URL,
    ):
        if candidate:
            return candidate.rstrip("/")
    return DEFAULT_BASE_URL


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _request(
    method: str,
    base_url: str,
    path: str,
    timeout: int = 30,
) -> Dict[str, Any]:
    url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    req = urllib.request.Request(
        url,
        method=method.upper(),
        headers={
            "User-Agent": UA,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            headers = {k.lower(): v for k, v in resp.headers.items()}
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        headers = {k.lower(): v for k, v in (exc.headers.items() if exc.headers else [])}
        status = exc.code
        try:
            body = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            body = {"raw": raw[:2000]}
        return {
            "ok": False,
            "status": status,
            "url": url,
            "error": body.get("error") if isinstance(body, dict) else str(body),
            "body": body,
            "headers": {
                "x-pagetend-fallback": headers.get("x-pagetend-fallback"),
            },
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": 0,
            "url": url,
            "error": str(exc),
            "body": None,
            "headers": {},
        }

    try:
        body = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return {
            "ok": False,
            "status": status,
            "url": url,
            "error": "response was not JSON",
            "body": {"raw": raw[:2000]},
            "headers": {
                "x-pagetend-fallback": headers.get("x-pagetend-fallback"),
            },
        }

    ok = 200 <= status < 300
    if isinstance(body, dict) and body.get("error") and status >= 400:
        ok = False

    return {
        "ok": ok,
        "status": status,
        "url": url,
        "error": None if ok else (body.get("error") if isinstance(body, dict) else "request failed"),
        "body": body,
        "headers": {
            "x-pagetend-fallback": headers.get("x-pagetend-fallback"),
        },
    }


def _wrap(tool: str, base_url: str, result: Dict[str, Any], summary: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "ok": bool(result.get("ok")),
        "tool": tool,
        "base_url": base_url,
        "status": result.get("status"),
        "url": result.get("url"),
    }
    if result.get("headers", {}).get("x-pagetend-fallback") is not None:
        out["fallback"] = str(result["headers"]["x-pagetend-fallback"]).lower() == "true"
    if result.get("error"):
        out["error"] = result["error"]
    if summary is not None:
        out["summary"] = summary
        out["data"] = result.get("body")
    else:
        out["data"] = result.get("body")
    return out


# ---------------------------------------------------------------------------
# Summaries (compact for models)
# ---------------------------------------------------------------------------

def _summarize_analytics(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {"note": "unexpected analytics payload"}
    posts = data.get("posts") or {}
    media = data.get("media") or {}
    inbox = data.get("inbox") or {}
    automation = data.get("automation") or {}
    meta = data.get("meta") or {}
    page = meta.get("page") or {}
    totals = meta.get("totals") or {}
    top = meta.get("topPost")
    return {
        "generatedAt": data.get("generatedAt"),
        "workspaceName": data.get("workspaceName"),
        "posts": {
            "total": posts.get("total"),
            "draft": posts.get("draft"),
            "ready": posts.get("ready"),
            "scheduled": posts.get("scheduled"),
            "published": posts.get("published"),
        },
        "media": {"stored": media.get("stored"), "total": media.get("total")},
        "inbox": {
            "total": inbox.get("total"),
            "open": inbox.get("open"),
            "highPriority": inbox.get("highPriority"),
        },
        "automation": {
            "enabled": automation.get("enabled"),
            "total": automation.get("total"),
        },
        "meta": {
            "connected": meta.get("connected"),
            "error": meta.get("error"),
            "pageName": page.get("name"),
            "followers": page.get("followersCount") or page.get("fanCount"),
            "totals": totals,
            "topPostId": (top or {}).get("id") if isinstance(top, dict) else None,
            "recentPostCount": len(meta.get("recentPosts") or []),
        },
    }


def _summarize_dashboard(data: Any, fallback: bool) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {"fallback": fallback, "note": "unexpected dashboard payload"}
    campaign = data.get("campaign") or {}
    rules = data.get("automationRules") or []
    return {
        "fallback": fallback,
        "workspaceName": data.get("workspaceName"),
        "calendarPosts": len(data.get("calendarPosts") or []),
        "queuedPosts": len(data.get("queuedPosts") or []),
        "mediaItems": len(data.get("mediaItems") or []),
        "campaign": {
            "name": campaign.get("name"),
            "progress": campaign.get("progress"),
            "postsPlanned": campaign.get("postsPlanned"),
            "reach": campaign.get("reach"),
            "engagementRate": campaign.get("engagementRate"),
        },
        "automationEnabled": sum(1 for r in rules if isinstance(r, dict) and r.get("enabled")),
        "automationTotal": len(rules),
        "queuedSample": [
            {"title": p.get("title"), "status": p.get("status"), "date": p.get("date")}
            for p in (data.get("queuedPosts") or [])[:5]
            if isinstance(p, dict)
        ],
    }


def _summarize_meta_live(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {"note": "unexpected meta/live payload"}
    if data.get("connected") is False:
        return {"connected": False, "error": data.get("error")}
    page = data.get("page") or {}
    posts = data.get("posts") or []
    return {
        "connected": data.get("connected"),
        "generatedAt": data.get("generatedAt"),
        "errors": data.get("errors") or [],
        "page": {
            "id": page.get("id"),
            "name": page.get("name"),
            "category": page.get("category"),
            "followers": page.get("followersCount") or page.get("fanCount"),
            "talkingAbout": page.get("talkingAboutCount"),
            "link": page.get("link"),
        },
        "totals": data.get("totals") or {},
        "recentPosts": [
            {
                "id": p.get("id"),
                "message": (p.get("message") or "")[:160],
                "createdAt": p.get("createdAt"),
                "comments": p.get("comments"),
                "reactions": p.get("reactions"),
                "shares": p.get("shares"),
                "permalink": p.get("permalink"),
            }
            for p in posts[:8]
            if isinstance(p, dict)
        ],
    }


def _summarize_settings(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {"note": "unexpected settings payload"}
    workspace = data.get("workspace") or {}
    integrations = data.get("integrations") or {}
    meta_conn = integrations.get("metaConnection") or {}
    return {
        "workspace": {
            "name": workspace.get("name"),
            "slug": workspace.get("slug"),
            "facebook_page_name": workspace.get("facebook_page_name"),
            "facebook_page_id": workspace.get("facebook_page_id"),
        },
        "counts": data.get("counts") or {},
        "automations": len(data.get("automations") or []),
        "integrations": {
            "facebook": integrations.get("facebook"),
            "metaConnected": integrations.get("metaConnected"),
            "openai": integrations.get("openai"),
            "supabase": integrations.get("supabase"),
            "metaLastCheckStatus": meta_conn.get("lastCheckStatus"),
            "metaLastCheckError": meta_conn.get("lastCheckError"),
            "metaPageName": meta_conn.get("pageName"),
        },
    }


def _summarize_signals(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {"note": "unexpected signals payload"}
    rows = data.get("rows") or []
    return {
        "generatedAt": data.get("generatedAt"),
        "bay": data.get("bay"),
        "rowCount": len(rows),
        "summary": data.get("summary"),
        "signals": data.get("signals"),
        "openSample": [
            {
                "sender": r.get("sender_name"),
                "channel": r.get("channel"),
                "subject": r.get("subject"),
                "status": r.get("status"),
                "priority": r.get("priority"),
                "sentiment": r.get("sentiment"),
            }
            for r in rows[:8]
            if isinstance(r, dict)
        ],
    }


def _summarize_list(data: Any, item_keys: Optional[List[str]] = None) -> Dict[str, Any]:
    items: List[Any]
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ("posts", "threads", "items", "rows", "data"):
            if isinstance(data.get(key), list):
                items = data[key]
                break
        else:
            return {"keys": list(data.keys()), "preview": data}
    else:
        return {"note": "unexpected list payload"}

    sample = []
    for item in items[:10]:
        if not isinstance(item, dict):
            sample.append(item)
            continue
        if item_keys:
            sample.append({k: item.get(k) for k in item_keys})
        else:
            # keep a shallow compact view
            sample.append({k: item.get(k) for k in list(item.keys())[:8]})
    return {"count": len(items), "sample": sample}


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def status(base_url: Optional[str] = None) -> Dict[str, Any]:
    """Check config + reachability of the PageTend host."""
    resolved = resolve_base_url(base_url)
    # Prefer settings as a lightweight health probe; fall back to dashboard
    probe = _request("GET", resolved, "/api/pagetend/settings", timeout=12)
    if not probe.get("ok"):
        probe = _request("GET", resolved, "/api/pagetend/dashboard", timeout=12)

    return {
        "ok": bool(probe.get("ok")),
        "tool": "status",
        "base_url": resolved,
        "config_file": str(CONFIG_FILE),
        "env_set": bool(_noneish(os.environ.get("PAGETEND_BASE_URL"))),
        "reachable": bool(probe.get("ok")),
        "status": probe.get("status"),
        "url": probe.get("url"),
        "error": probe.get("error"),
        "hint": (
            "Set PAGETEND_BASE_URL or write {\"base_url\": \"https://...\"} to ~/.pagetend/config.json"
            if not probe.get("ok")
            else "PageTend is reachable. Prefer analytics/dashboard/meta_live for stats."
        ),
    }


def analytics(base_url: Optional[str] = None, summary: Any = True) -> Dict[str, Any]:
    """Richest aggregated PageTend + Meta stats."""
    resolved = resolve_base_url(base_url)
    result = _request("GET", resolved, "/api/pagetend/analytics")
    if _truthy(summary, True) and result.get("ok"):
        return _wrap("analytics", resolved, result, _summarize_analytics(result.get("body")))
    return _wrap("analytics", resolved, result)


def dashboard(base_url: Optional[str] = None, summary: Any = True) -> Dict[str, Any]:
    """Dashboard snapshot. Always HTTP 200 from PageTend; check `fallback`."""
    resolved = resolve_base_url(base_url)
    result = _request("GET", resolved, "/api/pagetend/dashboard")
    fallback = str(result.get("headers", {}).get("x-pagetend-fallback") or "").lower() == "true"
    # dashboard always "ok" at HTTP level when reachable; surface fallback clearly
    if result.get("status") == 200:
        result["ok"] = True
        result["error"] = None
    if _truthy(summary, True) and result.get("ok"):
        out = _wrap("dashboard", resolved, result, _summarize_dashboard(result.get("body"), fallback))
        out["fallback"] = fallback
        if fallback:
            out["warning"] = "x-pagetend-fallback: true — numbers may be static fallback data, not live DB."
        return out
    out = _wrap("dashboard", resolved, result)
    out["fallback"] = fallback
    return out


def meta_live(base_url: Optional[str] = None, summary: Any = True) -> Dict[str, Any]:
    """Live Meta Graph pull: page profile, recent posts, engagement totals."""
    resolved = resolve_base_url(base_url)
    result = _request("GET", resolved, "/api/meta/live")
    if _truthy(summary, True) and result.get("ok"):
        return _wrap("meta_live", resolved, result, _summarize_meta_live(result.get("body")))
    return _wrap("meta_live", resolved, result)


def settings(base_url: Optional[str] = None, summary: Any = True) -> Dict[str, Any]:
    """Workspace counts + integration health (Meta/OpenAI/Supabase/Switchbay)."""
    resolved = resolve_base_url(base_url)
    result = _request("GET", resolved, "/api/pagetend/settings")
    if _truthy(summary, True) and result.get("ok"):
        return _wrap("settings", resolved, result, _summarize_settings(result.get("body")))
    return _wrap("settings", resolved, result)


def signals(base_url: Optional[str] = None, summary: Any = True) -> Dict[str, Any]:
    """Derived product-signal analytics from inbox threads."""
    resolved = resolve_base_url(base_url)
    result = _request("GET", resolved, "/api/pagetend/signals")
    if _truthy(summary, True) and result.get("ok"):
        return _wrap("signals", resolved, result, _summarize_signals(result.get("body")))
    return _wrap("signals", resolved, result)


def list_posts(base_url: Optional[str] = None, summary: Any = True) -> Dict[str, Any]:
    """List PageTend posts (read-only)."""
    resolved = resolve_base_url(base_url)
    result = _request("GET", resolved, "/api/pagetend/posts")
    if _truthy(summary, True) and result.get("ok"):
        return _wrap(
            "list_posts",
            resolved,
            result,
            _summarize_list(
                result.get("body"),
                ["id", "title", "status", "content_type", "color_tone", "scheduled_for", "published_at"],
            ),
        )
    return _wrap("list_posts", resolved, result)


def list_inbox(base_url: Optional[str] = None, summary: Any = True) -> Dict[str, Any]:
    """List inbox threads (read-only)."""
    resolved = resolve_base_url(base_url)
    result = _request("GET", resolved, "/api/pagetend/inbox")
    if _truthy(summary, True) and result.get("ok"):
        return _wrap(
            "list_inbox",
            resolved,
            result,
            _summarize_list(
                result.get("body"),
                ["id", "sender_name", "channel", "subject", "status", "priority", "sentiment", "last_message_at"],
            ),
        )
    return _wrap("list_inbox", resolved, result)


def _summarize_rolling(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {"note": "unexpected rolling-stats payload"}
    window = data.get("window") or {}
    return {
        "label": window.get("label") or f"Last {window.get('days', '?')} Days",
        "days": window.get("days"),
        "from": window.get("from"),
        "to": window.get("to"),
        "pageName": data.get("pageName"),
        "postsPublished": data.get("postsPublished"),
        "views": data.get("views"),
        "viewsFormatted": data.get("viewsFormatted"),
        "viewsPerPost": data.get("viewsPerPost"),
        "viewsPerPostFormatted": data.get("viewsPerPostFormatted"),
        "viewsSource": data.get("viewsSource"),
        "engagement": data.get("engagement"),
        "engagementPerPost": data.get("engagementPerPost"),
        "warnings": data.get("warnings") or [],
        "card": {
            "window": window.get("label") or f"Last {window.get('days', '?')} Days",
            "postsPublished": data.get("postsPublished"),
            "views": data.get("viewsFormatted") or data.get("views"),
            "viewsPerPost": data.get("viewsPerPostFormatted") or data.get("viewsPerPost"),
        },
    }


def _parse_iso(value: Any) -> Optional[float]:
    if not value or not isinstance(value, str):
        return None
    try:
        from datetime import datetime

        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _fallback_rolling(base_url: str, days: int) -> Dict[str, Any]:
    """Local fallback when /api/pagetend/rolling-stats is not deployed yet."""
    from datetime import datetime, timedelta, timezone

    until = datetime.now(timezone.utc)
    since = until - timedelta(days=days)
    since_ts = since.timestamp()
    until_ts = until.timestamp()

    posts_result = _request("GET", base_url, "/api/pagetend/posts")
    body = posts_result.get("body")
    posts: List[Any] = []
    if isinstance(body, dict) and isinstance(body.get("posts"), list):
        posts = body["posts"]
    elif isinstance(body, list):
        posts = body

    published = []
    for post in posts:
        if not isinstance(post, dict):
            continue
        published_at = _parse_iso(post.get("meta_published_at"))
        if published_at is None:
            continue
        if since_ts <= published_at <= until_ts:
            published.append(post)

    posts_published = len(published)
    meta = _request("GET", base_url, "/api/meta/live")
    meta_body = meta.get("body") if meta.get("ok") else {}
    meta_posts = (meta_body or {}).get("posts") if isinstance(meta_body, dict) else []
    engagement = {"comments": 0, "reactions": 0, "shares": 0, "engagement": 0}
    sampled = 0
    if isinstance(meta_posts, list):
        for post in meta_posts:
            if not isinstance(post, dict):
                continue
            created = _parse_iso(post.get("createdAt") or post.get("created_time"))
            if created is None or not (since_ts <= created <= until_ts):
                continue
            sampled += 1
            comments = int(post.get("comments") or 0)
            reactions = int(post.get("reactions") or 0)
            shares = int(post.get("shares") or 0)
            engagement["comments"] += comments
            engagement["reactions"] += reactions
            engagement["shares"] += shares
            engagement["engagement"] += comments + reactions + shares

    payload = {
        "window": {
            "days": days,
            "from": since.isoformat(),
            "to": until.isoformat(),
            "label": f"Last {days} Days",
        },
        "postsPublished": posts_published,
        "views": None,
        "viewsFormatted": None,
        "viewsPerPost": None,
        "viewsPerPostFormatted": None,
        "viewsSource": "unavailable",
        "engagement": engagement,
        "engagementPerPost": (
            round(engagement["engagement"] / posts_published) if posts_published else None
        ),
        "metaPostsSampled": sampled,
        "warnings": [
            "rolling-stats endpoint unavailable — used local fallback from /posts + /meta/live.",
            "True Meta views/impressions require /api/pagetend/rolling-stats (PageTend route).",
        ],
        "generatedAt": until.isoformat(),
        "fallback": True,
    }
    return {
        "ok": True,
        "status": 200,
        "url": f"{base_url}/api/pagetend/rolling-stats?days={days}",
        "error": None,
        "body": payload,
        "headers": {},
    }


def views_per_post(
    days: Any = 30,
    base_url: Optional[str] = None,
    summary: Any = True,
) -> Dict[str, Any]:
    """Rolling-window posts published + views + views-per-post.

    Prefers PageTend `/api/pagetend/rolling-stats`. Falls back to local
    post counts + engagement if that route is missing.
    """
    resolved = resolve_base_url(base_url)
    window_days = _parse_int(days, 30, minimum=1, maximum=365)

    result = _request("GET", resolved, f"/api/pagetend/rolling-stats?days={window_days}")
    if not result.get("ok") and result.get("status") in {0, 404}:
        result = _fallback_rolling(resolved, window_days)

    if _truthy(summary, True) and result.get("ok"):
        return _wrap("views_per_post", resolved, result, _summarize_rolling(result.get("body")))
    return _wrap("views_per_post", resolved, result)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

TOOLS = {
    "status": status,
    "analytics": analytics,
    "dashboard": dashboard,
    "meta_live": meta_live,
    "settings": settings,
    "signals": signals,
    "list_posts": list_posts,
    "list_inbox": list_inbox,
    "views_per_post": views_per_post,
}


def _cli() -> None:
    parser = argparse.ArgumentParser(description="PageTend Helper — read-only stats for Switchbay")
    sub = parser.add_subparsers(dest="tool", required=True)

    for name in TOOLS:
        p = sub.add_parser(name)
        p.add_argument("--base_url", default=None, help="PageTend origin, e.g. http://localhost:3000")
        if name != "status":
            p.add_argument(
                "--summary",
                default="true",
                help="Return compact summary (+ full data). true/false. Default true.",
            )
        if name == "views_per_post":
            p.add_argument(
                "--days",
                default="30",
                help="Rolling window length in days (1–365). Default 30.",
            )

    args = parser.parse_args()
    kwargs: Dict[str, Any] = {"base_url": args.base_url}
    if args.tool != "status":
        kwargs["summary"] = args.summary
    if args.tool == "views_per_post":
        kwargs["days"] = args.days

    try:
        result = TOOLS[args.tool](**kwargs)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if not result.get("ok"):
            sys.exit(1)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    _cli()
