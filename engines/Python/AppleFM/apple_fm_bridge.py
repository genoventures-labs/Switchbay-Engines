#!/usr/bin/env python3
"""Apple Foundation Models bridge for Switchbay.

Uses the `applefoundationmodels` package (pip install apple-foundation-models).
Requires macOS 26 Tahoe with Apple Intelligence enabled.

Protocol
--------
stdin:  one JSON line with the request
stdout: JSON lines (newline-delimited)
  {"type": "token",       "text": "..."}       streaming chunk
  {"type": "done",        "text": "..."}        end, full accumulated text
  {"type": "tool_call",   "id": "...", "name": "...", "args": {...}}  tool invocation
  {"type": "error",       "message": "..."}     hard error
  {"type": "unavailable", "message": "..."}     Apple Intelligence not available

When tool_call events are emitted the bridge blocks waiting for a tool_result
on stdin:
  {"type": "tool_result", "id": "...", "result": "..."}

This bidirectional protocol lets TypeScript execute Switchbay tools and
return results to the model without any network round-trip.
"""

import asyncio
import json
import sys
import threading
from typing import Optional

# ──────────────────────────────────────────────────────────────────
# AFM3 variant → generation parameter profiles
# All variants use the same on-device model for now; future Swift
# bridge will add true per-model routing via Foundation Models API.
# ──────────────────────────────────────────────────────────────────
VARIANT_PARAMS: dict[str, dict] = {
    # AFM 3 Core — 3B dense, fast, everyday tasks
    "core":           {"temperature": 1.0, "max_tokens": 1024},
    "default":        {"temperature": 1.0, "max_tokens": 1024},
    # AFM 3 Core Advanced — 20B sparse, multimodal, heavier tasks
    "core-advanced":  {"temperature": 0.7, "max_tokens": 2048},
    "advanced":       {"temperature": 0.7, "max_tokens": 2048},
    "medium":         {"temperature": 0.7, "max_tokens": 2048},
    # AFM 3 Cloud — fast server workhorse
    "cloud":          {"temperature": 0.9, "max_tokens": 2048},
    # AFM 3 Cloud Pro — complex reasoning (lower temp = more focused)
    "cloud-pro":      {"temperature": 0.3, "max_tokens": 4096},
    "pro":            {"temperature": 0.3, "max_tokens": 4096},
    # AFM 3 Cloud Image — text-to-image (not supported via text bridge)
    "image":          None,
}


def emit(obj: dict) -> None:
    print(json.dumps(obj), flush=True)


def read_tool_result() -> Optional[dict]:
    """Block on stdin for a tool_result line, return parsed dict or None."""
    try:
        line = sys.stdin.readline()
        if not line:
            return None
        return json.loads(line.strip())
    except Exception:
        return None


def main() -> None:
    try:
        from applefoundationmodels import AsyncSession, apple_intelligence_available
    except ImportError:
        emit({"type": "error", "message": (
            "applefoundationmodels not installed. "
            "Run: pip3 install apple-foundation-models --break-system-packages"
        )})
        sys.exit(1)

    if not apple_intelligence_available():
        try:
            from applefoundationmodels import Session
            reason = Session.get_availability_reason() or "unknown"
        except Exception:
            reason = "unknown"
        emit({"type": "unavailable", "message": (
            f"Apple Intelligence not available: {reason}. "
            "Requires macOS 26 Tahoe with Apple Intelligence enabled in "
            "System Settings > Apple Intelligence & Siri."
        )})
        return

    raw = sys.stdin.readline().strip()
    if not raw:
        emit({"type": "error", "message": "No input on stdin"})
        sys.exit(1)

    try:
        req = json.loads(raw)
    except json.JSONDecodeError as e:
        emit({"type": "error", "message": f"Invalid JSON: {e}"})
        sys.exit(1)

    asyncio.run(handle(AsyncSession, req))


