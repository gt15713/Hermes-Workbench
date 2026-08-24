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
