import asyncio

import pytest
from messaging_command import (
    _invocation_id,
    register_workbench_command,
    remember_inbound_command,
)


@pytest.fixture()
def wb(tmp_path, monkeypatch):
    import plugin_api as api
    import repo as repo_mod
    import wb_utils as wb_utils_mod

    for dirname in ("待验证", "待回看", "任务", "心理学随想", "梦中的邮件", "已处理", "回收站", "日志"):
        (tmp_path / dirname).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(api, "WORKBENCH_ROOT", tmp_path)
    monkeypatch.setattr(wb_utils_mod, "WORKBENCH_ROOT", tmp_path)
    monkeypatch.setattr(wb_utils_mod, "LOG_DIR", tmp_path / "日志")
    monkeypatch.setattr(repo_mod, "WORKBENCH_ROOT", tmp_path)
    monkeypatch.setattr(api.file_repo, "root", tmp_path)
    api.file_repo.db = repo_mod.SqliteRepo(tmp_path / "test-workbench.db", root=tmp_path)
    api.file_repo.read_from_db = False
    return tmp_path


class CommandContext:
    def __init__(self):
        self.commands = {}

    def register_command(self, name, handler, description="", args_hint=""):
        self.commands[name] = {
            "handler": handler,
            "description": description,
            "args_hint": args_hint,
        }


def test_registered_wb_command_does_not_permanently_dedupe_identical_text(wb):
    ctx = CommandContext()
    register_workbench_command(ctx)

    assert set(ctx.commands) == {"wb"}
    handler = ctx.commands["wb"]["handler"]
    first = asyncio.run(handler("任务 从微信私聊整理发布计划"))
    replay = asyncio.run(handler("任务 从微信私聊整理发布计划"))

    assert first.startswith("已创建任务 WB-")
    assert replay.startswith("未执行：task already exists")
    assert len(list((wb / "任务").glob("*.md"))) == 1

    import plugin_api as api
    from conversation_index import ConversationIndex

    indexed = ConversationIndex(api.file_repo.db.db_path).list_conversations()
    assert len(indexed) == 1
    assert indexed[0]["summary"] == "从微信私聊整理发布计划"
    assert indexed[0]["resume_mode"] == "summary"


def test_registered_wb_command_returns_plain_help(wb):
    ctx = CommandContext()
    register_workbench_command(ctx)

    reply = asyncio.run(ctx.commands["wb"]["handler"]("帮助"))

    assert "/wb 任务" in reply
    assert "/wb 继续" in reply


def test_invocation_id_is_unique_when_gateway_exposes_no_message_identity():
    assert _invocation_id() != _invocation_id()


def test_official_inbound_identity_makes_gateway_redelivery_idempotent(wb):
    ctx = CommandContext()
    register_workbench_command(ctx)
    handler = ctx.commands["wb"]["handler"]

    for _ in range(2):
        remember_inbound_command(
            "/wb 待验证 官方消息重投", "official-redelivery-1", "weixin"
        )
        asyncio.run(handler("待验证 官方消息重投"))

    aggregate = next((wb / "待验证").glob("*.md"))
    assert aggregate.read_text(encoding="utf-8").count("## 官方消息重投") == 1


def test_cross_platform_append_indexes_the_second_authorized_conversation(wb):
    ctx = CommandContext()
    register_workbench_command(ctx)
    handler = ctx.commands["wb"]["handler"]

    create_args = "任务 跨平台续接"
    remember_inbound_command(f"/wb {create_args}", "qq-create-1", "qq")
    create_reply = asyncio.run(handler(create_args))
    task_id = create_reply.split("：", 1)[0].removeprefix("已创建任务 ")

    append_args = f"继续 {task_id} 来自微信"
    remember_inbound_command(f"/wb {append_args}", "weixin-append-1", "weixin")
    append_reply = asyncio.run(handler(append_args))

    assert append_reply == f"已续接 {task_id}：来自微信"
    assert len(list((wb / "任务").glob("*.md"))) == 1

    import plugin_api as api
    from conversation_index import ConversationIndex

    indexed = ConversationIndex(api.file_repo.db.db_path).list_conversations()
    assert {(item["platform"], item["task_id"]) for item in indexed} == {
        ("qq", task_id),
        ("weixin", task_id),
    }
    assert {item["summary"] for item in indexed} == {"跨平台续接"}


def test_pre_auth_identity_cache_is_globally_bounded():
    import messaging_command

    for index in range(messaging_command._PENDING_MAX_KEYS + 20):
        remember_inbound_command(f"/wb 帮助 {index}", f"message-{index}", "qqbot")

    assert len(messaging_command._PENDING_IDS) <= messaging_command._PENDING_MAX_KEYS
