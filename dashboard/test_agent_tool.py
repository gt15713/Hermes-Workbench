import asyncio
import sqlite3

import pytest


@pytest.fixture()
def wb(tmp_path, monkeypatch):
    import plugin_api as api
    import repo as repo_mod
    import wb_utils as wb_utils_mod

    for dirname in (
        "待验证",
        "待回看",
        "任务",
        "心理学随想",
        "梦中的邮件",
        "已处理",
        "回收站",
        "日志",
    ):
        (tmp_path / dirname).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(api, "WORKBENCH_ROOT", tmp_path)
    monkeypatch.setattr(wb_utils_mod, "WORKBENCH_ROOT", tmp_path)
    monkeypatch.setattr(wb_utils_mod, "LOG_DIR", tmp_path / "日志")
    monkeypatch.setattr(repo_mod, "WORKBENCH_ROOT", tmp_path)
    original_db = api.file_repo.db
    original_read_from_db = api.file_repo.read_from_db
    monkeypatch.setattr(api.file_repo, "root", tmp_path)
    api.file_repo.db = repo_mod.SqliteRepo(tmp_path / "test-workbench.db", root=tmp_path)
    api.file_repo.read_from_db = False
    try:
        yield tmp_path
    finally:
        api.file_repo.db = original_db
        api.file_repo.read_from_db = original_read_from_db


class ToolContext:
    def __init__(self):
        self.tools = {}

    def register_tool(self, **kwargs):
        self.tools[kwargs["name"]] = kwargs


def test_tool_registration_exposes_no_identity_arguments():
    from agent_tool import register_workbench_tool

    ctx = ToolContext()
    register_workbench_tool(ctx)

    assert {
        name: tool["toolset"] for name, tool in ctx.tools.items()
    } == {"workbench_capture": "skills"}
    for registered in ctx.tools.values():
        assert registered.get("override", False) is False
        assert registered["is_async"] is True
        properties = registered["schema"]["parameters"]["properties"]
        assert not {
            "session_id",
            "platform",
            "message_id",
            "chat_id",
            "user_id",
        }.intersection(properties)


def test_fallback_identity_with_empty_message_id_succeeds(wb, tmp_path):
    """Red test 1: empty message_id + trusted session_id + one persisted user row → succeeds."""
    from agent_tool import (
        _resolve_state_db_message_id,
        handle_workbench_capture,
        _STATE_DB_PATH,
    )
    from conversation_index import ConversationIndex
    from gateway.session_context import clear_session_vars, set_session_vars
    import plugin_api as api

    # Create a mock state.db with one user message row
    state_db = tmp_path / "state.db"
    import sqlite3
    conn = sqlite3.connect(str(state_db))
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT)")
    conn.execute("INSERT INTO messages (id, session_id, role, content) VALUES (1, 'session-fallback', 'user', '测试消息')")
    conn.commit()
    conn.close()

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("agent_tool._STATE_DB_PATH", str(tmp_path))
    try:
        # Verify the resolver works
        opaque = _resolve_state_db_message_id("session-fallback")
        assert opaque == "wb-msg:session-fallback:1"

        # Now call the handler
        tokens = set_session_vars(
            session_id="session-fallback",
            platform="qqbot",
            message_id="",
        )
        try:
            reply = asyncio.run(
                handle_workbench_capture({"action": "task", "content": "回退身份测试"})
            )
        finally:
            clear_session_vars(tokens)

        # Verify it succeeded (task created)
        assert reply.startswith("已创建任务 WB-"), f"Expected task creation, got: {reply}"

        # Verify conversation ref is original
        indexed = ConversationIndex(api.file_repo.db.db_path).list_conversations()
        new_refs = [r for r in indexed if r["session_id"] == "session-fallback"]
        assert len(new_refs) == 1
        assert new_refs[0]["resume_mode"] == "original"
        assert new_refs[0]["session_id"] == "session-fallback"
    finally:
        monkeypatch.undo()


