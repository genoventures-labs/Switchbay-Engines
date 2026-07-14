"""Domain availability checker for Switchbay."""

from __future__ import annotations

import argparse
import json
import re
import sys

# IANA-derived common TLDs. Not exhaustive, but covers the vast majority of
# real-world domains without requiring a network call or external package.
VALID_TLDS = {
    "ac", "ad", "ae", "af", "ag", "ai", "al", "am", "ao", "aq", "ar", "as",
    "at", "au", "aw", "ax", "az", "ba", "bb", "bd", "be", "bf", "bg", "bh",
    "bi", "bj", "bm", "bn", "bo", "br", "bs", "bt", "bw", "by", "bz", "ca",
    "cc", "cd", "cf", "cg", "ch", "ci", "ck", "cl", "cm", "cn", "co", "cr",
    "cu", "cv", "cw", "cx", "cy", "cz", "de", "dj", "dk", "dm", "do", "dz",
    "ec", "ee", "eg", "er", "es", "et", "eu", "fi", "fj", "fk", "fm", "fo",
    "fr", "ga", "gb", "gd", "ge", "gf", "gg", "gh", "gi", "gl", "gm", "gn",
    "gp", "gq", "gr", "gs", "gt", "gu", "gw", "gy", "hk", "hm", "hn", "hr",
    "ht", "hu", "id", "ie", "il", "im", "in", "io", "iq", "ir", "is", "it",
    "je", "jm", "jo", "jp", "ke", "kg", "kh", "ki", "km", "kn", "kp", "kr",
    "kw", "ky", "kz", "la", "lb", "lc", "li", "lk", "lr", "ls", "lt", "lu",
    "lv", "ly", "ma", "mc", "md", "me", "mg", "mh", "mk", "ml", "mm", "mn",
    "mo", "mp", "mq", "mr", "ms", "mt", "mu", "mv", "mw", "mx", "my", "mz",
    "na", "nc", "ne", "nf", "ng", "ni", "nl", "no", "np", "nr", "nu", "nz",
    "om", "pa", "pe", "pf", "pg", "ph", "pk", "pl", "pm", "pn", "pr", "ps",
    "pt", "pw", "py", "qa", "re", "ro", "rs", "ru", "rw", "sa", "sb", "sc",
    "sd", "se", "sg", "sh", "si", "sk", "sl", "sm", "sn", "so", "sr", "ss",
    "st", "sv", "sx", "sy", "sz", "tc", "td", "tf", "tg", "th", "tj", "tk",
    "tl", "tm", "tn", "to", "tr", "tt", "tv", "tw", "tz", "ua", "ug", "uk",
    "us", "uy", "uz", "va", "vc", "ve", "vg", "vi", "vn", "vu", "wf", "ws",
    "ye", "yt", "za", "zm", "zw",
    # Generic TLDs
    "app", "art", "biz", "blog", "cloud", "club", "co", "com", "coop",
    "design", "dev", "education", "email", "events", "finance", "fun",
    "gallery", "global", "guru", "health", "help", "info", "int", "io",
    "jobs", "life", "link", "live", "media", "mobi", "museum", "name",
    "net", "news", "online", "org", "photo", "photos", "press", "pro",
    "pub", "radio", "run", "shop", "site", "social", "software", "space",
    "store", "studio", "support", "tech", "today", "tools", "travel",
    "tv", "web", "wiki", "work", "world", "wtf", "xyz", "zone",
}

_DOMAIN_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$"
)


def normalize_domain(domain: str) -> str:
    """Return a cleaned, lowercased domain name or raise ValueError."""
    value = domain.strip().lower()
    # Strip any accidental scheme the user may have included.
    for prefix in ("https://", "http://", "//"):
        if value.startswith(prefix):
            value = value[len(prefix):]
    # Strip trailing slashes or paths.
    value = value.split("/")[0]
    if not value:
        raise ValueError("domain is required")
    return value


def check_domain(domain: str) -> dict[str, object]:
    """Validate a domain and report whether availability lookup is possible.

    Availability lookup via WHOIS/RDAP is not yet implemented; the result
    clearly says so rather than returning an ambiguous None.
    """
    try:
        normalized = normalize_domain(domain)
    except ValueError as exc:
        return {"ok": False, "domain": domain, "available": False, "error": str(exc)}

    if not _DOMAIN_RE.match(normalized):
        return {"ok": False, "domain": normalized, "available": False, "error": "invalid domain format"}

    tld = normalized.rsplit(".", 1)[-1]
    if tld not in VALID_TLDS:
        return {
            "ok": False,
            "domain": normalized,
            "available": False,
            "tld": tld,
            "error": f"unrecognized TLD: .{tld}",
        }

    return {
        "ok": True,
        "domain": normalized,
        "tld": tld,
        "available": None,
        "note": "availability lookup not yet implemented — domain format and TLD are valid",
    }


def _cli() -> None:
    parser = argparse.ArgumentParser(description="Check if a domain is available.")
    parser.add_argument("--domain", required=True, help="The domain to check.")
    args = parser.parse_args()
    result = check_domain(args.domain)
    print(json.dumps(result))
    sys.exit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    _cli()
