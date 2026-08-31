"""Emit real production batch-Undo endpoint responses for cross-language tests."""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _configure(root: Path) -> None:
    for dirname in ("待验证", "待回看", "任务", "心理学随想", "梦中的邮件", "已处理", "回收站", "日志"):
        (root / dirname).mkdir(parents=True, exist_ok=True)
    probe_db = root.parent / "probe.db"
    os.environ["WORKBENCH_ROOT"] = str(root)
    os.environ["WORKBENCH_DB"] = str(probe_db)
    os.environ["WORKBENCH_CONFIG"] = str(root.parent / "probe-config.json")

    # Production modules construct their repositories at import time.  The
    # isolation environment must therefore exist before the very first import.
    global api, repo_module, wb_utils
    repo_module = importlib.import_module("repo")
    wb_utils = importlib.import_module("wb_utils")
    api = importlib.import_module("plugin_api")
    if repo_module.WORKBENCH_DB_PATH.resolve() != probe_db.resolve():
        raise RuntimeError("probe isolation failed: repo imported with a non-temporary database")
    isolated = repo_module.DualRepo(
        repo_module.FileRepo(root), repo_module.SqliteRepo(probe_db), False
    )
    api.WORKBENCH_ROOT = root
    api.file_repo = isolated
    wb_utils.WORKBENCH_ROOT = root
    wb_utils.LOG_DIR = root / "日志"
    repo_module.WORKBENCH_ROOT = root
    repo_module._repo = isolated


def _task(root: Path, name: str) -> None:
    (root / "任务" / name).write_text(
        f"---\ntype: task\nstatus: todo\n---\n\n# {name}\n", encoding="utf-8"
    )


def _run(awaitable):
    return asyncio.run(awaitable)


def _receipt(root: Path, *names: str) -> dict:
    for name in names:
        _task(root, name)
    return _run(api.batch({
        "action": "trash",
        "items": [{"dir": "任务", "file": name} for name in names],
    }))["undo_receipt"]


def run_scenario(scenario: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="wb-undo-contract-") as temp:
        root = Path(temp) / "workbench"
        _configure(root)
        real_write = api._write_batch_undo_record
        real_evidence = api._write_batch_recovery_evidence

        if scenario in {"intent-settle", "outcome-settle", "terminal-sidecar"}:
            receipt = _receipt(root, "one.md", "two.md")

            def injected_write(record, *args, **kwargs):
                state = record.get("state")
                second_intent = any(
                    item.get("file") == "two.md" and item.get("undo_state") == "intent"
                    for item in record.get("items") or []
                )
                has_outcome = bool((record.get("outcome") or {}).get("restored"))
                should_fail = (
                    scenario == "intent-settle" and ((state == "claimed" and second_intent) or state == "consumed")
                    or scenario == "outcome-settle" and ((state == "claimed" and has_outcome) or state == "consumed")
                    or scenario == "terminal-sidecar" and state == "consumed"
                )
                if should_fail:
                    raise OSError(f"injected {scenario} ledger write failure")
                return real_write(record, *args, **kwargs)

            api._write_batch_undo_record = injected_write
            if scenario == "terminal-sidecar":
                api._write_batch_recovery_evidence = lambda *_a, **_k: (_ for _ in ()).throw(
                    OSError("injected recovery sidecar write failure")
                )
            try:
                return {"receipt": receipt, "response": _run(api.undo_batch_trash(receipt))}
            except Exception as exc:
                ledger = json.loads(api._batch_undo_path(receipt["operation_id"]).read_text(encoding="utf-8"))
                claim_exists_after_exception = api._batch_undo_claim_path(receipt["operation_id"]).exists()
                api._write_batch_undo_record = real_write
                api._write_batch_recovery_evidence = real_evidence
                api._recover_batch_undo_operations()
                settled = json.loads(api._batch_undo_path(receipt["operation_id"]).read_text(encoding="utf-8"))
                return {
                    "receipt": receipt,
                    "exception": f"{type(exc).__name__}: {exc}",
                    "claimed_ledger": ledger,
                    "claim_exists_after_exception": claim_exists_after_exception,
                    "settled_ledger": settled,
                }
            finally:
                api._write_batch_undo_record = real_write
                api._write_batch_recovery_evidence = real_evidence

        if scenario == "rejections":
            responses = {}
            receipts = {}
            busy = _receipt(root, "busy.md")
            claim = api._acquire_batch_undo_claim(busy["operation_id"])
            receipts["operation busy"] = busy
            responses["operation busy"] = _run(api.undo_batch_trash(busy))
            api._release_batch_undo_claim(busy["operation_id"], claim)

            expired = _receipt(root, "expired.md")
            expired_path = api._batch_undo_path(expired["operation_id"])
            expired_record = json.loads(expired_path.read_text(encoding="utf-8"))
            expired_record["expires_at"] = datetime(2000, 1, 1, tzinfo=timezone.utc).isoformat()
            real_write(expired_record, expired_path)
            receipts["operation expired"] = expired
            responses["operation expired"] = _run(api.undo_batch_trash(expired))

            collision = _receipt(root, "collision.md")
            _task(root, "collision.md")
            receipts["original path collision"] = collision
            responses["original path collision"] = _run(api.undo_batch_trash(collision))
            return {"receipts": receipts, "responses": responses}

        raise ValueError(f"unknown scenario: {scenario}")


if __name__ == "__main__":
    print(json.dumps(run_scenario(sys.argv[1]), ensure_ascii=False))
