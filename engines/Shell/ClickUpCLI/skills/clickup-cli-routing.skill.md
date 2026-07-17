---
id: clickup-cli-routing
name: ClickUp CLI Routing
description: Use the clickup-cli engine (cup wrapper) for standup reads, search, task detail, and guarded ClickUp mutations.
engine: clickup-cli
languages: [shell]
agents: [any]
tags: [clickup, cup, tasks, sprint, standup, project-management, switchbay-engine]
triggers: [clickup, cup, standup, sprint, overdue tasks, my tasks, clickup comment, create clickup task]
---

# ClickUp CLI Routing

## Use When

- The user asks about ClickUp tasks, sprints, standups, overdue work, or comments.
- You need to create/update/comment/assign in ClickUp with approval.

## Engine

- Engine id: `clickup-cli`
- Requires `cup` on PATH (or `CUP_BIN`)
- Call `status` first if auth/connectivity is unknown

## Tool Selection

| Intent | Tool |
|---|---|
| Is cup/auth working? | `status` / `auth` |
| Standup | `summary` |
| My board | `assigned` / `overdue` / `inbox` / `sprint` |
| Find work | `search` / `tasks` |
| Ticket context | `task` → `activity` / `comments` / `subtasks` |
| Create work | `create` (list or parent required) |
| Change work | `update` / `comment` / `assign` |
| Remove work | `delete` (only if explicitly asked) |

## Method

1. Prefer read tools before mutations.
2. Use `search` or `tasks` to find IDs, then `task`/`activity` for detail.
3. For creates: pass `list` (or `sprint:current`) **or** `parent` for subtasks, plus `name`.
4. Mutations require approval — never invent confirmations.
5. Treat omitted optional args as absent (`None` is ignored by the wrapper).

## Guardrails

- Do not delete unless the user clearly asks.
- Do not post comments or reassign without intent.
- Cite task IDs/names from tool output; do not invent ClickUp state.
