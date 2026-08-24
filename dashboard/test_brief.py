# -*- coding: utf-8 -*-
"""Today briefing must be deterministic and evidence-backed."""

import plugin_api


def _board(*tasks):
    return {"today": "2026-08-24", "sections": [{"key": "task", "files": list(tasks)}]}


def test_brief_explains_each_rule(monkeypatch):
    monkeypatch.setattr(plugin_api, "board", lambda: _board(
        {"title": "旧任务", "status": "todo", "due": "2026-08-20"},
        {"title": "执行中", "status": "in_progress", "execution_result": "pending"},
        {"title": "已成功", "status": "done", "execution_result": "success"},
    ))
    plugin_api._BRIEF_CACHE = {"ts": 0.0, "payload": None}
    data = plugin_api.brief()
    assert data["schema_version"] == 2
    assert data["degraded"] is False
    assert {c["rule"] for c in data["cards"]} == {
        "due_before_today", "in_progress_without_terminal_result", "completed_task_still_active"
    }
    assert all(c["evidence"] for c in data["cards"])


def test_brief_does_not_invent_advice_without_evidence(monkeypatch):
    monkeypatch.setattr(plugin_api, "board", lambda: _board(
        {"title": "正常待办", "status": "todo", "due": "2026-08-25"}
    ))
    plugin_api._BRIEF_CACHE = {"ts": 0.0, "payload": None}
    assert plugin_api.brief()["cards"] == []


def test_brief_routes_in_progress_terminal_results_truthfully(monkeypatch):
    monkeypatch.setattr(plugin_api, "board", lambda: _board(
        {"title": "执行成功", "status": "in_progress", "execution_result": "success"},
        {"title": "执行失败", "status": "in_progress", "execution_result": "failure"},
    ))
    plugin_api._BRIEF_CACHE = {"ts": 0.0, "payload": None}

    cards = plugin_api.brief()["cards"]

    assert [c["rule"] for c in cards] == [
        "completed_task_still_active", "failed_execution_needs_recovery"
    ]
    assert all(c["rule"] != "in_progress_without_terminal_result" for c in cards)


def test_brief_cache_hits(monkeypatch):
    calls = {"n": 0}
    def fake_board():
        calls["n"] += 1
        return _board()
    monkeypatch.setattr(plugin_api, "board", fake_board)
    plugin_api._BRIEF_CACHE = {"ts": 0.0, "payload": None}
    plugin_api.brief()
    plugin_api.brief()
    assert calls["n"] == 1


def test_brief_degraded_on_board_failure(monkeypatch):
    def boom():
        raise RuntimeError("board unavailable")
    monkeypatch.setattr(plugin_api, "board", boom)
    plugin_api._BRIEF_CACHE = {"ts": 0.0, "payload": None}
    data = plugin_api.brief()
    assert data["degraded"] is True
    assert data["cards"] == []
