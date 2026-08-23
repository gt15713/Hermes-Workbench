# -*- coding: utf-8 -*-
"""方案 Z：/edit amend=true 整体替换正文 + edited_by_user 标记（2026-08-20）。

依赖 conftest 注入的临时 WORKBENCH_ROOT（收集期生效），同步写法 + asyncio.run。
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import plugin_api as api


def test_edit_amend_replaces_body_and_marks():
    task_dir = Path(os.environ["WORKBENCH_ROOT"]) / "任务"
    task_dir.mkdir(exist_ok=True)
    f = task_dir / "测试任务.md"
    f.write_text(
        "---\ntype: task\nstatus: todo\nschema_version: 1\nsource: qq\n---\n\n"
        "# 测试任务\n\n原始内容行\n",
        encoding="utf-8",
    )

    res = asyncio.run(
        api.edit_entry({"dir": "任务", "file": "测试任务.md", "amend": True, "content": "修正后的正文\n第二行"})
    )
    assert res.get("ok") is True

    text = f.read_text(encoding="utf-8")
    assert "edited_by_user: true" in text
    assert "edited_at:" in text
    assert "type: task" in text  # frontmatter 保留
    assert "status: todo" in text
    assert "# 测试任务" not in text  # 旧正文被替换
    assert "修正后的正文" in text


def test_edit_amend_without_content_rejected():
    task_dir = Path(os.environ["WORKBENCH_ROOT"]) / "任务"
    task_dir.mkdir(exist_ok=True)
    f = task_dir / "测试任务2.md"
    f.write_text("---\ntype: task\nstatus: todo\n---\n\n# 测试任务2\n", encoding="utf-8")

    res = asyncio.run(api.edit_entry({"dir": "任务", "file": "测试任务2.md", "amend": True, "content": ""}))
    assert res.get("ok") is False
    assert "requires content" in res.get("error", "")
