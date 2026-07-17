---
id: memory-helper-routing
name: Memory Helper Routing
description: On-demand search and recall across Switchbay memory stores so models pull context when needed instead of stuffing large memory into every turn.
engine: memory-helper
languages: [python]
agents: [any]
tags: [memory, recall, search, context, switchbay, notes, facts, sessions]
triggers: [memory, recall, remember, what do we know, notes, facts, prior session, user context, SWITCHBAY.md, pinned files, knowledge index]
---

# Memory Helper Routing

## Use When

- You need prior notes, facts, preferences, or session context for the current task.
- The user asks what was remembered, decided, or discussed before.
- Built-in turn context is thin and you should pull memory on demand instead of guessing.
- You want to avoid re-injecting large memory blobs every turn.

## Engine

- Engine id: `memory-helper`
- Call via `list_engine_tools` → `run_engine_tool`
- Always pass `workspace` as the absolute project root when known

## Tools

| Tool | Purpose | Approval? |
|---|---|---|
| `search_memory` | Ranked hits across memory stores (source, path, score, snippet) | No |
| `recall_memory` | Compact `context_pack` + structured facts from the best matches | No |

## What It Searches

| Scope | Paths |
|---|---|
| Global | `~/.switchbay/context/`, `~/.switchbay/sessions/` |
| Workspace | `SWITCHBAY.md`, `.switchbay/memory/{notes.md,facts.json,summary.md}`, `.switchbay/knowledge/index.json`, `pins.json`, `plan.json`, runtime guides |

## Method

1. Route by intent:
   - **Discover where something lives** → `search_memory`
   - **Need usable content for this turn** → `recall_memory`
2. Pass `workspace` every time you can. Without it, workspace-scoped stores may miss.
3. Start broad (`scope: all`). Narrow only when needed:
   - `scope: workspace` — project notes, facts, SWITCHBAY.md, knowledge, pins
   - `scope: global` — personal context + sessions
4. Optional `sources` filter (comma-separated): `context,switchbay,notes,facts,summary,knowledge,pins,sessions,plan,guides`
5. Prefer `recall_memory` for answering; use `search_memory` first when you need to locate the right store or verify a hit exists.
6. Cite the hit `source` + `path` when memory affects the answer.
7. If inventory shows missing files (no facts, empty notes, no knowledge index), say so — then suggest `memory_refresh` / `/index refresh` / `/remember` via Switchbay builtins when appropriate.

## Output

- `search_memory`: ranked hits with source, path, score, snippet.
- `recall_memory`: `context_pack` plus any structured `facts`.
- Explicit “no matches” when nothing scored — do not invent memories.

## Guardrails

- Read-only. Never fabricate notes, facts, or session content.
- Do not treat search snippets as complete truth — quote or paraphrase only what was returned.
- Skip/ignore sensitive-looking context filenames; never fish for secrets, tokens, or credentials.
- Prefer this engine for targeted recall; do not dump entire memory stores into the user reply.
- If both Memory Helper and built-in `memory_*` / knowledge tools are available, use Memory Helper for cross-store search/recall and builtins for write/refresh operations.
