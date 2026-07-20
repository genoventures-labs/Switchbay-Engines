# Facebook Page Insights Engine

Read-only analytics engine for Facebook Pages using Meta's Graph API.

## Environment

- `FACEBOOK_PAGE_ACCESS_TOKEN` — Page access token with permissions required by the requested metrics.
- `FACEBOOK_PAGE_ID` — default Page ID.
- `FACEBOOK_GRAPH_API_VERSION` — optional version override; defaults to `v25.0`.

Never place tokens in manifests, command arguments, logs, commits, or model responses. Prefer the environment variable.

## Routing

1. Run `status` when configuration is uncertain.
2. Use `page_profile` for Page identity and audience metadata.
3. Use `page_insights` for precise date windows and explicit metrics.
4. Use `list_posts` before `post_insights` to select posts efficiently.
5. Use `compare_periods` for directional analysis, noting that some metrics are snapshots rather than additive totals.

Meta may retire, rename, or restrict metrics by API version and Page permissions. Treat API errors as capability feedback, not zero values.
