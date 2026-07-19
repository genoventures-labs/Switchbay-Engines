# Web Ingest Engine

Use `ingest_website` when a model needs a webpage converted into durable, local, retrieval-friendly text.

- Start with `render=false`; it uses only the Python standard library.
- Retry with `render=true` only when the page is JavaScript-heavy or the static HTML is clearly incomplete.
- The render path requires `pip install playwright` and `playwright install chromium`.
- Outputs are written to a timestamped directory containing `page.md`, `chunks.jsonl`, and `metadata.json`.
- `chunks.jsonl` is the preferred RAG input: each line includes source URL, title, current section, character count, and SHA-256 digest.
- The engine blocks localhost, private, reserved, and unresolved network targets to reduce SSRF risk.
- It does not bypass authentication, paywalls, robots restrictions, CAPTCHAs, or anti-bot controls.
