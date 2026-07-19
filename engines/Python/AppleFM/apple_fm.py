#!/usr/bin/env python3
"""Apple Foundation Models engine tools for Switchbay.

Called by the engine runner via:
  python3 apple_fm.py <tool_name> [args_json]

AFM3 Model Family
-----------------
  core            AFM 3 Core         3B dense, on-device, fast, everyday tasks
  core-advanced   AFM 3 Core Advanced  20B sparse (1-4B active), multimodal, heavier tasks
  cloud           AFM 3 Cloud        Private Cloud Compute, fast server workhorse
  cloud-pro       AFM 3 Cloud Pro    Private Cloud Compute, complex reasoning
  image           AFM 3 Cloud Image  Visual generation / Image Playground (not yet in API)

Note: The current Python SDK routes all on-device inference to the system
default model. A future Swift bridge will add per-model selection for the
full AFM3 family. Cloud variants run on Apple's Private Cloud Compute and
are routed automatically by the framework when on-device is insufficient.
"""

import asyncio
import json
import sys

VARIANT_PARAMS = {
    "core":          {"temperature": 1.0, "max_tokens": 1024,  "label": "AFM 3 Core"},
    "default":       {"temperature": 1.0, "max_tokens": 1024,  "label": "AFM 3 Core"},
    "core-advanced": {"temperature": 0.7, "max_tokens": 2048,  "label": "AFM 3 Core Advanced"},
    "advanced":      {"temperature": 0.7, "max_tokens": 2048,  "label": "AFM 3 Core Advanced"},
    "medium":        {"temperature": 0.7, "max_tokens": 2048,  "label": "AFM 3 Core Advanced"},
    "cloud":         {"temperature": 0.9, "max_tokens": 2048,  "label": "AFM 3 Cloud"},
    "cloud-pro":     {"temperature": 0.3, "max_tokens": 4096,  "label": "AFM 3 Cloud Pro"},
    "pro":           {"temperature": 0.3, "max_tokens": 4096,  "label": "AFM 3 Cloud Pro"},
}


def main() -> None:
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: apple_fm.py <tool_name> [args_json]"}))
        sys.exit(1)

    tool_name = sys.argv[1]
    args: dict = {}
    if len(sys.argv) > 2:
        try:
            args = json.loads(sys.argv[2])
        except json.JSONDecodeError:
            pass

    if tool_name == "apple_fm_check":
        print(check_availability())
    elif tool_name == "apple_fm_generate":
        print(asyncio.run(generate(args)))
    else:
        print(json.dumps({"error": f"Unknown tool: {tool_name}"}))
        sys.exit(1)


def check_availability() -> str:
    try:
        from applefoundationmodels import Session, Availability, apple_intelligence_available
    except ImportError:
        return json.dumps({
            "available": False,
            "models": [],
            "message": (
                "applefoundationmodels not installed. "
                "Run: pip3 install apple-foundation-models --break-system-packages"
            ),
            "install_command": "pip3 install apple-foundation-models --break-system-packages",
        })

    available = apple_intelligence_available()
    status = Session.check_availability()
    reason = Session.get_availability_reason() or ""

    if available:
        models = [
            {
                "id": "apple-fm/core",
                "label": "AFM 3 Core",
                "params": "3B dense",
                "lane": "apple-local",
                "description": "Fast everyday tasks, runs entirely on-device (offline, free)",
            },
            {
                "id": "apple-fm/core-advanced",
                "label": "AFM 3 Core Advanced",
                "params": "20B sparse / 1–4B active",
                "lane": "apple-local",
                "description": "Heavier tasks, natively multimodal, on-device",
            },
            {
                "id": "apple-fm/cloud",
                "label": "AFM 3 Cloud",
                "params": "server",
                "lane": "apple-cloud",
                "description": "Server-side workhorse via Private Cloud Compute",
                "note": "Routed automatically by the framework; no data leaves Apple infra",
            },
            {
                "id": "apple-fm/cloud-pro",
                "label": "AFM 3 Cloud Pro",
                "params": "server (reasoning)",
                "lane": "apple-cloud",
                "description": "Complex reasoning and agentic tasks via Private Cloud Compute",
                "note": "Routed automatically by the framework; no data leaves Apple infra",
            },
            {
                "id": "apple-fm/image",
                "label": "AFM 3 Cloud Image",
                "params": "server (image gen)",
                "lane": "apple-image",
                "description": "Visual generation and editing, powers Image Playground",
                "note": "Text-to-image API not yet exposed in current Python SDK",
                "available": False,
            },
        ]
        return json.dumps({
            "available": True,
            "status": "AVAILABLE",
            "message": reason or "Apple Intelligence is available and ready.",
            "models": models,
            "sdk_version": _get_sdk_version(),
            "lane": "apple",
            "cli_usage": "switchbay --lane apple \"your prompt\"",
            "model_selection": "switchbay --lane apple --model core-advanced \"your prompt\"",
        })
    else:
        status_name = status.name if hasattr(status, "name") else str(status)
        return json.dumps({
            "available": False,
            "status": status_name,
            "message": reason or "Apple Intelligence not available.",
            "models": [],
            "setup": [
                "1. Upgrade to macOS 26 Tahoe",
                "2. Open System Settings > Apple Intelligence & Siri",
                "3. Enable Apple Intelligence and wait for model download",
            ],
        })


async def generate(args: dict) -> str:
    prompt: str = args.get("prompt") or ""
    system: str = args.get("system") or ""
    variant: str = args.get("model") or "core"

    if not prompt:
        return json.dumps({"error": "prompt is required"})

    if variant == "image":
        return json.dumps({
            "error": "AFM 3 Cloud Image (text-to-image) is not yet available via the Python SDK. "
                     "Use Image Playground in macOS 26 apps instead."
        })

    params = VARIANT_PARAMS.get(variant, VARIANT_PARAMS["core"])
    temperature = float(args.get("temperature") or params["temperature"])
    max_tokens = int(args.get("max_tokens") or params["max_tokens"])

    try:
        from applefoundationmodels import AsyncSession, apple_intelligence_available
    except ImportError:
        return json.dumps({"error": "applefoundationmodels not installed."})

    if not apple_intelligence_available():
        return json.dumps({"error": "Apple Intelligence not available on this device."})

    try:
        session_kwargs: dict = {}
        if system:
            session_kwargs["instructions"] = system
        async with AsyncSession(**session_kwargs) as session:
            response = await session.generate(prompt, temperature=temperature, max_tokens=max_tokens)
            return json.dumps({
                "text": response.text,
                "model": variant,
                "label": params["label"],
                "finish_reason": response.finish_reason or "stop",
            })
    except Exception as e:
        cls = type(e).__name__
        if "NotAvailable" in cls:
            return json.dumps({"error": "Apple Intelligence not available."})
        if "Guardrail" in cls:
            return json.dumps({"error": f"Content policy violation: {e}"})
        return json.dumps({"error": f"{cls}: {e}"})


def _get_sdk_version() -> str:
    try:
        import applefoundationmodels
        return getattr(applefoundationmodels, "__version__", "unknown")
    except Exception:
        return "unknown"


if __name__ == "__main__":
    main()
