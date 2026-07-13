---
id: gumroad-analytics
name: Gumroad Analytics
description: Run sales insight and reporting workflows against Gumroad store data using the GumOps engine.
engine: gumops
languages: [python]
agents: [backend, architect, reviewer]
tags: [gumroad, analytics, sales, revenue, reporting, insights]
triggers: [revenue, analytics, top products, top customers, monthly, sales report, compare months, sales by product, sales trend]
---

# Gumroad Analytics

## Use When

- The user wants a sales overview, revenue breakdown, or trend analysis.
- The user asks about top products or best customers.
- The user wants to compare two months or understand performance over time.
- The user wants a full report to share or review.

## Tool Selection Guide

| Intent | Tool |
|---|---|
| Quick snapshot: total sales, revenue, refunds | `gum_sales_summary` |
| See revenue broken down per product | `gum_sales_by_product` |
| See revenue broken down by month | `gum_sales_by_month` |
| Top N products by revenue | `gum_top_products [--top_n N]` |
| Top N customers by spend | `gum_top_customers [--top_n N]` |
| Month-over-month comparison | `gum_compare_months --month1 YYYY-MM --month2 YYYY-MM` |
| Full comprehensive report | `gum_sales_report` |
| Deep dive on a specific product | `gum_product_report --product_id` |
| Deep dive on a specific customer | `gum_customer_report --email` |

## Method

1. Clarify the time scope if the user asks about "recent" or "this month" without specifying.
2. Start lightweight: use `gum_sales_summary` before pulling a full `gum_sales_report` (which fetches all records).
3. For trend questions, use `gum_sales_by_month` and surface the top 3 months by revenue.
4. For top-performer questions, use `gum_top_products` and `gum_top_customers` together.
5. For month comparisons, confirm both month strings are in YYYY-MM format before calling `gum_compare_months`.
6. Summarize findings in plain language — label key numbers and percentage changes where relevant.

## Output

- A structured plain-language summary with key numbers called out.
- Month-over-month or product-level tables when comparison data is requested.
- Clear note if a requested period has no data.

## Guardrails

- `gum_sales_report` and `gum_product_report` fetch all paginated data — warn the user these may be slow for large stores.
- Never fabricate revenue figures. If a tool returns an error, report it.
- Do not include raw sale-level email data in summaries without explicit user request.
- Treat all revenue and customer data as internal — do not reproduce it in a format meant for external sharing without confirmation.
