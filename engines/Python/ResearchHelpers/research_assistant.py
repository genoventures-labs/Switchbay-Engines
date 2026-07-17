"""
Research Assistant Engine

Research Assistant Engine for Switchbay.

Tools:
- research_assistant: Assist with research tasks.
- data_visualization: Visualize data.
- data_modeling: Model data.


Usage:
  python engines/Python/ResearchHelpers/research_assistant.py research_assistant --task "..." --context "..." --output_type "..."
  python engines/Python/ResearchHelpers/research_assistant.py data_visualization --data "..." --visualization_type "..." --output_type "..."
  python engines/Python/ResearchHelpers/research_assistant.py data_modeling --data "..." --model_type "..." --output_type "..."

Data is stored in ~/.research_assistant/session.json (portable, local-first).
"""

from __future__ import annotations

import argparse
import json
import math
import re
import ssl
import statistics
import sys
import urllib.parse
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATA_DIR = Path.home() / ".research_assistant"
SESSION_FILE = DATA_DIR / "session.json"
OUTPUT_DIR = DATA_DIR / "outputs"


def _ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


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


def _truthy(value: Any, default: bool = False) -> bool:
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


def _choice(value: Any, allowed: set[str], default: str) -> str:
    text = (_noneish(str(value) if value is not None else None) or default).strip().lower()
    return text if text in allowed else default


# ---------------------------------------------------------------------------
# SSL + HTTP (same pattern as WebSearch / PINATA)
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
UA = "Mozilla/5.0 (compatible; SwitchbayResearchAssistant/1.0)"


# ---------------------------------------------------------------------------
# Session store
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_session() -> Dict[str, Any]:
    if SESSION_FILE.exists():
        try:
            return json.loads(SESSION_FILE.read_text("utf-8"))
        except Exception:
            pass
    return {
        "tasks": [],
        "visualizations": [],
        "models": [],
        "created_at": _now(),
    }


def _save_session(session: Dict[str, Any]) -> None:
    _ensure_dirs()
    session["updated_at"] = _now()
    SESSION_FILE.write_text(json.dumps(session, indent=2, ensure_ascii=False), "utf-8")


def _next_id(prefix: str, items: Sequence[Dict[str, Any]]) -> str:
    return f"{prefix}_{len(items) + 1:04d}"


# ---------------------------------------------------------------------------
# Light DuckDuckGo search (optional grounding for research_assistant)
# ---------------------------------------------------------------------------

class _DDGLiteParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: List[Dict[str, str]] = []
        self._in_link = False
        self._in_snippet = False
        self._pending_title = ""
        self._pending_url = ""
        self._pending_snippet = ""

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attr_dict = dict(attrs)
        classes = attr_dict.get("class", "") or ""
        if tag == "a" and "result-link" in classes:
            self._pending_url = attr_dict.get("href", "") or ""
            self._pending_title = ""
            self._in_link = True
        if tag == "td" and "result-snippet" in classes:
            self._pending_snippet = ""
            self._in_snippet = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_link:
            self._in_link = False
        if tag == "td" and self._in_snippet:
            self._in_snippet = False
            if self._pending_url and self._pending_title:
                self.results.append(
                    {
                        "title": self._pending_title.strip(),
                        "url": self._pending_url.strip(),
                        "description": self._pending_snippet.strip(),
                    }
                )
                self._pending_title = ""
                self._pending_url = ""
                self._pending_snippet = ""

    def handle_data(self, data: str) -> None:
        stripped = data.strip()
        if not stripped:
            return
        if self._in_link:
            self._pending_title += stripped
        elif self._in_snippet:
            self._pending_snippet += " " + stripped


