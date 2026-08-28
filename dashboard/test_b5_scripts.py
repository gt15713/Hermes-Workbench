# -*- coding: utf-8 -*-
"""P0-4（B5）：nudge/日报 --data 输出契约 schema 测试。

subprocess 调用 scripts 脚本（WORKBENCH_ROOT/WORKBENCH_DB 指向 conftest 隔离目录），
校验 JSON 结构（PRD §4.5）与周日标记（SUNDAY_REVIEW=on）。
"""

import json
import os
import subprocess
import sys
from pathlib import Path

# P0-A：脚本已收编进插件包（dashboard 的上级 scripts/）
SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _run(script: str, root: Path, db: Path) -> tuple[int, str]:
    env = dict(os.environ)
    env["WORKBENCH_ROOT"] = str(root)
    env["WORKBENCH_DB"] = str(db)
    for d in ("待验证", "待回看", "任务", "心理学随想", "梦中的邮件", "已处理", "回收站", "日志"):
        (root / d).mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / script), "--data"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=30,
    )
    return r.returncode, (r.stdout or "").strip()


def test_nudge_data_schema(tmp_path):
    code, out = _run("workbench_auto_nudge.py", tmp_path, tmp_path / "wb.db")
    assert code == 0
    d = json.loads(out)
    # D1（P2-1）扩展：stale/duplicate 加入契约（旧字段保留）
    assert set(d.keys()) == {"date", "overdue", "blocked", "today_due", "stale", "duplicate"}
    assert isinstance(d["overdue"], list)
    assert isinstance(d["blocked"], list)
    assert isinstance(d["today_due"], list)
    assert isinstance(d["stale"], list)
    assert isinstance(d["duplicate"], list)


def test_report_data_schema_and_sunday_flag(tmp_path):
    code, out = _run("workbench_daily_report.py", tmp_path, tmp_path / "wb.db")
    assert code == 0
    d = json.loads(out)
    # D2（P2-2）扩展：week 周聚合加入契约；S1-006 新增 data_validated/factual_validation
    assert set(d.keys()) == {"today", "is_sunday", "processed", "pending", "week", "data_validated", "factual_validation"}
    assert d["data_validated"] is True
    assert d["factual_validation"]["ok"] is True
    assert isinstance(d["is_sunday"], bool)
    assert isinstance(d["processed"], list)
    assert isinstance(d["pending"], list)
    assert isinstance(d["week"], dict)
