# -*- coding: utf-8 -*-
"""P0-3（B2）：读时懒同步 sync_from_files 测试。

覆盖（TD §12）：外部编辑同步 / 增量跳过一致文件 / 解析失败保留旧镜像 / 孤儿行清除。
"""

from pathlib import Path

import pytest
from contract import PARTITION_NAMES
from repo import DualRepo, FileRepo, SqliteRepo


@pytest.fixture()
def dual(tmp_path):
    for d in PARTITION_NAMES:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    return DualRepo(
        FileRepo(root=tmp_path),
        SqliteRepo(tmp_path / "wb.db", root=tmp_path),
        read_from_db=True,
    )


def _write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_sync_reingests_external_edit(dual, tmp_path):
    """外部（Obsidian）直接改文件 → sync 后镜像刷新（mtime/status）。"""
    p = tmp_path / "任务" / "外部编辑.md"
    _write(p, "---\ntype: task\nstatus: todo\n---\n\n# 外部编辑\n")
    # 首次经 repo 写入 → 镜像已有（mtime 一致）
    dual.write_text(p, "---\ntype: task\nstatus: todo\n---\n\n# 外部编辑\n")
    # 模拟外部直接改文件（不经 repo）→ status 变 completed
    _write(p, "---\ntype: task\nstatus: completed\n---\n\n# 外部编辑\n\n已完成\n")
    res = dual.sync_from_files()
    assert res["reingested"] == 1
    mtime = dual.db.get_mirror_mtime("任务", "外部编辑.md")
    assert mtime is not None and abs(mtime - p.stat().st_mtime) < 1e-6


def test_sync_incremental_skips_unchanged(dual, tmp_path):
    """增量：write_text 已镜像一致 → 零重摄；外部改一个 → 只重摄那个。"""
    p = tmp_path / "任务" / "稳定卡.md"
    dual.write_text(p, "---\ntype: task\nstatus: todo\n---\n\n# 稳定卡\n")
    first = dual.sync_from_files()
    assert first["reingested"] == 0  # write_text 已双写镜像 → 一致零重摄
    _write(p, "---\ntype: task\nstatus: todo\n---\n\n# 稳定卡\n\n外部追加\n")
    second = dual.sync_from_files()
    assert second["reingested"] == 1  # 只重摄外部改的那个
    third = dual.sync_from_files()
    assert third["reingested"] == 0  # 再次一致


def test_sync_parse_failure_keeps_mirror(dual, tmp_path, monkeypatch):
    """解析抛异常 → 保留旧镜像，不覆盖。"""
    import wb_utils

    p = tmp_path / "任务" / "坏文件.md"
    dual.write_text(p, "---\ntype: task\nstatus: todo\n---\n\n# 坏文件\n")
    old_mtime = dual.db.get_mirror_mtime("任务", "坏文件.md")

    def _boom(path):
        raise ValueError("parse boom")

    monkeypatch.setattr(wb_utils, "_parse_md", _boom)
    _write(p, "---\ntype: task\nstatus: completed\n---\n\n# 坏文件\n")  # 外部改（模拟解析会失败）
    res = dual.sync_from_files()
    assert res["reingested"] == 0  # 解析失败 → 不重摄
    assert dual.db.get_mirror_mtime("任务", "坏文件.md") == old_mtime  # 镜像保留旧值


def test_sync_removes_orphan_rows(dual, tmp_path):
    """DB 有镜像行但文件被删除 → sync 清除孤儿行。"""
    p = tmp_path / "待验证" / "孤儿.md"
    dual.write_text(p, "# 待验证收录 2026-08-16\n\n---\ntype: queued\nstatus: pending\n---\n\n## 条目\n")
    assert dual.db.get_mirror_mtime("待验证", "孤儿.md") is not None
    p.unlink()  # 外部删除
    res = dual.sync_from_files()
    assert res["removed"] == 1
    assert dual.db.get_mirror_mtime("待验证", "孤儿.md") is None