def _search_web(query: str, count: int = 5) -> List[Dict[str, str]]:
    """Best-effort web search. Returns [] on network/parse failure."""
    try:
        data = urllib.parse.urlencode({"q": query}).encode("utf-8")
        req = Request(
            "https://lite.duckduckgo.com/lite/",
            data=data,
            headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.5",
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": "https://lite.duckduckgo.com/lite/",
            },
            method="POST",
        )
        with urlopen(req, timeout=15, context=_SSL) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        parser = _DDGLiteParser()
        parser.feed(raw)
        return parser.results[:count]
    except (URLError, HTTPError, TimeoutError, OSError, Exception):
        return []


# ---------------------------------------------------------------------------
# Data parsing helpers
# ---------------------------------------------------------------------------

Number = Union[int, float]
ParsedData = Dict[str, Any]


def _parse_data(data: str) -> ParsedData:
    """Parse CLI --data into a normalized structure.

    Accepts:
      - JSON array of numbers: [1, 2, 3]
      - JSON array of objects: [{"x":1,"y":2}, ...]
      - JSON object of series: {"a":[1,2], "b":[3,4]}
      - CSV-ish lines: "label,value\\na,1\\nb,2"
      - Whitespace/comma separated numbers: "1 2 3" or "1,2,3"
    """
    raw = (data or "").strip()
    if not raw:
        raise ValueError("data is required")

    # JSON first
    if raw[0] in "[{":
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON data: {exc}") from exc
        return _normalize_parsed(parsed)

    # CSV with header
    lines = [ln.strip() for ln in raw.replace("\\n", "\n").splitlines() if ln.strip()]
    if len(lines) >= 2 and ("," in lines[0] or "\t" in lines[0]):
        delim = "\t" if "\t" in lines[0] else ","
        headers = [h.strip() for h in lines[0].split(delim)]
        rows: List[Dict[str, Any]] = []
        for line in lines[1:]:
            parts = [p.strip() for p in line.split(delim)]
            row: Dict[str, Any] = {}
            for i, h in enumerate(headers):
                val: Any = parts[i] if i < len(parts) else ""
                try:
                    val = float(val) if "." in str(val) else int(val)
                except (TypeError, ValueError):
                    pass
                row[h] = val
            rows.append(row)
        return _normalize_parsed(rows)

    # Flat numbers
    tokens = re.split(r"[\s,;]+", raw)
    nums: List[float] = []
    for tok in tokens:
        if not tok:
            continue
        try:
            nums.append(float(tok))
        except ValueError as exc:
            raise ValueError(f"could not parse data token '{tok}'") from exc
    return _normalize_parsed(nums)


def _normalize_parsed(parsed: Any) -> ParsedData:
    if isinstance(parsed, list) and parsed and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in parsed):
        values = [float(x) for x in parsed]
        return {
            "shape": "series",
            "labels": [str(i) for i in range(len(values))],
            "values": values,
            "series": {"values": values},
            "rows": [{"index": i, "value": v} for i, v in enumerate(values)],
        }

    if isinstance(parsed, list) and parsed and all(isinstance(x, dict) for x in parsed):
        rows = parsed
        keys = list(rows[0].keys())
        numeric_keys = [
            k for k in keys if all(isinstance(r.get(k), (int, float)) and not isinstance(r.get(k), bool) for r in rows)
        ]
        label_key = next((k for k in keys if k not in numeric_keys), None)
        primary = numeric_keys[0] if numeric_keys else None
        labels = [str(r.get(label_key, i)) for i, r in enumerate(rows)] if label_key else [str(i) for i in range(len(rows))]
        values = [float(r[primary]) for r in rows] if primary else []
        series = {k: [float(r[k]) for r in rows] for k in numeric_keys}
        return {
            "shape": "table",
            "labels": labels,
            "values": values,
            "series": series,
            "rows": rows,
            "label_key": label_key,
            "value_key": primary,
        }

    if isinstance(parsed, dict):
        # object of named series
        if all(isinstance(v, list) for v in parsed.values()):
            series = {str(k): [float(x) for x in v] for k, v in parsed.items()}
            first = next(iter(series.values()), [])
            return {
                "shape": "multi_series",
                "labels": [str(i) for i in range(len(first))],
                "values": list(first),
                "series": series,
                "rows": [{"index": i, **{k: series[k][i] for k in series if i < len(series[k])}} for i in range(len(first))],
            }
        # single record of scalars → treat values as a series
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in parsed.values()):
            labels = [str(k) for k in parsed.keys()]
            values = [float(v) for v in parsed.values()]
            return {
                "shape": "series",
                "labels": labels,
                "values": values,
                "series": {"values": values},
                "rows": [{"label": l, "value": v} for l, v in zip(labels, values)],
            }

    raise ValueError(
        "unsupported data shape — use a JSON number array, object-of-arrays, "
        "array-of-objects, or CSV with a header row"
    )


