# -*- coding: utf-8 -*-
"""WB-S1-027 lifecycle-bound delivery retry contracts (TDD RED -> GREEN)."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta

import pytest
import scheduler


@pytest.fixture()
def isolated_state(monkeypatch, tmp_path):
    state_file = tmp_path / "scheduler-state.json"
    log_file = tmp_path / "workbench-scheduler.log"
    monkeypatch.setattr(scheduler, "_STATE_FILE", state_file)
    monkeypatch.setattr(scheduler, "_LOG_FILE", log_file)
    scheduler._DELIVERY_SUCCESS_CACHE.clear()
    yield state_file
    scheduler._DELIVERY_SUCCESS_CACHE.clear()


def _write_state(path, state: dict) -> None:
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def test_unqueued_delivery_failure_stays_actionable(isolated_state):
    attempt_key = "daily_report|2026-08-29 20:00"
    _write_state(
        isolated_state,
        {
            "schema_version": 2,
            "last_runs": {},
            "job_states": {
                "daily_report": {
                    "phase": "failed",
                    "attempt_key": attempt_key,
                    "last_error": "delivery:error-no-hermes",
                }
            },
            "errors": {
                "count": 1,
                "last": {
                    "job": "daily_report",
                    "at": "2026-08-29T20:00:05",
                    "reason": "delivery:error-no-hermes",
                },
            },
            "pending_delivery": None,
        },
    )

    count, last = scheduler._active_errors(scheduler._load_state())

    assert count == 1
    assert last is not None
    assert last["reason"] == "delivery:error-no-hermes"


@pytest.mark.parametrize("reason", ["delivery:failed", "delivery:error-no-hermes"])
def test_pending_null_never_proves_delivery_recovery(reason, isolated_state):
    _write_state(
        isolated_state,
        {
            "last_runs": {},
            "job_states": {},
            "errors": {"count": 1, "last": {"job": "daily_report", "reason": reason}},
            "pending_delivery": None,
        },
    )
    assert scheduler._active_errors(scheduler._load_state()) == (
        1,
        {"job": "daily_report", "reason": reason},
    )


def test_queue_occupied_rejection_preserves_existing_pending_and_error(isolated_state):
    _write_state(
        isolated_state,
        {
            "last_runs": {},
            "job_states": {},
            "errors": {
                "count": 1,
                "last": {"job": "daily_report", "reason": "delivery:failed"},
            },
            "pending_delivery": {"text": "first message", "attempts": 0},
        },
    )
    assert scheduler._queue_delivery("conflicting message") is False
    state = scheduler._load_state()
    assert state["pending_delivery"]["text"] == "first message"
    assert scheduler._active_errors(state)[0] == 1


def test_dropped_retry_remains_actionable(monkeypatch, isolated_state):
    _write_state(
        isolated_state,
        {
            "last_runs": {},
            "job_states": {},
            "errors": {
                "count": 1,
                "last": {"job": "daily_report", "reason": "delivery:failed"},
            },
            "pending_delivery": {
                "text": "drop me",
                "attempts": scheduler._DELIVERY_RETRY_MAX - 1,
                "next_attempt_at": (datetime.now() - timedelta(minutes=1)).isoformat(timespec="seconds"),
            },
        },
    )
    monkeypatch.setattr(scheduler, "_deliver", lambda _text: "failed")
    assert scheduler._retry_pending_delivery() is False
    state = scheduler._load_state()
    assert state["pending_delivery"] is None
    assert state["errors"]["last"]["reason"] == "delivery:dropped"
    assert scheduler._active_errors(state)[0] == 1


def test_legacy_pending_without_identity_is_explicitly_unresolved(isolated_state):
    _write_state(
        isolated_state,
        {
            "last_runs": {},
            "job_states": {},
            "errors": {
                "count": 1,
                "last": {"job": "daily_report", "reason": "delivery:error-no-hermes"},
            },
            "pending_delivery": {
                "text": "legacy message",
                "attempts": 0,
                "next_attempt_at": (datetime.now() + timedelta(minutes=1)).isoformat(timespec="seconds"),
            },
        },
    )
    state = scheduler._load_state()
    count, last = scheduler._active_errors(state)
    assert count == 1 and last is not None
    assert state["pending_delivery"].get("job_key") is None


def test_corrupt_state_is_actionable_fail_closed(isolated_state):
    isolated_state.write_text("{not-json", encoding="utf-8")
    state = scheduler._load_state()
    count, last = scheduler._active_errors(state)
    assert count >= 1
    assert last is not None
    assert last["reason"] == "state:corrupt-or-unreadable"


def test_non_delivery_error_is_not_reduced_by_delivery_queue_shape(isolated_state):
    _write_state(
        isolated_state,
        {
            "last_runs": {},
            "job_states": {},
            "errors": {
                "count": 2,
                "last": {"job": "maintenance", "reason": "exception:disk-full"},
            },
            "pending_delivery": None,
        },
    )
    count, last = scheduler._active_errors(scheduler._load_state())
    assert count == 2
    assert last["reason"] == "exception:disk-full"


def test_identity_bound_retry_success_completes_original_attempt(monkeypatch, isolated_state):
    attempt_key = "daily_report|2026-08-29 20:00"
    error_id = "daily_report|2026-08-29T20:00:05|delivery:error-no-hermes"
    _write_state(
        isolated_state,
        {
            "schema_version": 2,
            "last_runs": {},
            "job_states": {
                "daily_report": {
                    "phase": "artifact_written",
                    "attempt_key": attempt_key,
                    "started_at": "2026-08-29T20:00:05",
                    "artifact_written_at": "2026-08-29T20:00:06",
                    "last_error": "delivery:error-no-hermes; queued for retry",
                }
            },
            "errors": {
                "count": 1,
                "last": {
                    "id": error_id,
                    "job": "daily_report",
                    "attempt_key": attempt_key,
                    "at": "2026-08-29T20:00:05",
                    "reason": "delivery:error-no-hermes",
                },
            },
            "pending_delivery": {
                "schema_version": 2,
                "job_key": "daily_report",
                "attempt_key": attempt_key,
                "message_id": scheduler._message_identity("recoverable message"),
                "error_id": error_id,
                "text": "recoverable message",
                "attempts": 0,
                "next_attempt_at": (
                    datetime.now() - timedelta(minutes=1)
                ).isoformat(timespec="seconds"),
            },
        },
    )
    monkeypatch.setattr(scheduler, "_deliver", lambda _text: "sent")

    assert scheduler._retry_pending_delivery() is True
    state = scheduler._load_state()
    job_state = state["job_states"]["daily_report"]
    assert job_state["phase"] == scheduler.PHASE_COMPLETED
    assert job_state["attempt_key"] == attempt_key
    assert "delivery_sent_at" in job_state
    assert "completed_at" in job_state
    assert state["last_runs"]["daily_report"] == attempt_key
    assert state["pending_delivery"] is None
    assert state["errors"]["count"] == 0
    assert state["errors"]["last"] is None


def _identity_pending(text: str, attempt_key: str, error_id: str) -> dict:
    return {
        "schema_version": 2,
        "job_key": "daily_report",
        "attempt_key": attempt_key,
        "message_id": scheduler._message_identity(text),
        "error_id": error_id,
        "text": text,
        "attempts": 0,
        "next_attempt_at": (datetime.now() - timedelta(minutes=1)).isoformat(timespec="seconds"),
    }


def test_queue_schema_and_duplicate_are_identity_bound(isolated_state):
    attempt_key = "daily_report|2026-08-29 20:00"
    error_id = "error-1"
    assert scheduler._queue_delivery(
        "same message",
        job_key="daily_report",
        attempt_key=attempt_key,
        error_id=error_id,
    )
    first = scheduler._load_state()["pending_delivery"]
    assert first["schema_version"] == 2
    assert first["job_key"] == "daily_report"
    assert first["attempt_key"] == attempt_key
    assert first["message_id"] == scheduler._message_identity("same message")
    assert first["error_id"] == error_id
    assert first["attempts"] == 0
    assert first["next_attempt_at"]

    assert scheduler._queue_delivery(
        "same message",
        job_key="daily_report",
        attempt_key=attempt_key,
        error_id=error_id,
    )
    assert scheduler._load_state()["pending_delivery"] == first
    assert not scheduler._queue_delivery(
        "same message",
        job_key="daily_report",
        attempt_key="daily_report|2026-08-30 20:00",
        error_id="error-2",
    )
    assert scheduler._load_state()["pending_delivery"] == first


def test_run_job_passes_original_attempt_identity_to_daily_queue(monkeypatch, isolated_state):
    import asyncio

    attempt_key = "daily_report|2026-08-29 20:00"

    def runner(_ctx):
        context = scheduler._DELIVERY_CONTEXT.get()
        reason = "delivery:failed"
        error_id = scheduler._error_identity(
            context["job_key"], context["attempt_key"], context["started_at"], reason
        )
        assert scheduler._queue_delivery(
            "daily report message",
            job_key=context["job_key"],
            attempt_key=context["attempt_key"],
            error_id=error_id,
        )
        return {
            "worklog": "written",
            "delivery": "failed",
            "queued_retry": True,
            "delivery_validation": {"required": True, "status": "failed", "ok": False},
        }

    monkeypatch.setitem(scheduler._JOB_RUNNERS, "daily_report", runner)
    asyncio.run(scheduler.Scheduler(None)._run_job({"key": "daily_report"}, attempt_key))
    state = scheduler._load_state()
    pending = state["pending_delivery"]
    assert pending["job_key"] == "daily_report"
    assert pending["attempt_key"] == attempt_key
    assert pending["error_id"] == state["errors"]["last"]["id"]
    assert state["job_states"]["daily_report"]["phase"] == scheduler.PHASE_ARTIFACT_WRITTEN


def test_retry_resolves_only_matching_error(monkeypatch, isolated_state):
    attempt_key = "daily_report|2026-08-29 20:00"
    delivery_error = {
        "id": "delivery-error",
        "job": "daily_report",
        "attempt_key": attempt_key,
        "at": "2026-08-29T20:00:05",
        "reason": "delivery:failed",
    }
    other_error = {
        "id": "other-error",
        "job": "maintenance",
        "attempt_key": "maintenance|2026-08-29 04:00",
        "at": "2026-08-29T04:00:05",
        "reason": "exception:disk-full",
    }
    _write_state(
        isolated_state,
        {
            "last_runs": {},
            "job_states": {
                "daily_report": {"phase": "artifact_written", "attempt_key": attempt_key}
            },
            "errors": {
                "count": 2,
                "last": delivery_error,
                "unresolved": [other_error, delivery_error],
            },
            "pending_delivery": _identity_pending("message", attempt_key, "delivery-error"),
        },
    )
    monkeypatch.setattr(scheduler, "_deliver", lambda _text: "sent")
    assert scheduler._retry_pending_delivery()
    state = scheduler._load_state()
    assert state["errors"]["count"] == 1
    assert state["errors"]["last"]["id"] == "other-error"
    assert state["errors"]["unresolved"] == [other_error]


def test_conflicting_attempt_never_sends_or_completes(monkeypatch, isolated_state):
    old_attempt = "daily_report|2026-08-29 20:00"
    new_attempt = "daily_report|2026-08-30 20:00"
    pending = _identity_pending("message", old_attempt, "delivery-error")
    _write_state(
        isolated_state,
        {
            "last_runs": {},
            "job_states": {"daily_report": {"phase": "artifact_written", "attempt_key": new_attempt}},
            "errors": {"count": 1, "last": {"id": "delivery-error", "reason": "delivery:failed"}},
            "pending_delivery": pending,
        },
    )
    calls = []
    monkeypatch.setattr(scheduler, "_deliver", lambda text: calls.append(text) or "sent")
    assert not scheduler._retry_pending_delivery()
    state = scheduler._load_state()
    assert calls == []
    assert state["pending_delivery"]["unresolved_reason"] == "delivery:identity-conflict"
    assert state["job_states"]["daily_report"]["attempt_key"] == new_attempt
    assert state["last_runs"] == {}


def test_repeated_success_is_idempotent_without_resend(monkeypatch, isolated_state):
    attempt_key = "daily_report|2026-08-29 20:00"
    pending = _identity_pending("message", attempt_key, "delivery-error")
    _write_state(
        isolated_state,
        {
            "last_runs": {"daily_report": attempt_key},
            "job_states": {
                "daily_report": {
                    "phase": "completed",
                    "attempt_key": attempt_key,
                    "delivery_sent_at": "2026-08-29T20:01:00",
                    "completed_at": "2026-08-29T20:01:00",
                }
            },
            "errors": {"count": 0, "last": None},
            "pending_delivery": pending,
        },
    )
    monkeypatch.setattr(
        scheduler,
        "_deliver",
        lambda _text: pytest.fail("completed attempt must not resend"),
    )
    assert scheduler._retry_pending_delivery()
    state = scheduler._load_state()
    assert state["pending_delivery"] is None
    assert state["last_runs"]["daily_report"] == attempt_key
    assert state["job_states"]["daily_report"]["completed_at"] == "2026-08-29T20:01:00"


def test_save_failure_reentry_does_not_resend(monkeypatch, isolated_state):
    attempt_key = "daily_report|2026-08-29 20:00"
    pending = _identity_pending("message", attempt_key, "delivery-error")
    _write_state(
        isolated_state,
        {
            "last_runs": {},
            "job_states": {
                "daily_report": {"phase": "artifact_written", "attempt_key": attempt_key}
            },
            "errors": {
                "count": 1,
                "last": {"id": "delivery-error", "reason": "delivery:failed"},
            },
            "pending_delivery": pending,
        },
    )
    deliveries = []
    monkeypatch.setattr(scheduler, "_deliver", lambda text: deliveries.append(text) or "sent")
    real_save = scheduler._save_state
    saves = {"count": 0}

    def fail_first_save(state):
        saves["count"] += 1
        if saves["count"] == 1:
            return False
        return real_save(state)

    monkeypatch.setattr(scheduler, "_save_state", fail_first_save)
    assert not scheduler._retry_pending_delivery()
    assert scheduler._retry_pending_delivery()
    assert deliveries == ["message"]
    state = scheduler._load_state()
    assert state["pending_delivery"] is None
    assert state["last_runs"]["daily_report"] == attempt_key


def test_legacy_success_stays_unresolved_and_does_not_complete(monkeypatch, isolated_state):
    attempt_key = "daily_report|2026-08-29 20:00"
    _write_state(
        isolated_state,
        {
            "last_runs": {},
            "job_states": {
                "daily_report": {"phase": "artifact_written", "attempt_key": attempt_key}
            },
            "errors": {
                "count": 1,
                "last": {"job": "daily_report", "reason": "delivery:failed"},
            },
            "pending_delivery": {
                "text": "legacy message",
                "attempts": 0,
                "next_attempt_at": (datetime.now() - timedelta(minutes=1)).isoformat(timespec="seconds"),
            },
        },
    )
    monkeypatch.setattr(scheduler, "_deliver", lambda _text: "sent")
    assert scheduler._retry_pending_delivery()
    state = scheduler._load_state()
    assert state["pending_delivery"] is None
    assert state["last_runs"] == {}
    assert state["job_states"]["daily_report"]["phase"] == "artifact_written"
    assert state["legacy_delivery_unresolved"]["reason"] == "delivery:legacy-sent-unresolved"
    assert scheduler._active_errors(state)[0] == 1


def test_identity_retry_drop_never_completes_attempt(monkeypatch, isolated_state):
    attempt_key = "daily_report|2026-08-29 20:00"
    pending = _identity_pending("message", attempt_key, "delivery-error")
    pending["attempts"] = scheduler._DELIVERY_RETRY_MAX - 1
    _write_state(
        isolated_state,
        {
            "last_runs": {},
            "job_states": {
                "daily_report": {"phase": "artifact_written", "attempt_key": attempt_key}
            },
            "errors": {
                "count": 1,
                "last": {
                    "id": "delivery-error",
                    "job": "daily_report",
                    "attempt_key": attempt_key,
                    "reason": "delivery:failed",
                },
            },
            "pending_delivery": pending,
        },
    )
    monkeypatch.setattr(scheduler, "_deliver", lambda _text: "failed")
    assert not scheduler._retry_pending_delivery()
    state = scheduler._load_state()
    assert state["pending_delivery"] is None
    assert state["last_runs"] == {}
    assert state["job_states"]["daily_report"]["phase"] == "artifact_written"
    assert state["job_states"]["daily_report"]["last_error"] == "delivery:dropped"
    assert state["errors"]["last"]["reason"] == "delivery:dropped"
    assert state["dropped_deliveries"][0]["attempt_key"] == attempt_key


def test_legacy_unresolved_blocks_daily_catch_up(monkeypatch, isolated_state):
    import workbench_config

    _write_state(
        isolated_state,
        {
            "last_runs": {},
            "job_states": {},
            "errors": {
                "count": 1,
                "last": {"job": "daily_report", "reason": "delivery:legacy-sent-unresolved"},
            },
            "pending_delivery": None,
            "legacy_delivery_unresolved": {
                "job_key": "daily_report",
                "message_id": "legacy-message",
                "reason": "delivery:legacy-sent-unresolved",
            },
        },
    )
    monkeypatch.setattr(workbench_config, "get_catch_up_hours", lambda: 24)
    monkeypatch.setattr(workbench_config, "get_schedule", lambda: {})
    monkeypatch.setattr(
        scheduler,
        "JOBS",
        [{"key": "daily_report", "expr": f"{datetime.now().minute} {datetime.now().hour} * * *"}],
    )
    calls = []

    async def fake_run(_job, _attempt_key):
        calls.append((_job, _attempt_key))

    instance = scheduler.Scheduler(None)
    monkeypatch.setattr(instance, "_run_job", fake_run)
    asyncio.run(instance._catch_up())
    assert calls == []


def test_error_identity_mismatch_never_completes_after_send(monkeypatch, isolated_state):
    attempt_key = "daily_report|2026-08-29 20:00"
    pending = _identity_pending("message", attempt_key, "wrong-error")
    _write_state(
        isolated_state,
        {
            "last_runs": {},
            "job_states": {
                "daily_report": {"phase": "artifact_written", "attempt_key": attempt_key}
            },
            "errors": {
                "count": 1,
                "last": {"id": "actual-error", "reason": "delivery:failed"},
                "unresolved": [{"id": "actual-error", "reason": "delivery:failed"}],
            },
            "pending_delivery": pending,
        },
    )
    calls = []
    monkeypatch.setattr(scheduler, "_deliver", lambda text: calls.append(text) or "sent")
    assert not scheduler._retry_pending_delivery()
    state = scheduler._load_state()
    assert calls == ["message"]
    assert state["job_states"]["daily_report"]["phase"] == "artifact_written"
    assert state["last_runs"] == {}
    assert state["pending_delivery"]["unresolved_reason"] == "delivery:identity-unresolved"
    assert state["errors"]["count"] == 1


def test_duplicate_error_identity_does_not_increment_count(isolated_state):
    attempt_key = "daily_report|2026-08-29 20:00"
    started_at = "2026-08-29T20:00:05"
    scheduler._record_error("daily_report", started_at, "delivery:failed", attempt_key)
    scheduler._record_error("daily_report", started_at, "delivery:failed", attempt_key)
    state = scheduler._load_state()
    assert state["errors"]["count"] == 1
    assert len(state["errors"]["unresolved"]) == 1
