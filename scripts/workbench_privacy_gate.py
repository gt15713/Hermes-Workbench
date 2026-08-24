# -*- coding: utf-8 -*-
"""Fail when tracked release files contain known local-only markers.

Patterns are assembled from fragments so this scanner and its documentation do
not match themselves. Output contains locations only, never the sensitive line.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Iterable

_MARKERS = (
    "C:" + "/Users",
    "C:" + "\\Users",
    "D:" + "/Obsidian",
    "D:" + "\\Obsidian",
    "Ka" + "yura",
    "827" + "B",
    "\u4e2a\u4eba\u5de5\u4f5c\u53f0",
)
_SKIP_NAMES = {"workbench-config.json", "workbench.db", "build-info.json"}
_SKIP_PARTS = {".git", "node_modules", "__pycache__"}


def scan_paths(paths: Iterable[Path], *, root: Path) -> list[str]:
    hits: list[str] = []
    for path in paths:
        relative = path.resolve().relative_to(root.resolve())
        if path.name in _SKIP_NAMES or any(part in _SKIP_PARTS for part in relative.parts):
            continue
        if path.name.startswith("scheduler-") or ".bak" in path.name.lower():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            hits.append(f"{relative.as_posix()}:unreadable")
            continue
        for number, line in enumerate(lines, 1):
            if any(marker in line for marker in _MARKERS):
                hits.append(f"{relative.as_posix()}:{number}")
    return hits


def tracked_paths(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True
    )
    return [root / item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    hits = scan_paths(tracked_paths(root), root=root)
    if hits:
        print("privacy gate failed; local-only markers found at:", file=sys.stderr)
        for hit in hits:
            print(f"- {hit}", file=sys.stderr)
        return 1
    print("privacy gate: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
