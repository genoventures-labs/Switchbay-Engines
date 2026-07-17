## ClickUp CLI Engine

Shell wrapper around the agent-friendly `cup` CLI for Switchbay.

## Tools
- Read: `status`, `auth`, `summary`, `assigned`, `overdue`, `inbox`, `sprint`, `sprints`, `spaces`, `members`, `tasks`, `search`, `task`, `activity`, `comments`, `subtasks`
- Write (approval): `create`, `update`, `comment`, `assign`, `delete`

## Setup
```bash
# cup should already be on PATH (e.g. ~/.bun/bin/cup)
cup auth --json
# or non-interactive:
cup init --token <TOKEN> --team <TEAM_ID>
```

Optional: `export CUP_BIN=/path/to/cup`

## Notes
- Engine id: `clickup-cli`
- Commands are relative to this folder (`bash clickup_cli_runner.sh …`)
- Omitted Switchbay args may arrive as `None` and are ignored for optional flags
- Sibling Node engine `clickup` also wraps cup via Bun — this Shell engine is the lightweight bash path