def test_fallback_identity_is_idempotent_on_retry(wb, tmp_path):
    """Red test 2: retrying the same persisted turn is idempotent."""
    from agent_tool import handle_workbench_capture, _STATE_DB_PATH
    from conversation_index import ConversationIndex
    from gateway.session_context import clear_session_vars, set_session_vars
    import plugin_api as api

    # Create mock state.db
    state_db = tmp_path / "state.db"
    import sqlite3
    conn = sqlite3.connect(str(state_db))
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT)")
    conn.execute("INSERT INTO messages (id, session_id, role, content) VALUES (99, 'session-idempotent', 'user', '幂等测试')")
    conn.commit()
    conn.close()

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("agent_tool._STATE_DB_PATH", str(tmp_path))
    try:
        tokens = set_session_vars(
            session_id="session-idempotent",
            platform="qqbot",
            message_id="",
        )
        try:
            # First call
            reply1 = asyncio.run(
                handle_workbench_capture({"action": "task", "content": "幂等测试"})
            )
            # Second call - same turn
            reply2 = asyncio.run(
                handle_workbench_capture({"action": "task", "content": "幂等测试"})
            )
        finally:
            clear_session_vars(tokens)

        # First call created task; second call should be idempotent
        assert reply1.startswith("已创建任务 WB-"), f"First call failed: {reply1}"
        assert reply2 == "该命令已经处理。" or reply2.startswith("已续接"), f"Second call not idempotent: {reply2}"

        # Verify only one task and one ref
        tasks = list((wb / "任务").glob("*.md"))
        assert len(tasks) == 1

        indexed = ConversationIndex(api.file_repo.db.db_path).list_conversations()
        session_refs = [r for r in indexed if r["session_id"] == "session-idempotent"]
        assert len(session_refs) == 1
    finally:
        monkeypatch.undo()


def test_fallback_identity_unique_per_turn(wb, tmp_path):
    """S1-007 contract: two turns in one session handled correctly.

    First turn (row 10) succeeds and binds row 10; second turn (row 11) succeeds
    and binds the NEWEST row (11) with a DIFFERENT internal identity.
    """
    from agent_tool import handle_workbench_capture, _STATE_DB_PATH
    from conversation_index import ConversationIndex
    from gateway.session_context import clear_session_vars, set_session_vars
    import plugin_api as api

    state_db = tmp_path / "state.db"
    import sqlite3
    conn = sqlite3.connect(str(state_db))
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT)")
    # First turn: one user message
    conn.execute("INSERT INTO messages (id, session_id, role, content) VALUES (10, 'session-multi', 'user', '第一条')")
    conn.commit()
    conn.close()

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("agent_tool._STATE_DB_PATH", str(tmp_path))
    try:
        # First turn: succeeds
        tokens = set_session_vars(
            session_id="session-multi",
            platform="qqbot",
            message_id="",
        )
        try:
            reply = asyncio.run(
                handle_workbench_capture({"action": "task", "content": "第一条消息"})
            )
        finally:
            clear_session_vars(tokens)
        assert reply.startswith("已创建任务 WB-"), f"First turn should succeed: {reply}"

        # Second turn: add another user message to simulate second turn
        conn2 = sqlite3.connect(str(state_db))
        conn2.execute("INSERT INTO messages (id, session_id, role, content) VALUES (11, 'session-multi', 'user', '第二条')")
        conn2.commit()
        conn2.close()

        tokens2 = set_session_vars(
            session_id="session-multi",
            platform="qqbot",
            message_id="",
        )
        try:
            reply2 = asyncio.run(
                handle_workbench_capture({"action": "task", "content": "第二条消息"})
            )
        finally:
            clear_session_vars(tokens2)
        # Second turn binds the newest row -> succeeds with a different ref
        assert reply2.startswith("已创建任务 WB-"), f"Second turn should succeed: {reply2}"
        indexed2 = ConversationIndex(api.file_repo.db.db_path).list_conversations()
        multi_refs = [r for r in indexed2 if r["session_id"] == "session-multi"]
        assert len(multi_refs) == 2, f"expected two refs (two turns), got {len(multi_refs)}"
        assert multi_refs[0]["session_id"] == "session-multi"
    finally:
        monkeypatch.undo()


