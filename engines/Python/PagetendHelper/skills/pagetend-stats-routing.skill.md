---
id: pagetend-stats-routing
name: PageTend Stats Routing
description: Pull PageTend analytics, dashboard, Meta live stats, settings, signals, posts, and inbox via the read-only pagetend engine.
engine: pagetend
languages: [python]
agents: [any]
tags: [pagetend, analytics, meta, facebook, inbox, stats, dashboard, switchbay-engine]
triggers: [pagetend, page tend, facebook page stats, meta engagement, inbox signals, scheduled posts, page analytics, page dashboard]
---

# PageTend Stats Routing

## Use When

- The user asks for PageTend / Facebook page stats, queue, inbox, or Meta engagement.
- You need integration health (Meta connected? OpenAI? Supabase?).
- You want product signals derived from inbox threads.

## Engine

- Engine id: `pagetend`
- Configure `PAGETEND_BASE_URL` or `~/.pagetend/config.json`
- Default host: `http://localhost:3000`
- Read-only — never invent write/mutate calls

## Tool Selection

| Intent | Tool |
|---|---|
| Is PageTend up / configured? | `status` |
| Full stats breakdown + Meta totals | `analytics` |
| Calendar / queue / campaign snapshot | `dashboard` |
| Live Meta page + recent posts | `meta_live` |
| Counts + integration health | `settings` |
| Inbox-derived product signals | `signals` |
| Browse posts | `list_posts` |
| Browse inbox threads | `list_inbox` |
| Last N days views / views-per-post | `views_per_post` |

## Method

1. Call `status` first if the base URL or reachability is unknown.
2. For “how’s the page doing?” prefer `analytics` (richest). Use `meta_live` when you need freshest Meta Graph numbers.
3. For rolling-window performance (“last 30 days views per post”) use `views_per_post` with `days` (default 30). Lead with `summary.card`.
4. For scheduling / queue questions use `dashboard`, then verify `fallback` is not `true` before trusting figures.
5. Keep `summary: true` (default) so responses stay compact; dig into `data` only when needed.
6. Cite which endpoint the numbers came from and whether Meta was connected. If `views` is null, say views/impressions were unavailable and report engagement instead when present.
7. Do not invent monthly totals when the user asked for a rolling window — use `views_per_post`.

## Output

- Lead with the compact `summary` fields (counts, followers, engagement totals).
- Call out `fallback: true` or Meta `connected: false` / `errors[]` explicitly.
- For lists, report `count` + a short sample — not the entire payload unless asked.

## Guardrails

- PageTend has **no API auth**. Do not print or share tunnel URLs casually.
- Do not call POST/PATCH/PUT/DELETE against PageTend from this engine.
- Do not treat dashboard fallback data as live truth.
- Do not fabricate engagement numbers when a call fails — report the error and suggest checking `PAGETEND_BASE_URL` / that PageTend is running.