def _mean(xs: Sequence[float]) -> float:
    return statistics.fmean(xs) if xs else 0.0


def _stdev(xs: Sequence[float]) -> float:
    return statistics.pstdev(xs) if len(xs) >= 1 else 0.0


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    n = min(len(xs), len(ys))
    if n < 2:
        return None
    x = list(xs[:n])
    y = list(ys[:n])
    mx, my = _mean(x), _mean(y)
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    den_x = math.sqrt(sum((a - mx) ** 2 for a in x))
    den_y = math.sqrt(sum((b - my) ** 2 for b in y))
    if den_x == 0 or den_y == 0:
        return None
    return num / (den_x * den_y)


def _linear_regression(xs: Sequence[float], ys: Sequence[float]) -> Dict[str, Any]:
    n = min(len(xs), len(ys))
    if n < 2:
        raise ValueError("regression requires at least 2 points")
    x = list(xs[:n])
    y = list(ys[:n])
    mx, my = _mean(x), _mean(y)
    var_x = sum((a - mx) ** 2 for a in x)
    if var_x == 0:
        raise ValueError("regression undefined: x has zero variance")
    slope = sum((a - mx) * (b - my) for a, b in zip(x, y)) / var_x
    intercept = my - slope * mx
    preds = [slope * a + intercept for a in x]
    ss_res = sum((b - p) ** 2 for b, p in zip(y, preds))
    ss_tot = sum((b - my) ** 2 for b in y)
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot else 1.0
    return {
        "slope": slope,
        "intercept": intercept,
        "r_squared": r2,
        "n": n,
        "equation": f"y = {slope:.6g}x + {intercept:.6g}",
    }


# ---------------------------------------------------------------------------
# Tool: research_assistant
# ---------------------------------------------------------------------------

OUTPUT_TYPES_RESEARCH = {"brief", "plan", "notes", "report", "json"}


def _extract_keywords(text: str, limit: int = 8) -> List[str]:
    stop = {
        "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "as", "is", "are", "was", "were", "be",
        "this", "that", "these", "those", "it", "its", "into", "about",
        "how", "what", "why", "when", "where", "which", "who", "whom",
        "can", "could", "should", "would", "will", "may", "might", "do",
        "does", "did", "my", "your", "our", "their", "me", "we", "you",
        "i", "research", "analyze", "analysis", "study", "look", "find",
    }
    words = re.findall(r"[A-Za-z][A-Za-z0-9_\-]{2,}", text.lower())
    seen: List[str] = []
    for w in words:
        if w in stop or w in seen:
            continue
        seen.append(w)
        if len(seen) >= limit:
            break
    return seen


def _build_research_questions(task: str, keywords: List[str]) -> List[str]:
    topic = task.strip().rstrip("?.!")
    qs = [
        f"What are the core facts and definitions related to: {topic}?",
        f"What recent developments, data, or primary sources matter for: {topic}?",
        f"What are the main competing viewpoints or uncertainties around: {topic}?",
        f"What evidence would confirm or falsify the leading claims about: {topic}?",
    ]
    if keywords:
        qs.append(f"How do {', '.join(keywords[:3])} interact in this topic?")
    return qs


