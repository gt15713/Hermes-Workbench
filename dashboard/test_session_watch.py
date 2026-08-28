# -*- coding: utf-8 -*-
"""P0-2（B3）：会话结束检测 session_watch 测试。

覆盖（TD §12）：三源判定（completed/failed/unknown 安全侧）/ 回写幂等 / 端到端。
"""

from pathlib import Path

import pytest
from contract import PARTITION_NAMES
from session_watch import (
    apply_result,
    decide,
    run_watch,
)


@pytest.fixture()
def root(tmp_path):
    for d in PARTITION_NAMES:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    return tmp_path


def _mk_in_progress(
    root: Path,
    name: str = "任务X.md",
    session_id: str = "sess-1",
    execution_result: str = "pending",
    task_id: str = "",
) -> Path:
    p = root / "任务" / name
    task_id_line = f"task_id: {task_id}\n" if task_id else ""
    p.write_text(
        f"---\ntype: task\nstatus: in_progress\nsession_id: {session_id}\n"
        f"{task_id_line}"
        f"execution_result: {execution_result}\n---\n\n# {name[:-3]}\n",
        encoding="utf-8",
    )
    return p


# ---------- 显式执行结果判定 ----------

def test_decide_plain_or_human_completion_text_is_not_task_success():
    assert decide("# 任务\n") == "unknown"
    assert decide("# 任务\n\n## 完成记录\n\n- 会话已结束\n") == "unknown"


def test_decide_requires_explicit_machine_readable_result():
    success = "---\ntype: task\nstatus: in_progress\nexecution_result: success\n---\n\n# 任务\n"
    failure = "---\ntype: task\nstatus: in_progress\nexecution_result: failure\n---\n\n# 任务\n"
    assert decide(success) == "completed"
    assert decide(failure) == "failed"


def test_decide_safety_keeps_unknown_for_invalid_result():
    text = "---\ntype: task\nstatus: in_progress\nexecution_result: maybe\n---\n\n# 任务\n"
    assert decide(text) == "unknown"


# ---------- 回写 ----------

def test_apply_completed_and_idempotent(root):
    from repo import DualRepo, FileRepo, SqliteRepo

    dual = DualRepo(FileRepo(root=root), SqliteRepo(root / "wb.db", root=root))
    p = _mk_in_progress(root, "完成卡.md")
    item = {"path": p, "text": p.read_text(encoding="utf-8"), "session_id": "s1"}
    act1 = apply_result(item, "completed", root, dual=dual)
    assert act1 == "completed"
    text = p.read_text(encoding="utf-8")
    assert "status: completed" in text
    assert "## 完成记录" in text
    # 幂等：再次 apply → skipped（不重复追加）
    item2 = {"path": p, "text": p.read_text(encoding="utf-8"), "session_id": "s1"}
    act2 = apply_result(item2, "completed", root, dual=dual)
    assert act2 == "skipped"
    assert p.read_text(encoding="utf-8").count("## 完成记录") == 1


def test_apply_failed_restores_todo(root):
    from repo import DualRepo, FileRepo, SqliteRepo

    dual = DualRepo(FileRepo(root=root), SqliteRepo(root / "wb.db", root=root))
    p = _mk_in_progress(root, "失败卡.md")
    item = {"path": p, "text": p.read_text(encoding="utf-8"), "session_id": "s2"}
    act = apply_result(item, "failed", root, dual=dual)
    assert act == "failed"
    text = p.read_text(encoding="utf-8")
    assert "status: todo" in text
    assert "## 执行失败记录" in text


def test_apply_completed_syncs_authorized_conversation(root):
    from conversation_index import ConversationIndex
    from repo import DualRepo, FileRepo, SqliteRepo

    db = SqliteRepo(root / "wb.db", root=root)
    dual = DualRepo(FileRepo(root=root), db)
    p = _mk_in_progress(
        root, "索引完成.md", execution_result="success", task_id="WB-20000001"
    )
    index = ConversationIndex(db.db_path)
    index.upsert_authorized(
        platform="qqbot",
        message_id="private-session-watch-complete",
        summary="后台完成",
        task_id="WB-20000001",
        status="in_progress",
        session_id="sess-1",
    )

    action = apply_result(
        {"path": p, "text": p.read_text(encoding="utf-8"), "session_id": "sess-1"},
        "completed",
        root,
        dual=dual,
    )

    assert action == "completed"
    assert index.list_conversations()[0]["status"] == "completed"


def test_apply_failed_syncs_todo_and_preserves_source_session(root):
    from conversation_index import ConversationIndex
    from repo import DualRepo, FileRepo, SqliteRepo

    db = SqliteRepo(root / "wb.db", root=root)
    dual = DualRepo(FileRepo(root=root), db)
    p = _mk_in_progress(
        root, "索引失败.md", execution_result="failure", task_id="WB-20000002"
    )
    index = ConversationIndex(db.db_path)
    index.upsert_authorized(
        platform="weixin",
        message_id="private-session-watch-failure",
        summary="后台失败",
        task_id="WB-20000002",
        status="in_progress",
        session_id="sess-1",
    )

    action = apply_result(
        {"path": p, "text": p.read_text(encoding="utf-8"), "session_id": "sess-1"},
        "failed",
        root,
        dual=dual,
    )

    assert action == "failed"
    row = index.list_conversations()[0]
    assert row["status"] == "todo"
    assert row["session_id"] == "sess-1"
    assert row["resume_mode"] == "original"
    assert "session_id: sess-1" not in p.read_text(encoding="utf-8")


# ---------- 端到端 ----------

def test_run_watch_end_to_end(root):
    from repo import DualRepo, FileRepo, SqliteRepo

    dual = DualRepo(FileRepo(root=root), SqliteRepo(root / "wb.db", root=root))
    _mk_in_progress(root, "完成卡.md", "sess-a", execution_result="success")
    _mk_in_progress(root, "失败卡.md", "sess-b", execution_result="failure")
    _mk_in_progress(root, "挂起卡.md", "sess-c")
    res = run_watch(root, dual=dual)
    assert res["scanned"] == 3
    assert res["completed"] == 1
    assert res["failed"] == 1
    assert res["pending"] == ["挂起卡.md"]  # 安全侧保持 in_progress
    assert "status: completed" in (root / "任务" / "完成卡.md").read_text(encoding="utf-8")
    assert "status: todo" in (root / "任务" / "失败卡.md").read_text(encoding="utf-8")
    assert "status: in_progress" in (root / "任务" / "挂起卡.md").read_text(encoding="utf-8")
