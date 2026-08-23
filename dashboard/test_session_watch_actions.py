# -*- coding: utf-8 -*-
"""C3（P1-1）：会话→任务提取——行动项解析 / ingest 落待验证 / 幂等 / 每日上限 / 低置信合并。"""

from datetime import date as _date
from pathlib import Path

import plugin_api as api
import pytest
import session_watch as sw


@pytest.fixture()
def wb(tmp_path, monkeypatch):
    """与 test_plugin_api.wb 同构：临时根 + 分区 + DB 镜像。"""
    import repo as repo_mod
    import wb_utils as wb_utils_mod

    for d in ("待验证", "待回看", "任务", "心理学随想", "梦中的邮件", "已处理", "回收站", "日志"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(api, "WORKBENCH_ROOT", tmp_path)
    monkeypatch.setattr(wb_utils_mod, "WORKBENCH_ROOT", tmp_path)
    monkeypatch.setattr(wb_utils_mod, "LOG_DIR", tmp_path / "日志")
    monkeypatch.setattr(repo_mod, "WORKBENCH_ROOT", tmp_path)
    monkeypatch.setattr(api.file_repo, "root", tmp_path)
    api.file_repo.db = repo_mod.SqliteRepo(tmp_path / "test-workbench.db", root=tmp_path)
    api.file_repo.read_from_db = False
    return tmp_path


def _write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class TestExtractActions:
    def test_parses_action_section(self, wb):
        text = "# 任务\n\n## 行动项\n\n- [ ] 整理报告\n- 调研 API\n- [x] 已完成项\n\n## 其他\n"
        assert sw._extract_actions(text) == ["整理报告", "调研 API", "已完成项"]

    def test_no_section_returns_empty(self, wb):
        assert sw._extract_actions("# 任务\n\n## 备注\n") == []

    def test_limit_five(self, wb):
        text = "## 行动项\n\n" + "\n".join(f"- 行动{i}" for i in range(8))
        assert len(sw._extract_actions(text)) == 5

    def test_ignores_code_and_heading(self, wb):
        text = "## 行动项\n\n- 真实项\n```\n- 代码项\n```\n## 下节\n"
        actions = sw._extract_actions(text)
        assert "真实项" in actions
        assert "代码项" not in actions


class TestExtractSummary:
    def test_summary(self, wb):
        text = "## 会话总结\n\n讨论了三件事\n\n## 其他\n"
        assert sw._extract_summary(text) == "讨论了三件事"

    def test_no_summary(self, wb):
        assert sw._extract_summary("# 任务\n") is None


class TestIngestActions:
    def _dual(self, wb):
        from repo import DualRepo, FileRepo, SqliteRepo

        return DualRepo(FileRepo(root=wb), SqliteRepo(root=wb))

    def test_ingest_to_pending_with_parent_ref(self, wb):
        p = wb / "任务" / "parent.md"
        _write(p, "---\ntype: task\nstatus: in_progress\nsession_id: sess-1\n---\n\n# 父任务\n\n## 行动项\n\n- [ ] 新任务A\n- 新任务B\n")
        item = {"path": p, "session_id": "sess-1", "text": p.read_text(encoding="utf-8")}
        res = sw.ingest_actions(item, self._dual(wb))
        assert res["ingested"] == 2
        agg = wb / "待验证" / f"{_date.today().strftime('%Y-%m-%d')}.md"
        assert agg.exists()
        text = agg.read_text(encoding="utf-8")
        assert "新任务A" in text
        assert "新任务B" in text
        assert "parent.md" in text  # 父任务引用
        assert "sess-1" in text  # session_id

    def test_idempotent_replay(self, wb):
        p = wb / "任务" / "parent.md"
        _write(p, "---\ntype: task\nstatus: in_progress\nsession_id: sess-2\n---\n\n# 父任务\n\n## 行动项\n\n- [ ] 幂等项\n")
        item = {"path": p, "session_id": "sess-2", "text": p.read_text(encoding="utf-8")}
        r1 = sw.ingest_actions(item, self._dual(wb))
        assert r1["ingested"] == 1
        # 重放（同 message_id）→ duplicate，不重复写
        r2 = sw.ingest_actions(item, self._dual(wb))
        assert r2["ingested"] == 0
        assert r2["duplicate"] == 1
        agg = wb / "待验证" / f"{_date.today().strftime('%Y-%m-%d')}.md"
        text = agg.read_text(encoding="utf-8")
        assert text.count("幂等项") == 1

    def test_daily_cap(self, wb):
        p = wb / "任务" / "parent.md"
        _write(p, "---\ntype: task\nstatus: in_progress\nsession_id: sess-3\n---\n\n# 父任务\n\n## 行动项\n\n" + "\n".join(f"- 行动{i}" for i in range(5)))
        item = {"path": p, "session_id": "sess-3", "text": p.read_text(encoding="utf-8")}
        dual = self._dual(wb)
        res = sw.ingest_actions(item, dual, daily_cap=3)
        assert res["ingested"] == 3
        assert res["capped"] == 2  # 提取上限 5 条 - 已写 3 条

    def test_low_confidence_merge_summary(self, wb):
        p = wb / "任务" / "parent.md"
        _write(p, "---\ntype: task\nstatus: in_progress\nsession_id: sess-4\n---\n\n# 父任务\n\n## 会话总结\n\n讨论了方向，暂无明确行动项\n")
        item = {"path": p, "session_id": "sess-4", "text": p.read_text(encoding="utf-8")}
        res = sw.ingest_actions(item, self._dual(wb))
        assert res["merged"] == 1
        assert res["ingested"] == 1
        agg = wb / "待验证" / f"{_date.today().strftime('%Y-%m-%d')}.md"
        assert "会话总结" in agg.read_text(encoding="utf-8")

    def test_no_actions_no_summary_no_write(self, wb):
        p = wb / "任务" / "parent.md"
        _write(p, "---\ntype: task\nstatus: in_progress\nsession_id: sess-5\n---\n\n# 父任务\n\n## 完成记录\n\n- 完成\n")
        item = {"path": p, "session_id": "sess-5", "text": p.read_text(encoding="utf-8")}
        res = sw.ingest_actions(item, self._dual(wb))
        assert res == {"ingested": 0, "duplicate": 0, "capped": 0, "merged": 0}
        assert list((wb / "待验证").glob("*.md")) == []


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