def test_fallback_identity_refuses_ambiguous_session(wb, tmp_path):
    """Red test 5: ambiguous rows fail closed without mutation."""
    from agent_tool import handle_workbench_capture, _STATE_DB_PATH
    from gateway.session_context import clear_session_vars, set_session_vars
    import plugin_api as api

    state_db = tmp_path / "state.db"
    import sqlite3
    conn = sqlite3.connect(str(state_db))
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT)")
    # No user messages at all
    conn.commit()
    conn.close()

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("agent_tool._STATE_DB_PATH", str(tmp_path))
    try:
        tokens = set_session_vars(
            session_id="session-no-user",
            platform="qqbot",
            message_id="",
        )
        try:
            reply = asyncio.run(
                handle_workbench_capture({"action": "task", "content": "不应落盘"})
            )
        finally:
            clear_session_vars(tokens)

        assert "未找到用户消息记录" in reply or "请改用 /wb" in reply
        assert list((wb / "任务").glob("*.md")) == []
    finally:
        monkeypatch.undo()


def test_fallback_non_user_rows_fail_closed(wb, tmp_path):
    """Red test 5 variant: only tool/assistant rows exist, no user row."""
    from agent_tool import handle_workbench_capture, _STATE_DB_PATH
    from gateway.session_context import clear_session_vars, set_session_vars
    import plugin_api as api

    state_db = tmp_path / "state.db"
    import sqlite3
    conn = sqlite3.connect(str(state_db))
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT)")
    conn.execute("INSERT INTO messages (id, session_id, role, content) VALUES (42, 'session-assistant-only', 'assistant', 'AI回复')")
    conn.commit()
    conn.close()

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("agent_tool._STATE_DB_PATH", str(tmp_path))
    try:
        tokens = set_session_vars(
            session_id="session-assistant-only",
            platform="qqbot",
            message_id="",
        )
        try:
            reply = asyncio.run(
                handle_workbench_capture({"action": "task", "content": "不应落盘"})
            )
        finally:
            clear_session_vars(tokens)

        assert "未找到用户消息记录" in reply or "请改用 /wb" in reply
        assert list((wb / "任务").glob("*.md")) == []
    finally:
        monkeypatch.undo()


def test_fallback_identity_newest_row_used_in_multi_turn(wb, tmp_path):
    """S1-007 RED: ordinary QQ/Weixin sessions contain multiple user turns.
    The bridge must bind the NEWEST persisted user row (current turn), not the
    first/oldest row. Current implementation rejects any session with >1 user
    row ("多条用户消息"), so this test must FAIL before the fix.
    """
    from agent_tool import _resolve_state_db_message_id, _STATE_DB_PATH
    state_db = tmp_path / "state.db"
    import sqlite3
    conn = sqlite3.connect(str(state_db))
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT)")
    conn.execute("INSERT INTO messages (id, session_id, role, content) VALUES (10, 'session-multi', 'user', '第一条')")
    conn.execute("INSERT INTO messages (id, session_id, role, content) VALUES (11, 'session-multi', 'user', '第二条')")
    conn.commit()
    conn.close()

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("agent_tool._STATE_DB_PATH", str(tmp_path))
    try:
        opaque = _resolve_state_db_message_id("session-multi")
        # The current turn is the SECOND user turn -> newest row id=11
        assert opaque == "wb-msg:session-multi:11", f"newest row expected, got {opaque}"
    finally:
        monkeypatch.undo()


