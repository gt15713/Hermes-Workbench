# -*- coding: utf-8 -*-
"""镜像 status 自愈测试（2026-08-23）：agent 直接写库导致的 status 空漂移 → 读板 sync 自愈。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pytest  # noqa: E402

from repo import DualRepo, FileRepo, SqliteRepo  # noqa: E402


@pytest.fixture()
def dual(tmp_path):
    for d in ("待验证", "待回看", "任务", "心理学随想", "梦中的邮件", "已处理", "回收站"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    repo = DualRepo(FileRepo(root=tmp_path), SqliteRepo(root=tmp_path))
    return repo, tmp_path


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


class TestStatusRepair:
    def test_empty_status_repaired_on_sync(self, dual):
        repo, root = dual
        p = root / "已处理" / "t.md"
        text = "---\nstatus: completed\n---\n# t\n"
        _write(p, text)
        # 模拟 agent 直接写库：status 空、mtime 与文件一致（sync 原本会按「一致」跳过）
        repo.db._upsert("已处理", "t.md", p.stat().st_mtime, text, "")
        assert repo.db.get_status("已处理", "t.md") == ""

        r = repo.sync_from_files()
        assert r["repaired"] == 1
        assert repo.db.get_status("已处理", "t.md") == "completed"

        # 幂等：再次同步不重复修复
        r2 = repo.sync_from_files()
        assert r2["repaired"] == 0
        assert repo.db.get_status("已处理", "t.md") == "completed"

    def test_normal_status_not_touched(self, dual):
        repo, root = dual
        p = root / "任务" / "t.md"
        text = "---\nstatus: todo\n---\n# t\n"
        _write(p, text)
        repo.db._upsert("任务", "t.md", p.stat().st_mtime, text, "todo")
        r = repo.sync_from_files()
        assert r["repaired"] == 0
        assert repo.db.get_status("任务", "t.md") == "todo"

    def test_no_status_in_file_stays_empty(self, dual):
        repo, root = dual
        p = root / "待验证" / "t.md"
        text = "# 无状态条目\n"
        _write(p, text)
        repo.db._upsert("待验证", "t.md", p.stat().st_mtime, text, "")
        r = repo.sync_from_files()
        assert r["repaired"] == 0
        assert repo.db.get_status("待验证", "t.md") == ""
