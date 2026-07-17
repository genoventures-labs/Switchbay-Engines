## MemoryHelper Engine

## What is this?
On-demand memory search/recall for Switchbay models. Lets the agent pull relevant notes, facts, personal context, knowledge hits, pins, and session history when needed — instead of injecting a huge memory blob every turn.

## Tools
- `search_memory` — Ranked hits across Switchbay stores (source, path, score, snippet).
- `recall_memory` — Compact `context_pack` + structured facts from the best matches.

## Sources scanned
- Global: `~/.switchbay/context/`, `~/.switchbay/sessions/`
- Workspace: `SWITCHBAY.md`, `.switchbay/memory/{notes.md,facts.json,summary.md}`, `.switchbay/knowledge/index.json`, `pins.json`, `plan.json`, runtime guides

## Notes
- Pass `--workspace` / `workspace` as the absolute project root when available.
- Read-only. Skips sensitive-looking context filenames.
- Engine id: `memory-helper`.
