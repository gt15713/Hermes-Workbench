# -*- coding: utf-8 -*-
"""workbench_config 测试：默认值 / 读写 / 校验 / 时间换算 / 分区辅助（2026-08-22 设置面板）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pytest  # noqa: E402
import workbench_config as wc  # noqa: E402


@pytest.fixture()
def isolated(monkeypatch, tmp_path):
    """隔离配置 + 工作台根（不碰真实配置/数据）。"""
    cfg = tmp_path / "workbench-config.json"
    monkeypatch.setenv("WORKBENCH_CONFIG", str(cfg))
    # env 在模块 import 后改不影响 CONFIG_FILE，须直接指路径（GT「config 保存路径」疑点根因）
    wc.CONFIG_FILE = cfg
    monkeypatch.delenv("WORKBENCH_ROOT", raising=False)
    monkeypatch.delenv("OBSIDIAN_VAULT", raising=False)
    monkeypatch.delenv("WORKBENCH_DELIVER_TARGET", raising=False)
    root = tmp_path / "wb"
    for d in ("待验证", "待回看", "任务", "心理学随想", "梦中的邮件", "已处理", "回收站"):
        (root / d).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("WORKBENCH_ROOT", str(root))
    return cfg, root


class TestDefaults:
    def test_missing_file_falls_back(self, isolated):
        assert not isolated[0].exists()
        cfg = wc.load_config()
        assert cfg["root"] == wc.DEFAULT_ROOT
        assert len(cfg["partitions"]) == 5

    def test_fixed_partitions_present(self, isolated):
        names = wc.get_partition_names()
        assert {"待验证", "待回看", "任务", "已处理", "回收站"} <= names
        assert len(names) == 5


class TestTimeConversion:
    def test_expr_to_time(self):
        assert wc.expr_to_time("0 20 * * *") == "20:00"
        assert wc.expr_to_time("15 12 * * *") == "12:15"
        assert wc.expr_to_time("30 12 * * *") == "12:30"

    def test_time_to_expr(self):
        assert wc.time_to_expr("20:00") == "0 20 * * *"
        assert wc.time_to_expr("12:15") == "15 12 * * *"
        assert wc.time_to_expr("9:05") == "5 9 * * *"

    def test_invalid_time_raises(self):
        with pytest.raises(ValueError):
            wc.time_to_expr("25:00")
        with pytest.raises(ValueError):
            wc.time_to_expr("12:60")
        with pytest.raises(ValueError):
            wc.time_to_expr("abc")


class TestNormalize:
    def test_custom_partition_and_time(self, isolated):
        base = wc.default_config()
        base["partitions"].append({"name": "读书笔记", "type": "thought", "fixed": False})
        base["scheduler"]["daily_report"] = {"enabled": True, "time": "21:30"}
        n = wc.normalize_config(base)
        assert n["scheduler"]["daily_report"]["expr"] == "30 21 * * *"
        assert any(p["name"] == "读书笔记" for p in n["partitions"])

    def test_fixed_partition_cannot_be_removed(self, isolated):
        base = wc.default_config()
        base["partitions"] = [p for p in base["partitions"] if p["name"] != "任务"]
        with pytest.raises(ValueError, match="固定分区"):
            wc.normalize_config(base)

    def test_legacy_7_partition_config_upgrades(self, isolated):
        """旧 7 分区配置（心理/梦邮 fixed:false、待验证 fixed:false）→ 升级兼容：
        5 固定强制 fixed，心理/梦邮保留为可删用户分区。"""
        base = wc.default_config()
        legacy = [
            {"name": "待验证", "type": "thought", "fixed": False},
            {"name": "待回看", "type": "video", "fixed": True},
            {"name": "任务", "type": "task", "fixed": True},
            {"name": "心理学随想", "type": "psych", "fixed": False},
            {"name": "梦中的邮件", "type": "dream", "fixed": False},
            {"name": "已处理", "type": "done", "fixed": True},
            {"name": "回收站", "type": "trash", "fixed": True},
        ]
        base["partitions"] = legacy
        n = wc.normalize_config(base)
        by_name = {p["name"]: p for p in n["partitions"]}
        assert by_name["待验证"]["fixed"] is True  # 旧标记被强制升级
        assert by_name["心理学随想"]["fixed"] is False  # 用户分区保留可删
        assert len(n["partitions"]) == 7

    def test_empty_vault_and_deliver_allowed(self, isolated):
        base = wc.default_config()
        base["vault"] = ""
        base["deliver_target"] = ""
        n = wc.normalize_config(base)
        assert n["vault"] == ""
        assert n["deliver_target"] == ""

    def test_invalid_partition_name(self, isolated):
        base = wc.default_config()
        base["partitions"].append({"name": "a/b", "type": "thought", "fixed": False})
        with pytest.raises(ValueError, match="非法字符"):
            wc.normalize_config(base)

    def test_duplicate_partition_name(self, isolated):
        base = wc.default_config()
        base["partitions"].append({"name": "任务", "type": "task", "fixed": False})
        with pytest.raises(ValueError, match="重复"):
            wc.normalize_config(base)

    def test_invalid_type(self, isolated):
        base = wc.default_config()
        base["partitions"].append({"name": "x", "type": "bogus", "fixed": False})
        with pytest.raises(ValueError, match="类型非法"):
            wc.normalize_config(base)

    def test_ttl_bounds(self, isolated):
        base = wc.default_config()
        base["ttl"]["days"] = 999
        with pytest.raises(ValueError, match="1-365"):
            wc.normalize_config(base)


class TestRoundTrip:
    def test_save_load(self, isolated):
        cfg, _root = isolated
        base = wc.default_config()
        base["partitions"].append({"name": "读书笔记", "type": "thought", "fixed": False})
        base["deliver_target"] = "qqbot:test"
        base["ttl"]["days"] = 14
        wc.save_config(base)
        loaded = wc.load_config()
        assert loaded["ttl"]["days"] == 14
        assert any(p["name"] == "读书笔记" for p in loaded["partitions"])
        assert loaded["deliver_target"] == "qqbot:test"
        assert cfg.exists()

    def test_corrupt_file_falls_back(self, isolated):
        cfg, _root = isolated
        cfg.write_text("{broken", encoding="utf-8")
        assert wc.load_config()["root"] == wc.DEFAULT_ROOT


class TestPartitionHelpers:
    def test_counts(self, isolated):
        _cfg, root = isolated
        (root / "任务" / "t.md").write_text("---\nstatus: todo\n---\n# t\n", encoding="utf-8")
        counts = wc.partition_counts(root)
        assert counts["任务"] == 1
        assert counts["待验证"] == 0

    def test_ensure_dirs(self, isolated):
        _cfg, root = isolated
        base = wc.default_config()
        base["partitions"].append({"name": "读书笔记", "type": "thought", "fixed": False})
        created = wc.ensure_partition_dirs(root, base["partitions"])
        assert "读书笔记" in created
        assert (root / "读书笔记").is_dir()
