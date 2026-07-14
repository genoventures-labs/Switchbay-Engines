"""TLD checker for Switchbay."""

from __future__ import annotations

import argparse
import json
import sys

# Keep in sync with simple_check.py — same source-of-truth set.
from simple_check import VALID_TLDS, normalize_domain


def check_tld(domain: str) -> dict[str, object]:
    """Return whether the domain's TLD is recognized."""
    try:
        normalized = normalize_domain(domain)
    except ValueError as exc:
        return {"ok": False, "domain": domain, "tld": None, "valid_tld": False, "error": str(exc)}

    tld = normalized.rsplit(".", 1)[-1] if "." in normalized else None
    if tld is None:
        return {"ok": False, "domain": normalized, "tld": None, "valid_tld": False, "error": "no TLD found"}

    valid = tld in VALID_TLDS
    return {
        "ok": valid,
        "domain": normalized,
        "tld": tld,
        "valid_tld": valid,
        "error": None if valid else f"unrecognized TLD: .{tld}",
    }


def _cli() -> None:
    parser = argparse.ArgumentParser(description="Check if a domain has a recognized TLD.")
    parser.add_argument("--domain", required=True, help="The domain to check.")
    args = parser.parse_args()
    result = check_tld(args.domain)
    print(json.dumps(result))
    sys.exit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    _cli()
