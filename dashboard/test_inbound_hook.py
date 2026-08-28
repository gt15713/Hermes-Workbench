# -*- coding: utf-8 -*-
"""入站平台强制登记测试（P2，2026-08-22）。

覆盖：should_auto_register / auto_register_dir / build_ingest_body 纯函数 +
      hook 回调对非 QQ 平台忽略。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from types import SimpleNamespace  # noqa: E402

import wb_utils  # noqa: E402
from inbound_hook import (  # noqa: E402
    _event_type_from_event,
    _on_pre_gateway_dispatch,
    build_ingest_body,
)


class TestShouldAutoRegister:
    def test_no_link_research_question_registers(self):
        assert wb_utils.should_auto_register("Workbench 是否还值得做") is True

    def test_short_chat_skipped(self):
        assert wb_utils.should_auto_register("最近怎么样") is False
        assert wb_utils.should_auto_register("早上好") is False

    def test_link_registers(self):
        assert wb_utils.should_auto_register("【视频】 https://b23.tv/abc") is True

    def test_negation_skips(self):
        assert wb_utils.should_auto_register("不要收录这个") is False


class TestAutoRegisterDir:
    def test_research_to_task(self):
        assert wb_utils.auto_register_dir("Workbench 是否还值得做") == "任务"

    def test_link_with_research_to_task(self):
        assert wb_utils.auto_register_dir("https://b23.tv/abc 调研下项目") == "任务"

    def test_bare_link_to_staging(self):
        assert wb_utils.auto_register_dir("【视频】 https://b23.tv/abc") == "待回看"

    def test_ingest_word_to_task(self):
        assert wb_utils.auto_register_dir("整理进笔记：xxx") == "任务"


class TestBuildIngestBody:
    def test_official_message_id_takes_precedence_over_content_fingerprint(self):
        first = build_ingest_body("Workbench 是否还值得做", "official-1001")
        second = build_ingest_body("Workbench 是否还值得做", "official-1002")

        assert first is not None
        assert second is not None
        assert first["message_id"] == "qqbot:official-1001"
        assert second["message_id"] == "qqbot:official-1002"

    def test_message_id_uses_title_fingerprint(self):
        body = build_ingest_body("Workbench 是否还值得做")
        assert body is not None
        assert body["message_id"] == "Workbench 是否还值得做"
        assert body["dir"] == "任务"

    def test_message_id_uses_url_fingerprint(self):
        body = build_ingest_body("【视频】 https://b23.tv/abc")
        assert body is not None
        assert body["message_id"] == "b23.tv/abc"
        assert body["dir"] == "待回看"

    def test_chat_returns_none(self):
        assert build_ingest_body("早上好") is None

    def test_command_prefix_returns_none(self):
        assert build_ingest_body("/complete 测试任务") is None


class TestHookPlatformFilter:
    def test_hook_captures_existing_source_session_id(self, monkeypatch):
        import inbound_hook

        captured = {}
        event = SimpleNamespace(
            text="/wb 任务 原会话",
            message_id="official-session-1",
            raw_message={},
            source=SimpleNamespace(platform=SimpleNamespace(value="qqbot")),
        )
        gateway = SimpleNamespace(
            _session_key_for_source=lambda source: "agent:main:qqbot:dm:redacted"
        )
        session_store = SimpleNamespace(
            peek_session_id=lambda key: (
                "real-hermes-session"
                if key == "agent:main:qqbot:dm:redacted"
                else None
            )
        )
        monkeypatch.setattr(
            inbound_hook,
            "remember_inbound_command",
            lambda *args, **kwargs: captured.update(args=args, kwargs=kwargs),
            raising=False,
        )

        assert _on_pre_gateway_dispatch(
            event=event, gateway=gateway, session_store=session_store
        ) is None
        assert captured["kwargs"]["session_id"] == "real-hermes-session"

    def test_event_type_uses_only_known_qq_event_names(self):
        valid = SimpleNamespace(raw_message={"event_type": "GROUP_MESSAGE_CREATE"})
        invalid = SimpleNamespace(raw_message={"event_type": "secret message body"})

        assert _event_type_from_event(valid) == "GROUP_MESSAGE_CREATE"
        assert _event_type_from_event(invalid) == "UNKNOWN"

    def test_non_qq_platform_ignored(self):
        event = SimpleNamespace(
            text="Workbench 是否还值得做",
            source=SimpleNamespace(platform=SimpleNamespace(value="telegram")),
        )
        assert _on_pre_gateway_dispatch(event=event) is None

    def test_qq_pre_auth_hook_never_builds_or_persists_task(self, monkeypatch):
        import inbound_hook

        event = SimpleNamespace(
            text="调研并归档这条未授权消息",
            message_id="official-1",
            raw_message={},
            source=SimpleNamespace(platform=SimpleNamespace(value="qqbot")),
        )
        monkeypatch.setattr(
            inbound_hook,
            "build_ingest_body",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("pre-auth write")),
        )

        assert _on_pre_gateway_dispatch(event=event) is None

    def test_session_lookup_degrades_to_summary_when_gateway_or_store_missing(self, monkeypatch):
        """WB-S1-012 A3 契约 3：gateway/session_store 缺失时 session_id 回落空串 → resume_mode=summary。

        不抛异常、不阻断 hook；后续 upsert 会因空 session_id 走摘要续接（fail-closed）。
        """
        import inbound_hook

        captured = {}
        event = SimpleNamespace(
            text="/wb 任务 原会话",
            message_id="official-degrade-1",
            raw_message={},
            source=SimpleNamespace(platform=SimpleNamespace(value="qqbot")),
        )
        monkeypatch.setattr(
            inbound_hook,
            "remember_inbound_command",
            lambda *args, **kwargs: captured.update(args=args, kwargs=kwargs),
            raising=False,
        )

        # gateway 缺失 / session_store 缺失 / peek_session_id 不可调用 → 全部回落空串
        assert inbound_hook._existing_session_id(event, None, None) == ""
        assert inbound_hook._existing_session_id(event, object(), None) == ""
        gateway = SimpleNamespace(_session_key_for_source=lambda source: "agent:main:qqbot:dm:x")
        store_no_peek = SimpleNamespace()
        assert inbound_hook._existing_session_id(event, gateway, store_no_peek) == ""

        # 完整链路仍能记录（空 session_id 不阻断）
        assert _on_pre_gateway_dispatch(event=event, gateway=None, session_store=None) is None
        assert captured["kwargs"]["session_id"] == ""

    def test_different_dm_accounts_keep_separate_ref_identity(self, tmp_path):
        """WB-S1-012 A3 契约 5：QQ 私聊两个不同账号不凭弱信息串会话。

        ref_id 由 (platform, official message_id) 派生——不同账号的官方消息 ID 不同 →
        各自独立 conversation_refs；仅 task_id 相同的任务共享 task 身份，不共享会话身份。
        """
        from conversation_index import ConversationIndex

        index = ConversationIndex(tmp_path / "index.db")
        index.upsert_authorized(
            platform="qqbot", message_id="acct-a-msg-1", summary="A 的任务",
            task_id="WB-AAAA1111", status="active", session_id="sess-acct-a",
        )
        index.upsert_authorized(
            platform="qqbot", message_id="acct-b-msg-1", summary="B 的任务",
            task_id="WB-BBBB2222", status="active", session_id="sess-acct-b",
        )

        rows = index.list_conversations()
        assert len(rows) == 2
        assert {r["session_id"] for r in rows} == {"sess-acct-a", "sess-acct-b"}
        assert {r["ref_id"] for r in rows} != {"", None}
        assert len({r["ref_id"] for r in rows}) == 2
        # 不同账号 → resume_mode 各自 original（有各自稳定 session_id），互不覆盖
        assert {r["resume_mode"] for r in rows} == {"original"}

    def test_qq_group_and_c2c_do_not_collide_ref_identity(self, tmp_path):
        """WB-S1-012 A3 契约 6：QQ 群会话与 C2C 私聊不得用错误 session key。

        Workbench 侧：ref 身份按官方 message_id 隔离（群/私聊消息 ID 域不同）；
        会话 key 归属 Hermes core build_session_key（chat_type=dm vs group 分离），
        Workbench 不自行拼接——此处验证索引层不互相覆盖。
        """
        from conversation_index import ConversationIndex

        index = ConversationIndex(tmp_path / "index.db")
        index.upsert_authorized(
            platform="qqbot", message_id="group-msg-9", summary="群里 @ 的任务",
            task_id="WB-CCCC3333", status="active", session_id="sess-group",
        )
        index.upsert_authorized(
            platform="qqbot", message_id="c2c-msg-9", summary="私聊的任务",
            task_id="WB-DDDD4444", status="active", session_id="sess-c2c",
        )

        rows = index.list_conversations()
        assert len(rows) == 2
        assert {r["session_id"] for r in rows} == {"sess-group", "sess-c2c"}
        assert len({r["ref_id"] for r in rows}) == 2