def _build_search_angles(task: str, keywords: List[str]) -> List[str]:
    base = task.strip()
    angles = [base, f"{base} overview", f"{base} statistics", f"{base} criticism"]
    if len(keywords) >= 2:
        angles.append(" ".join(keywords[:4]))
    # de-dupe while preserving order
    out: List[str] = []
    for a in angles:
        if a not in out:
            out.append(a)
    return out


def research_assistant(
    task: str,
    context: str = "",
    output_type: str = "brief",
    search: Any = True,
    search_count: Any = 5,
) -> Dict[str, Any]:
    """Structure a research task into a reusable brief/plan and persist it.

    Args:
        task: What to research.
        context: Optional background, constraints, or known facts.
        output_type: brief | plan | notes | report | json
        search: If true, attempt a light web search for seed sources.
        search_count: Max seed sources to fetch.
    """
    task = (task or "").strip()
    if not task or task in {"None", "null"}:
        raise ValueError("task is required")

    output_type = _choice(output_type, OUTPUT_TYPES_RESEARCH, "brief")
    context = _noneish(context) or ""
    do_search = _truthy(search, True)
    count = _parse_int(search_count, 5, minimum=1, maximum=10)

    keywords = _extract_keywords(f"{task} {context}")
    questions = _build_research_questions(task, keywords)
    search_angles = _build_search_angles(task, keywords)

    sources: List[Dict[str, str]] = []
    search_note = "search skipped"
    if do_search:
        sources = _search_web(search_angles[0], count=count)
        search_note = f"fetched {len(sources)} seed source(s)" if sources else "web search returned no results (offline or blocked)"

    plan_steps = [
        "Clarify the research question and success criteria.",
        "Gather primary sources and recent evidence (WebSearch / web_fetch / domain docs).",
        "Extract claims, separate facts from inference, and note confidence.",
        "Stress-test with disconfirming evidence and alternative explanations.",
        "Synthesize findings into the requested deliverable and cite sources.",
    ]

    brief = {
        "task": task,
        "context": context or None,
        "keywords": keywords,
        "research_questions": questions,
        "search_angles": search_angles,
        "plan": plan_steps,
        "seed_sources": sources,
        "guidance": [
            "Prefer primary sources and official docs over secondary summaries.",
            "Separate direct evidence / pattern / inference / recommendation.",
            "Use companion engines (web-search, pinata, artifact_creation) for fetch and deliverables.",
            "Persist notable notes back into this session via another research_assistant call.",
        ],
    }

    # Shape output payload
    if output_type == "plan":
        payload: Dict[str, Any] = {
            "plan": plan_steps,
            "research_questions": questions,
            "search_angles": search_angles,
            "seed_sources": sources,
        }
    elif output_type == "notes":
        source_lines = (
            [f"- {s.get('title')}: {s.get('url')}" for s in sources]
            if sources
            else ["- (none yet)"]
        )
        payload = {
            "notes": [
                f"Task: {task}",
                f"Context: {context or '(none)'}",
                f"Keywords: {', '.join(keywords) or '(none)'}",
                "Open questions:",
                *[f"- {q}" for q in questions],
                "Seed sources:",
                *source_lines,
            ],
            "seed_sources": sources,
        }
    elif output_type == "report":
        lines = [
            f"# Research Report: {task}",
            "",
            "## Context",
            context or "_No additional context provided._",
            "",
            "## Keywords",
            ", ".join(keywords) if keywords else "_None extracted._",
            "",
            "## Research Questions",
            *[f"- {q}" for q in questions],
            "",
            "## Proposed Plan",
            *[f"{i}. {step}" for i, step in enumerate(plan_steps, 1)],
            "",
            "## Seed Sources",
        ]
        if sources:
            for s in sources:
                lines.append(f"- [{s.get('title')}]({s.get('url')}) — {s.get('description', '')}")
        else:
            lines.append("_No seed sources fetched yet. Use web-search for deeper coverage._")
        lines.extend(
            [
                "",
                "## Findings",
                "_Pending — fill in after source review._",
                "",
                "## Caveats",
                "- Seed search is best-effort and may be incomplete.",
                "- Do not treat search snippets as verified claims.",
            ]
        )
        report_md = "\n".join(lines)
        _ensure_dirs()
        report_path = OUTPUT_DIR / f"research_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        report_path.write_text(report_md, "utf-8")
        payload = {"markdown": report_md, "path": str(report_path), "seed_sources": sources}
    else:
        # brief + json share the same structured object
        payload = brief

    session = _load_session()
    entry = {
        "id": _next_id("task", session.get("tasks", [])),
        "created_at": _now(),
        "task": task,
        "context": context or None,
        "output_type": output_type,
        "keywords": keywords,
        "seed_source_count": len(sources),
    }
    session.setdefault("tasks", []).append(entry)
    _save_session(session)

    return {
        "ok": True,
        "tool": "research_assistant",
        "output_type": output_type,
        "task_id": entry["id"],
        "search_note": search_note,
        "session_file": str(SESSION_FILE),
        "result": payload,
    }