async def handle(AsyncSession, req: dict) -> None:
    system: str = req.get("system") or ""
    messages: list = req.get("messages") or []
    variant: str = req.get("model") or "default"
    tool_defs: list = req.get("tools") or []

    # Check if this variant is supported
    params = VARIANT_PARAMS.get(variant)
    if params is None:
        emit({"type": "error", "message": (
            f"Model variant '{variant}' (AFM 3 Cloud Image) is not supported "
            "via text generation. Use the apple_fm_generate engine tool for "
            "image generation when Apple adds Python API support."
        )})
        return

    temperature: float = float(req.get("temperature") or params["temperature"])
    max_tokens: int = int(req.get("max_tokens") or params["max_tokens"])

    # Separate conversation from current message
    conversation = [m for m in messages if m.get("role") in ("user", "assistant", "tool")]
    if not conversation:
        emit({"type": "error", "message": "No messages"})
        return

    # Find last user message
    last_user_idx = None
    for i in range(len(conversation) - 1, -1, -1):
        if conversation[i].get("role") == "user":
            last_user_idx = i
            break

    if last_user_idx is None:
        emit({"type": "error", "message": "No user message found"})
        return

    history = conversation[:last_user_idx]
    current_text = _extract_text(conversation[last_user_idx].get("content", ""))

    # Build augmented system prompt
    augmented_system = _build_system(system, tool_defs)

    # Build history context — injected into system prompt for efficiency.
    # Avoids replay overhead (N-1 API calls for N-turn conversations).
    if history:
        history_text = _format_history(history)
        if augmented_system:
            augmented_system += f"\n\n---\n## Conversation so far\n{history_text}"
        else:
            augmented_system = f"## Conversation so far\n{history_text}"

    # Build native tool functions if tools were provided
    native_tools = []
    if tool_defs:
        native_tools = _make_tool_proxies(tool_defs)

    try:
        session_kwargs: dict = {}
        if augmented_system:
            session_kwargs["instructions"] = augmented_system
        if native_tools:
            session_kwargs["tools"] = native_tools

        async with AsyncSession(**session_kwargs) as session:
            full_text = ""
            async for chunk in session.generate(
                current_text,
                stream=True,
                temperature=temperature,
                max_tokens=max_tokens,
            ):
                if chunk.content:
                    full_text += chunk.content
                    emit({"type": "token", "text": chunk.content})
                if chunk.finish_reason == "tool_calls":
                    break

            emit({"type": "done", "text": full_text})
    except Exception as e:
        cls = type(e).__name__
        if "NotAvailable" in cls or "Availability" in cls:
            emit({"type": "unavailable", "message": f"Apple Intelligence not available: {e}"})
        elif "Guardrail" in cls:
            emit({"type": "error", "message": f"Content policy violation: {e}"})
        else:
            emit({"type": "error", "message": f"{cls}: {e}"})


def _build_system(system: str, tool_defs: list) -> str:
    """Inject tool descriptions into system prompt for inline tool calling."""
    if not tool_defs:
        return system
    tool_docs = []
    for t in tool_defs:
        fn = t.get("function", {})
        schema = json.dumps(fn.get("parameters") or {})
        tool_docs.append(f"- **{fn.get('name','')}**: {fn.get('description','')}\n  Parameters: {schema}")
    tool_section = (
        "\n\n## Available Tools\n"
        "When you need to call a tool, output it using this exact format:\n"
        "<tool_call>{\"name\": \"tool_name\", \"args\": {\"param\": \"value\"}}</tool_call>\n\n"
        + "\n".join(tool_docs)
    )
    return (system + tool_section) if system else tool_section.lstrip()


def _make_tool_proxies(tool_defs: list) -> list:
    """
    Create Python tool proxy functions for the SDK's native tool calling.

    Each proxy, when called by the model, emits a tool_call event, blocks
    waiting for a tool_result on stdin, and returns the result string.
    Note: this uses a lock so only one tool runs at a time (SDK constraint).
    """
    tool_lock = threading.Lock()
    proxies = []
    for t in tool_defs:
        fn = t.get("function", {})
        name = fn.get("name", "")
        description = fn.get("description", "")
        if not name:
            continue

        def make_proxy(tool_name: str, tool_desc: str):
            def proxy(**kwargs) -> str:
                with tool_lock:
                    tool_id = f"tc_{tool_name}_{id(kwargs)}"
                    emit({"type": "tool_call", "id": tool_id, "name": tool_name, "args": kwargs})
                    result = read_tool_result()
                    if result and result.get("type") == "tool_result":
                        return str(result.get("result", ""))
                    return f"Error: tool result not received for {tool_name}"
            proxy.__name__ = tool_name
            proxy.__doc__ = tool_desc
            return proxy

        proxies.append(make_proxy(name, description))
    return proxies


def _format_history(history: list) -> str:
    """Format conversation history as readable text for system prompt injection."""
    lines = []
    for msg in history:
        role = msg.get("role", "unknown")
        content = _extract_text(msg.get("content", ""))
        if role == "user":
            lines.append(f"User: {content}")
        elif role == "assistant":
            lines.append(f"Assistant: {content}")
        elif role == "tool":
            lines.append(f"[Tool result: {content}]")
    return "\n".join(lines)


def _extract_text(content) -> str:
    """Extract plain text from a message content field."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                text = part.get("text") or part.get("content") or ""
                if text:
                    parts.append(str(text))
            elif isinstance(part, str):
                parts.append(part)
        return " ".join(parts)
    return str(content) if content is not None else ""


if __name__ == "__main__":
    main()
