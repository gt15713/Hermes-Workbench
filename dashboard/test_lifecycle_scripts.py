import os
import subprocess
import sys
from pathlib import Path

from conversation_index import ConversationIndex

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _run_script(script: str, root: Path, db_path: Path, *args: str):
    env = dict(os.environ)
    env["WORKBENCH_ROOT"] = str(root)
    env["WORKBENCH_DB"] = str(db_path)
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=30,
    )


def _prepare(root: Path):
    for name in ("待验证", "任务", "已处理", "回收站", "日志"):
        (root / name).mkdir(parents=True, exist_ok=True)


def _seed(index: ConversationIndex, task_id: str):
    index.upsert_authorized(
        platform="qqbot",
        message_id=f"private-{task_id}",
        summary="后台脚本同步",
        task_id=task_id,
        status="active",
    )


def test_defer_script_syncs_authorized_conversation_to_todo(tmp_path):
    _prepare(tmp_path)
    db_path = tmp_path / "workbench.db"
    index = ConversationIndex(db_path)
    _seed(index, "WB-30000001")
    (tmp_path / "任务" / "defer-script.md").write_text(
        "---\ntype: task\nstatus: todo\ntask_id: WB-30000001\ndue: 2000-01-01\n---\n\n# 顺延脚本\n",
        encoding="utf-8",
    )

    result = _run_script("workbench_defer.py", tmp_path, db_path)

    assert result.returncode == 0, result.stderr
    assert index.list_conversations()[0]["status"] == "todo"


def test_archive_script_syncs_authorized_conversation_to_completed(tmp_path):
    _prepare(tmp_path)
    db_path = tmp_path / "workbench.db"
    index = ConversationIndex(db_path)
    _seed(index, "WB-30000002")
    task = tmp_path / "任务" / "archive-script.md"
    task.write_text(
        "---\ntype: task\nstatus: completed\ntask_id: WB-30000002\n---\n\n# 归档脚本\n",
        encoding="utf-8",
    )

    result = _run_script("workbench_archive.py", tmp_path, db_path)

    assert result.returncode == 0, result.stderr
    assert not task.exists()
    assert (tmp_path / "已处理" / task.name).is_file()
    assert index.list_conversations()[0]["status"] == "completed"


def test_content_receipt_script_records_real_path_and_archives_capture(tmp_path):
    _prepare(tmp_path)
    db_path = tmp_path / "workbench.db"
    capture_id = "0123456789abcdef"
    task_id = "WB-01234567"
    marker = {
        "capture_id": capture_id,
        "source_ref": "redacted",
        "original_url": "https://example.com/source",
        "canonical_url": "https://example.com/source",
        "original_text": "正文",
        "title": "回执脚本",
        "extraction_state": "extracted",
        "review_state": "sink_queued",
        "note_path": "",
        "last_error": "",
        "captured_at": "2026-08-25T10:00:00+00:00",
        "reviewed_at": "2026-08-25T10:01:00+00:00",
        "sink_task_id": task_id,
        "sink_task_dir": "任务",
        "sink_task_file": "content-ingest-0123456789abcdef.md",
        "sink_task_path": "D:/Obsidian/个人工作台/任务/content-ingest-0123456789abcdef.md",
    }
    import json
    capture = tmp_path / "待验证" / f"content-{capture_id}.md"
    capture.write_text(
        f"<!-- wb_content: {json.dumps(marker, ensure_ascii=False, separators=(',', ':'))} -->\n\n# 回执脚本\n",
        encoding="utf-8",
    )

    result = _run_script(
        "hermes_wb_content_receipt.py", tmp_path, db_path,
        "--capture-id", capture_id, "--task-id", task_id,
        "--note-path", "AI工具/回执脚本.md",
    )

    assert result.returncode == 0, result.stderr
    assert not capture.exists()
    archived = tmp_path / "已处理" / capture.name
    assert archived.is_file()
    assert '"review_state":"sunk"' in archived.read_text(encoding="utf-8")
    assert '"note_path":"AI工具/回执脚本.md"' in archived.read_text(encoding="utf-8")
