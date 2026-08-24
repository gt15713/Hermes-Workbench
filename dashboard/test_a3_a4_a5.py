# -*- coding: utf-8 -*-
"""A3 回收站 TTL + A4 全局搜索 + A5 标签体系 回归测试。

运行：cd dashboard && python -m pytest test_a3_a4_a5.py -v
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import auto_archive  # noqa: E402
import plugin_api as api  # noqa: E402
import repo as repo_mod  # noqa: E402
import ttl  # noqa: E402
import wb_utils as wb_utils_mod  # noqa: E402
from wb_utils import _parse_tags  # noqa: E402


@pytest.fixture()
def wb(tmp_path, monkeypatch):
    for d in ("待验证", "待回看", "任务", "心理学随想", "梦中的邮件", "已处理", "回收站", "日志"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(api, "WORKBENCH_ROOT", tmp_path)
    monkeypatch.setattr(wb_utils_mod, "WORKBENCH_ROOT", tmp_path)
    monkeypatch.setattr(repo_mod, "WORKBENCH_ROOT", tmp_path)
    monkeypatch.setattr(api.file_repo, "root", tmp_path)
    # 修复：db/read_from_db 必须用 monkeypatch.setattr（直接赋值会永久污染全局单例，连累后续测试文件）
    monkeypatch.setattr(api.file_repo, "db", repo_mod.SqliteRepo(tmp_path / "test-workbench.db", root=tmp_path))
    monkeypatch.setattr(api.file_repo, "read_from_db", False)
    return tmp_path


def _write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------- A5：标签解析 ----------

class TestParseTags:
    def test_inline_list(self):
        assert _parse_tags(["工作", "urgent"]) == ["工作", "urgent"]

    def test_comma_string(self):
        assert _parse_tags("工作, urgent") == ["工作", "urgent"]

    def test_single_and_none(self):
        assert _parse_tags("工作") == ["工作"]
        assert _parse_tags(None) == []
        assert _parse_tags("") == []

    def test_dedup_and_strip(self):
        assert _parse_tags("a, a,  b") == ["a", "b"]

    def test_parse_md_carries_tags(self, wb):
        p = wb / "任务" / "t.md"
        _write(p, "---\ntype: task\nstatus: todo\ntags: [工作, urgent]\n---\n\n# 带标签任务\n")
        d = api._parse_md(p)
        assert d["tags"] == ["工作", "urgent"]

    def test_parse_md_no_tags(self, wb):
        p = wb / "任务" / "t2.md"
        _write(p, "---\ntype: task\nstatus: todo\n---\n\n# 无标签\n")
        assert api._parse_md(p)["tags"] == []


# ---------- A4：/search ----------

class TestSearchEndpoint:
    def _seed(self, wb):
        _write(
            wb / "任务" / "alpha.md",
            "---\ntype: task\nstatus: todo\ntags: [工作, urgent]\n---\n\n# 爬虫调研\n\n这里提到硅基流动 API\n",
        )
        _write(
            wb / "待验证" / "2026-08-15.md",
            "# 待验证收录 2026-08-15\n\n---\ntype: queued\nstatus: pending\ntags: 心理学\n---\n\n## 如何正确怼人\n",
        )
        _write(
            wb / "任务" / "beta.md",
            "---\ntype: task\nstatus: todo\n---\n\n# 无标签任务\n",
        )

    def test_search_matches_content(self, wb):
        self._seed(wb)
        r = api.search(q="硅基流动")
        assert r["total"] >= 1
        titles = [x["title"] for x in r["results"]]
        assert "爬虫调研" in titles

    def test_search_matches_title_and_file(self, wb):
        self._seed(wb)
        r = api.search(q="无标签任务")
        assert r["results"][0]["file"] == "beta.md"
        r2 = api.search(q="alpha")
        assert r2["results"][0]["file"] == "alpha.md"

    def test_search_by_tag(self, wb):
        self._seed(wb)
        r = api.search(tag="工作")
        files = {x["file"] for x in r["results"]}
        assert files == {"alpha.md"}

    def test_search_tag_plus_query(self, wb):
        self._seed(wb)
        r = api.search(q="心理学", tag="心理学")
        assert r["total"] == 1
        assert r["results"][0]["file"] == "2026-08-15.md"

    def test_search_empty(self, wb):
        self._seed(wb)
        r = api.search(q="不存在的关键词xyz")
        assert r["total"] == 0
        assert r["results"] == []


# ---------- A3：回收站 TTL ----------

class TestTrashTtl:
    def test_scan_only_overdue(self, wb, monkeypatch):
        monkeypatch.setattr(ttl, "ROOT", wb)
        old = date.today() - timedelta(days=40)
        recent = date.today() - timedelta(days=10)
        _write(wb / "回收站" / "old.md", f"---\ntype: task\ntrashed_at: {old.isoformat()}\n---\n")
        _write(wb / "回收站" / "fresh.md", f"---\ntype: task\ntrashed_at: {recent.isoformat()}\n---\n")
        _write(wb / "回收站" / "no-ts.md", "---\ntype: task\nstatus: todo\n---\n")
        overdue = ttl.scan_trash_overdue(ttl_days=30, root=wb)
        names = [x[0] for x in overdue]
        assert names == ["old.md"]  # 40 天超期；10 天未超期；无时间戳跳过

    def test_scan_ttl_days_threshold(self, wb):
        old = date.today() - timedelta(days=20)
        _write(wb / "回收站" / "mid.md", f"---\ntrashed_at: {old.isoformat()}\n---\n")
        assert [x[0] for x in ttl.scan_trash_overdue(ttl_days=15, root=wb)] == ["mid.md"]
        assert ttl.scan_trash_overdue(ttl_days=30, root=wb) == []

    def test_delete_and_events(self, wb, monkeypatch):
        monkeypatch.setattr(ttl, "ROOT", wb)
        monkeypatch.setattr(ttl, "DB_PATH", wb / "ttl.db")
        old = date.today() - timedelta(days=40)
        _write(wb / "回收站" / "gone.md", f"---\ntrashed_at: {old.isoformat()}\n---\n")
        overdue = ttl.scan_trash_overdue(30, root=wb)
        deleted = ttl.delete_overdue(overdue, root=wb)
        assert deleted == ["gone.md"]
        assert not (wb / "回收站" / "gone.md").exists()
        ttl.record_events(overdue, db_path=wb / "ttl.db")
        import sqlite3

        conn = sqlite3.connect(str(wb / "ttl.db"))
        rows = conn.execute(
            "SELECT partition, filename, kind FROM task_events WHERE kind='trash_ttl'"
        ).fetchall()
        conn.close()
        assert ("回收站", "gone.md", "trash_ttl") in rows


# ---------- 执行复位（2026-08-17：孤儿执行清理） ----------

class TestResetExecution:
    def test_reset_clears_session_id(self, wb):
        """reset_execution 把 in_progress 复位为 todo 并清掉残留 session_id。"""
        import asyncio

        p = wb / "任务" / "t.md"
        _write(
            p,
            "---\ntype: task\nstatus: in_progress\nsession_id: deadbeef\n"
            "execution_result: pending\nexecution_started_at: 2026-08-17T22:00:00\n---\n\n# 任务\n",
        )
        r = asyncio.run(
            api.reset_execution({"dir": "任务", "file": "t.md", "reason": "测试复位"})
        )
        assert r.get("ok") is True
        assert r.get("status") == "todo"
        txt = p.read_text(encoding="utf-8")
        assert "status: todo" in txt
        assert "session_id:" not in txt  # 死会话 id 必须清除（打开会话不再跳空白）
        assert "execution_result:" not in txt
        assert "execution_started_at:" not in txt
        assert "执行失败记录" in txt


class TestCompleteInProgress:
    def test_in_progress_without_success_cannot_be_archived(self, wb):
        """未收到明确成功结果的执行中任务不得被手动归档。"""
        import asyncio

        p = wb / "任务" / "still-running.md"
        _write(p, "---\ntype: task\nstatus: in_progress\nexecution_result: pending\n---\n\n# 仍在执行\n")
        r = asyncio.run(api.complete({"dir": "任务", "file": "still-running.md"}))
        assert r.get("ok") is False
        assert r.get("error") == "execution result required"
        assert p.exists()

    def test_complete_in_progress_archives(self, wb):
        """执行完成（in_progress）的任务也应能归档到已处理（2026-08-17 修复）。"""
        import asyncio

        p = wb / "任务" / "done-task.md"
        _write(p, "---\ntype: task\nstatus: in_progress\nexecution_result: success\n---\n\n# 已执行任务\n")
        r = asyncio.run(api.complete({"dir": "任务", "file": "done-task.md"}))
        assert r.get("ok") is True
        assert r.get("archived") is True
        assert not p.exists()  # 已移出任务区
        done_files = [f.name for f in (wb / "已处理").glob("*.md")]
        assert r["archived_as"] in done_files
        archived = (wb / "已处理" / r["archived_as"]).read_text(encoding="utf-8")
        assert "status: completed" in archived
        assert "完成记录" in archived


class TestAutoArchive:
    def test_legacy_done_success_is_reconciled(self, wb):
        """Agent 写入 legacy `done` 时也必须进入正式归档入口。"""
        _write(
            wb / "任务" / "legacy-done.md",
            "---\ntype: task\nstatus: done\nsession_id: sess-legacy\n"
            "execution_result: success\n---\n\n# 旧终态任务\n",
        )

        assert ("legacy-done.md", "completed") in auto_archive.scan_execution_results(root=wb)

        result = auto_archive.reconcile("legacy-done.md", "completed")
        assert result.get("ok") is True
        assert not (wb / "任务" / "legacy-done.md").exists()
        assert "status: completed" in (wb / "已处理" / "legacy-done.md").read_text(encoding="utf-8")

    def test_completed_task_stuck_in_task_partition_is_reconciled(self, wb):
        """外部完成写入不能让任务永久滞留在任务区。"""
        _write(
            wb / "任务" / "stuck.md",
            "---\ntype: task\nstatus: completed\nsession_id: sess-stuck\n"
            "execution_result: success\n---\n\n# 滞留完成任务\n",
        )

        assert ("stuck.md", "completed") in auto_archive.scan_execution_results(root=wb)

        result = auto_archive.reconcile("stuck.md", "completed")

        assert result.get("ok") is True
        assert result.get("archived") is True
        assert not (wb / "任务" / "stuck.md").exists()
        archived = (wb / "已处理" / "stuck.md").read_text(encoding="utf-8")
        assert "completed_at:" in archived
        assert "## 完成记录" in archived

    def test_scan_only_returns_explicit_terminal_results(self, wb):
        _write(
            wb / "任务" / "success.md",
            "---\nstatus: in_progress\nsession_id: sess1\nexecution_result: success\n---\n",
        )
        _write(
            wb / "任务" / "failure.md",
            "---\nstatus: in_progress\nsession_id: sess2\nexecution_result: failure\n---\n",
        )
        _write(
            wb / "任务" / "pending.md",
            "---\nstatus: in_progress\nsession_id: sess3\nexecution_result: pending\n---\n\n## 完成记录\n- 会话结束\n",
        )
        found = auto_archive.scan_execution_results(root=wb)
        assert ("success.md", "completed") in found
        assert ("failure.md", "failed") in found
        names = {f for f, _ in found}
        assert "pending.md" not in names

    def test_reconcile_archives_success_and_restores_failure(self, wb):
        _write(
            wb / "任务" / "success.md",
            "---\ntype: task\nstatus: in_progress\nsession_id: sess1\nexecution_result: success\n---\n\n# 成功任务\n",
        )
        _write(
            wb / "任务" / "failure.md",
            "---\ntype: task\nstatus: in_progress\nsession_id: sess2\nexecution_result: failure\n---\n\n# 失败任务\n",
        )

        success = auto_archive.reconcile("success.md", "completed")
        failure = auto_archive.reconcile("failure.md", "failed")

        assert success.get("ok") is True
        assert success.get("archived") is True
        assert not (wb / "任务" / "success.md").exists()
        assert any(p.name.startswith("success") for p in (wb / "已处理").glob("*.md"))
        assert failure.get("ok") is True
        failure_text = (wb / "任务" / "failure.md").read_text(encoding="utf-8")
        assert "status: todo" in failure_text
        assert "session_id:" not in failure_text


class TestResolvePsych:
    def test_resolve_psych_entry_archives(self, wb, legacy_partitions):
        """心理学随想条目级「确认处理」应可用（2026-08-17 白名单补全）。"""
        import asyncio

        p = wb / "心理学随想" / "2026-08-17.md"
        _write(
            p,
            "---\ntype: queued\nstatus: pending\n---\n\n## 一条心理学随想\n\n内容\n",
        )
        r = asyncio.run(
            api.resolve(
                {
                    "dir": "心理学随想",
                    "file": "2026-08-17.md",
                    "entry_title": "一条心理学随想",
                }
            )
        )
        assert r.get("ok") is True
        assert r.get("archived") is True
        assert (wb / "已处理" / r["file"]).exists()
        archived = (wb / "已处理" / r["file"]).read_text(encoding="utf-8")
        assert "status: cleared" in archived
        assert "一条心理学随想" in archived
