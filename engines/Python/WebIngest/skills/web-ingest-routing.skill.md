---
id: web-ingest-routing
name: Web Ingest Routing
description: Convert public websites into clean Markdown and metadata-rich chunks for model retrieval and RAG.
engine: web-ingest
languages: [python]
agents: [any]
tags: [web, html, markdown, rag, ingestion]
triggers: [ingest website, website to markdown, html to markdown, prepare webpage for rag, chunk webpage]
---

# Web Ingest Routing

## Use When

Use this engine when the model needs stable local text from a public webpage, especially before retrieval, summarization, citation extraction, or knowledge-base indexing.

## Tool Map

- `status`: verify the engine and optional Playwright renderer.
- `ingest_website`: fetch, normalize, convert, chunk, and persist one page.

## Method

1. Call `ingest_website` with `render=false`.
2. Inspect `preview`, `markdown_chars`, and `chunk_count`.
3. If content is missing because the site renders client-side, retry with `render=true`.
4. Feed `chunks.jsonl` into the retrieval/indexing stage; use `page.md` for human review or full-page context.

## Output

A timestamped directory containing:

- `page.md` — normalized Markdown.
- `chunks.jsonl` — RAG-ready chunks with source metadata and hashes.
- `metadata.json` — fetch mode, final URL, title, counts, and output paths.
- `source.html` — optional debugging artifact when `save_html=true`.

## Guardrails

- Public HTTP(S) pages only.
- Do not use it to bypass authentication, paywalls, CAPTCHAs, or access controls.
- Prefer static mode because it is faster, lighter, and dependency-free.
- Use Playwright only when the static page is incomplete.
