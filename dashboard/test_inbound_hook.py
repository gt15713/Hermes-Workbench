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
from inbound_hook import build_ingest_body, _on_pre_gateway_dispatch  # noqa: E402


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
    def test_non_qq_platform_ignored(self):
        event = SimpleNamespace(
            text="Workbench 是否还值得做",
            source=SimpleNamespace(platform=SimpleNamespace(value="telegram")),
        )
        assert _on_pre_gateway_dispatch(event=event) is None
