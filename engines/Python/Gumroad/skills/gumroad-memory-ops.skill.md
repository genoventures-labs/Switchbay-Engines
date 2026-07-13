---
id: gumroad-memory-ops
name: Gumroad Memory Ops
description: Read and write GumOps working memory to persist Gumroad store context, notes, and cached API data across sessions.
engine: gumops
languages: [python]
agents: [backend, debugger, docs]
tags: [gumroad, memory, working-memory, context, persistence]
triggers: [memory, remember, store context, working memory, refresh memory, recall, cached data, gumroad memory]
---

# Gumroad Memory Ops

## Use When

- You need fresh Gumroad data at the start of a session without calling every API tool separately.
- The user asks what was stored, previously noted, or last refreshed.
- You want to persist a note, insight, or label about the store for later retrieval.
- You're debugging stale memory or verifying what the agent knows.

## Tool Selection Guide

| Intent | Tool |
|---|---|
| Sync latest products, sales summary, and account info | `gum_refresh_memory` |
| See everything stored in memory | `gum_memory_list` |
| Read a specific memory entry | `gum_memory_get --key` |
| Store a note, label, or value | `gum_memory_add --key --value` |
| Search memory by keyword | `gum_memory_find --query` |
| Review recent memory at a glance | `gum_memory_summary` |

## Key Naming Conventions

Memory uses colon-namespaced keys set by `refresh_from_gumroad`:

| Key | Contents |
|---|---|
| `gumroad:products` | Latest product list from the API |
| `gumroad:sales_summary` | Total sales, revenue, and refund count |
| `gumroad:account_info` | Seller name, email, and counts |

Custom notes can use any key. Suggested convention: `note:<slug>`, `label:<product-id>`, `context:<topic>`.

## Method

1. At session start, run `gum_memory_summary` to see what's already known.
2. If core keys are missing or stale (check timestamps), run `gum_refresh_memory`.
3. Use `gum_memory_get` for targeted key reads; use `gum_memory_find` for fuzzy discovery.
4. Use `gum_memory_add` to persist any insight, label, or context you want available next session.
5. After writing, confirm the stored item with `gum_memory_get` on the same key.

## Output

- Timestamped memory items showing key, value snippet, and when it was last updated.
- Clear confirmation when a value is stored or refreshed.
- Explicit note if a key is not found — do not assume it has a value.

## Guardrails

- Never fabricate memory contents — only report what `gum_memory_get` or `gum_memory_summary` returns.
- `gum_refresh_memory` makes live Gumroad API calls — do not call it in a tight loop.
- Memory is file-backed at `~/.gumops_working_memory/memory.json` — it persists across sessions but is local-only.
- Do not store sensitive credentials, passwords, or private customer PII in working memory.
