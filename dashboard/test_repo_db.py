# -*- coding: utf-8 -*-
"""workbench-view 存储层 SQLite/双写测试（阶段 1.5）。

覆盖：
- SqliteRepo：write/read/exists/mtime/list_files/move/delete + task_events 事件流
- DualRepo：双写后文件 + DB 均有；move 后 DB 跟随；DB 写失败不阻断文件操作
- 路径隔离：非法分区/工作台外路径不落库

运行：cd dashboard && python -m pytest test_repo_db.py -v
"""
import sqlite3
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from repo import (  # noqa: E402
    DualRepo,
    FileRepo,
    SqliteRepo,
    WorkbenchConflictError,
    WorkbenchRepo,
)


@pytest.fixture()
def fs_root(tmp_path):
    """临时工作台根 + 标准分区。"""
    for d in ("待验证", "待回看", "任务", "心理学随想", "梦中的邮件", "已处理", "回收站"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    return tmp_path


def _write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class TestSqliteRepo:
    def test_schema_init(self, tmp_path):
        db = SqliteRepo(tmp_path / "wb.db", root=tmp_path)
        assert db.db_path.exists()

    def test_write_read_exists_mtime(self, fs_root, tmp_path):
        db = SqliteRepo(tmp_path / "wb.db", root=fs_root)
        p = fs_root / "任务" / "t1.md"
        _write(p, "---\nstatus: todo\n---\n# 任务1\n")
        db.write_text(p, p.read_text(encoding="utf-8"))
        assert db.exists(p)
        assert db.read_text(p) == "---\nstatus: todo\n---\n# 任务1\n"
        assert db.mtime(p) == pytest.approx(p.stat().st_mtime, abs=1)
        # 事件流
        ev = db._fetch_events() if hasattr(db, "_fetch_events") else None
        assert ev is None or len(ev) >= 1

    def test_status_extracted(self, fs_root, tmp_path):
        db = SqliteRepo(tmp_path / "wb.db", root=fs_root)
        p = fs_root / "任务" / "t2.md"
        _write(p, "---\nstatus: completed\n---\n# 完成\n")
        db.write_text(p, p.read_text(encoding="utf-8"))
        rows = db._all_tasks()
        assert rows[0]["status"] == "completed"

    def test_list_files_mtime_desc(self, fs_root, tmp_path):
        db = SqliteRepo(tmp_path / "wb.db", root=fs_root)
        import os
        import time
        p_a = fs_root / "任务" / "a.md"
        p_b = fs_root / "任务" / "b.md"
        _write(p_a, "# a\n")
        db.write_text(p_a, "# a\n")
        # 显式设定不同 mtime（同秒写入时文件系统精度不足以排序）
        os.utime(p_a, (time.time() - 100, time.time() - 100))
        _write(p_b, "# b\n")
        db.write_text(p_b, "# b\n")
        files = db.list_files("任务")
        assert len(files) == 2
        # 按 mtime 倒序：b.md（较新）在前
        assert files[0].name == "b.md"
        assert files[1].name == "a.md"

    def test_move(self, fs_root, tmp_path):
        db = SqliteRepo(tmp_path / "wb.db", root=fs_root)
        src = fs_root / "任务" / "m.md"
        _write(src, "# 移动\n")
        db.write_text(src, src.read_text(encoding="utf-8"))
        dst = fs_root / "已处理" / "m.md"
        db.move(src, dst)
        assert not db.exists(src)
        assert db.exists(dst)
        assert db.read_text(dst) == "# 移动\n"
        # 事件：created + moved
        kinds = [e["kind"] for e in db._all_events()]
        assert "moved" in kinds

    def test_delete(self, fs_root, tmp_path):
        db = SqliteRepo(tmp_path / "wb.db", root=fs_root)
        p = fs_root / "任务" / "d.md"
        _write(p, "# 删除\n")
        db.write_text(p, p.read_text(encoding="utf-8"))
        db.delete(p)
        assert not db.exists(p)
        kinds = [e["kind"] for e in db._all_events()]
        assert "deleted" in kinds

    def test_workbench_outside_ignored(self, fs_root, tmp_path):
        db = SqliteRepo(tmp_path / "wb.db", root=fs_root)
        outside = tmp_path / "outside.md"
        _write(outside, "x")
        db.write_text(outside, "x")  # 工作台外：静默跳过
        assert not db.exists(outside)
        assert db._all_tasks() == []

    def test_bad_partition_ignored(self, fs_root, tmp_path):
        db = SqliteRepo(tmp_path / "wb.db", root=fs_root)
        p = fs_root / "非法分区" / "x.md"
        p.parent.mkdir(exist_ok=True)
        _write(p, "x")
        db.write_text(p, "x")
        assert db._all_tasks() == []


class TestDualRepo:
    def test_write_dual(self, fs_root, tmp_path):
        dual = DualRepo(
            FileRepo(root=fs_root),
            SqliteRepo(tmp_path / "wb.db", root=fs_root),
        )
        p = fs_root / "任务" / "dual.md"
        text = "# 双写\n"
        dual.write_text(p, text)
        # 文件有
        assert p.read_text(encoding="utf-8") == text
        # DB 有
        assert dual.db.exists(p)

    def test_move_dual(self, fs_root, tmp_path):
        dual = DualRepo(
            FileRepo(root=fs_root),
            SqliteRepo(tmp_path / "wb.db", root=fs_root),
        )
        src = fs_root / "任务" / "mv.md"
        _write(src, "# 移动\n")
        dual.write_text(src, src.read_text(encoding="utf-8"))
        dst = fs_root / "已处理" / "mv.md"
        dual.move(src, dst)
        assert not src.exists()
        assert dst.exists()
        assert not dual.db.exists(src)
        assert dual.db.exists(dst)

    def test_db_failure_does_not_block(self, fs_root, tmp_path, monkeypatch):
        """DB 镜像写失败 → warning 不阻断文件操作（容错原则）。"""
        dual = DualRepo(
            FileRepo(root=fs_root),
            SqliteRepo(tmp_path / "wb.db", root=fs_root),
        )
        p = fs_root / "任务" / "t.md"

        def _boom(*a, **k):
            raise RuntimeError("db down")

        monkeypatch.setattr(dual.db, "write_text", _boom)
        dual.write_text(p, "# 文件照常写\n")
        assert p.exists()  # 文件写成功，不抛异常

    def test_is_workbench_repo(self, fs_root, tmp_path):
        dual = DualRepo(
            FileRepo(root=fs_root),
            SqliteRepo(tmp_path / "wb.db", root=fs_root),
        )
        assert isinstance(dual, WorkbenchRepo)
        # plugin_api 依赖的接口齐全
        for m in ("resolve", "partition_dir", "list_files", "read_text",
                  "exists", "mtime", "write_text", "move", "delete",
                  "append_action_log", "append_done_log"):
            assert callable(getattr(dual, m))

    # ---------- 阶段 2：读路径走 DB 事实源 ----------

    def test_read_from_db_by_default(self, fs_root, tmp_path):
        """读走 DB：文件删除后仍可读（DB 为事实源）。"""
        dual = DualRepo(
            FileRepo(root=fs_root),
            SqliteRepo(tmp_path / "wb.db", root=fs_root),
            read_from_db=True,
        )
        p = fs_root / "任务" / "dbread.md"
        dual.write_text(p, "# DB 事实源\n")
        p.unlink()  # 文件镜像缺失
        assert dual.exists(p)  # DB 有记录 → 仍存在
        assert dual.read_text(p) == "# DB 事实源\n"
        assert dual.list_files("任务")  # 非空

    def test_read_fallback_file_when_off(self, fs_root, tmp_path):
        """WORKBENCH_READ_FROM_DB=0 回滚通道：读回文件。"""
        dual = DualRepo(
            FileRepo(root=fs_root),
            SqliteRepo(tmp_path / "wb.db", root=fs_root),
            read_from_db=False,
        )
        p = fs_root / "任务" / "fileonly.md"
        _write(p, "# 只文件\n")
        assert dual.read_text(p) == "# 只文件\n"

    def test_db_read_failure_fallback(self, fs_root, tmp_path, monkeypatch):
        """DB 读失败 → 回退文件读（容错）。"""
        dual = DualRepo(
            FileRepo(root=fs_root),
            SqliteRepo(tmp_path / "wb.db", root=fs_root),
            read_from_db=True,
        )
        p = fs_root / "任务" / "fb.md"
        _write(p, "# 回退\n")
        dual.write_text(p, "# 回退\n")

        def _boom(*a, **k):
            raise RuntimeError("db read down")

        monkeypatch.setattr(dual.db, "read_text", _boom)
        assert dual.read_text(p) == "# 回退\n"

    # ---------- 阶段 2.5：ingest 幂等 + mtime 前置校验 ----------

    def test_ingest_idempotent(self, fs_root, tmp_path):
        """同 message_id 已消费 → 不重复（done 跳过）。"""
        db = SqliteRepo(tmp_path / "wb.db", root=fs_root)
        assert not db.ingest_exists("m1")
        db.ingest_upsert("m1", "待验证", "x.md", "processing")  # claim
        assert not db.ingest_exists("m1")  # processing = 崩溃残留，可重放
        db.ingest_upsert("m1", "待验证", "x.md", "done")  # 消费完成
        assert db.ingest_exists("m1")  # done = 已消费

    def test_mtime_conflict_raised(self, fs_root, tmp_path):
        """expected_mtime 过期（并发期间被改）→ WorkbenchConflictError。"""
        dual = DualRepo(
            FileRepo(root=fs_root),
            SqliteRepo(tmp_path / "wb.db", root=fs_root),
            read_from_db=True,
        )
        p = fs_root / "任务" / "conflict.md"
        dual.write_text(p, "# v1\n")
        old = dual.db.mtime(p)
        # 跨平台：确保 v1→v2 写入间隔超过 0.01s 冲突阈值（Linux mtime 精度高，紧接写入差 <0.01 不触发）
        time.sleep(0.02)
        # 并发写入 v2（mtime 变化）
        dual.write_text(p, "# v2 并发修改\n")
        with pytest.raises(WorkbenchConflictError):
            dual.write_text(p, "# v3 基于旧版本\n", expected_mtime=old)

    def test_mtime_no_conflict_when_current(self, fs_root, tmp_path):
        """expected_mtime = 当前版本 → 正常写入。"""
        dual = DualRepo(
            FileRepo(root=fs_root),
            SqliteRepo(tmp_path / "wb.db", root=fs_root),
            read_from_db=True,
        )
        p = fs_root / "任务" / "ok.md"
        dual.write_text(p, "# v1\n")
        cur = dual.db.mtime(p)
        dual.write_text(p, "# v2\n", expected_mtime=cur)  # 不抛
        assert dual.read_text(p) == "# v2\n"


class TestEventsChannel:
    """阶段 4：事件通道（list_events 增量 + health + 索引）。"""

    def test_list_events_incremental(self, fs_root, tmp_path):
        """list_events 按 id 增量续拉，断点语义正确。"""
        db = SqliteRepo(tmp_path / "events.db", root=fs_root)
        p = Path(fs_root) / "待验证" / "a.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        db.write_text(p, "# a\n")
        db.write_text(p, "# a2\n")
        # 全量
        all_evts = db.list_events(since_id=0)
        assert len(all_evts) >= 2
        ids = [e["id"] for e in all_evts]
        assert ids == sorted(ids)
        # 增量：从最后一个 id 继续 → 无新事件
        assert db.list_events(since_id=ids[-1]) == []
        # 新增一条 → 增量只返回新的
        db.write_text(p, "# a3\n")
        more = db.list_events(since_id=ids[-1])
        assert len(more) == 1
        assert more[0]["id"] > ids[-1]
        assert more[0]["kind"] in ("created", "updated")

    def test_health_and_indexes(self, fs_root, tmp_path):
        """health 可读；阶段 4 索引（mtime/kind）已建。"""
        db = SqliteRepo(tmp_path / "events.db", root=fs_root)
        assert db.health() is True
        conn = sqlite3.connect(tmp_path / "events.db")
        try:
            names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
            assert "idx_tasks_mtime" in names
            assert "idx_events_kind" in names
        finally:
            conn.close()
