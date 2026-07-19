---
id: web-to-markdown-routing
name: Web to Markdown Routing
description: Convert public websites into local Markdown corpora for retrieval, grounding, and RAG.
engine: web-to-markdown
languages: [python]
agents: [any]
tags: [web, markdown, rag, retrieval, corpus]
triggers: [ingest website, website to markdown, crawl docs, build web corpus, prepare website for RAG]
---

## Use When

A task needs website content converted into stable local documents that models can retrieve, cite, summarize, compare, or index.

## Tool Map

- `fetch_page`: one known URL; can return Markdown directly or save it.
- `crawl_site`: bounded same-origin crawl; creates `pages/*.md`, `corpus.json`, and `documents.jsonl`.
- `inspect_corpus`: inventory a corpus before reading individual documents.

## Method

1. Prefer `fetch_page` when one URL is enough.
2. For a site, call `crawl_site` with low depth and a strict page cap first.
3. Use `include` or `exclude` regexes to focus documentation sections and avoid account, cart, search, tag, or calendar loops.
4. Call `inspect_corpus`, select relevant documents, then pass only those documents into downstream retrieval or model context.

## Output

Markdown documents include YAML frontmatter with source URL, canonical URL, title, description, language, fetch time, and content hash. `documents.jsonl` contains one complete text-plus-metadata record per page for direct ingestion.

## Guardrails

- Respect `robots.txt` unless the user has a legitimate reason and permission not to.
- Do not crawl authenticated, private, paywalled, or access-controlled content without authorization.
- Keep page limits and delay conservative.
- The engine does not execute JavaScript; report thin output candidly rather than inventing missing content.
