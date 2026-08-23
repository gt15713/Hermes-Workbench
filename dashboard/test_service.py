"""service.py 服务层测试（阶段 1）。

验证：
- build_service 装配成功（动作映射齐全）
- execute 未知动作返回统一错误信封
- 便捷方法转发到注册动作（complete 端到端走 service）
"""
import asyncio
from datetime import date
from pathlib import Path

import plugin_api as api
import pytest
from repo import FileRepo
from service import build_service


@pytest.fixture()
def wb(tmp_path, monkeypatch):
    import repo as repo_mod
    import wb_utils as wb_utils_mod

    for d in ("待验证", "待回看", "任务", "心理学随想", "梦中的邮件", "已处理", "回收站", "日志"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(api, "WORKBENCH_ROOT", tmp_path)
    monkeypatch.setattr(api, "LOG_DIR", tmp_path / "日志")
    monkeypatch.setattr(wb_utils_mod, "WORKBENCH_ROOT", tmp_path)
    monkeypatch.setattr(wb_utils_mod, "LOG_DIR", tmp_path / "日志")
    monkeypatch.setattr(repo_mod, "WORKBENCH_ROOT", tmp_path)
    monkeypatch.setattr(api.file_repo, "root", tmp_path)
    # 阶段 1.5：DB 镜像指向临时库，避免污染真实 workbench.db
    api.file_repo.db = repo_mod.SqliteRepo(tmp_path / "test-workbench.db", root=tmp_path)
    # 阶段 2：解析/端点测试用文件读（read_from_db=False），DB 读由 test_repo_db 覆盖
    api.file_repo.read_from_db = False
    return tmp_path


def _write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class TestBuildService:
    def test_build_service_action_map_complete(self, wb):
        svc = build_service(FileRepo(root=wb))
        for name in ("board", "recent", "complete", "resolve", "to-task", "trash",
                     "restore", "defer", "abandon", "reopen", "execute",
                     "bind-session", "reset-execution", "add", "batch"):
            assert name in svc._actions

    def test_unknown_action_error_envelope(self, wb):
        svc = build_service(FileRepo(root=wb))
        r = svc.execute("no-such-action", {})
        assert r.get("ok") is False
        assert "unknown action" in r.get("error", "")

    def test_complete_via_service_end_to_end(self, wb):
        svc = build_service(FileRepo(root=wb))
        p = wb / "任务" / "svc-complete.md"
        _write(p, "---\ntype: task\nstatus: todo\n---\n\n# 服务层测试\n")
        r = asyncio.run(svc.complete({"dir": "任务", "file": "svc-complete.md"}))
        assert r.get("ok") is True
        assert not p.exists()
        assert (wb / "已处理" / "svc-complete.md").exists()
        today = date.today().isoformat()
        index = wb / "已处理" / f"{today}.md"
        assert index.exists()
        assert "svc-complete" in index.read_text(encoding="utf-8", errors="replace")

    def test_board_via_service(self, wb):
        svc = build_service(FileRepo(root=wb))
        r = svc.board()
        assert "today" in r
        assert "sections" in r
