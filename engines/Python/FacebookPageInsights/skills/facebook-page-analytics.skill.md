---
id: facebook-page-analytics
name: Facebook Page Analytics
description: Route read-only Facebook Page analysis through the facebook-page-insights engine.
engine: facebook-page-insights
languages: [python]
agents: [any]
tags: [facebook, meta, graph-api, analytics, page-insights]
triggers: [facebook page stats, facebook insights, analyze page performance, compare facebook periods, top facebook posts]
---

# Use When

Use this skill when the user wants general analysis of a Facebook Page they administer: audience totals, reach or impressions, engagement, post inventory, post-level performance, or period-over-period changes.

# Tool Map

- `status`: validate credentials, Page ID, and API reachability.
- `page_profile`: inspect Page metadata and audience counters.
- `page_insights`: retrieve explicit Page insight metrics for a date range.
- `list_posts`: gather recent Page posts and visible engagement summaries.
- `post_insights`: retrieve metrics for one selected post.
- `compare_periods`: compare two adjacent equal-length windows.

# Method

Start with `status` if configuration has not been verified. Pull only the metrics needed for the question. For content analysis, call `list_posts`, rank or filter candidates, then call `post_insights` on the smaller set. Separate observed values from interpretation, and include the exact date range and metric names in the answer.

# Guardrails

This engine is read-only. Do not publish, edit, delete, message, moderate, or manage ads. Never echo access tokens. Meta permissions, metric availability, and retention vary by API version and Page configuration; report API errors directly and do not convert unavailable metrics into zeros.
