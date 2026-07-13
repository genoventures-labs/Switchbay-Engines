---
id: gumroad-seller-ops
name: Gumroad Seller Ops
description: Choose and run the right GumOps engine tool for product lookups, sale lookups, and account queries.
engine: gumops
languages: [python]
agents: [backend, reviewer, debugger]
tags: [gumroad, products, sales, seller, operations]
triggers: [gumroad, products, sales, seller, account, list products, find product, find sale, sale by email]
---

# Gumroad Seller Ops

## Use When

- The user asks about their Gumroad account, products, or a specific sale.
- You need to look up a product by name or ID.
- You need to find a customer's purchases by email.
- You need to confirm account status before running analytics or refunds.

## Tool Selection Guide

| Intent | Tool |
|---|---|
| Confirm seller identity and store status | `gum_account_info` |
| Browse all products | `gum_list_products` (paginate with `--page`) |
| Get full details on one product | `gum_get_product --product_id` |
| Search for a product by name | `gum_find_product --name` |
| Find a buyer's purchases | `gum_find_sales_by_email --email` |
| Get a full customer history | `gum_customer_report --email` |
| Get a full product sales history | `gum_product_report --product_id` |

## Method

1. Start with `gum_account_info` if account context is missing or ambiguous.
2. Use `gum_find_product` for name-based lookups before falling back to `gum_list_products`.
3. Use `gum_find_sales_by_email` for buyer queries; use `gum_customer_report` when full history is needed.
4. Always confirm the product ID exists before passing it to a report or refund tool.
5. Present results as a concise summary — don't dump raw JSON unless asked.

## Output

- Confirmed identity or product match.
- Structured list or detail view of the requested record.
- Clear error message if the record is not found.

## Guardrails

- Never guess or invent product IDs or sale IDs.
- If a name search returns no match, report it and stop — do not proceed to refund or analytics.
- Treat buyer email data as sensitive — do not echo it back unnecessarily.
