# -*- coding: utf-8 -*-
"""API-A（/edit 扩展 tags/priority）+ API-B（/ingest-message 补 created 事件）测试。

B1 切片验收（PRD §2.5 + TD §12）：
- API-A：文件级 tags 整体替换（去重）/ priority 校验（P0-P3，非法忽略）/ 条目级忽略不报错 / 向后兼容
- API-B：ingest 成功后 task_events 有 created 且仅一条 / duplicate 不补 / 失败仅告警
"""

import os
import sqlite3
from pathlib import Path

import plugin_api
from fastapi import FastAPI
from fastapi.testclient import TestClient
from wb_utils import _extract_frontmatter

_app = FastAPI()
_app.include_router(plugin_api.router)
client = TestClient(_app)


def _root() -> Path:
    return Path(os.environ["WORKBENCH_ROOT"])


def _db() -> sqlite3.Connection:
    return sqlite3.connect(os.environ["WORKBENCH_DB"])


def _mk_task(name: str = "任务A.md") -> Path:
    d = _root() / "任务"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text("---\ntype: task\nstatus: todo\n---\n\n# 任务A\n\n正文\n", encoding="utf-8")
    return p


def _mk_agg(name: str = "2026-08-16.md") -> Path:
    d = _root() / "待验证"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(
        "# 待验证收录 2026-08-16\n\n---\ntype: queued\nstatus: pending\n---\n\n## 条目X\n\n内容\n",
        encoding="utf-8",
    )
    return p


# ---------- API-A：/edit ----------

def test_edit_tags_overwrite_dedupe():
    p = _mk_task("tags卡.md")
    r = client.post("/edit", json={"dir": "任务", "file": p.name, "tags": ["a", "b", "a"]})
    assert r.status_code == 200
    assert r.json().get("ok") is True
    fm, _, _, _ = _extract_frontmatter(p.read_text(encoding="utf-8"))
    assert fm["tags"] == ["a", "b"]  # 整体替换 + 去重


def test_edit_tags_string_form_and_replace():
    p = _mk_task("tags卡2.md")
    client.post("/edit", json={"dir": "任务", "file": p.name, "tags": ["x"]})
    r = client.post("/edit", json={"dir": "任务", "file": p.name, "tags": "y, z"})
    assert r.json().get("ok") is True
    fm, _, _, _ = _extract_frontmatter(p.read_text(encoding="utf-8"))
    assert fm["tags"] == ["y", "z"]  # 第二次整体替换旧值


def test_edit_priority_normalize_and_invalid_ignored():
    p = _mk_task("prio卡.md")
    r = client.post("/edit", json={"dir": "任务", "file": p.name, "priority": "p1"})
    assert r.json().get("ok") is True
    fm, _, _, _ = _extract_frontmatter(p.read_text(encoding="utf-8"))
    assert fm["priority"] == "P1"  # 大小写归一
    r2 = client.post("/edit", json={"dir": "任务", "file": p.name, "priority": "P9"})
    assert r2.json().get("ok") is False  # 非法忽略 → 无变更
    assert r2.json().get("error") == "nothing to change"


def test_edit_entry_level_tags_ignored():
    p = _mk_agg()
    r = client.post(
        "/edit",
        json={"dir": "待验证", "file": p.name, "entry_title": "条目X", "title": "条目X2", "tags": ["t1"]},
    )
    assert r.status_code == 200
    assert r.json().get("ok") is True  # 条目级不报错
    fm, _, _, _ = _extract_frontmatter(p.read_text(encoding="utf-8"))
    assert "tags" not in fm  # tags 被忽略，未写入 frontmatter
    assert "## 条目X2" in p.read_text(encoding="utf-8")  # title 生效


def test_edit_backward_compat_no_new_params():
    p = _mk_task("兼容卡.md")
    r = client.post("/edit", json={"dir": "任务", "file": p.name, "title": "新标题"})
    assert r.json().get("ok") is True  # 不传新参数行为不变


# ---------- API-B：/ingest-message ----------

def test_ingest_creates_created_event_once():
    r = client.post("/ingest-message", json={"message_id": "b1-m1", "dir": "待验证", "title": "新条目A"})
    assert r.json().get("ok") is True
    # API-B：恰好一条带收录信息的 created 业务事件（UPDATE 镜像空行或 INSERT，两种场景都成立）
    rows = _db().execute(
        "SELECT payload FROM task_events WHERE kind='created' AND partition='待验证' AND payload LIKE '收录：新条目A%'"
    ).fetchall()
    assert len(rows) == 1


def test_ingest_duplicate_no_second_event():
    client.post("/ingest-message", json={"message_id": "b1-m2", "dir": "待验证", "title": "重复条目"})
    r2 = client.post("/ingest-message", json={"message_id": "b1-m2", "dir": "待验证", "title": "重复条目"})
    assert r2.json().get("duplicate") is True
    # duplicate 不重复补事件（幂等）
    rows = _db().execute(
        "SELECT payload FROM task_events WHERE kind='created' AND partition='待验证' AND payload LIKE '收录：重复条目%'"
    ).fetchall()
    assert len(rows) == 1
