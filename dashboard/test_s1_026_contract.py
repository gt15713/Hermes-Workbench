# -*- coding: utf-8 -*-
"""WB-S1-026 schema/parser/delivery lifecycle contract (RED -> GREEN)."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import scheduler

DAILY_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "workbench_daily_report.py"


def _load_daily_module():
    spec = importlib.util.spec_from_file_location("wb_s1_026_daily_report", DAILY_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _valid_data() -> dict:
    return {
        "today": "2026-08-29",
        "is_sunday": False,
        "processed": ["完成契约修复"],
        "pending": [{"label": "任务", "title": "交 CoderX 审查", "due": "", "blocked": False}],
        "week": {
            "monday": "2026-08-24",
            "completed": ["完成契约修复"],
            "completed_count": 1,
            "new_count": 1,
            "remaining_count": 1,
            "due_next_week": 0,
            "blocked_count": 0,
        },
    }


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda d: d.pop("today"), "today missing or not str"),
        (lambda d: d.__setitem__("processed", "bad"), "processed not list[str]"),
        (lambda d: d.__setitem__("pending", [{"title": "missing label"}]), "pending[0] missing title/label"),
        (lambda d: d.pop("week"), "week not dict"),
        (lambda d: d["week"].__setitem__("completed", "bad"), "week.completed not list[str]"),
        (lambda d: d["week"].__setitem__("new_count", "1"), "week.new_count not int"),
    ],
)
def test_schema_invalid_has_exact_field_issue(mutate, expected):
    module = _load_daily_module()
    data = _valid_data()
    mutate(data)
    result = module.validate_report_data(data)
    assert result["schema_ok"] is False
    assert expected in result["issues"]
    assert result["issues"], "schema_ok=false must never have empty issues"


@pytest.mark.parametrize("argv", [[], ["--data"]])
def test_main_schema_invalid_stdout_empty_stderr_json_nonzero(monkeypatch, capsys, argv):
    module = _load_daily_module()
    bad = _valid_data()
    bad.pop("today")
    monkeypatch.setattr(module, "collect", lambda _date=None: bad)
    monkeypatch.setattr(sys, "argv", [str(DAILY_SCRIPT), *argv])
    rc = module.main()
    captured = capsys.readouterr()
    assert rc != 0
    assert captured.out == ""
    payload = json.loads(captured.err)
    assert payload["error"] == "daily_report_data_invalid"
    assert payload["schema_ok"] is False
    assert payload["schema_issues"]
    assert payload["fact_issues"] == []
    assert "today missing or not str" in payload["issues"]


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("prefix", "prefix<WORKLOG>a</WORKLOG><QQMSG>b</QQMSG>"),
        ("suffix", "<WORKLOG>a</WORKLOG><QQMSG>b</QQMSG>suffix"),
        ("duplicate", "<WORKLOG>a</WORKLOG><QQMSG>b</QQMSG><WORKLOG>c</WORKLOG><QQMSG>d</QQMSG>"),
        ("reverse", "<QQMSG>b</QQMSG><WORKLOG>a</WORKLOG>"),
        ("nested", "<WORKLOG>a<QQMSG>b</QQMSG></WORKLOG><QQMSG>c</QQMSG>"),
        ("crossed", "<WORKLOG>a<QQMSG>b</WORKLOG></QQMSG>"),
        ("empty-worklog", "<WORKLOG>  </WORKLOG><QQMSG>b</QQMSG>"),
        ("empty-qq", "<WORKLOG>a</WORKLOG><QQMSG>\n</QQMSG>"),
    ],
)
def test_strict_parser_rejects_invalid_matrix(name, text):
    result = scheduler._validate_fallback_text(text)
    assert result["ok"] is False, name
    assert result["issues"], name


def test_split_output_strict_and_validator_share_parser_contract():
    text = "\n<WORKLOG>alpha</WORKLOG>\n<QQMSG>beta</QQMSG>\n"
    parsed = scheduler._split_output(text, strict=True)
    validated = scheduler._validate_fallback_text(text)
    assert parsed["ok"] is True
    assert validated == parsed
    assert parsed["worklog"] == "alpha" and parsed["qq"] == "beta"


def test_split_output_loose_mode_remains_explicit_for_model_compatibility():
    assert scheduler._split_output("plain model text", strict=False) == {
        "worklog": "",
        "qq": "plain model text",
    }


def _result(status: str, *, required: bool = True, queued: bool = False) -> dict:
    ok = required and status == "sent"
    if not required:
        ok = status == "not_applicable"
    return {
        "generated": "ok",
        "worklog": "written",
        "delivery": status,
        "queued_retry": queued,
        "delivery_validation": {
            "required": required,
            "ok": ok,
            "status": status,
            "reason": "" if ok else status,
            "issues": [] if ok else [status],
        },
    }


@pytest.mark.parametrize(
    ("result", "expected_phase", "expected_health"),
    [
        (_result("sent"), scheduler.PHASE_DELIVERY_SENT, True),
        (_result("not_applicable", required=False), scheduler.PHASE_COMPLETED, True),
        (_result("failed", queued=True), scheduler.PHASE_ARTIFACT_WRITTEN, False),
        (_result("error-no-hermes", queued=True), scheduler.PHASE_ARTIFACT_WRITTEN, False),
        (_result("failed", queued=False), scheduler.PHASE_FAILED, False),
        (_result("error-no-hermes", queued=False), scheduler.PHASE_FAILED, False),
        (_result("unconfigured"), scheduler.PHASE_FAILED, False),
        (_result("skipped-empty"), scheduler.PHASE_FAILED, False),
        (_result("unknown-status"), scheduler.PHASE_FAILED, False),
    ],
)
def test_delivery_contract_matrix(result, expected_phase, expected_health):
    ok, reason = scheduler._result_health(result)
    phase, phase_error = scheduler._derive_phase("daily_report", result, ok, reason)
    assert ok is expected_health
    assert phase == expected_phase
    if not expected_health:
        assert phase_error


@pytest.fixture()
def isolated_state(monkeypatch, tmp_path):
    state_file = tmp_path / "scheduler-state.json"
    log_file = tmp_path / "workbench-scheduler.log"
    monkeypatch.setattr(scheduler, "_STATE_FILE", state_file)
    monkeypatch.setattr(scheduler, "_LOG_FILE", log_file)
    return state_file, log_file


@pytest.mark.parametrize(
    ("status", "required", "queued", "expected_phase", "completed"),
    [
        ("sent", True, False, scheduler.PHASE_COMPLETED, True),
        ("not_applicable", False, False, scheduler.PHASE_COMPLETED, True),
        ("failed", True, True, scheduler.PHASE_ARTIFACT_WRITTEN, False),
        ("error-no-hermes", True, True, scheduler.PHASE_ARTIFACT_WRITTEN, False),
        ("failed", True, False, scheduler.PHASE_FAILED, False),
        ("error-no-hermes", True, False, scheduler.PHASE_FAILED, False),
        ("unconfigured", True, False, scheduler.PHASE_FAILED, False),
        ("skipped-empty", True, False, scheduler.PHASE_FAILED, False),
        ("unknown-status", True, False, scheduler.PHASE_FAILED, False),
    ],
)
def test_run_job_required_non_sent_never_updates_last_runs(
    monkeypatch, isolated_state, status, required, queued, expected_phase, completed
):
    value = _result(status, required=required, queued=queued)
    monkeypatch.setattr(scheduler, "_JOB_RUNNERS", {"daily_report": lambda _ctx: deepcopy(value)})
    obj = scheduler.Scheduler(None)
    attempt = "daily_report|2026-08-29 20:00"
    asyncio.run(obj._run_job({"key": "daily_report"}, attempt))
    state = scheduler._load_state()
    assert state["job_states"]["daily_report"]["phase"] == expected_phase
    assert (state["last_runs"].get("daily_report") == attempt) is completed
    log_entry = json.loads(isolated_state[1].read_text(encoding="utf-8").splitlines()[-1])
    assert log_entry["ok"] is completed


def test_queue_delivery_same_message_is_idempotent(isolated_state):
    assert scheduler._queue_delivery("retry me") is True
    first = scheduler._load_state()["pending_delivery"]
    assert scheduler._queue_delivery("retry me") is True
    second = scheduler._load_state()["pending_delivery"]
    assert first == second


def test_error_no_hermes_queues_once_and_existing_retry_sends(monkeypatch, isolated_state):
    calls = []
    assert scheduler._queue_delivery("recoverable message") is True
    state = scheduler._load_state()
    state["pending_delivery"]["next_attempt_at"] = (
        datetime.now() - timedelta(minutes=1)
    ).isoformat(timespec="seconds")
    state["errors"] = {
        "count": 1,
        "last": {"job": "daily_report", "reason": "delivery:error-no-hermes"},
    }
    scheduler._save_state(state)
    monkeypatch.setattr(scheduler, "_deliver", lambda text: calls.append(text) or "sent")
    assert scheduler._retry_pending_delivery() is True
    assert calls == ["recoverable message"]
    final_state = scheduler._load_state()
    assert final_state["pending_delivery"] is None
    assert final_state["errors"]["count"] == 1
    assert final_state["errors"]["last"]["reason"] == "delivery:legacy-sent-unresolved"
    assert final_state["legacy_delivery_unresolved"]["reason"] == "delivery:legacy-sent-unresolved"


def test_job_daily_error_no_hermes_is_retryable_but_unconfigured_is_not(monkeypatch):
    queued = []
    monkeypatch.setattr(scheduler, "_script_data", lambda _name: {
        **_valid_data(),
        "data_validated": True,
        "factual_validation": {"ok": True, "issues": []},
    })
    monkeypatch.setattr(
        scheduler,
        "_generate",
        lambda *_args, **_kwargs: json.dumps(
            {"processed": ["P1"], "pending": ["Q1"], "week_completed": ["W1"]},
            ensure_ascii=False,
        ),
    )
    monkeypatch.setattr(scheduler, "_current_health_snapshot", lambda: {"status": "green"})
    monkeypatch.setattr(scheduler, "_write_daily_worklog", lambda _text: "written")
    monkeypatch.setattr(
        scheduler,
        "_queue_delivery",
        lambda text, **identity: queued.append((text, identity)) or True,
    )
    import workbench_config

    monkeypatch.setattr(workbench_config, "get_write_worklog", lambda: True)
    monkeypatch.setattr(scheduler, "_deliver", lambda _text: "error-no-hermes")
    transient = scheduler._job_daily_report(None)
    assert transient["queued_retry"] is True
    assert len(queued) == 1

    queued.clear()
    monkeypatch.setattr(scheduler, "_deliver", lambda _text: "unconfigured")
    permanent = scheduler._job_daily_report(None)
    assert permanent["queued_retry"] is False
    assert queued == []
