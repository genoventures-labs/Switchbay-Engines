#!/usr/bin/env python3
"""MacOS helper engine for Switchbay.

Outputs JSON for agent consumption.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def result(ok: bool, action: str, **data):
    payload = {"ok": ok, "action": action, **data}
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if ok else 1


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def cmd_status(_args):
    return result(True, "status", message="MacOS engine ready", platform=sys.platform, cwd=str(Path.cwd()))


def cmd_query(args):
    return result(True, "query", query=args.text, message="Use open-app, defaults-get, clipboard, or screenshot tools for MacOS tasks.")


def cmd_open_app(args):
    proc = run(["open", args.target])
    return result(proc.returncode == 0, "open-app", target=args.target, stdout=proc.stdout, stderr=proc.stderr, returncode=proc.returncode)


def cmd_run_script(args):
    proc = run(["/bin/zsh", "-lc", args.script])
    return result(proc.returncode == 0, "run-script", stdout=proc.stdout, stderr=proc.stderr, returncode=proc.returncode)


def cmd_defaults_get(args):
    proc = run(["defaults", "read", args.domain, args.key])
    return result(proc.returncode == 0, "defaults-get", domain=args.domain, key=args.key, stdout=proc.stdout, stderr=proc.stderr, returncode=proc.returncode)


def cmd_defaults_set(args):
    proc = run(["defaults", "write", args.domain, args.key, args.value])
    return result(proc.returncode == 0, "defaults-set", domain=args.domain, key=args.key, value=args.value, stdout=proc.stdout, stderr=proc.stderr, returncode=proc.returncode)


def cmd_notify(args):
    script = f'display notification {args.message!r} with title {args.title!r}'
    proc = run(["osascript", "-e", script])
    return result(proc.returncode == 0, "notify", title=args.title, message=args.message, stdout=proc.stdout, stderr=proc.stderr, returncode=proc.returncode)


def cmd_clipboard_get(_args):
    proc = run(["pbpaste"])
    return result(proc.returncode == 0, "clipboard-get", text=proc.stdout, stderr=proc.stderr, returncode=proc.returncode)


def cmd_clipboard_set(args):
    proc = subprocess.run(["pbcopy"], input=args.text, text=True, capture_output=True)
    return result(proc.returncode == 0, "clipboard-set", text=args.text, stderr=proc.stderr, returncode=proc.returncode)


def cmd_screenshot(args):
    proc = run(["screencapture", "-x", args.output])
    return result(proc.returncode == 0, "screenshot", output=args.output, stdout=proc.stdout, stderr=proc.stderr, returncode=proc.returncode)


def build_parser():
    p = argparse.ArgumentParser(prog="macos_agent")
    sp = p.add_subparsers(dest="cmd", required=True)

    sp.add_parser("status").set_defaults(func=cmd_status)

    q = sp.add_parser("query")
    q.add_argument("--text", required=True)
    q.set_defaults(func=cmd_query)

    oa = sp.add_parser("open-app")
    oa.add_argument("--target", required=True)
    oa.set_defaults(func=cmd_open_app)

    rs = sp.add_parser("run-script")
    rs.add_argument("--script", required=True)
    rs.set_defaults(func=cmd_run_script)

    dg = sp.add_parser("defaults-get")
    dg.add_argument("--domain", required=True)
    dg.add_argument("--key", required=True)
    dg.set_defaults(func=cmd_defaults_get)

    ds = sp.add_parser("defaults-set")
    ds.add_argument("--domain", required=True)
    ds.add_argument("--key", required=True)
    ds.add_argument("--value", required=True)
    ds.set_defaults(func=cmd_defaults_set)

    nt = sp.add_parser("notify")
    nt.add_argument("--title", required=True)
    nt.add_argument("--message", required=True)
    nt.set_defaults(func=cmd_notify)

    cg = sp.add_parser("clipboard-get")
    cg.set_defaults(func=cmd_clipboard_get)

    cs = sp.add_parser("clipboard-set")
    cs.add_argument("--text", required=True)
    cs.set_defaults(func=cmd_clipboard_set)

    ss = sp.add_parser("screenshot")
    ss.add_argument("--output", required=True)
    ss.set_defaults(func=cmd_screenshot)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