def test_multi_turn_identities_differ_per_turn(wb, tmp_path):
    """S1-007 RED: two turns in one session receive DIFFERENT internal identities.
    Turn 1 binds row 20; turn 2 (newer row 21) binds a different identity.
    Current implementation fails closed on the second turn (multi-row), so RED.
    """
    from agent_tool import _resolve_state_db_message_id, _STATE_DB_PATH
    state_db = tmp_path / "state.db"
    import sqlite3
    conn = sqlite3.connect(str(state_db))
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT)")
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("agent_tool._STATE_DB_PATH", str(tmp_path))
    try:
        conn.execute("INSERT INTO messages (id, session_id, role, content) VALUES (20, 'session-twoturn', 'user', '回合一')")
        conn.commit()
        id1 = _resolve_state_db_message_id("session-twoturn")
        assert id1 == "wb-msg:session-twoturn:20"
        conn.execute("INSERT INTO messages (id, session_id, role, content) VALUES (21, 'session-twoturn', 'user', '回合二')")
        conn.commit()
        id2 = _resolve_state_db_message_id("session-twoturn")
        assert id2 == "wb-msg:session-twoturn:21"
        assert id1 != id2
    finally:
        conn.close()
        monkeypatch.undo()


def test_fallback_identity_scoped_per_session_concurrent(wb, tmp_path):
    """S1-007 RED: concurrent QQ and Weixin sessions never exchange identities."""
    from agent_tool import _resolve_state_db_message_id, _STATE_DB_PATH
    state_db = tmp_path / "state.db"
    import sqlite3
    conn = sqlite3.connect(str(state_db))
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT)")
    conn.execute("INSERT INTO messages (id, session_id, role, content) VALUES (100, 'session-qq', 'user', 'QQ消息')")
    conn.execute("INSERT INTO messages (id, session_id, role, content) VALUES (101, 'session-wx', 'user', '微信消息')")
    conn.commit()
    conn.close()

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("agent_tool._STATE_DB_PATH", str(tmp_path))
    try:
        qq_id = _resolve_state_db_message_id("session-qq")
        wx_id = _resolve_state_db_message_id("session-wx")
        assert qq_id.endswith(":100")
        assert wx_id.endswith(":101")
        assert qq_id != wx_id
        assert "session-qq" in qq_id and "session-qq" not in wx_id
        # Scoped query: wx session never sees the qq row, and never the reverse
        assert "100" not in wx_id
    finally:
        monkeypatch.undo()



def test_official_message_id_remains_preferred(wb, tmp_path):
    """Red test 6: existing official message ID is preferred over fallback."""
    from agent_tool import handle_workbench_capture, _STATE_DB_PATH
    from conversation_index import ConversationIndex
    from gateway.session_context import clear_session_vars, set_session_vars
    import plugin_api as api

    # Create mock state.db with a user row (should NOT be used)
    state_db = tmp_path / "state.db"
    import sqlite3
    conn = sqlite3.connect(str(state_db))
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT)")
    conn.execute("INSERT INTO messages (id, session_id, role, content) VALUES (7, 'session-official', 'user', '官方消息优先')")
    conn.commit()
    conn.close()

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("agent_tool._STATE_DB_PATH", str(tmp_path))
    try:
        tokens = set_session_vars(
            session_id="session-official",
            platform="qqbot",
            message_id="official-message-id-001",
        )
        try:
            reply = asyncio.run(
                handle_workbench_capture({"action": "task", "content": "官方消息优先测试"})
            )
        finally:
            clear_session_vars(tokens)

        assert reply.startswith("已创建任务 WB-"), f"Official message ID test failed: {reply}"
        indexed = ConversationIndex(api.file_repo.db.db_path).list_conversations()
        new_refs = [r for r in indexed if r["session_id"] == "session-official"]
        assert len(new_refs) == 1
        assert new_refs[0]["resume_mode"] == "original"
    finally:
        monkeypatch.undo()


