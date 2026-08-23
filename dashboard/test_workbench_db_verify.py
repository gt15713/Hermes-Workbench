# -*- coding: utf-8 -*-
"""workbench_db_verify 移动收敛测试（2026-08-15 归档闭环 DB 镜像同步修复）。

背景：归档闭环若用手工文件操作（patch status + move + 写索引），DB 镜像不会跟随
（/complete 与归档巡检走 DualRepo 才会同步）。verify --fix 需识别「同文件名 + 同内容
出现在其他分区」为移动，把 DB 行迁移到新分区并刷新 status/mtime。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from repo import SqliteRepo  # noqa: E402
from workbench_db_verify import verify  # noqa: E402


@pytest.fixture()
def fs_root(tmp_path):
    """临时工作台根 + 标准分区。"""
    for d in ("待验证", "待回看", "任务", "心理学随想", "梦中的邮件", "已处理", "回收站"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    return tmp_path


def _write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _seed_task(fs_root, db) -> Path:
    """任务区种子：DB 与文件一致（status: in_progress）。"""
    p = fs_root / "任务" / "t1.md"
    text = "---\ntype: task\nstatus: in_progress\ncreated: 2026-08-15\n---\n\n# 任务1\n"
    _write(p, text)
    db.write_text(p, text)
    return p


def _manual_archive(fs_root, p: Path) -> Path:
    """模拟 Hermes 手工三步闭环：只动文件（patch status + move + 写索引），不碰 DB。"""
    archived = fs_root / "已处理" / p.name
    text = p.read_text(encoding="utf-8").replace("status: in_progress", "status: completed")
    _write(archived, text)
    p.unlink()
    idx = fs_root / "已处理" / "2026-08-15.md"
    _write(idx, "# 已处理 2026-08-15\n\n## 任务（1 条）\n\n- [[t1|任务1]]\n")
    return archived


class TestMovedConvergence:
    def test_verify_reports_moved_without_fix(self, fs_root, tmp_path):
        db = SqliteRepo(tmp_path / "wb.db", root=fs_root)
        p = _seed_task(fs_root, db)
        _manual_archive(fs_root, p)

        missing, orphan, mismatch, moved, fixed = verify(fs_root, db, fix=False)
        assert "任务/t1.md -> 已处理/t1.md" in moved
        assert "已处理/2026-08-15.md" in missing
        # 归类为 moved 后不再算 orphan
        assert not any("任务/t1.md" in x for x in orphan)
        assert mismatch == []
        assert fixed == 0

    def test_verify_fix_converges_moved(self, fs_root, tmp_path):
        db = SqliteRepo(tmp_path / "wb.db", root=fs_root)
        p = _seed_task(fs_root, db)
        archived = _manual_archive(fs_root, p)

        missing, orphan, mismatch, moved, fixed = verify(fs_root, db, fix=True)
        assert missing == [] and orphan == [] and mismatch == [] and moved == []
        assert fixed == 3  # 已处理/t1.md 迁移 + 已处理/2026-08-15.md 入库 + ... （见下）

        assert not db.exists(fs_root / "任务" / "t1.md")
        assert db.exists(archived)
        rows = {(r["partition"], r["filename"]): r for r in db._all_tasks()}
        assert rows[("已处理", "t1.md")]["status"] == "completed"
        assert rows[("已处理", "2026-08-15.md")]["status"] == ""

    def test_same_name_other_partition_moves_even_if_content_edited(self, fs_root, tmp_path):
        """归档会改写内容（status/completed_at/完成记录）——实体身份按文件名，同名即移动。"""
        db = SqliteRepo(tmp_path / "wb.db", root=fs_root)
        p = _seed_task(fs_root, db)
        _write(fs_root / "已处理" / p.name, "# 完全不同的文件\n")
        p.unlink()

        _, orphan, _, moved, _ = verify(fs_root, db, fix=False)
        assert "任务/t1.md -> 已处理/t1.md" in moved
        assert not any("任务/t1.md" in x for x in orphan)

    def test_true_orphan_stays_when_no_same_name_anywhere(self, fs_root, tmp_path):
        """文件确实不存在且无同名文件 → 孤儿守卫：--fix 也不删，等删除端点显式清 DB。"""
        db = SqliteRepo(tmp_path / "wb.db", root=fs_root)
        p = _seed_task(fs_root, db)
        p.unlink()

        _, orphan, _, moved, _ = verify(fs_root, db, fix=False)
        assert moved == []
        assert "任务/t1.md" in orphan

        _, orphan2, _, _, fixed = verify(fs_root, db, fix=True)
        assert "任务/t1.md" in orphan2
        assert fixed == 0
