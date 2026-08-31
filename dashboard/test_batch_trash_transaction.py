"""WB-S1-057 RED/GREEN — recoverable batch-trash transaction and atomic claim."""

from __future__ import annotations

import asyncio
import json
import multiprocessing
import time
from pathlib import Path

import plugin_api as api
import pytest
import repo as repo_module
import wb_utils


@pytest.fixture()
def wb(tmp_path, monkeypatch):
    root = tmp_path / "workbench"
    for dirname in ("待验证", "待回看", "任务", "心理学随想", "梦中的邮件", "已处理", "回收站", "日志"):
        (root / dirname).mkdir(parents=True, exist_ok=True)
    isolated_repo = repo_module.DualRepo(
        file_repo=repo_module.FileRepo(root),
        sqlite_repo=repo_module.SqliteRepo(tmp_path / "workbench.db"),
        read_from_db=False,
    )
    monkeypatch.setattr(api, "WORKBENCH_ROOT", root)
    monkeypatch.setattr(api, "file_repo", isolated_repo)
    monkeypatch.setattr(wb_utils, "WORKBENCH_ROOT", root)
    monkeypatch.setattr(wb_utils, "LOG_DIR", root / "日志")
    monkeypatch.setattr(repo_module, "WORKBENCH_ROOT", root)
    monkeypatch.setattr(repo_module, "_repo", isolated_repo)
    return root


def _run(awaitable):
    return asyncio.run(awaitable)


def _task(root: Path, name: str):
    path = root / "任务" / name
    path.write_text(f"---\ntype: task\nstatus: todo\n---\n\n# {name}\n", encoding="utf-8")
    return path


def _batch(*names: str):
    return _run(api.batch({"action": "trash", "items": [{"dir": "任务", "file": name} for name in names]}))


def test_durable_prepared_identity_exists_before_first_move(wb, monkeypatch):
    _task(wb, "one.md")
    real_move = api._rename_with_retry
    observed = []

    def inspect_before_move(src, dst):
        prepared = list((wb / ".batch-undo").glob("*.prepared.json"))
        assert len(prepared) == 1
        record = json.loads(prepared[0].read_text(encoding="utf-8"))
        assert record["version"] == 2
        assert record["state"] == "prepared"
        assert record["items"][0]["dir"] == "任务"
        assert record["items"][0]["file"] == "one.md"
        assert record["items"][0]["trash_file"] == "one.md"
        observed.append(record["operation_id"])
        return real_move(src, dst)

    monkeypatch.setattr(api, "_rename_with_retry", inspect_before_move)
    result = _batch("one.md")
    assert result["undo_receipt"]["operation_id"] == observed[0]


def test_prepared_record_write_failure_moves_nothing(wb, monkeypatch):
    _task(wb, "one.md")

    def fail_prepared(record, *args, **kwargs):
        raise OSError("injected prepared write failure")

    monkeypatch.setattr(api, "_write_batch_undo_record", fail_prepared)
    result = _batch("one.md")
    assert result["summary"] == {"ok": 0, "fail": 1}
    assert "undo_receipt" not in result
    assert (wb / "任务" / "one.md").is_file()
    assert not (wb / "回收站" / "one.md").exists()


def test_post_state_digest_failure_rolls_back_without_orphan(wb, monkeypatch):
    _task(wb, "one.md")
    monkeypatch.setattr(api, "_file_digest", lambda _path: (_ for _ in ()).throw(OSError("digest failure")))
    result = _batch("one.md")
    assert result["summary"] == {"ok": 0, "fail": 1}
    assert "undo_receipt" not in result
    assert (wb / "任务" / "one.md").is_file()
    assert not (wb / "回收站" / "one.md").exists()
    records = list((wb / ".batch-undo").glob("*.prepared.json"))
    assert len(records) == 1
    assert json.loads(records[0].read_text(encoding="utf-8"))["state"] in {"aborted", "prepared"}


def test_final_record_write_failure_rolls_back_without_receipt(wb, monkeypatch):
    _task(wb, "one.md")
    real_write = api._write_batch_undo_record

    def fail_final(record, *args, **kwargs):
        if record.get("state") == "finalized":
            raise OSError("injected final write failure")
        return real_write(record, *args, **kwargs)

    monkeypatch.setattr(api, "_write_batch_undo_record", fail_final)
    result = _batch("one.md")
    assert result["summary"] == {"ok": 0, "fail": 1}
    assert "undo_receipt" not in result
    assert (wb / "任务" / "one.md").is_file()
    assert not (wb / "回收站" / "one.md").exists()


def test_unknown_schema_rejected_and_v1_draft_remains_readable(wb):
    _task(wb, "unknown.md")
    receipt = _batch("unknown.md")["undo_receipt"]
    final = wb / ".batch-undo" / f"{receipt['operation_id']}.json"
    record = json.loads(final.read_text(encoding="utf-8"))
    record["version"] = 999
    final.write_text(json.dumps(record), encoding="utf-8")
    rejected = _run(api.undo_batch_trash(receipt))
    assert rejected["ok"] is False
    assert rejected["receipt"]["consumed"] is False
    assert "schema" in rejected["error"]
    assert (wb / "回收站" / "unknown.md").is_file()


def _claim_worker(root_text, receipt, start, output, worker_id):
    root = Path(root_text)
    import plugin_api as worker_api
    import repo as worker_repo
    import wb_utils as worker_utils

    isolated = worker_repo.DualRepo(
        file_repo=worker_repo.FileRepo(root),
        sqlite_repo=worker_repo.SqliteRepo(root.parent / f"worker-{worker_id}.db"),
        read_from_db=False,
    )
    worker_api.WORKBENCH_ROOT = root
    worker_api.file_repo = isolated
    worker_utils.WORKBENCH_ROOT = root
    worker_utils.LOG_DIR = root / "日志"
    worker_repo.WORKBENCH_ROOT = root
    worker_repo._repo = isolated

    async def probe_restore(_body):
        (root / f"restore-entered-{worker_id}").write_text("entered", encoding="utf-8")
        time.sleep(0.35)
        return {"ok": True}

    worker_api.restore = probe_restore
    start.wait(5)
    result = asyncio.run(worker_api.undo_batch_trash(receipt))
    output.put(result)


def test_two_processes_single_claim_before_restore(wb):
    _task(wb, "once.md")
    receipt = _batch("once.md")["undo_receipt"]
    ctx = multiprocessing.get_context("spawn")
    start = ctx.Event()
    output = ctx.Queue()
    workers = [ctx.Process(target=_claim_worker, args=(str(wb), receipt, start, output, i)) for i in range(2)]
    for worker in workers:
        worker.start()
    start.set()
    results = [output.get(timeout=10) for _ in workers]
    for worker in workers:
        worker.join(10)
        assert worker.exitcode == 0

    entered = list(wb.glob("restore-entered-*"))
    assert len(entered) == 1
    assert sum(result.get("receipt", {}).get("consumed") is True for result in results) == 1
    rejected = [result for result in results if result.get("receipt", {}).get("consumed") is not True]
    assert len(rejected) == 1
    assert rejected[0]["restored"] == []
    assert rejected[0]["receipt"]["consumed"] is False
    assert rejected[0]["error"] in {"operation busy", "operation already consumed"}
