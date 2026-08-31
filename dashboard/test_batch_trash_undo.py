"""WB-S1-056 / FR-020 — authoritative Undo for successful batch trash rows."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

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


def _task(wb, name, body="body"):
    path = wb / "任务" / name
    path.write_text(f"---\ntype: task\nstatus: todo\n---\n\n# {name}\n\n{body}\n", encoding="utf-8")
    return path


def _batch(*names):
    return _run(api.batch({"action": "trash", "items": [{"dir": "任务", "file": name} for name in names]}))


def _undo(receipt, *, items=None):
    return _run(api.undo_batch_trash({
        "schema": receipt["schema"],
        "version": receipt["version"],
        "operation_id": receipt["operation_id"],
        "action": "trash",
        "items": receipt["items"] if items is None else items,
    }))


def test_batch_trash_receipt_contains_exact_successes_only(wb):
    _task(wb, "ok.md")
    result = _batch("ok.md", "missing.md")

    assert result["summary"] == {"ok": 1, "fail": 1}
    assert isinstance(result["operation_id"], str) and result["operation_id"]
    assert result["undo_receipt"] == {
        "schema": "workbench.batch-trash-undo",
        "version": 2,
        "operation_id": result["operation_id"],
        "action": "trash",
        "expires_at": result["undo_receipt"]["expires_at"],
        "items": [{"dir": "任务", "file": "ok.md"}],
    }
    assert all(row["file"] != "missing.md" for row in result["undo_receipt"]["items"])


def test_full_success_undo_uses_restore_and_never_permanent_delete(wb, monkeypatch):
    _task(wb, "one.md")
    _task(wb, "two.md")
    receipt = _batch("one.md", "two.md")["undo_receipt"]
    delete_calls = []

    async def forbidden_delete(body):
        delete_calls.append(body)
        raise AssertionError("permanent delete must not be called")

    monkeypatch.setattr(api, "delete_file", forbidden_delete)
    result = _undo(receipt)

    assert result["ok"] is True
    assert result["restored"] == [
        {"dir": "任务", "file": "one.md"},
        {"dir": "任务", "file": "two.md"},
    ]
    assert result["failed"] == []
    assert result["summary"] == {"restored": 2, "failed": 0}
    assert result["receipt"]["operation_id"] == receipt["operation_id"]
    assert result["receipt"]["consumed"] is True
    assert delete_calls == []
    assert (wb / "任务" / "one.md").is_file()
    assert (wb / "任务" / "two.md").is_file()


@pytest.mark.parametrize("kind", ["tampered", "mixed_failed", "partial_missing"])
def test_identity_tamper_or_nonexact_set_fails_closed(wb, kind):
    _task(wb, "ok.md")
    result = _batch("ok.md", "failed.md")
    receipt = result["undo_receipt"]
    if kind == "tampered":
        items = [{"dir": "任务", "file": "other.md"}]
    elif kind == "mixed_failed":
        items = [*receipt["items"], {"dir": "任务", "file": "failed.md"}]
    else:
        items = []

    rejected = _undo(receipt, items=items)

    assert rejected["ok"] is False
    assert rejected["restored"] == []
    assert rejected["failed"] == []
    assert rejected["summary"] == {"restored": 0, "failed": 0}
    assert (wb / "回收站" / "ok.md").is_file()
    assert not (wb / "任务" / "ok.md").exists()


def test_expired_and_double_submit_are_single_consume(wb, monkeypatch):
    now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(api, "_batch_undo_now", lambda: now)
    _task(wb, "expired.md")
    expired_receipt = _batch("expired.md")["undo_receipt"]
    monkeypatch.setattr(api, "_batch_undo_now", lambda: now + timedelta(hours=1))
    expired = _undo(expired_receipt)
    assert expired["ok"] is False and expired["restored"] == []
    assert (wb / "回收站" / "expired.md").is_file()

    monkeypatch.setattr(api, "_batch_undo_now", lambda: now)
    _task(wb, "once.md")
    receipt = _batch("once.md")["undo_receipt"]
    first = _undo(receipt)
    second = _undo(receipt)
    assert first["summary"] == {"restored": 1, "failed": 0}
    assert second["ok"] is False and second["summary"] == {"restored": 0, "failed": 0}
    assert (wb / "任务" / "once.md").is_file()


@pytest.mark.parametrize("drift", ["content", "missing", "collision"])
def test_post_state_drift_missing_or_collision_fails_closed_zero_moves(wb, drift):
    _task(wb, "one.md")
    _task(wb, "two.md")
    receipt = _batch("one.md", "two.md")["undo_receipt"]
    if drift == "content":
        (wb / "回收站" / "two.md").write_text("externally modified", encoding="utf-8")
    elif drift == "missing":
        (wb / "回收站" / "two.md").rename(wb / "回收站" / "externally-moved.md")
    else:
        _task(wb, "two.md", "collision")

    rejected = _undo(receipt)

    assert rejected["ok"] is False
    assert rejected["restored"] == []
    assert not (wb / "任务" / "one.md").exists()
    assert (wb / "回收站" / "one.md").is_file()


def test_runtime_partial_undo_keeps_failures_visible_and_consumes_once(wb, monkeypatch):
    _task(wb, "one.md")
    _task(wb, "two.md")
    receipt = _batch("one.md", "two.md")["undo_receipt"]
    real_restore = api.restore
    calls = 0

    async def flaky_restore(body):
        nonlocal calls
        calls += 1
        if calls == 2:
            return {"ok": False, "error": "simulated restore failure"}
        return await real_restore(body)

    monkeypatch.setattr(api, "restore", flaky_restore)
    result = _undo(receipt)

    assert result["ok"] is True
    assert result["restored"] == [{"dir": "任务", "file": "one.md"}]
    assert result["failed"] == [{"dir": "任务", "file": "two.md", "error": "simulated restore failure"}]
    assert result["summary"] == {"restored": 1, "failed": 1}
    assert result["receipt"]["consumed"] is True
    assert (wb / "任务" / "one.md").is_file()
    assert (wb / "回收站" / "two.md").is_file()
    assert _undo(receipt)["ok"] is False
