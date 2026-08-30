"""WB-S1-049 A — runtime /batch envelope, canonical identity and zero-write gates."""

import asyncio

import plugin_api as api
import pytest
import repo as repo_module
import wb_utils


@pytest.fixture()
def wb(tmp_path, monkeypatch):
    """Function-local Workbench root/DB; every production dependency is rebound."""
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


def _run(body):
    return asyncio.run(api.batch(body))


def _touch(wb, name="x.md"):
    path = wb / "任务" / name
    path.write_text("---\ntype: task\nstatus: todo\n---\n\n# x\n", encoding="utf-8")
    return path


def test_action_type_gate_is_total_and_field_complete():
    for action in ([], {}, None):
        result = _run({"action": action, "items": []})
        assert result == {
            "ok": False,
            "done": [],
            "failed": [],
            "summary": {"ok": 0, "fail": 0},
            "error": "action must be a string",
        }


def test_malformed_later_item_calls_no_handler_and_writes_nothing(monkeypatch, wb):
    path = _touch(wb)
    calls = 0

    async def fake_complete(_body):
        nonlocal calls
        calls += 1
        path.write_text("mutated", encoding="utf-8")
        return {"ok": True, "file": path.name}

    monkeypatch.setattr(api, "complete", fake_complete)
    result = _run({"action": "complete", "items": [{"dir": "任务", "file": path.name}, []]})
    assert result["ok"] is False
    assert result["done"] == [] and result["failed"] == []
    assert calls == 0
    assert "status: todo" in path.read_text(encoding="utf-8")


def test_entry_whitespace_is_canonical_for_resolve(monkeypatch, wb):
    _touch(wb)
    calls = 0

    async def fake_resolve(_body):
        nonlocal calls
        calls += 1
        return {"ok": True, "file": "x.md"}

    monkeypatch.setattr(api, "resolve", fake_resolve)
    result = _run({"action": "resolve", "items": [
        {"dir": "任务", "file": "x.md", "entry_title": "x"},
        {"dir": "任务", "file": "x.md", "entry_title": " x "},
    ]})
    assert result["error"] == "duplicate identity at items[1]"
    assert calls == 0


def test_path_alias_is_canonical(monkeypatch, wb):
    _touch(wb)
    calls = 0

    async def fake_trash(_body):
        nonlocal calls
        calls += 1
        return {"ok": True, "trashed": "x.md"}

    monkeypatch.setattr(api, "trash", fake_trash)
    result = _run({"action": "trash", "items": [
        {"dir": "任务", "file": "x.md"},
        {"dir": "任务", "file": "./x.md"},
    ]})
    assert result["error"] == "duplicate identity at items[1]"
    assert calls == 0


def test_trash_and_complete_ignore_entry_in_identity(monkeypatch, wb):
    _touch(wb)
    for action, handler_name in (("trash", "trash"), ("complete", "complete")):
        calls = 0

        async def fake_handler(_body):
            nonlocal calls
            calls += 1
            return {"ok": True, "file": "x.md"}

        monkeypatch.setattr(api, handler_name, fake_handler)
        result = _run({"action": action, "items": [
            {"dir": "任务", "file": "x.md", "entry_title": "one"},
            {"dir": "任务", "file": "x.md", "entry_title": "two"},
        ]})
        assert result["error"] == "duplicate identity at items[1]"
        assert calls == 0


def test_batch_consumes_real_resolve_and_to_task_entry_handlers(wb):
    review = wb / "待验证" / "review.md"
    review.write_text("---\ntype: queued\nstatus: queued\n---\n\n# review\n\n## Keep this\n\n- body\n\n## Convert me\n\n- task body\n", encoding="utf-8")
    resolved = _run({"action": "resolve", "items": [{"dir": "待验证", "file": "review.md", "entry_title": " Convert me "}]})
    assert resolved["summary"] == {"ok": 1, "fail": 0}
    assert resolved["done"][0]["entry"] == "Convert me"
    assert (wb / "已处理" / "review-Convert-me.md").is_file()
    assert "## Keep this" in review.read_text(encoding="utf-8")

    source = wb / "待回看" / "task-source.md"
    source.write_text("---\ntype: queued\nstatus: PENDING\n---\n\n# source\n\n## Make task\n\n- do it\n", encoding="utf-8")
    converted = _run({"action": "to-task", "items": [{"dir": "待回看", "file": "task-source.md", "entry_title": "Make task"}]})
    assert converted["summary"] == {"ok": 1, "fail": 0}
    assert (wb / "任务" / "Make-task.md").is_file()


def test_batch_consumes_real_complete_states_and_trash_boundary(wb):
    completed = _touch(wb, "already-completed.md")
    completed.write_text(completed.read_text(encoding="utf-8").replace("status: todo", "status: completed"), encoding="utf-8")
    done = _touch(wb, "done-success.md")
    done.write_text(done.read_text(encoding="utf-8").replace("status: todo", "status: done\nexecution_result: success"), encoding="utf-8")
    result = _run({"action": "complete", "items": [
        {"dir": "任务", "file": "already-completed.md"},
        {"dir": "任务", "file": "done-success.md"},
    ]})
    assert result["summary"] == {"ok": 2, "fail": 0}
    assert all((wb / "已处理" / name).is_file() for name in ("already-completed.md", "done-success.md"))

    trash_source = _touch(wb, "trash-me.md")
    trashed = _run({"action": "trash", "items": [{"dir": "任务", "file": "trash-me.md", "entry_title": "ignored"}]})
    assert trashed["summary"] == {"ok": 1, "fail": 0}
    assert not trash_source.exists() and (wb / "回收站" / "trash-me.md").is_file()

    rejected = _run({"action": "trash", "items": [{"dir": "不存在", "file": "x.md"}]})
    assert rejected["summary"] == {"ok": 0, "fail": 0}
    assert rejected["done"] == [] and rejected["failed"] == []
    assert "invalid identity" in rejected["error"]
