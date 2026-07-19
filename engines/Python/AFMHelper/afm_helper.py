"""AFM Helper Engine — deterministic scaffolding for Apple's Foundation Models.

This engine does not call Apple's Foundation Models directly. It prepares compact,
well-scoped requests for small on-device models and validates/repairs their output.
All tools print JSON for Switchbay.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any, Dict, List, Optional

NONEISH = {"", "none", "null"}


def _noneish(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return None if text.lower() in NONEISH else text


def _parse_int(value: Any, default: int, minimum: int = 1, maximum: int = 100000) -> int:
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


def _split_items(value: Any) -> List[str]:
    text = _noneish(value)
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            pass
    return [item.strip() for item in re.split(r"[\n,;]+", text) if item.strip()]


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 2) // 3)


def _sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def _compact(text: str, max_chars: int) -> str:
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    chosen: List[str] = []
    used = 0
    for sentence in _sentences(text):
        if used + len(sentence) + 1 > max_chars:
            break
        chosen.append(sentence)
        used += len(sentence) + 1
    if chosen:
        return " ".join(chosen)
    return text[: max(0, max_chars - 1)].rstrip() + "…"


def analyze_task(task: str, context: Any = None, max_context_tokens: Any = "1800") -> Dict[str, Any]:
    task_text = _noneish(task)
    if not task_text:
        raise ValueError("task must not be empty")
    context_text = _noneish(context) or ""
    budget = _parse_int(max_context_tokens, 1800, 128, 32000)
    combined = f"{task_text}\n{context_text}".strip()
    tokens = _estimate_tokens(combined)
    ambiguity_markers = ["maybe", "somehow", "etc", "something", "better", "improve", "handle it"]
    ambiguities = [m for m in ambiguity_markers if m in task_text.lower()]
    compound = len(re.findall(r"\b(and|then|also|plus|after|before)\b", task_text.lower()))
    needs_decomposition = tokens > int(budget * 0.75) or compound >= 3
    return {
        "ok": True,
        "summary": {
            "estimated_input_tokens": tokens,
            "context_budget": budget,
            "fits_budget": tokens <= budget,
            "needs_decomposition": needs_decomposition,
            "ambiguity_count": len(ambiguities),
        },
        "recommendation": {
            "mode": "decompose" if needs_decomposition else "single_pass",
            "temperature": 0.0 if any(k in task_text.lower() for k in ["json", "schema", "extract", "classify"]) else 0.2,
            "request_structured_output": any(k in task_text.lower() for k in ["json", "fields", "schema", "extract", "classify"]),
            "trim_context": tokens > budget,
        },
        "ambiguity_markers": ambiguities,
    }


def decompose_task(task: str, max_steps: Any = "6") -> Dict[str, Any]:
    task_text = _noneish(task)
    if not task_text:
        raise ValueError("task must not be empty")
    limit = _parse_int(max_steps, 6, 2, 12)
    pieces = [p.strip(" .") for p in re.split(r"\b(?:then|and then|after that|finally|also)\b|[\n;]+", task_text, flags=re.I) if p.strip(" .")]
    if len(pieces) <= 1:
        pieces = [task_text]
    steps = []
    for idx, piece in enumerate(pieces[:limit], start=1):
        steps.append({
            "step": idx,
            "instruction": piece,
            "expected_output": "A concise, directly usable result for this step.",
            "depends_on": [idx - 1] if idx > 1 else [],
        })
    return {"ok": True, "step_count": len(steps), "steps": steps}


def compile_prompt(task: str, context: Any = None, constraints: Any = None, output_schema: Any = None, max_input_tokens: Any = "2200") -> Dict[str, Any]:
    task_text = _noneish(task)
    if not task_text:
        raise ValueError("task must not be empty")
    context_text = _noneish(context) or ""
    constraints_list = _split_items(constraints)
    schema_text = _noneish(output_schema)
    budget = _parse_int(max_input_tokens, 2200, 256, 32000)
    fixed = 900 + len(task_text) + sum(len(x) for x in constraints_list) + (len(schema_text) if schema_text else 0)
    context_chars = max(0, (budget * 3) - fixed)
    compact_context = _compact(context_text, context_chars) if context_text else ""

    sections = [
        "ROLE\nYou are a precise on-device assistant. Follow the requested format exactly.",
        f"TASK\n{task_text}",
    ]
    if compact_context:
        sections.append(f"CONTEXT\n{compact_context}")
    if constraints_list:
        sections.append("CONSTRAINTS\n" + "\n".join(f"- {item}" for item in constraints_list))
    if schema_text:
        sections.append(f"OUTPUT FORMAT\nReturn only valid JSON matching this schema or example:\n{schema_text}")
    else:
        sections.append("OUTPUT FORMAT\nReturn the answer directly. Be concise. Do not narrate your process.")
    sections.append("CHECK\nBefore answering, verify completeness, format, and that no requested field is missing.")
    prompt = "\n\n".join(sections)
    return {
        "ok": True,
        "prompt": prompt,
        "summary": {
            "estimated_tokens": _estimate_tokens(prompt),
            "budget": budget,
            "context_truncated": compact_context != " ".join(context_text.split()) if context_text else False,
            "constraint_count": len(constraints_list),
            "structured_output": bool(schema_text),
        },
    }


def build_context(query: str, documents: str, max_tokens: Any = "1600", max_chunks: Any = "8") -> Dict[str, Any]:
    query_text = _noneish(query)
    docs_text = _noneish(documents)
    if not query_text or not docs_text:
        raise ValueError("query and documents are required")
    token_budget = _parse_int(max_tokens, 1600, 128, 32000)
    chunk_limit = _parse_int(max_chunks, 8, 1, 50)
    keywords = {w for w in re.findall(r"[a-zA-Z0-9_]{3,}", query_text.lower())}
    raw_chunks = [c.strip() for c in re.split(r"\n\s*\n|(?<=\.)\s+(?=[A-Z])", docs_text) if c.strip()]
    ranked = []
    for idx, chunk in enumerate(raw_chunks):
        words = set(re.findall(r"[a-zA-Z0-9_]{3,}", chunk.lower()))
        overlap = len(keywords & words)
        density = overlap / max(1, len(keywords))
        ranked.append((overlap, density, -idx, chunk))
    ranked.sort(reverse=True)
    selected, used = [], 0
    for overlap, density, _, chunk in ranked:
        if len(selected) >= chunk_limit:
            break
        chunk_tokens = _estimate_tokens(chunk)
        if used + chunk_tokens > token_budget:
            remaining_chars = max(0, (token_budget - used) * 3)
            if remaining_chars > 80:
                chunk = _compact(chunk, remaining_chars)
                chunk_tokens = _estimate_tokens(chunk)
            else:
                continue
        selected.append({"text": chunk, "keyword_hits": overlap, "relevance": round(density, 3)})
        used += chunk_tokens
    return {"ok": True, "query": query_text, "estimated_tokens": used, "chunks": selected}


def _extract_json_candidate(text: str) -> str:
    stripped = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", stripped, flags=re.I | re.S)
    if fenced:
        stripped = fenced.group(1).strip()
    starts = [p for p in (stripped.find("{"), stripped.find("[")) if p >= 0]
    if starts:
        start = min(starts)
        end = max(stripped.rfind("}"), stripped.rfind("]"))
        if end >= start:
            stripped = stripped[start : end + 1]
    return stripped


def repair_json(text: str) -> Dict[str, Any]:
    raw = _noneish(text)
    if not raw:
        raise ValueError("text must not be empty")
    candidate = _extract_json_candidate(raw)
    attempts = [candidate]
    repaired = re.sub(r",\s*([}\]])", r"\1", candidate)
    repaired = re.sub(r"\bTrue\b", "true", repaired)
    repaired = re.sub(r"\bFalse\b", "false", repaired)
    repaired = re.sub(r"\bNone\b", "null", repaired)
    attempts.append(repaired)
    for idx, attempt in enumerate(attempts):
        try:
            parsed = json.loads(attempt)
            return {"ok": True, "repaired": idx > 0 or attempt != raw.strip(), "data": parsed, "json": json.dumps(parsed, ensure_ascii=False)}
        except json.JSONDecodeError:
            continue
    return {"ok": False, "error": "Could not deterministically repair JSON", "candidate": repaired}


def validate_output(text: str, required_keys: Any = None, max_chars: Any = "12000", expect_json: Any = "false") -> Dict[str, Any]:
    raw = _noneish(text)
    if raw is None:
        raise ValueError("text must not be empty")
    keys = _split_items(required_keys)
    limit = _parse_int(max_chars, 12000, 1, 1000000)
    json_expected = _truthy(expect_json, False)
    errors: List[str] = []
    warnings: List[str] = []
    data: Any = None
    if len(raw) > limit:
        errors.append(f"output exceeds max_chars ({len(raw)} > {limit})")
    if json_expected:
        repaired = repair_json(raw)
        if not repaired.get("ok"):
            errors.append("output is not valid JSON")
        else:
            data = repaired["data"]
            if repaired.get("repaired"):
                warnings.append("JSON required deterministic cleanup")
            if keys:
                if not isinstance(data, dict):
                    errors.append("required_keys were supplied but JSON root is not an object")
                else:
                    missing = [key for key in keys if key not in data]
                    if missing:
                        errors.append("missing required keys: " + ", ".join(missing))
    elif keys:
        lowered = raw.lower()
        missing = [key for key in keys if key.lower() not in lowered]
        if missing:
            warnings.append("possible missing fields: " + ", ".join(missing))
    return {
        "ok": not errors,
        "summary": {"characters": len(raw), "estimated_tokens": _estimate_tokens(raw), "error_count": len(errors), "warning_count": len(warnings)},
        "errors": errors,
        "warnings": warnings,
        "data": data,
    }


TOOLS = {
    "analyze_task": analyze_task,
    "decompose_task": decompose_task,
    "compile_prompt": compile_prompt,
    "build_context": build_context,
    "repair_json": repair_json,
    "validate_output": validate_output,
}


def _cli() -> None:
    parser = argparse.ArgumentParser(description="Small-model scaffolding for Apple Foundation Models")
    sub = parser.add_subparsers(dest="tool", required=True)

    p = sub.add_parser("analyze_task")
    p.add_argument("--task", required=True)
    p.add_argument("--context", default=None)
    p.add_argument("--max_context_tokens", default="1800")

    p = sub.add_parser("decompose_task")
    p.add_argument("--task", required=True)
    p.add_argument("--max_steps", default="6")

    p = sub.add_parser("compile_prompt")
    p.add_argument("--task", required=True)
    p.add_argument("--context", default=None)
    p.add_argument("--constraints", default=None)
    p.add_argument("--output_schema", default=None)
    p.add_argument("--max_input_tokens", default="2200")

    p = sub.add_parser("build_context")
    p.add_argument("--query", required=True)
    p.add_argument("--documents", required=True)
    p.add_argument("--max_tokens", default="1600")
    p.add_argument("--max_chunks", default="8")

    p = sub.add_parser("repair_json")
    p.add_argument("--text", required=True)

    p = sub.add_parser("validate_output")
    p.add_argument("--text", required=True)
    p.add_argument("--required_keys", default=None)
    p.add_argument("--max_chars", default="12000")
    p.add_argument("--expect_json", default="false")

    args = parser.parse_args()
    kwargs = vars(args)
    tool = kwargs.pop("tool")
    try:
        result = TOOLS[tool](**kwargs)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    _cli()
