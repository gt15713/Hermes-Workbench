# -*- coding: utf-8 -*-
"""WB-S1-028 nudge/shared delivery lifecycle contracts (TDD RED -> GREEN)."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta

import pytest
import scheduler


@pytest.fixture()
def isolated_state(monkeypatch, tmp_path):
    state_file = tmp_path / "scheduler-state.json"
    monkeypatch.setattr(scheduler, "_STATE_FILE", state_file)
    monkeypatch.setattr(scheduler, "_LOG_FILE", tmp_path / "workbench-scheduler.log")
    scheduler._DELIVERY_SUCCESS_CACHE.clear()
    yield state_file
    scheduler._DELIVERY_SUCCESS_CACHE.clear()


def _write_state(path, state: dict) -> None:
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _mock_nudge(monkeypatch, delivery: str = "failed") -> list[str]:
    deliveries: list[str] = []
    monkeypatch.setattr(scheduler, "_script_data", lambda _name: {"overdue": ["task"]})
    monkeypatch.setattr(scheduler, "_generate", lambda *_args, **_kwargs: "generated nudge")
    monkeypatch.setattr(
        scheduler,
        "_split_output",
        lambda _text: {"worklog": "", "qq": "nudge message"},
    )
    monkeypatch.setattr(
        scheduler,
        "_deliver",
        lambda text: deliveries.append(text) or delivery,
    )
    return deliveries


def _run_nudge(attempt_key: str) -> None:
    asyncio.run(scheduler.Scheduler(None)._run_job({"key": "nudge"}, attempt_key))


def _identity_pending(job_key: str, text: str, attempt_key: str, error_id: str) -> dict:
    return {
        "schema_version": scheduler._PENDING_DELIVERY_SCHEMA_VERSION,
        "job_key": job_key,
        "attempt_key": attempt_key,
        "message_id": scheduler._message_identity(text),
        "error_id": error_id,
        "text": text,
        "attempts": 0,
        "next_attempt_at": (datetime.now() - timedelta(minutes=1)).isoformat(timespec="seconds"),
    }


def test_nudge_failure_queues_parseable_lifecycle_identity(monkeypatch, isolated_state):
    attempt_key = "nudge|2026-08-29 12:15"
    deliveries = _mock_nudge(monkeypatch)

    _run_nudge(attempt_key)

    state = scheduler._load_state()
    pending = state["pending_delivery"]
    assert deliveries == ["nudge message"]
    assert scheduler._identity_bound_pending(pending)
    assert pending["job_key"] == "nudge"
    assert pending["attempt_key"] == attempt_key
    assert pending["message_id"] == scheduler._message_identity("nudge message")
    assert pending["error_id"] == state["errors"]["last"]["id"]
    assert "legacy_unresolved" not in pending
    assert state["job_states"]["nudge"]["phase"] == scheduler.PHASE_ARTIFACT_WRITTEN


def test_nudge_retry_success_completes_only_original_attempt(monkeypatch, isolated_state):
    attempt_key = "nudge|2026-08-29 12:15"
    _mock_nudge(monkeypatch)
    _run_nudge(attempt_key)
    state = scheduler._load_state()
    original_error_id = state["errors"]["last"]["id"]
    state["pending_delivery"]["next_attempt_at"] = "2020-01-01T00:00:00"
    scheduler._save_state(state)
    retry_deliveries: list[str] = []
    monkeypatch.setattr(
        scheduler,
        "_deliver",
        lambda text: retry_deliveries.append(text) or "sent",
    )

    assert scheduler._retry_pending_delivery() is True

    final = scheduler._load_state()
    job_state = final["job_states"]["nudge"]
    assert retry_deliveries == ["nudge message"]
    assert job_state["attempt_key"] == attempt_key
    assert job_state["phase"] == scheduler.PHASE_COMPLETED
    assert job_state["delivery_sent_at"]
    assert job_state["completed_at"]
    assert final["last_runs"]["nudge"] == attempt_key
    assert final["pending_delivery"] is None
    assert final["errors"]["count"] == 0
    assert final["errors"]["last"] is None
    assert all(
        item.get("id") != original_error_id
        for item in final["errors"].get("unresolved", [])
    )


def test_shared_slot_collision_preserves_daily_and_exposes_nudge_error(monkeypatch, isolated_state):
    daily_attempt = "daily_report|2026-08-29 20:00"
    daily_error = {
        "id": "daily-error",
        "job": "daily_report",
        "attempt_key": daily_attempt,
        "at": "2026-08-29T20:00:05",
        "reason": "delivery:failed",
    }
    daily_pending = _identity_pending(
        "daily_report", "daily message", daily_attempt, daily_error["id"]
    )
    _write_state(
        isolated_state,
        {
            "schema_version": 2,
            "last_runs": {},
            "job_states": {
                "daily_report": {
                    "phase": scheduler.PHASE_ARTIFACT_WRITTEN,
                    "attempt_key": daily_attempt,
                }
            },
            "errors": {"count": 1, "last": daily_error, "unresolved": [daily_error]},
            "pending_delivery": daily_pending,
        },
    )
    _mock_nudge(monkeypatch)
    summaries: list[dict] = []
    monkeypatch.setattr(
        scheduler,
        "_append_log",
        lambda _job, _started, _ok, summary: summaries.append(summary),
    )
    nudge_attempt = "nudge|2026-08-29 12:15"

    _run_nudge(nudge_attempt)

    state = scheduler._load_state()
    assert state["pending_delivery"] == daily_pending
    assert summaries[-1]["queued_retry"] is False
    assert state["errors"]["count"] == 2
    assert state["errors"]["last"]["job"] == "nudge"
    assert state["errors"]["last"]["attempt_key"] == nudge_attempt
    assert state["errors"]["last"]["reason"] == "delivery:failed"
    assert {item["id"] for item in state["errors"]["unresolved"]} == {
        "daily-error",
        state["errors"]["last"]["id"],
    }
    assert state["job_states"]["daily_report"]["attempt_key"] == daily_attempt
    assert state["job_states"]["nudge"]["phase"] == scheduler.PHASE_FAILED


def test_legacy_pending_success_stays_explicitly_unresolved(monkeypatch, isolated_state):
    attempt_key = "nudge|2026-08-28 12:15"
    _write_state(
        isolated_state,
        {
            "last_runs": {},
            "job_states": {
                "nudge": {
                    "phase": scheduler.PHASE_ARTIFACT_WRITTEN,
                    "attempt_key": attempt_key,
                }
            },
            "errors": {
                "count": 1,
                "last": {"job": "nudge", "reason": "delivery:failed"},
            },
            "pending_delivery": {
                "text": "legacy nudge",
                "attempts": 0,
                "next_attempt_at": "2020-01-01T00:00:00",
            },
        },
    )
    monkeypatch.setattr(scheduler, "_deliver", lambda _text: "sent")

    assert scheduler._retry_pending_delivery() is True

    state = scheduler._load_state()
    assert state["pending_delivery"] is None
    assert state["last_runs"] == {}
    assert state["job_states"]["nudge"]["phase"] == scheduler.PHASE_ARTIFACT_WRITTEN
    assert state["errors"]["count"] == 1
    assert state["errors"]["last"]["reason"] == "delivery:legacy-sent-unresolved"
    assert state["legacy_delivery_unresolved"]["job_key"] == "nudge"


def test_at_least_once_across_process_restart_can_resend_after_success_before_save(
    monkeypatch, isolated_state
):
    """Document the crash window: process-local cache is not durable exactly-once."""
    attempt_key = "nudge|2026-08-29 12:15"
    error = {
        "id": "nudge-error",
        "job": "nudge",
        "attempt_key": attempt_key,
        "reason": "delivery:failed",
    }
    _write_state(
        isolated_state,
        {
            "last_runs": {},
            "job_states": {
                "nudge": {
                    "phase": scheduler.PHASE_ARTIFACT_WRITTEN,
                    "attempt_key": attempt_key,
                }
            },
            "errors": {"count": 1, "last": error, "unresolved": [error]},
            "pending_delivery": _identity_pending(
                "nudge", "nudge message", attempt_key, error["id"]
            ),
        },
    )
    deliveries: list[str] = []
    monkeypatch.setattr(
        scheduler,
        "_deliver",
        lambda text: deliveries.append(text) or "sent",
    )
    real_save = scheduler._save_state
    save_calls = {"count": 0}

    def fail_first_save(state):
        save_calls["count"] += 1
        if save_calls["count"] == 1:
            return False
        return real_save(state)

    monkeypatch.setattr(scheduler, "_save_state", fail_first_save)
    assert scheduler._retry_pending_delivery() is False
    assert deliveries == ["nudge message"]

    # Simulated restart loses only the in-memory success cache. The persisted
    # pending item is intentionally retried: at-least-once, possibly duplicated.
    scheduler._DELIVERY_SUCCESS_CACHE.clear()
    assert scheduler._retry_pending_delivery() is True
    assert deliveries == ["nudge message", "nudge message"]
    assert scheduler._load_state()["job_states"]["nudge"]["phase"] == scheduler.PHASE_COMPLETED
