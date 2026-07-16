"""PINATA Engine — Reddit Research Workbench

A deliberate, model-in-the-loop research tool. You control every step.
The engine handles the fetch, filter, persistence, and scoring mechanics.
The model (and you) decide what to save, challenge, cluster, and ship.

Tools:
  search_reddit      — Query Reddit posts or comments via PullPush
  save_signal        — Persist an approved signal to the local session store
  list_signals       — List all saved signals (optionally filtered by tag)
  cluster_signals    — Group saved signals into named pain themes via LLM
  challenge_thesis   — Find disconfirming evidence for a stated opportunity
  score_opportunity  — Score one opportunity across the PINATA rubric
  publish_matrix     — Write the final Winner / Next Up / Losers matrix to disk

Usage (CLI):
  python pinata.py search_reddit --query "..." --type posts --size 15
  python pinata.py save_signal --id "abc123" --title "..." --body "..." --url "..." [--tags "pain,pricing"]
  python pinata.py list_signals [--tag pain]
  python pinata.py cluster_signals
  python pinata.py challenge_thesis --thesis "..."
  python pinata.py score_opportunity --name "..." --description "..."
  python pinata.py publish_matrix --winner "..." --next_up "..." --losers "..."

Data is stored in ~/.pinata/session.json (portable, local-first).
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATA_DIR = Path.home() / ".pinata"
SESSION_FILE = DATA_DIR / "session.json"
MATRIX_FILE = DATA_DIR / "opportunity_matrix.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# SSL (same pattern as WebSearch engine)
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
UA = "Mozilla/5.0 (compatible; PINATA-Workbench/1.0)"


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _get(url: str, timeout: int = 20) -> Dict[str, Any]:
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=timeout, context=_SSL) as r:
        return json.loads(r.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Session store (local JSON, append-only signals list)
# ---------------------------------------------------------------------------

def _load_session() -> Dict[str, Any]:
    if SESSION_FILE.exists():
        try:
            return json.loads(SESSION_FILE.read_text("utf-8"))
        except Exception:
            pass
    return {"signals": [], "clusters": [], "scores": [], "created_at": _now()}


def _save_session(session: Dict[str, Any]) -> None:
    session["updated_at"] = _now()
    SESSION_FILE.write_text(json.dumps(session, indent=2, ensure_ascii=False), "utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Tool: search_reddit
# ---------------------------------------------------------------------------

PULLPUSH_BASE = "https://api.pullpush.io/reddit/search"

PAIN_PHRASES = [
    "i hate", "frustrated with", "alternative to", "looking for",
    "what do you use", "manual process", "spreadsheet", "takes hours",
    "wish there was", "too expensive", "missing feature", "switching from",
    "would pay for", "is there a way", "can't find", "no good option",
    "broken", "terrible", "nightmare", "workaround",
]


def _build_pullpush_url(
    query: str,
    kind: str,
    subreddit: Optional[str],
    sort_type: str,
    min_score: int,
    size: int,
    after: Optional[str],
    before: Optional[str],
) -> str:
    """Build a PullPush API URL for posts or comments."""
    if kind == "posts":
        base = f"{PULLPUSH_BASE}/submission/"
        params: Dict[str, Any] = {
            "type": "submission",
            "title": query,
            "sort_type": sort_type,
            "sort": "desc",
            "score": f">{min_score}",
            "size": size,
            "lang_id": "detect",
        }
    else:
        base = f"{PULLPUSH_BASE}/comment/"
        params = {
            "type": "comment",
            "q": query,
            "sort_type": sort_type,
            "sort": "desc",
            "score": f">{min_score}",
            "size": size,
            "lang_id": "detect",
        }

    if subreddit:
        params["subreddit"] = subreddit
    if after:
        params["after"] = after
    if before:
        params["before"] = before

    return base + "?" + urllib.parse.urlencode(params)


def _clean_text(text: Optional[str]) -> str:
    if not text:
        return ""
    # Strip common Reddit markdown artifacts
    return " ".join(text.replace("\n", " ").replace("\r", " ").split())[:2000]


def _signal_score(item: Dict[str, Any], kind: str) -> int:
    """Rough pain-signal score: upvotes + pain-phrase hits in text."""
    score = item.get("score", 0) or 0
    body = (item.get("selftext") or item.get("body") or item.get("title") or "").lower()
    pain_hits = sum(1 for p in PAIN_PHRASES if p in body)
    return score + (pain_hits * 5)


def search_reddit(
    query: str,
    kind: str = "posts",
    subreddit: Optional[str] = None,
    sort_type: str = "num_comments",
    min_score: int = 5,
    size: int = 15,
    after: Optional[str] = None,
    before: Optional[str] = None,
) -> Dict[str, Any]:
    """Search Reddit posts or comments via PullPush.

    Args:
        query:      Search string (title match for posts, body search for comments).
        kind:       'posts' or 'comments'. Default: posts.
        subreddit:  Optional subreddit name without r/ prefix.
        sort_type:  'num_comments' | 'score' | 'created_utc'. Default: num_comments.
        min_score:  Minimum upvote score filter. Default: 5.
        size:       Results per page. Max 100. Default: 15.
        after:      Unix timestamp — return results after this time.
        before:     Unix timestamp — return results before this time.

    Returns structured, pre-cleaned results with a pain_score for each item.
    """
    if kind not in ("posts", "comments"):
        raise ValueError("kind must be 'posts' or 'comments'.")
    if not query.strip():
        raise ValueError("query must not be empty.")

    size = max(1, min(size, 100))
    url = _build_pullpush_url(query, kind, subreddit, sort_type, min_score, size, after, before)

    try:
        raw = _get(url)
    except (URLError, HTTPError) as exc:
        return {"error": str(exc), "query": query, "kind": kind, "results": []}

    items = raw.get("data", [])
    results = []

    for item in items:
        if kind == "posts":
            entry = {
                "id": item.get("id", ""),
                "kind": "post",
                "title": _clean_text(item.get("title")),
                "body": _clean_text(item.get("selftext")),
                "subreddit": item.get("subreddit", ""),
                "author": item.get("author", ""),
                "score": item.get("score", 0),
                "num_comments": item.get("num_comments", 0),
                "url": f"https://reddit.com{item.get('permalink', '')}",
                "created_utc": item.get("created_utc", 0),
                "pain_score": _signal_score(item, kind),
            }
        else:
            entry = {
                "id": item.get("id", ""),
                "kind": "comment",
                "title": _clean_text(item.get("link_title")),
                "body": _clean_text(item.get("body")),
                "subreddit": item.get("subreddit", ""),
                "author": item.get("author", ""),
                "score": item.get("score", 0),
                "url": f"https://reddit.com{item.get('permalink', '')}",
                "created_utc": item.get("created_utc", 0),
                "pain_score": _signal_score(item, kind),
            }
        results.append(entry)

    # Sort by pain_score descending
    results.sort(key=lambda x: x["pain_score"], reverse=True)

    return {
        "query": query,
        "kind": kind,
        "subreddit": subreddit,
        "total_fetched": len(results),
        "min_score_filter": min_score,
        "results": results,
    }


# ---------------------------------------------------------------------------
# Tool: save_signal
# ---------------------------------------------------------------------------

def save_signal(
    id: str,
    title: str,
    body: str,
    url: str,
    subreddit: str = "",
    kind: str = "post",
    score: int = 0,
    tags: Optional[str] = None,
    note: str = "",
) -> Dict[str, Any]:
    """Save an approved signal to the session store.

    Args:
        id:        Reddit item ID (used for deduplication).
        title:     Post or comment title / link_title.
        body:      The cleaned text body.
        url:       Reddit permalink.
        subreddit: Subreddit name.
        kind:      'post' or 'comment'.
        score:     Reddit upvote score.
        tags:      Comma-separated tags, e.g. 'pain,pricing,workaround'.
        note:      Your research note about why this signal matters.
    """
    session = _load_session()
    existing_ids = {s["id"] for s in session["signals"]}

    if id in existing_ids:
        return {"status": "duplicate", "id": id, "message": "Signal already saved."}

    tag_list = [t.strip() for t in tags.split(",")] if tags else []

    signal = {
        "id": id,
        "kind": kind,
        "title": title,
        "body": body[:1500],
        "url": url,
        "subreddit": subreddit,
        "score": score,
        "tags": tag_list,
        "note": note,
        "saved_at": _now(),
    }

    session["signals"].append(signal)
    _save_session(session)

    return {
        "status": "saved",
        "id": id,
        "total_signals": len(session["signals"]),
        "tags": tag_list,
    }


# ---------------------------------------------------------------------------
# Tool: list_signals
# ---------------------------------------------------------------------------

def list_signals(tag: Optional[str] = None) -> Dict[str, Any]:
    """List all saved signals, optionally filtered by tag.

    Args:
        tag: Optional tag to filter by (e.g. 'pain', 'pricing').
    """
    session = _load_session()
    signals = session.get("signals", [])

    if tag:
        signals = [s for s in signals if tag in s.get("tags", [])]

    summary = [
        {
            "id": s["id"],
            "kind": s["kind"],
            "title": s["title"][:100],
            "subreddit": s.get("subreddit", ""),
            "score": s.get("score", 0),
            "tags": s.get("tags", []),
            "note": s.get("note", "")[:120],
            "saved_at": s.get("saved_at", ""),
        }
        for s in signals
    ]

    return {
        "total": len(summary),
        "filter_tag": tag,
        "signals": summary,
    }


# ---------------------------------------------------------------------------
# Tool: cluster_signals
# ---------------------------------------------------------------------------

def cluster_signals() -> Dict[str, Any]:
    """Group saved signals into named pain-theme clusters.

    Uses a lightweight heuristic approach: groups by dominant tag,
    then by keyword co-occurrence in title + body. No LLM call required —
    keeps the workbench local-first and deterministic.

    For deeper semantic clustering, pass the output to your model.
    """
    session = _load_session()
    signals = session.get("signals", [])

    if not signals:
        return {"status": "empty", "message": "No signals saved yet. Use save_signal first.", "clusters": []}

    # 1. Group by explicit tags first
    tag_groups: Dict[str, List[Dict]] = {}
    untagged = []

    for s in signals:
        tags = s.get("tags", [])
        if tags:
            primary = tags[0]
            tag_groups.setdefault(primary, []).append(s)
        else:
            untagged.append(s)

    # 2. Keyword clusters for untagged signals
    keyword_clusters: Dict[str, List[Dict]] = {}
    keyword_map = {
        "pricing": ["expensive", "price", "cost", "pay", "cheap", "affordable", "subscription"],
        "workaround": ["workaround", "spreadsheet", "manual", "hours", "hacky", "script", "copy paste"],
        "missing_feature": ["missing", "wish", "feature", "can't", "doesn't", "no way", "no option"],
        "switching": ["switching", "alternative", "migrate", "moved from", "left", "dropped"],
        "frustration": ["hate", "frustrated", "broken", "terrible", "nightmare", "awful"],
    }

    for s in untagged:
        text = (s.get("title", "") + " " + s.get("body", "")).lower()
        matched = None
        for cluster_name, keywords in keyword_map.items():
            if any(k in text for k in keywords):
                matched = cluster_name
                break
        if matched:
            keyword_clusters.setdefault(matched, []).append(s)
        else:
            keyword_clusters.setdefault("other", []).append(s)

    # Merge both grouping strategies
    all_clusters: Dict[str, List[Dict]] = {**tag_groups}
    for k, v in keyword_clusters.items():
        if k in all_clusters:
            all_clusters[k].extend(v)
        else:
            all_clusters[k] = v

    output = []
    for cluster_name, members in all_clusters.items():
        output.append({
            "cluster": cluster_name,
            "count": len(members),
            "signal_ids": [m["id"] for m in members],
            "titles": [m["title"][:80] for m in members],
        })

    output.sort(key=lambda x: x["count"], reverse=True)

    # Persist clusters
    session["clusters"] = output
    _save_session(session)

    return {
        "status": "clustered",
        "total_signals": len(signals),
        "cluster_count": len(output),
        "clusters": output,
    }


# ---------------------------------------------------------------------------
# Tool: challenge_thesis
# ---------------------------------------------------------------------------

CHALLENGE_ANGLES = [
    "already solved by {thesis} alternatives",
    "{thesis} happy users satisfied",
    "{thesis} not enough demand",
    "{thesis} free solution exists",
    "{thesis} too niche",
    "{thesis} regulation blocks",
    "{thesis} no willingness to pay",
    "{thesis} crowded market",
]


def challenge_thesis(thesis: str, size: int = 10) -> Dict[str, Any]:
    """Search for disconfirming evidence against a stated opportunity thesis.

    Runs multiple adversarial queries on Reddit looking for:
    satisfied users, existing solutions, low WTP, fragmented demand.

    Args:
        thesis: The opportunity you want to stress-test. Be specific.
        size:   Results per adversarial query. Default: 10.
    """
    if not thesis.strip():
        raise ValueError("thesis must not be empty.")

    adversarial_queries = [
        f"{thesis} solved",
        f"{thesis} love it works great",
        f"best {thesis} tool recommendation",
        f"{thesis} free alternative",
        f"{thesis} not worth it",
        f"happy with {thesis}",
    ]

    all_results = []
    for q in adversarial_queries:
        try:
            res = search_reddit(query=q, kind="posts", min_score=3, size=size)
            for item in res.get("results", []):
                item["adversarial_query"] = q
            all_results.extend(res.get("results", []))
            time.sleep(0.3)  # polite delay
        except Exception:
            continue

    # Also check comments
    try:
        res = search_reddit(query=f"{thesis} already exists tool", kind="comments", min_score=3, size=size)
        for item in res.get("results", []):
            item["adversarial_query"] = "comment: already exists"
        all_results.extend(res.get("results", []))
    except Exception:
        pass

    # Sort by score descending — high-score positive posts are most concerning
    all_results.sort(key=lambda x: x.get("score", 0), reverse=True)

    return {
        "thesis": thesis,
        "adversarial_queries_run": len(adversarial_queries) + 1,
        "total_results": len(all_results),
        "warning": "High-scoring results here may indicate the problem is already solved or demand is low. Review carefully.",
        "results": all_results[:40],  # cap at 40 items
    }


# ---------------------------------------------------------------------------
# Tool: score_opportunity
# ---------------------------------------------------------------------------

RUBRIC = {
    "pain_intensity":         {"weight": 20, "description": "How severe is the pain? (1–5)"},
    "recurrence":             {"weight": 15, "description": "How often does this pain come up? (1–5)"},
    "willingness_to_pay":     {"weight": 20, "description": "Do people signal budget or pay intent? (1–5)"},
    "dissatisfaction":        {"weight": 15, "description": "How bad are current alternatives? (1–5)"},
    "reachability":           {"weight": 10, "description": "Can you reach these users? (1–5)"},
    "competitive_whitespace":  {"weight": 10, "description": "Is the competitive space open? (1–5)"},
    "build_complexity":        {"weight": 10, "description": "How hard to build? Inverse — 5 = easy. (1–5)"},
}


def score_opportunity(
    name: str,
    description: str,
    pain_intensity: int = 3,
    recurrence: int = 3,
    willingness_to_pay: int = 3,
    dissatisfaction: int = 3,
    reachability: int = 3,
    competitive_whitespace: int = 3,
    build_complexity: int = 3,
) -> Dict[str, Any]:
    """Score an opportunity across the PINATA rubric.

    Each dimension is 1–5. Scores are weighted to a 0–100 final score.
    The tier (Winner / Next Up / Loser) is auto-assigned by score bracket.

    Args:
        name:                  Short opportunity name.
        description:           What the product/feature/SaaS does.
        pain_intensity:        1–5. How acute is the pain?
        recurrence:            1–5. How frequently does it occur?
        willingness_to_pay:    1–5. Evidence of budget / pay intent.
        dissatisfaction:       1–5. How bad are current solutions?
        reachability:          1–5. Distribution access to target users.
        competitive_whitespace: 1–5. Openness of the competitive space.
        build_complexity:      1–5. Inverse — 5 means easy to build.
    """
    raw_scores = {
        "pain_intensity": pain_intensity,
        "recurrence": recurrence,
        "willingness_to_pay": willingness_to_pay,
        "dissatisfaction": dissatisfaction,
        "reachability": reachability,
        "competitive_whitespace": competitive_whitespace,
        "build_complexity": build_complexity,
    }

    # Validate
    for dim, val in raw_scores.items():
        if not (1 <= val <= 5):
            raise ValueError(f"{dim} must be between 1 and 5. Got: {val}")

    # Weighted score (each dimension normalised to 0–1, then weighted)
    total = 0.0
    breakdown = {}
    for dim, val in raw_scores.items():
        weight = RUBRIC[dim]["weight"]
        contribution = ((val - 1) / 4) * weight  # map 1–5 → 0–weight
        total += contribution
        breakdown[dim] = {
            "raw": val,
            "weight": weight,
            "contribution": round(contribution, 2),
            "description": RUBRIC[dim]["description"],
        }

    final_score = round(total, 1)

    if final_score >= 70:
        tier = "Winner"
    elif final_score >= 45:
        tier = "Next Up"
    else:
        tier = "Loser"

    result = {
        "name": name,
        "description": description,
        "score": final_score,
        "max_score": 100.0,
        "tier": tier,
        "breakdown": breakdown,
        "scored_at": _now(),
    }

    # Persist
    session = _load_session()
    session.setdefault("scores", [])
    # Replace if already scored
    session["scores"] = [s for s in session["scores"] if s.get("name") != name]
    session["scores"].append(result)
    _save_session(session)

    return result


# ---------------------------------------------------------------------------
# Tool: publish_matrix
# ---------------------------------------------------------------------------

def publish_matrix(
    winner: str,
    next_up: str,
    losers: str,
    research_notes: str = "",
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Write the final opportunity matrix to disk.

    Pulls all saved scores from the session, appends manual summaries,
    and writes a structured JSON + human-readable Markdown side-by-side.

    Args:
        winner:         Description of the winning opportunity.
        next_up:        Description of next-up opportunities (can be multi-line).
        losers:         What was rejected and why.
        research_notes: Any additional context or caveats.
        output_path:    Optional custom path. Defaults to ~/.pinata/opportunity_matrix.json
    """
    session = _load_session()
    scores = session.get("scores", [])
    clusters = session.get("clusters", [])

    # Sort scores by score descending
    scores_sorted = sorted(scores, key=lambda x: x.get("score", 0), reverse=True)

    matrix = {
        "generated_at": _now(),
        "summary": {
            "winner": winner,
            "next_up": next_up,
            "losers": losers,
            "research_notes": research_notes,
        },
        "scored_opportunities": scores_sorted,
        "signal_clusters": clusters,
        "total_signals_saved": len(session.get("signals", [])),
    }

    out_path = Path(output_path) if output_path else MATRIX_FILE
    out_path.write_text(json.dumps(matrix, indent=2, ensure_ascii=False), "utf-8")

    # Also write a Markdown version
    md_path = out_path.with_suffix(".md")
    md_lines = [
        "# PINATA Opportunity Matrix",
        f"_Generated: {_now()}_",
        "",
        "## 🏆 Winner",
        winner,
        "",
        "## 🔜 Next Up",
        next_up,
        "",
        "## ❌ Losers",
        losers,
        "",
    ]

    if research_notes:
        md_lines += ["## 📝 Research Notes", research_notes, ""]

    if scores_sorted:
        md_lines += ["## Scored Opportunities", ""]
        for s in scores_sorted:
            md_lines.append(f"### {s['name']} — {s['tier']} ({s['score']}/100)")
            md_lines.append(s.get("description", ""))
            md_lines.append("")
            for dim, detail in s.get("breakdown", {}).items():
                md_lines.append(f"- **{dim}**: {detail['raw']}/5 (weight {detail['weight']})")
            md_lines.append("")

    if clusters:
        md_lines += ["## Signal Clusters", ""]
        for c in clusters:
            md_lines.append(f"### {c['cluster']} ({c['count']} signals)")
            for t in c.get("titles", [])[:5]:
                md_lines.append(f"- {t}")
            md_lines.append("")

    md_path.write_text("\n".join(md_lines), "utf-8")

    return {
        "status": "published",
        "json_path": str(out_path),
        "markdown_path": str(md_path),
        "opportunities_scored": len(scores_sorted),
        "clusters_included": len(clusters),
        "signals_referenced": len(session.get("signals", [])),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli():
    parser = argparse.ArgumentParser(description="PINATA Research Workbench")
    sub = parser.add_subparsers(dest="tool", required=True)

    # search_reddit
    p = sub.add_parser("search_reddit")
    p.add_argument("--query", required=True)
    p.add_argument("--kind", default="posts", choices=["posts", "comments"])
    p.add_argument("--subreddit", default=None)
    p.add_argument("--sort_type", default="num_comments", choices=["num_comments", "score", "created_utc"])
    p.add_argument("--min_score", type=int, default=5)
    p.add_argument("--size", type=int, default=15)
    p.add_argument("--after", default=None)
    p.add_argument("--before", default=None)

    # save_signal
    p = sub.add_parser("save_signal")
    p.add_argument("--id", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--body", required=True)
    p.add_argument("--url", required=True)
    p.add_argument("--subreddit", default="")
    p.add_argument("--kind", default="post")
    p.add_argument("--score", type=int, default=0)
    p.add_argument("--tags", default=None)
    p.add_argument("--note", default="")

    # list_signals
    p = sub.add_parser("list_signals")
    p.add_argument("--tag", default=None)

    # cluster_signals
    sub.add_parser("cluster_signals")

    # challenge_thesis
    p = sub.add_parser("challenge_thesis")
    p.add_argument("--thesis", required=True)
    p.add_argument("--size", type=int, default=10)

    # score_opportunity
    p = sub.add_parser("score_opportunity")
    p.add_argument("--name", required=True)
    p.add_argument("--description", required=True)
    p.add_argument("--pain_intensity", type=int, default=3)
    p.add_argument("--recurrence", type=int, default=3)
    p.add_argument("--willingness_to_pay", type=int, default=3)
    p.add_argument("--dissatisfaction", type=int, default=3)
    p.add_argument("--reachability", type=int, default=3)
    p.add_argument("--competitive_whitespace", type=int, default=3)
    p.add_argument("--build_complexity", type=int, default=3)

    # publish_matrix
    p = sub.add_parser("publish_matrix")
    p.add_argument("--winner", required=True)
    p.add_argument("--next_up", required=True)
    p.add_argument("--losers", required=True)
    p.add_argument("--research_notes", default="")
    p.add_argument("--output_path", default=None)

    args = parser.parse_args()
    kwargs = {k: v for k, v in vars(args).items() if k != "tool"}

    try:
        fn = {
            "search_reddit": search_reddit,
            "save_signal": save_signal,
            "list_signals": list_signals,
            "cluster_signals": cluster_signals,
            "challenge_thesis": challenge_thesis,
            "score_opportunity": score_opportunity,
            "publish_matrix": publish_matrix,
        }[args.tool]
        result = fn(**kwargs)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    _cli()