def test_real_platform_resolution_exposes_workbench_tool_to_qq_and_weixin():
    from agent_tool import register_workbench_tool
    from hermes_cli.tools_config import _get_platform_tools
    from model_tools import _clear_tool_defs_cache, get_tool_definitions
    from tools.registry import registry

    class RegistryContext:
        def register_tool(self, **kwargs):
            registry.register(
                name=kwargs["name"],
                toolset=kwargs["toolset"],
                schema=kwargs["schema"],
                handler=kwargs["handler"],
                is_async=kwargs.get("is_async", False),
                description=kwargs.get("description", ""),
                emoji=kwargs.get("emoji", ""),
                override=kwargs.get("override", False),
            )

    previous = registry.snapshot_registration("workbench_capture")
    register_workbench_tool(RegistryContext())
    current = registry.snapshot_registration("workbench_capture")
    _clear_tool_defs_cache()
    try:
        config = {
            "platform_toolsets": {
                "qqbot": ["hermes-qqbot"],
                "weixin": ["hermes-weixin"],
            }
        }
        for platform in ("qqbot", "weixin"):
            enabled = sorted(_get_platform_tools(config, platform))
            definitions = get_tool_definitions(
                enabled_toolsets=enabled,
                quiet_mode=True,
                skip_tool_search_assembly=True,
            )
            names = {item["function"]["name"] for item in definitions}
            assert "workbench_capture" in names
    finally:
        if current is not None:
            registry.restore_registration(
                "workbench_capture", current, previous
            )
        _clear_tool_defs_cache()


def test_mutation_without_official_message_id_fails_closed(wb, tmp_path):
    from agent_tool import handle_workbench_capture, _STATE_DB_PATH
    from gateway.session_context import clear_session_vars, set_session_vars

    # Create empty mock state.db (no rows for any session)
    import sqlite3
    state_db = tmp_path / "state.db"
    conn = sqlite3.connect(str(state_db))
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT)")
    conn.commit()
    conn.close()

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("agent_tool._STATE_DB_PATH", str(tmp_path))
    try:
        tokens = set_session_vars(
            session_id="session-a",
            platform="qqbot",
            message_id="",
        )
        try:
            reply = asyncio.run(
                handle_workbench_capture({"action": "task", "content": "不会落盘"})
            )
        finally:
            clear_session_vars(tokens)

        assert "未找到用户消息记录" in reply or "请改用 /wb" in reply
        assert list((wb / "任务").glob("*.md")) == []
    finally:
        monkeypatch.undo()


def test_mutation_without_original_session_id_fails_closed(wb):
    from agent_tool import handle_workbench_capture
    from gateway.session_context import clear_session_vars, set_session_vars

    tokens = set_session_vars(
        session_id="",
        platform="weixin",
        message_id="message-without-session",
    )
    try:
        reply = asyncio.run(
            handle_workbench_capture({"action": "task", "content": "不会降级收录"})
        )
    finally:
        clear_session_vars(tokens)

    assert reply == "未执行：当前消息尚未建立可续接的 Hermes 原会话，请改用 /wb 命令。"
    assert list((wb / "任务").glob("*.md")) == []


def test_authorized_tool_creates_original_conversation_ref(wb):
    from agent_tool import handle_workbench_capture
    from conversation_index import ConversationIndex
    from gateway.session_context import clear_session_vars, set_session_vars
    import plugin_api as api

    tokens = set_session_vars(
        session_id="session-original",
        platform="weixin",
        message_id="message-original",
    )
    try:
        reply = asyncio.run(
            handle_workbench_capture({"action": "task", "content": "授权后原会话"})
        )
    finally:
        clear_session_vars(tokens)

    assert reply.startswith("已创建任务 WB-")
    indexed = ConversationIndex(api.file_repo.db.db_path).list_conversations()
    assert len(indexed) == 1
    assert indexed[0]["platform"] == "weixin"
    assert indexed[0]["session_id"] == "session-original"
    assert indexed[0]["resume_mode"] == "original"
    with sqlite3.connect(api.file_repo.db.db_path) as conn:
        event_payloads = [
            row[0]
            for row in conn.execute(
                "SELECT payload FROM task_events WHERE payload IS NOT NULL"
            ).fetchall()
        ]
    assert all("授权后原会话" not in payload for payload in event_payloads)
    action_log = (wb / "日志" / "操作日志.md")
    if action_log.exists():
        assert "授权后原会话" not in action_log.read_text(encoding="utf-8")