# ---------------------------------------------------------------------------
# Tool: data_visualization
# ---------------------------------------------------------------------------

VIZ_TYPES = {"auto", "bar", "line", "scatter", "histogram", "table"}
VIZ_OUTPUTS = {"spec", "ascii", "svg", "html", "json", "png"}


def _choose_viz(shape: str, requested: str) -> str:
    if requested != "auto":
        return requested
    if shape == "table":
        return "bar"
    if shape == "multi_series":
        return "line"
    return "bar"


def _ascii_bar(labels: Sequence[str], values: Sequence[float], width: int = 40) -> str:
    if not values:
        return "(no data)"
    max_v = max(abs(v) for v in values) or 1.0
    lines = []
    for label, value in zip(labels, values):
        bar_len = int(round((abs(value) / max_v) * width))
        bar = ("#" if value >= 0 else "-") * bar_len
        lines.append(f"{str(label)[:16]:<16} | {bar} {value:g}")
    return "\n".join(lines)


def _ascii_table(rows: Sequence[Dict[str, Any]], limit: int = 50) -> str:
    if not rows:
        return "(empty)"
    keys = list(rows[0].keys())
    widths = {k: max(len(str(k)), *(len(str(r.get(k, ""))) for r in rows[:limit])) for k in keys}
    header = " | ".join(str(k).ljust(widths[k]) for k in keys)
    sep = "-+-".join("-" * widths[k] for k in keys)
    body = [" | ".join(str(r.get(k, "")).ljust(widths[k]) for k in keys) for r in rows[:limit]]
    return "\n".join([header, sep, *body])


