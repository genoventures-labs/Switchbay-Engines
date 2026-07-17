## PageTend Helper

Read-only Switchbay engine for PageTend stats and status.

## Tools
- `status` — config + reachability
- `analytics` — richest aggregated stats (+ Meta totals)
- `dashboard` — calendar/queue/campaign snapshot (check `fallback`)
- `meta_live` — live Meta page + recent posts
- `settings` — counts + integration health
- `signals` — inbox-derived product signals
- `list_posts` / `list_inbox` — read-only lists
- `views_per_post` — rolling-window posts published + views + views/post (`--days`, default 30)

## Config
1. `PAGETEND_BASE_URL`
2. `~/.pagetend/config.json` → `{"base_url":"http://localhost:3000"}`
3. Default: `http://localhost:3000`

## Notes
- PageTend API has **no auth** — keep the URL private.
- This engine never mutates (no POST/PATCH/PUT/DELETE).
- Engine id: `pagetend`
- Integration doc: `PageTend/docs/pagetend-api-integration.md`
