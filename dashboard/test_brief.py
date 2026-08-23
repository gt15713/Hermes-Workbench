# -*- coding: utf-8 -*-
"""P0-1（B4）：/brief 端点测试（schema / 缓存 / degraded 降级）。

生成通道 subprocess `hermes -z` 用 monkeypatch 替换（测试不真实调用 Hermes）。
"""

import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import plugin_api

_app = FastAPI()
_app.include_router(plugin_api.router)
client = TestClient(_app)


class _FakeResult:
    def __init__(self, out: str):
        self.stdout = out
        self.stderr = ""


def test_brief_schema_and_type_filter(monkeypatch):
    def fake_run(cmd, **kwargs):
        cards = [
            {"type": "new_task", "title": "采购", "reason": "会话提及", "action": "ingest"},
            {"type": "duplicate", "title": "重复", "reason": "与X相同", "action": "view"},
            {"type": "blocked", "title": "阻塞", "reason": "等审批", "action": "view"},
            {"type": "overdue", "title": "超期", "reason": "5天", "action": "reassess"},
            {"type": "decision", "title": "决策", "reason": "需拍板", "action": "view"},
            {"type": "bad_type", "title": "非法类型", "reason": "应过滤", "action": "x"},
        ]
        return _FakeResult(json.dumps(cards, ensure_ascii=False))

    monkeypatch.setattr("subprocess.run", fake_run)
    plugin_api._BRIEF_CACHE = {"ts": 0.0, "payload": None}
    r = client.post("/brief")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["degraded"] is False
    assert len(data["cards"]) == 5  # 非法类型被过滤，≤5
    for c in data["cards"]:
        assert c["type"] in ("new_task", "duplicate", "blocked", "overdue", "decision")


def test_brief_cache_hits(monkeypatch):
    calls = {"n": 0}

    def fake_run(cmd, **kwargs):
        calls["n"] += 1
        return _FakeResult(json.dumps([{"type": "decision", "title": "D", "reason": "r", "action": "view"}]))

    monkeypatch.setattr("subprocess.run", fake_run)
    plugin_api._BRIEF_CACHE = {"ts": 0.0, "payload": None}
    client.post("/brief")
    client.post("/brief")
    client.post("/brief")
    assert calls["n"] == 1  # 缓存命中，只生成一次


def test_brief_degraded_on_failure(monkeypatch):
    def boom(cmd, **kwargs):
        raise RuntimeError("hermes unavailable")

    monkeypatch.setattr("subprocess.run", boom)
    plugin_api._BRIEF_CACHE = {"ts": 0.0, "payload": None}
    r = client.post("/brief")
    data = r.json()
    assert data["ok"] is True
    assert data["degraded"] is True
    assert data["cards"] == []
