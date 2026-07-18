---
id: clerk-waitlist-routing
name: Clerk Waitlist Routing
description: Route read-only Clerk waitlist questions to the clerk-waitlist engine for configuration checks, entry lookup, filtered browsing, and compact totals.
engine: clerk-waitlist
languages: [python]
agents: [any]
tags: [clerk, waitlist, signup, leads, analytics, read-only, switchbay-engine]
triggers: [clerk waitlist, waitlist stats, waitlist entries, pending signups, invited users, waitlist status, signup queue]
---

# Clerk Waitlist Routing

## Use When

- The user asks how many people are on a Clerk waitlist or how entries are distributed by status.
- The user wants to browse, filter, paginate, or search waitlist entries.
- The user provides an exact Clerk waitlist entry ID and wants its details.
- You need to verify that the Clerk secret is configured and the Backend API is reachable.

## Engine

- Engine id: `clerk-waitlist`
- Required environment variable: `CLERK_SECRET_KEY`
- Read-only by design; it exposes no create, invite, reject, complete, lock, unlock, or delete action.

## Tool Selection

| Intent | Tool |
|---|---|
| Is Clerk configured and reachable? | `status` |
| Browse or filter waitlist entries | `list_entries` |
| Find one exact entry by Clerk waitlist ID | `get_entry` |
| Get totals and status distribution | `summarize` |

## Method

1. Call `status` first when configuration or API reachability is unknown.
2. For broad questions such as “how is the waitlist doing?”, call `summarize` and lead with `summary.total_count`, `summary.by_status`, and whether `summary.complete` is true.
3. For browsing, use `list_entries` with the narrowest useful filters. Prefer a modest `limit` and paginate with `offset` instead of requesting an oversized payload.
4. Use `get_entry` only when an exact waitlist entry ID is available. For email or partial-ID search, use `list_entries` with `query`.
5. Preserve the distinction between `total_count` and the number of entries returned or fetched.
6. Report Clerk API errors directly. Do not replace failed calls with guessed totals.

## Output

- Lead with a compact operational answer before listing records.
- For lists, report returned count, total count, active filters, and whether more pages exist.
- Show email addresses only when needed for the user’s request; avoid dumping the entire waitlist by default.
- Include normalized ISO timestamps when discussing age, recency, oldest entries, or newest entries.

## Guardrails

- Never expose or echo `CLERK_SECRET_KEY`.
- Never imply this engine can mutate Clerk records.
- Do not infer conversion, activation, or product usage from waitlist status alone.
- Treat personally identifying waitlist data as sensitive operational data and minimize unnecessary output.
- If `summary.complete` is false, clearly label the result as partial.