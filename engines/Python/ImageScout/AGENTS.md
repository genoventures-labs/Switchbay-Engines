# Image Scout

Image Scout prepares image evidence for Switchbay vision lanes. It does not call
a model itself. Use it to inspect, normalize, tile, OCR, prompt, or encode local
images and public image URLs before handing artifacts to a cloud vision model.

## Dependencies

- Required: Python 3.10+ and Pillow (`python3 -m pip install Pillow`)
- Optional: Tesseract for fully local OCR (`brew install tesseract` on macOS)
- No API key or paid service is required.

## Routing

- Start with `inspect_image` when image size, format, or suitability is unknown.
- Use `prepare_image` for an ordinary single-image vision request.
- Use `build_vision_bundle` for large screenshots, documents, charts, code, or
  images where small details matter.
- Use `build_vision_bundle_with_ocr` when exact visible text matters.
- Use `encode_for_provider` only when the caller needs a native base64 content
  block on disk. It supports OpenAI Responses/Chat, Anthropic, and Gemini.

## Guardrails

- Treat OCR as a hint; verify it against pixels.
- Keep visible facts separate from interpretation.
- Do not claim precision beyond the image resolution.
- Public URLs are allowed. Private, loopback, and link-local destinations are
  blocked by default to prevent server-side request forgery.
- Generated base64 stays in payload files rather than flooding model context.