def _svg_bars(labels: Sequence[str], values: Sequence[float], title: str = "Chart") -> str:
    width, height = 640, 360
    pad_l, pad_r, pad_t, pad_b = 60, 20, 40, 60
    chart_w = width - pad_l - pad_r
    chart_h = height - pad_t - pad_b
    max_v = max(values) if values else 1.0
    min_v = min(0.0, min(values) if values else 0.0)
    span = (max_v - min_v) or 1.0
    n = max(len(values), 1)
    bar_w = chart_w / n * 0.7
    gap = chart_w / n

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect width="100%" height="100%" fill="#fafafa"/>',
        f'<text x="{width/2}" y="24" text-anchor="middle" font-family="system-ui,sans-serif" font-size="16">{title}</text>',
        f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{height-pad_b}" stroke="#333"/>',
        f'<line x1="{pad_l}" y1="{height-pad_b}" x2="{width-pad_r}" y2="{height-pad_b}" stroke="#333"/>',
    ]
    zero_y = pad_t + chart_h * (max_v / span)
    for i, (label, value) in enumerate(zip(labels, values)):
        x = pad_l + i * gap + (gap - bar_w) / 2
        h = chart_h * (abs(value) / span)
        y = zero_y - h if value >= 0 else zero_y
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{h:.1f}" fill="#2f6fed"/>')
        parts.append(
            f'<text x="{x + bar_w/2:.1f}" y="{height - pad_b + 16}" text-anchor="middle" '
            f'font-family="system-ui,sans-serif" font-size="10">{_xml_escape(str(label)[:12])}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts)


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _try_matplotlib_png(
    labels: Sequence[str],
    values: Sequence[float],
    viz_type: str,
    title: str,
    path: Path,
) -> Optional[str]:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    fig, ax = plt.subplots(figsize=(8, 4.5))
    if viz_type == "line":
        ax.plot(range(len(values)), values, marker="o")
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(list(labels), rotation=45, ha="right")
    elif viz_type == "scatter":
        ax.scatter(range(len(values)), values)
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(list(labels), rotation=45, ha="right")
    elif viz_type == "histogram":
        ax.hist(values, bins=min(20, max(5, len(values) // 2 or 5)), color="#2f6fed", edgecolor="white")
    else:
        ax.bar(range(len(values)), values, color="#2f6fed")
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(list(labels), rotation=45, ha="right")
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return str(path)


def data_visualization(
    data: str,
    visualization_type: str = "auto",
    output_type: str = "spec",
    title: str = "Data Visualization",
) -> Dict[str, Any]:
    """Visualize structured data as a chart spec and optional rendered artifact.

    Args:
        data: JSON / CSV / number list.
        visualization_type: auto | bar | line | scatter | histogram | table
        output_type: spec | ascii | svg | html | json | png
        title: Chart title used in rendered outputs.
    """
    visualization_type = _choice(visualization_type, VIZ_TYPES, "auto")
    output_type = _choice(output_type, VIZ_OUTPUTS, "spec")
    title = _noneish(title) or "Data Visualization"


    parsed = _parse_data(data)
    viz = _choose_viz(parsed["shape"], visualization_type)
    labels = parsed["labels"]
    values = parsed["values"]

    spec = {
        "type": viz,
        "title": title,
        "shape": parsed["shape"],
        "labels": labels,
        "values": values,
        "series": parsed.get("series", {}),
        "encodings": {
            "x": parsed.get("label_key") or "index",
            "y": parsed.get("value_key") or "value",
        },
    }

    artifact_path: Optional[str] = None
    rendered: Any = None

    if output_type in {"spec", "json"}:
        rendered = spec
    elif output_type == "ascii":
        if viz == "table":
            rendered = _ascii_table(parsed["rows"])
        elif viz == "histogram":
            # rough ascii histogram via rounded bins
            rendered = _ascii_bar(
                [f"bin{i}" for i in range(len(values))],
                values,
            )
        else:
            rendered = _ascii_bar(labels, values)
    elif output_type == "svg":
        svg = _svg_bars(labels, values, title=title)
        _ensure_dirs()
        path = OUTPUT_DIR / f"viz_{datetime.now().strftime('%Y%m%d_%H%M%S')}.svg"
        path.write_text(svg, "utf-8")
        artifact_path = str(path)
        rendered = {"svg": svg, "path": artifact_path}
    elif output_type == "html":
        svg = _svg_bars(labels, values, title=title)
        html = (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            f"<title>{_xml_escape(title)}</title></head><body>"
            f"<h1>{_xml_escape(title)}</h1>{svg}</body></html>"
        )
        _ensure_dirs()
        path = OUTPUT_DIR / f"viz_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        path.write_text(html, "utf-8")
        artifact_path = str(path)
        rendered = {"path": artifact_path}
    elif output_type == "png":
        _ensure_dirs()
        path = OUTPUT_DIR / f"viz_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        saved = _try_matplotlib_png(labels, values, viz, title, path)
        if saved:
            artifact_path = saved
            rendered = {"path": artifact_path}
        else:
            # fallback to SVG when matplotlib missing
            svg = _svg_bars(labels, values, title=title)
            fallback = path.with_suffix(".svg")
            fallback.write_text(svg, "utf-8")
            artifact_path = str(fallback)
            rendered = {
                "path": artifact_path,
                "note": "matplotlib not installed — wrote SVG instead. pip install matplotlib for PNG.",
            }

    session = _load_session()
    entry = {
        "id": _next_id("viz", session.get("visualizations", [])),
        "created_at": _now(),
        "visualization_type": viz,
        "output_type": output_type,
        "title": title,
        "n_points": len(values),
        "artifact_path": artifact_path,
    }
    session.setdefault("visualizations", []).append(entry)
    _save_session(session)

    return {
        "ok": True,
        "tool": "data_visualization",
        "viz_id": entry["id"],
        "visualization_type": viz,
        "output_type": output_type,
        "n_points": len(values),
        "artifact_path": artifact_path,
        "session_file": str(SESSION_FILE),
        "spec": spec,
        "result": rendered,
    }


# ---------------------------------------------------------------------------
# Tool: data_modeling
# ---------------------------------------------------------------------------

MODEL_TYPES = {"summary", "correlation", "regression", "trend", "forecast"}
MODEL_OUTPUTS = {"json", "markdown", "table"}


def _summarize_series(name: str, values: Sequence[float]) -> Dict[str, Any]:
    if not values:
        return {"name": name, "n": 0}
    ordered = sorted(values)
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    return {
        "name": name,
        "n": len(values),
        "min": min(values),
        "max": max(values),
        "mean": _mean(values),
        "median": median,
        "stdev": _stdev(values),
        "sum": sum(values),
    }


def data_modeling(
    data: str,
    model_type: str = "summary",
    output_type: str = "json",
) -> Dict[str, Any]:
    """Run lightweight statistical models on structured data.

    Args:
        data: JSON / CSV / number list.
        model_type: summary | correlation | regression | trend | forecast
        output_type: json | markdown | table
    """
    model_type = _choice(model_type, MODEL_TYPES, "summary")
    output_type = _choice(output_type, MODEL_OUTPUTS, "json")

    parsed = _parse_data(data)
    series: Dict[str, List[float]] = {k: list(v) for k, v in parsed.get("series", {}).items()}
    if not series and parsed.get("values"):
        series = {"values": list(parsed["values"])}

    model: Dict[str, Any]

    if model_type == "summary":
        model = {
            "type": "summary",
            "series": [_summarize_series(name, vals) for name, vals in series.items()],
        }

    elif model_type == "correlation":
        names = list(series.keys())
        matrix: List[Dict[str, Any]] = []
        for i, a in enumerate(names):
            for b in names[i:]:
                r = _pearson(series[a], series[b])
                matrix.append({"x": a, "y": b, "r": r})
        model = {"type": "correlation", "pairs": matrix}

    elif model_type in {"regression", "trend"}:
        names = list(series.keys())
        if len(names) >= 2:
            x_name, y_name = names[0], names[1]
            xs, ys = series[x_name], series[y_name]
        else:
            y_name = names[0]
            ys = series[y_name]
            x_name = "index"
            xs = [float(i) for i in range(len(ys))]
        fit = _linear_regression(xs, ys)
        model = {
            "type": model_type,
            "x": x_name,
            "y": y_name,
            **fit,
            "interpretation": (
                f"{y_name} changes by ~{fit['slope']:.4g} per unit of {x_name} "
                f"(R²={fit['r_squared']:.3f})."
            ),
        }

    else:  # forecast — naive linear extrapolation
        names = list(series.keys())
        y_name = names[0]
        ys = series[y_name]
        xs = [float(i) for i in range(len(ys))]
        fit = _linear_regression(xs, ys)
        horizon = min(5, max(1, len(ys) // 3 or 1))
        forecasts = []
        for step in range(1, horizon + 1):
            x = float(len(ys) - 1 + step)
            forecasts.append({"step": step, "x": x, "y_hat": fit["slope"] * x + fit["intercept"]})
        model = {
            "type": "forecast",
            "method": "linear_extrapolation",
            "series": y_name,
            "fit": fit,
            "horizon": horizon,
            "forecasts": forecasts,
            "warning": "Naive linear forecast — not suitable for seasonal or nonlinear series.",
        }

    # Format
    if output_type == "markdown":
        lines = [f"# Model: {model_type}", "", "```json", json.dumps(model, indent=2), "```"]
        rendered: Any = "\n".join(lines)
    elif output_type == "table":
        if model_type == "summary":
            rendered = _ascii_table(model["series"])
        elif model_type == "correlation":
            rendered = _ascii_table(model["pairs"])
        elif model_type == "forecast":
            rendered = _ascii_table(model["forecasts"])
        else:
            rendered = _ascii_table(
                [
                    {"metric": "slope", "value": model.get("slope")},
                    {"metric": "intercept", "value": model.get("intercept")},
                    {"metric": "r_squared", "value": model.get("r_squared")},
                    {"metric": "n", "value": model.get("n")},
                ]
            )
    else:
        rendered = model

    session = _load_session()
    entry = {
        "id": _next_id("model", session.get("models", [])),
        "created_at": _now(),
        "model_type": model_type,
        "output_type": output_type,
        "series_count": len(series),
    }
    session.setdefault("models", []).append(entry)
    _save_session(session)

    return {
        "ok": True,
        "tool": "data_modeling",
        "model_id": entry["id"],
        "model_type": model_type,
        "output_type": output_type,
        "session_file": str(SESSION_FILE),
        "model": model,
        "result": rendered,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli() -> None:
    parser = argparse.ArgumentParser(description="Research Assistant Engine for Switchbay")
    sub = parser.add_subparsers(dest="tool", required=True)

    p = sub.add_parser("research_assistant", help="Structure and persist a research task")
    p.add_argument("--task", required=True, help="Research question or assignment")
    p.add_argument("--context", default="", help="Optional background or constraints")
    p.add_argument(
        "--output_type",
        default="brief",
        help="brief | plan | notes | report | json",
    )
    p.add_argument(
        "--search",
        default="true",
        help="Fetch seed web sources (true/false). Default: true",
    )
    p.add_argument("--search_count", default="5", help="Max seed sources (default 5)")

    p = sub.add_parser("data_visualization", help="Visualize structured data")
    p.add_argument("--data", required=True, help="JSON, CSV, or number list")
    p.add_argument(
        "--visualization_type",
        default="auto",
        help="auto | bar | line | scatter | histogram | table",
    )
    p.add_argument(
        "--output_type",
        default="spec",
        help="spec | ascii | svg | html | json | png",
    )
    p.add_argument("--title", default="Data Visualization", help="Chart title")

    p = sub.add_parser("data_modeling", help="Run lightweight statistical models")
    p.add_argument("--data", required=True, help="JSON, CSV, or number list")
    p.add_argument(
        "--model_type",
        default="summary",
        help="summary | correlation | regression | trend | forecast",
    )
    p.add_argument(
        "--output_type",
        default="json",
        help="json | markdown | table",
    )

    args = parser.parse_args()
    kwargs = {k: v for k, v in vars(args).items() if k != "tool"}

    try:
        if args.tool == "research_assistant":
            result = research_assistant(**kwargs)
        elif args.tool == "data_visualization":
            result = data_visualization(**kwargs)
        elif args.tool == "data_modeling":
            result = data_modeling(**kwargs)
        else:
            raise ValueError(f"Unknown tool: {args.tool}")

        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    _cli()
