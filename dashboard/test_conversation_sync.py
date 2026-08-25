import sqlite3

from conversation_index import ConversationIndex
from conversation_sync import sync_by_task_text


def test_sync_retries_a_transient_sqlite_lock(tmp_path, monkeypatch):
    db_path = tmp_path / "workbench.db"
    index = ConversationIndex(db_path)
    index.upsert_authorized(
        platform="qq",
        message_id="message-1",
        summary="短暂锁",
        task_id="WB-AABBCCDD",
        status="active",
    )
    original = ConversationIndex.update_by_task_id
    attempts = 0

    def locked_twice(self, task_id, **changes):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise sqlite3.OperationalError("database is locked")
        return original(self, task_id, **changes)

    monkeypatch.setattr(ConversationIndex, "update_by_task_id", locked_twice)

    result = sync_by_task_text(
        db_path,
        "---\ntask_id: WB-AABBCCDD\n---\n",
        status="completed",
    )

    assert result == {"ok": True, "updated": 1}
    assert attempts == 3
    assert index.list_conversations()[0]["status"] == "completed"


def test_sync_does_not_retry_a_non_lock_database_error(tmp_path, monkeypatch):
    db_path = tmp_path / "workbench.db"
    ConversationIndex(db_path)
    attempts = 0

    def broken(self, task_id, **changes):
        nonlocal attempts
        attempts += 1
        raise sqlite3.OperationalError("no such table")

    monkeypatch.setattr(ConversationIndex, "update_by_task_id", broken)

    result = sync_by_task_text(
        db_path,
        "---\ntask_id: WB-AABBCCDD\n---\n",
        status="completed",
    )

    assert result == {
        "ok": False,
        "updated": 0,
        "error": "conversation index unavailable",
    }
    assert attempts == 1