def test_index_failure_is_repaired_by_same_message_retry(wb, monkeypatch):
    from agent_tool import handle_workbench_capture
    from conversation_index import ConversationIndex
    from gateway.session_context import clear_session_vars, set_session_vars
    import plugin_api as api

    real_upsert = ConversationIndex.upsert_authorized
    calls = 0

    def fail_once(self, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated index outage")
        return real_upsert(self, **kwargs)

    monkeypatch.setattr(ConversationIndex, "upsert_authorized", fail_once)
    tokens = set_session_vars(
        session_id="session-retry",
        platform="weixin",
        message_id="message-retry",
    )
    try:
        with pytest.raises(RuntimeError, match="simulated index outage"):
            asyncio.run(
                handle_workbench_capture({"action": "task", "content": "索引补偿任务"})
            )
        reply = asyncio.run(
            handle_workbench_capture({"action": "task", "content": "索引补偿任务"})
        )
    finally:
        clear_session_vars(tokens)

    assert reply == "该命令已经处理。"
    assert len(list((wb / "任务").glob("*.md"))) == 1
    indexed = ConversationIndex(api.file_repo.db.db_path).list_conversations()
    assert len(indexed) == 1
    assert indexed[0]["session_id"] == "session-retry"
    assert indexed[0]["resume_mode"] == "original"


def test_continue_keeps_added_content_out_of_event_payloads(wb):
    from agent_tool import handle_workbench_capture
    from gateway.session_context import clear_session_vars, set_session_vars
    import plugin_api as api

    create_tokens = set_session_vars(
        session_id="session-create",
        platform="weixin",
        message_id="message-create-private",
    )
    try:
        created = asyncio.run(
            handle_workbench_capture({"action": "task", "content": "隐私续接母任务"})
        )
    finally:
        clear_session_vars(create_tokens)
    task_id = created.split("：", 1)[0].removeprefix("已创建任务 ")

    append_tokens = set_session_vars(
        session_id="session-append",
        platform="qqbot",
        message_id="message-append-private",
    )
    try:
        reply = asyncio.run(
            handle_workbench_capture(
                {"action": "continue", "task_ref": task_id, "content": "不可进入事件日志的补充正文"}
            )
        )
    finally:
        clear_session_vars(append_tokens)

    assert reply.startswith(f"已续接 {task_id}")
    with sqlite3.connect(api.file_repo.db.db_path) as conn:
        payloads = [
            row[0]
            for row in conn.execute(
                "SELECT payload FROM task_events WHERE payload IS NOT NULL"
            ).fetchall()
        ]
    assert all("不可进入事件日志的补充正文" not in payload for payload in payloads)


def test_concurrent_agent_turns_do_not_exchange_session_identity(wb):
    from agent_tool import handle_workbench_capture
    from conversation_index import ConversationIndex
    from gateway.session_context import clear_session_vars, set_session_vars
    import plugin_api as api

    async def capture(platform, message_id, session_id, content, delay):
        tokens = set_session_vars(
            session_id=session_id,
            platform=platform,
            message_id=message_id,
        )
        try:
            await asyncio.sleep(delay)
            return await handle_workbench_capture({"action": "task", "content": content})
        finally:
            clear_session_vars(tokens)

    async def run():
        return await asyncio.gather(
            capture("qqbot", "message-a", "session-a", "并发任务甲", 0.03),
            capture("weixin", "message-b", "session-b", "并发任务乙", 0.0),
        )

    replies = asyncio.run(run())

    assert all(reply.startswith("已创建任务 WB-") for reply in replies)
    indexed = ConversationIndex(api.file_repo.db.db_path).list_conversations()
    assert {(item["platform"], item["session_id"]) for item in indexed} == {
        ("qq", "session-a"),
        ("weixin", "session-b"),
    }
    assert all(item["resume_mode"] == "original" for item in indexed)
