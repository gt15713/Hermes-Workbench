# -*- coding: utf-8 -*-
"""设置端点测试（/settings GET/POST）：读取 / 保存 / 分区保护（2026-08-22）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pytest  # noqa: E402


@pytest.fixture()
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKBENCH_CONFIG", str(tmp_path / "workbench-config.json"))
    root = tmp_path / "wb"
    for d in ("待验证", "待回看", "任务", "心理学随想", "梦中的邮件", "已处理", "回收站"):
        (root / d).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("WORKBENCH_ROOT", str(root))
    import plugin_api  # noqa: F401
    import workbench_config as wc

    wc.CONFIG_FILE = tmp_path / "workbench-config.json"
    return root


class TestGetSettings:
    def test_returns_defaults(self, isolated):
        from plugin_api import get_settings

        r = get_settings()
        assert r["ok"] is True
        assert len(r["config"]["partitions"]) == 5
        assert r["config"]["scheduler"]["daily_report"]["time"] == "20:00"
        assert r["config"]["scheduler"]["nudge"]["time"] == "12:15"
        assert r["effective"]["root"] == str(isolated)
        assert r["restart_required"] == ["root", "vault"]


class TestUpdateSettings:
    def test_add_partition_creates_dir(self, isolated):
        from plugin_api import get_settings, update_settings

        base = get_settings()["config"]
        base["partitions"].append({"name": "读书笔记", "type": "thought", "fixed": False})
        r = update_settings(base)
        assert r["ok"] is True
        assert "读书笔记" in r["created_partitions"]
        assert (isolated / "读书笔记").is_dir()
        assert any(p["name"] == "读书笔记" for p in get_settings()["config"]["partitions"])

    def test_remove_non_empty_partition_blocked(self, isolated):
        from plugin_api import get_settings, update_settings

        # P0-B：待验证已是固定分区，非空阻断须用自定义（非固定）分区验证
        base = get_settings()["config"]
        base["partitions"].append({"name": "读书笔记", "type": "thought", "fixed": False})
        assert update_settings(base)["ok"] is True
        (isolated / "读书笔记" / "a.md").write_text("# a\n", encoding="utf-8")
        base2 = get_settings()["config"]
        base2["partitions"] = [p for p in base2["partitions"] if p["name"] != "读书笔记"]
        r = update_settings(base2)
        assert r["ok"] is False
        assert "非空" in r["error"]

    def test_remove_fixed_partition_blocked(self, isolated):
        from plugin_api import get_settings, update_settings

        base = get_settings()["config"]
        base["partitions"] = [p for p in base["partitions"] if p["name"] != "任务"]
        r = update_settings(base)
        assert r["ok"] is False

    def test_change_daily_report_time(self, isolated):
        from plugin_api import get_settings, update_settings

        base = get_settings()["config"]
        base["scheduler"]["daily_report"]["time"] = "21:30"
        r = update_settings(base)
        assert r["ok"] is True
        assert get_settings()["config"]["scheduler"]["daily_report"]["time"] == "21:30"
