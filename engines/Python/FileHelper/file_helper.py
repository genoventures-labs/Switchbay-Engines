"""FileHelper Engine

Local-first utilities for inspecting and transforming files.

Core goals:
- Safe, predictable file reads with guardrails.
- Simple search/replace helpers.
- Lightweight directory listing.

This module is designed to be called as a tool from Switchbay.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_ROOT = Path.cwd()


@dataclass
class FilePreview:
    path: str
    exists: bool
    is_dir: bool
    size_bytes: int
    content: Optional[str] = None


def _resolve_path(path: str, root: Optional[str] = None) -> Path:
    base = Path(root).resolve() if root else DEFAULT_ROOT.resolve()
    p = (base / path).resolve() if not os.path.isabs(path) else Path(path).resolve()
    # Guardrail: don’t allow escaping the root when root is provided.
    if root:
        if not str(p).startswith(str(base) + os.sep) and p != base:
            raise ValueError(f"Path escapes root: {path}")
    return p


def list_directory(path: str = ".", root: Optional[str] = None, recursive: bool = False) -> List[Dict[str, Any]]:
    """List directory entries.

    Returns items with: name, path, is_dir, size_bytes.
    """
    p = _resolve_path(path, root=root)
    if not p.exists():
        raise FileNotFoundError(str(p))
    if not p.is_dir():
        raise NotADirectoryError(str(p))

    results: List[Dict[str, Any]] = []

    def add_item(fp: Path):
        try:
            st = fp.stat()
            results.append(
                {
                    "name": fp.name,
                    "path": str(fp),
                    "is_dir": fp.is_dir(),
                    "size_bytes": st.st_size,
                }
            )
        except FileNotFoundError:
            pass

    if recursive:
        for fp in p.rglob("*"):
            add_item(fp)
    else:
        for fp in p.iterdir():
            add_item(fp)

    # Stable ordering
    results.sort(key=lambda x: (x["is_dir"], x["path"]))
    return results


def read_file(path: str, root: Optional[str] = None, max_bytes: int = 200_000) -> Dict[str, Any]:
    """Read a file as text with a max size guard.

    Returns: {path, size_bytes, content}.
    """
    p = _resolve_path(path, root=root)
    if not p.exists():
        raise FileNotFoundError(str(p))
    if p.is_dir():
        raise IsADirectoryError(str(p))

    size = p.stat().st_size
    if size > max_bytes:
        raise ValueError(f"File too large ({size} bytes). max_bytes={max_bytes}")

    content = p.read_text(encoding="utf-8", errors="replace")
    return {"path": str(p), "size_bytes": size, "content": content}


def search_in_file(
    path: str,
    query: str,
    root: Optional[str] = None,
    regex: bool = False,
    context_lines: int = 2,
    max_results: int = 50,
) -> List[Dict[str, Any]]:
    """Search for a string/regex in a file and return line-context hits."""
    p = _resolve_path(path, root=root)
    if not p.exists():
        raise FileNotFoundError(str(p))
    if p.is_dir():
        raise IsADirectoryError(str(p))

    text = p.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    if regex:
        pattern = re.compile(query)
        def is_match(line: str) -> bool:
            return bool(pattern.search(line))
    else:
        def is_match(line: str) -> bool:
            return query in line

    results: List[Dict[str, Any]] = []
    for i, line in enumerate(lines):
        if is_match(line):
            start = max(0, i - context_lines)
            end = min(len(lines), i + context_lines + 1)
            results.append(
                {
                    "line_number": i + 1,
                    "match_line": line,
                    "context": "\n".join(lines[start:end]),
                }
            )
            if len(results) >= max_results:
                break

    return results


def replace_in_file(
    path: str,
    search: str,
    replace: str,
    root: Optional[str] = None,
    regex: bool = False,
    count: int = 0,
) -> Dict[str, Any]:
    """Replace text inside a file (in-place).

    WARNING: This mutates the file.

    count=0 means replace all.
    Returns: {path, replaced_count}.
    """
    p = _resolve_path(path, root=root)
    if not p.exists():
        raise FileNotFoundError(str(p))
    if p.is_dir():
        raise IsADirectoryError(str(p))

    content = p.read_text(encoding="utf-8", errors="replace")

    if regex:
        pattern = re.compile(search)
        new_content, n = pattern.subn(replace, content, count=count if count else 0)
    else:
        if count and count > 0:
            new_content = content.replace(search, replace, count)
            n = min(content.count(search), count)
        else:
            n = content.count(search)
            new_content = content.replace(search, replace)

    if new_content != content:
        p.write_text(new_content, encoding="utf-8")

    return {"path": str(p), "replaced_count": n, "changed": new_content != content}


__all__ = [
    "list_directory",
    "read_file",
    "search_in_file",
    "replace_in_file",
]
