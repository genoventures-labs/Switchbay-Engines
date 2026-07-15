"""GumOps Runner — direct CLI entry point for the GumOps Switchbay engine.

Each subcommand maps to a tool in gumops.engine.json. Outputs JSON to stdout
so Switchbay can parse results cleanly. All errors are caught and returned as
{"ok": false, "error": "<message>"} so the engine never crashes the caller.

Usage:
    python gumops_runner.py <subcommand> [--arg value ...]

Subcommands:
    health_check
    account_info
    list_products       [--page INT]
    get_product         --product_id STR
    find_product        --name STR
    sales_summary
    sales_by_product
    sales_by_month
    top_products        [--top_n INT]
    top_customers       [--top_n INT]
    find_sales_by_email --email STR
    sales_report
    compare_months      --month1 STR --month2 STR
    customer_report     --email STR
    product_report      --product_id STR
    refund_preview      --sale_id STR [--amount FLOAT]
    refund_sale         --sale_id STR [--amount FLOAT]
    refresh_memory
    memory_list
    memory_get          --key STR
    memory_add          --key STR --value STR
    memory_find         --query STR
    memory_summary
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path bootstrap — allow running from repo root or engine dir
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from gumsdk import GumroadSDK, DEFAULT_API_BASE  # noqa: E402


def _sdk() -> GumroadSDK:
    return GumroadSDK()


def _ok(data) -> None:
    print(json.dumps({"ok": True, "result": data}, indent=2, ensure_ascii=False))


def _err(msg: str) -> None:
    print(json.dumps({"ok": False, "error": str(msg)}, indent=2, ensure_ascii=False))
    sys.exit(1)


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def cmd_account_info(_args) -> None:
    try:
        user = _sdk().get_user()
        u = user.get("user", user)
        _ok({
            "name": u.get("name"),
            "email": u.get("email"),
            "bio": u.get("bio"),
            "twitter_handle": u.get("twitter_handle"),
            "url": u.get("url"),
        })
    except Exception as exc:
        _err(exc)


def cmd_list_products(args) -> None:
    try:
        data = _sdk().list_products(page=args.page)
        products = data.get("products") or []
        _ok([
            {
                "id": p.get("id"),
                "name": p.get("name"),
                "permalink": p.get("permalink"),
                "url": p.get("url"),
                "published": p.get("published"),
                "price": p.get("price"),
            }
            for p in products
        ])
    except Exception as exc:
        _err(exc)


def cmd_get_product(args) -> None:
    try:
        data = _sdk().get_product(args.product_id)
        _ok(data.get("product", data))
    except Exception as exc:
        _err(exc)


def cmd_find_product(args) -> None:
    try:
        product = _sdk().find_product_by_name(args.name)
        if product is None:
            _ok({"found": False, "name": args.name})
        else:
            _ok({"found": True, "product": product})
    except Exception as exc:
        _err(exc)


def cmd_sales_summary(_args) -> None:
    try:
        summary = _sdk().get_sales_summary()
        _ok(summary)
    except Exception as exc:
        _err(exc)


def cmd_sales_by_product(_args) -> None:
    try:
        _ok(_sdk().insight_sales_by_product())
    except Exception as exc:
        _err(exc)


def cmd_sales_by_month(_args) -> None:
    try:
        _ok(_sdk().monthly_sales_summary())
    except Exception as exc:
        _err(exc)


def cmd_top_products(args) -> None:
    try:
        _ok(_sdk().top_selling_products(top_n=args.top_n))
    except Exception as exc:
        _err(exc)


def cmd_top_customers(args) -> None:
    try:
        _ok(_sdk().top_customers(top_n=args.top_n))
    except Exception as exc:
        _err(exc)


def cmd_find_sales_by_email(args) -> None:
    try:
        sales = _sdk().find_sale_by_email(args.email)
        _ok({"email": args.email, "count": len(sales), "sales": sales})
    except Exception as exc:
        _err(exc)


def cmd_sales_report(_args) -> None:
    try:
        _ok(_sdk().generate_sales_report())
    except Exception as exc:
        _err(exc)


def cmd_sales_range(args) -> None:
    try:
        all_sales = _sdk().list_all_sales()
        filtered = [
            s for s in all_sales
            if args.start <= s.get("created_at", "")[:10] <= args.end
        ]
        total_revenue = sum(float(s.get("price", 0)) for s in filtered)
        _ok({
            "start_date": args.start,
            "end_date": args.end,
            "total_sales": len(filtered),
            "total_revenue_usd": round(total_revenue / 100, 2),
            "sales": filtered,
        })
    except Exception as exc:
        _err(exc)


def cmd_compare_months(args) -> None:
    try:
        _ok(_sdk().compare_monthly_sales(args.month1, args.month2))
    except Exception as exc:
        _err(exc)


def cmd_customer_report(args) -> None:
    try:
        _ok(_sdk().generate_customer_report(args.email))
    except Exception as exc:
        _err(exc)


def cmd_product_report(args) -> None:
    try:
        _ok(_sdk().generate_product_report(args.product_id))
    except Exception as exc:
        _err(exc)


def cmd_refund_preview(args) -> None:
    try:
        amount = args.amount if args.amount is not None else None
        result = _sdk().preview_refund(sale_id=args.sale_id, amount=amount)
        _ok({"preview": True, "sale_id": args.sale_id, "amount": amount, "response": result})
    except Exception as exc:
        _err(exc)


def cmd_health_check(_args) -> None:
    try:
        sdk = _sdk()
        report = sdk.health_check()
        _ok(report)
    except ValueError as exc:
        # Token missing — GumroadSDK raises ValueError before we can call health_check
        _ok({
            "token_present": False,
            "token_prefix": None,
            "api_base": DEFAULT_API_BASE,
            "endpoints": {},
            "healthy": False,
            "errors": [str(exc)],
        })
    except Exception as exc:
        _err(exc)


def cmd_refund_sale(args) -> None:
    try:
        amount = args.amount if args.amount is not None else None
        result = _sdk().refund_sale(sale_id=args.sale_id, amount=amount)
        _ok({"refunded": True, "sale_id": args.sale_id, "amount": amount, "response": result})
    except Exception as exc:
        _err(exc)


# ---------------------------------------------------------------------------
# Memory subcommands — import from working_memory module
# ---------------------------------------------------------------------------

def _wm():
    """Lazy import of working_memory to avoid hard-wiring at module load."""
    wm_path = _HERE / "working_memory"
    if str(wm_path) not in sys.path:
        sys.path.insert(0, str(wm_path))
    import working_memory as wm  # noqa: PLC0415
    return wm


def cmd_refresh_memory(_args) -> None:
    try:
        wm = _wm()
        results = wm.refresh_from_gumroad()
        _ok({"refreshed": list(results.keys()), "timestamps": results})
    except Exception as exc:
        _err(exc)


def cmd_memory_list(_args) -> None:
    try:
        wm = _wm()
        _ok({"keys": wm.list_memory_keys()})
    except Exception as exc:
        _err(exc)


def cmd_memory_get(args) -> None:
    try:
        wm = _wm()
        item = wm.get_memory(args.key)
        if item is None:
            _ok({"found": False, "key": args.key})
        else:
            from dataclasses import asdict
            _ok({"found": True, "item": asdict(item)})
    except Exception as exc:
        _err(exc)


def cmd_memory_add(args) -> None:
    try:
        wm = _wm()
        # Try to parse value as JSON, fall back to raw string
        try:
            value = json.loads(args.value)
        except (json.JSONDecodeError, TypeError):
            value = args.value
        from dataclasses import asdict
        item = wm.add_memory(args.key, value)
        _ok({"stored": True, "item": asdict(item)})
    except Exception as exc:
        _err(exc)


def cmd_memory_find(args) -> None:
    try:
        wm = _wm()
        query = args.query.lower()
        from dataclasses import asdict

        def predicate(item):
            return (
                query in item.key.lower()
                or query in repr(item.value).lower()
                or query in repr(item.metadata).lower()
            )

        results = wm.find_memory(predicate)
        _ok({"query": args.query, "count": len(results), "items": [asdict(r) for r in results]})
    except Exception as exc:
        _err(exc)


def cmd_memory_summary(_args) -> None:
    try:
        wm = _wm()
        _ok({"summary": wm.summarize_memory()})
    except Exception as exc:
        _err(exc)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gumops_runner",
        description="GumOps Switchbay engine runner.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # health_check
    sub.add_parser("health_check")

    # account_info
    sub.add_parser("account_info")

    # list_products
    p = sub.add_parser("list_products")
    p.add_argument("--page", type=int, default=1)

    # get_product
    p = sub.add_parser("get_product")
    p.add_argument("--product_id", required=True)

    # find_product
    p = sub.add_parser("find_product")
    p.add_argument("--name", required=True)

    # sales_summary
    sub.add_parser("sales_summary")

    # sales_by_product
    sub.add_parser("sales_by_product")

    # sales_by_month
    sub.add_parser("sales_by_month")

    # top_products
    p = sub.add_parser("top_products")
    p.add_argument("--top_n", type=int, default=5)

    # top_customers
    p = sub.add_parser("top_customers")
    p.add_argument("--top_n", type=int, default=5)

    # find_sales_by_email
    p = sub.add_parser("find_sales_by_email")
    p.add_argument("--email", required=True)

    # sales_report
    sub.add_parser("sales_report")

    # sales_range
    p = sub.add_parser("sales_range")
    p.add_argument("--start", required=True, help="Inclusive start date YYYY-MM-DD")
    p.add_argument("--end", required=True, help="Inclusive end date YYYY-MM-DD")

    # compare_months
    p = sub.add_parser("compare_months")
    p.add_argument("--month1", required=True)
    p.add_argument("--month2", required=True)

    # customer_report
    p = sub.add_parser("customer_report")
    p.add_argument("--email", required=True)

    # product_report
    p = sub.add_parser("product_report")
    p.add_argument("--product_id", required=True)

    # refund_preview
    p = sub.add_parser("refund_preview")
    p.add_argument("--sale_id", required=True)
    p.add_argument("--amount", type=float, default=None)

    # refund_sale
    p = sub.add_parser("refund_sale")
    p.add_argument("--sale_id", required=True)
    p.add_argument("--amount", type=float, default=None)

    # memory
    sub.add_parser("refresh_memory")
    sub.add_parser("memory_list")

    p = sub.add_parser("memory_get")
    p.add_argument("--key", required=True)

    p = sub.add_parser("memory_add")
    p.add_argument("--key", required=True)
    p.add_argument("--value", required=True)

    p = sub.add_parser("memory_find")
    p.add_argument("--query", required=True)

    sub.add_parser("memory_summary")

    return parser


DISPATCH = {
    "health_check": cmd_health_check,
    "account_info": cmd_account_info,
    "list_products": cmd_list_products,
    "get_product": cmd_get_product,
    "find_product": cmd_find_product,
    "sales_summary": cmd_sales_summary,
    "sales_by_product": cmd_sales_by_product,
    "sales_by_month": cmd_sales_by_month,
    "top_products": cmd_top_products,
    "top_customers": cmd_top_customers,
    "find_sales_by_email": cmd_find_sales_by_email,
    "sales_report": cmd_sales_report,
    "sales_range": cmd_sales_range,
    "compare_months": cmd_compare_months,
    "customer_report": cmd_customer_report,
    "product_report": cmd_product_report,
    "refund_preview": cmd_refund_preview,
    "refund_sale": cmd_refund_sale,
    "refresh_memory": cmd_refresh_memory,
    "memory_list": cmd_memory_list,
    "memory_get": cmd_memory_get,
    "memory_add": cmd_memory_add,
    "memory_find": cmd_memory_find,
    "memory_summary": cmd_memory_summary,
}


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    handler = DISPATCH.get(args.command)
    if handler is None:
        _err(f"Unknown command: {args.command}")
    else:
        handler(args)
