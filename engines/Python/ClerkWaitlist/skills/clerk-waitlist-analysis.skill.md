---
id: clerk-waitlist-analysis
name: Clerk Waitlist Analysis
description: Analyze read-only Clerk waitlist snapshots without overstating conversion, growth, or completeness.
engine: clerk-waitlist
languages: [python]
agents: [any]
tags: [clerk, waitlist, analytics, funnel, operations, privacy, read-only, switchbay-engine]
triggers: [analyze clerk waitlist, waitlist health, waitlist growth, waitlist funnel, pending versus invited, oldest waitlist entries, waitlist report]
---

# Clerk Waitlist Analysis

## Use When

- The user wants an operational readout of Clerk waitlist volume and status mix.
- The user asks which entries are newest, oldest, pending, invited, completed, or rejected.
- The user wants a concise waitlist report, anomaly check, or follow-up queue.
- You need to distinguish observed Clerk data from product or marketing inference.

## Tool Map

| Analysis need | Tool |
|---|---|
| Total size and status mix | `summarize` |
| Inspect a status cohort or date ordering | `list_entries` |
| Verify a specific record | `get_entry` |
| Confirm data access before analysis | `status` |

## Method

1. Start with `summarize` using `fetch_all: true` unless the user explicitly requests a quick sample or the dataset is too large for a full pass.
2. Check `summary.complete` before presenting totals as comprehensive.
3. Compute status shares only from fetched counts and label the denominator. A status share is not a conversion rate.
4. Use `list_entries` with `status: pending` and `order_by: +created_at` to inspect the oldest pending records when the user asks about backlog or follow-up priority.
5. Use `order_by: -created_at` for newest signups and recent activity snapshots.
6. Separate facts from inference:
   - Fact: Clerk status counts, timestamps, returned records, and pagination metadata.
   - Inference: possible backlog, campaign response, lead quality, or operational urgency.
7. When comparing snapshots, require data from both periods. Do not claim growth from a single current snapshot.

## Output

Use this compact structure when appropriate:

- **Snapshot:** total count, fetched count, completeness, oldest/newest timestamps.
- **Status mix:** counts and clearly labeled shares.
- **Operational signal:** the strongest evidence-backed observation.
- **Follow-up:** a narrow next query, such as oldest pending entries or newest signups.
- **Confidence:** high when complete; limited when sampled, filtered, or API errors occurred.

## Guardrails

- Do not call pending-to-completed share a conversion rate without cohort timing and denominator context.
- Do not infer acquisition source, campaign attribution, user intent, or revenue from Clerk waitlist records.
- Do not expose full email lists unless the user explicitly needs record-level output.
- Do not recommend or perform mutations; this skill is view-only.
- Never fabricate historical trends when only one snapshot exists.
- Clearly disclose filters, limits, offsets, and incomplete pagination.