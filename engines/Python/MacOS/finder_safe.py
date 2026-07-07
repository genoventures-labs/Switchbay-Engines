#!/usr/bin/env python3
"""Safe Finder helper for Switchbay macOS tasks.

Supports read-only operations only:
- show: reveal item in Finder (files use reveal; folders open directly)
- open: open item
- info: print basic metadata
- reveal-parent: open the containing folder
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ALLOWED_ROOTS = [Path.home().resolve(), Path("/Users/Shared").resolve(), Path.cwd().resolve()]


def emit(ok: bool, action: str, **data):
    print(json.dumps({"ok": ok, "action": action, **data}, ensure_ascii=False))
    return 0 if ok else 1


def _is_under(root: Path, target: Path) -> bool:
    try:
        return os.path.commonpath([str(root), str(target)]) == str(root)
    except Exception:
        return False


def is_allowed(path: Path) -> bool:
    try:
        resolved = path.expanduser().resolve()
    except FileNotFoundError:
        resolved = path.expanduser().absolute()
    return any(_is_under(root, resolved) for root in ALLOWED_ROOTS)


def stat_info(path: Path):
    st = path.stat()
    return {
        "path": str(path.resolve()),
        "exists": True,
        "is_file": path.is_file(),
        "is_dir": path.is_dir(),
        "size": st.st_size,
        "mtime": st.st_mtime,
    }


def cmd_show(path: Path):
    # Files: reveal in Finder; Dirs: open the directory directly
    if path.is_dir():
        proc = subprocess.run(["open", str(path)], capture_output=True, text=True)
        return emit(proc.returncode == 0, "show", path=str(path), mode="open-dir", stdout=proc.stdout, stderr=proc.stderr, returncode=proc.returncode)
    else:
        proc = subprocess.run(["open", "-R", str(path)], capture_output=True, text=True)
        return emit(proc.returncode == 0, "show", path=str(path), mode="reveal-file", stdout=proc.stdout, stderr=proc.stderr, returncode=proc.returncode)


def cmd_open(path: Path):
    proc = subprocess.run(["open", str(path)], capture_output=True, text=True)
    return emit(proc.returncode == 0, "open", path=str(path), stdout=proc.stdout, stderr=proc.stderr, returncode=proc.returncode)


def cmd_info(path: Path):
    if not path.exists():
        return emit(False, "info", path=str(path), error="path not found")
    return emit(True, "info", **stat_info(path))


def cmd_reveal_parent(path: Path):
    parent = path.expanduser().resolve().parent
    # Open the parent folder (do not use -R on parent, which would reveal it in its own parent)
    proc = subprocess.run(["open", str(parent)], capture_output=True, text=True)
    return emit(
        proc.returncode == 0,
        "reveal-parent",
        path=str(path),
        parent=str(parent),
        stdout=proc.stdout,
        stderr=proc.stderr,
        returncode=proc.returncode,
    )


def main():
    p = argparse.ArgumentParser(prog="finder_safe")
    p.add_argument("subcommand", choices=["show", "open", "info", "reveal-parent"])
    p.add_argument("--path", required=True)
    args = p.parse_args()

    path = Path(args.path).expanduser()
    if not is_allowed(path):
        return emit(False, args.subcommand, path=str(path), error="path outside allowed roots")

    if args.subcommand == "show":
        return cmd_show(path)
    if args.subcommand == "open":
        return cmd_open(path)
    if args.subcommand == "info":
        return cmd_info(path)
    return cmd_reveal_parent(path)


if __name__ == "__main__":
    raise SystemExit(main())
