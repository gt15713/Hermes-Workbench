# -*- coding: utf-8 -*-
"""A2 一期 storage_mode 测试：配置校验 / getter / 安全网 / DualRepo 写分叉（2026-08-23）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pytest  # noqa: E402

import workbench_config as wc  # noqa: E402
from repo import DualRepo, FileRepo, SqliteRepo  # noqa: E402


@pytest.fixture()
def dual(tmp_path):
    for d in ("待验证", "待回看", "任务", "已处理", "回收站"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    return DualRepo(FileRepo(root=tmp_path), SqliteRepo(root=tmp_path)), tmp_path


class TestStorageModeConfig:
    def test_default_is_dual(self, monkeypatch, tmp_path):
        monkeypatch.setenv("WORKBENCH_CONFIG", str(tmp_path / "nope.json"))
        assert wc.get_storage_mode() == "dual"

    def test_normalize_valid_modes(self, monkeypatch, tmp_path):
        monkeypatch.setenv("WORKBENCH_CONFIG", str(tmp_path / "cfg.json"))
        for mode in ("dual", "db_only", "file_only"):
            base = wc.default_config()
            base["storage_mode"] = mode
            assert wc.normalize_config(base)["storage_mode"] == mode

    def test_normalize_invalid_mode_raises(self, monkeypatch, tmp_path):
        monkeypatch.setenv("WORKBENCH_CONFIG", str(tmp_path / "cfg.json"))
        base = wc.default_config()
        base["storage_mode"] = "bogus"
        with pytest.raises(ValueError, match="storage_mode"):
            wc.normalize_config(base)

    def test_env_override(self, monkeypatch, tmp_path):
        monkeypatch.setenv("WORKBENCH_STORAGE_MODE", "db_only")
        assert wc.get_storage_mode() == "db_only"

    def test_safety_net_root_content_forces_dual(self, monkeypatch, tmp_path):
        """无配置 + root 已有 .md + 期望 db_only → 强制回退 dual（防半成品）。"""
        monkeypatch.setenv("WORKBENCH_CONFIG", str(tmp_path / "none.json"))
        monkeypatch.delenv("WORKBENCH_STORAGE_MODE", raising=False)
        root = tmp_path / "wb"
        (root / "待验证").mkdir(parents=True, exist_ok=True)
        (root / "待验证" / "a.md").write_text("# a\n", encoding="utf-8")
        monkeypatch.setenv("WORKBENCH_ROOT", str(root))
        # 模拟「默认已翻 db_only」的未来场景：默认被改时安全网仍生效
        monkeypatch.setattr(wc, "DEFAULT_STORAGE_MODE", "db_only")
        assert wc.get_storage_mode() == "dual"


class TestDualRepoWriteFork:
    def test_dual_writes_both(self, dual, monkeypatch):
        repo, root = dual
        monkeypatch.setattr(wc, "get_storage_mode", lambda: "dual")
        p = root / "任务" / "t.md"
        repo.write_text(p, "---\nstatus: todo\n---\n# t\n")
        assert p.exists()
        assert repo.db.get_status("任务", "t.md") == "todo"

    def test_db_only_writes_db_not_file(self, dual, monkeypatch):
        repo, root = dual
        monkeypatch.setattr(wc, "get_storage_mode", lambda: "db_only")
        p = root / "任务" / "t.md"
        repo.write_text(p, "---\nstatus: todo\n---\n# t\n")
        assert not p.exists()  # 文件不落盘
        assert repo.db.get_status("任务", "t.md") == "todo"  # DB 有记录

    def test_file_only_writes_file_not_db(self, dual, monkeypatch):
        repo, root = dual
        monkeypatch.setattr(wc, "get_storage_mode", lambda: "file_only")
        p = root / "任务" / "t.md"
        repo.write_text(p, "---\nstatus: todo\n---\n# t\n")
        assert p.exists()
        assert repo.db.get_status("任务", "t.md") == ""  # DB 无记录

    def test_db_only_delete_skips_file(self, dual, monkeypatch):
        repo, root = dual
        monkeypatch.setattr(wc, "get_storage_mode", lambda: "dual")
        p = root / "任务" / "t.md"
        repo.write_text(p, "---\nstatus: todo\n---\n# t\n")
        assert p.exists()
        monkeypatch.setattr(wc, "get_storage_mode", lambda: "db_only")
        repo.delete(p)
        assert p.exists()  # db_only 不删文件实体
        assert repo.db.get_status("任务", "t.md") == ""
