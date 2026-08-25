from conversation_index import ConversationIndex


def test_authorized_task_is_indexed_once_without_raw_platform_identity(tmp_path):
    index = ConversationIndex(tmp_path / "index.db")
    first = index.upsert_authorized(
        platform="qqbot",
        message_id="official-secret-message-id",
        summary="评估学习视频",
        task_id="WB-12345678",
        status="active",
    )
    second = index.upsert_authorized(
        platform="qqbot",
        message_id="official-secret-message-id",
        summary="评估学习视频",
        task_id="WB-12345678",
        status="active",
    )

    rows = index.list_conversations()
    assert first == second
    assert len(rows) == 1
    assert rows[0]["platform"] == "qq"
    assert rows[0]["task_id"] == "WB-12345678"
    assert rows[0]["resume_mode"] == "summary"
    assert "official-secret-message-id" not in (tmp_path / "index.db").read_bytes().decode(
        "latin1"
    )


def test_missing_official_message_id_is_rejected(tmp_path):
    index = ConversationIndex(tmp_path / "index.db")
    result = index.upsert_authorized(
        platform="weixin",
        message_id="",
        summary="一条任务",
        task_id="WB-87654321",
        status="active",
    )

    assert result == {"ok": False, "error": "official message_id required"}
    assert index.list_conversations() == []


def test_update_by_task_id_updates_every_authorized_reference_without_message_id(tmp_path):
    index = ConversationIndex(tmp_path / "index.db")
    for platform, message_id in (("qqbot", "qq-private-id"), ("weixin", "wx-private-id")):
        index.upsert_authorized(
            platform=platform,
            message_id=message_id,
            summary="同一个跨平台任务",
            task_id="WB-AABBCCDD",
            status="active",
        )

    result = index.update_by_task_id(
        "WB-AABBCCDD", status="in_progress", session_id="session-visible-1"
    )

    rows = index.list_conversations()
    assert result == {"ok": True, "updated": 2}
    assert len(rows) == 2
    assert {row["status"] for row in rows} == {"in_progress"}
    assert {row["session_id"] for row in rows} == {"session-visible-1"}
    assert {row["resume_mode"] for row in rows} == {"original"}


def test_update_by_task_id_empty_or_unknown_is_an_idempotent_noop(tmp_path):
    index = ConversationIndex(tmp_path / "index.db")

    assert index.update_by_task_id("", status="completed") == {"ok": True, "updated": 0}
    assert index.update_by_task_id("WB-UNKNOWN", status="completed") == {
        "ok": True,
        "updated": 0,
    }
