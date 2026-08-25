# -*- coding: utf-8 -*-
"""Apply a reviewed-content ingestion receipt through the Workbench API code path."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

_DASHBOARD = Path(__file__).resolve().parent.parent / "dashboard"
if str(_DASHBOARD) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD))


def main() -> int:
    parser = argparse.ArgumentParser(description="Workbench 内容摄入回执")
    parser.add_argument("--capture-id", required=True)
    parser.add_argument("--task-id", required=True)
    outcome = parser.add_mutually_exclusive_group(required=True)
    outcome.add_argument("--note-path")
    outcome.add_argument("--error")
    args = parser.parse_args()

    import plugin_api  # noqa: PLC0415
    # The receipt must remain recoverable from the Markdown fact source even
    # when the SQLite mirror is stale after an interrupted Agent run.
    plugin_api.file_repo.read_from_db = False

    body = {
        "capture_id": args.capture_id,
        "task_id": args.task_id,
        "note_path": args.note_path or "",
        "error": args.error or "",
    }
    try:
        result = asyncio.run(plugin_api.content_sink_receipt(body))
    except Exception as exc:  # noqa: BLE001
        result = {"ok": False, "error": f"execution failed: {exc}"}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
