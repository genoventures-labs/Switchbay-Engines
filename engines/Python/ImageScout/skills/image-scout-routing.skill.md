---
id: image-scout-routing
name: Image Scout Routing
description: Prepare local paths and image URLs for accurate cloud vision analysis.
engine: image-scout
languages: [python]
agents: [any]
tags: [vision, images, screenshots, ocr, multimodal, switchbay-engine]
triggers: [analyze image, inspect screenshot, read image text, image URL, local image path, vision payload]
---

# Image Scout Routing

## Use When

Use this engine when a model must understand an image from a local path or
public URL, especially when the source is oversized, rotated, transparent,
text-heavy, or visually dense.

## Tool Map

- `inspect_image`: metadata, integrity, dimensions, and detail-strategy advice.
- `prepare_image`: one normalized provider-safe image.
- `build_vision_bundle`: overview plus overlapping detail tiles and manifest.
- `build_vision_bundle_with_ocr`: bundle plus optional local Tesseract OCR.
- `vision_prompt`: task-specific reasoning instructions without image mutation.
- `encode_for_provider`: provider-native base64 JSON saved outside model context.
- `doctor`: dependency and capability status.

## Method

1. Inspect unknown sources.
2. For normal images, prepare one normalized artifact.
3. For dense images, build a bundle and analyze its `reading_order`: overview
   first, then tiles.
4. Use the manifest's response contract: visible facts, extracted text,
   interpretation, and uncertainties.
5. Use native provider encoding only at the final transport boundary.

## Guardrails

- Never treat OCR as authoritative without pixel verification.
- Never invent obscured text or unseen image regions.
- Keep base64 payloads on disk and return their paths.
- Do not bypass private-network URL blocking for untrusted model-supplied URLs.
