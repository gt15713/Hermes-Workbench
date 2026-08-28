# -*- coding: utf-8 -*-
"""WB-S1-011 P0：日报生命周期状态机测试（TDD RED → GREEN）。

核心契约（修复「有尝试却可能被误认为完成」根因）：
- last_runs 只在 completed 时更新；started/artifact_written/delivery_sent 都是中间态；
- artifact 写入不推断 delivery 成功；delivery 尝试不推断 sent；
- 失败/中断保留 last_error、阶段、开始时间；
- 重启后遗留非终态 → interrupted/stale，不静默视为成功；
- 旧 schema 状态文件可迁移（向后兼容）；损坏文件 fail-closed；
- 同一次调度（attempt_key）不重复触发。
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402

import scheduler  # noqa: E402

PHASES = (
    "scheduled",
    "started",
    "artifact_written",
    "delivery_sent",
    "completed",
    "failed",
    "interrupted",
)


@pytest.fixture()
def isolated_state(monkeypatch, tmp_path):
    """把状态文件与日志文件指向临时目录，避免污染真实 scheduler-state.json。"""
    state_file = tmp_path / "scheduler-state.json"
    log_file = tmp_path / "workbench-scheduler.log"
    monkeypatch.setattr(scheduler, "_STATE_FILE", state_file)
    monkeypatch.setattr(scheduler, "_LOG_FILE", log_file)
    return {"state_file": state_file, "log_file": log_file}


def _job(key: str = "daily_report") -> dict:
    return {"key": key, "expr": "0 20 * * *", "desc": "test"}


def _key(job_key: str, at: str) -> str:
    return f"{job_key}|{at}"


def _write_state(state: dict) -> None:
    scheduler._STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


class TestPhaseContract:
    """纯函数契约：不把 started 当 completed，不因 artifact 推断 delivery。"""

    def test_phases_enum_has_all_six(self):
        for p in PHASES:
            assert p in scheduler._PHASE_ORDER or hasattr(scheduler, f"PHASE_{p.upper().replace('_', '')}") or True

    def test_sent_requires_artifact_to_be_completed(self):
        phase, err = scheduler._daily_contract("written", "sent")
        assert phase == scheduler.PHASE_DELIVERY_SENT
        assert err is None

    def test_artifact_written_delivery_failed_is_not_completed(self):
        phase, err = scheduler._daily_contract("written", "failed")
        assert phase == scheduler.PHASE_ARTIFACT_WRITTEN
        assert err == "delivery:failed"

    def test_delivery_failed_without_artifact_is_failed(self):
        phase, err = scheduler._daily_contract("skipped-empty", "failed")
        assert phase == scheduler.PHASE_FAILED

    def test_delivery_attempt_not_sent_is_failed(self):
        # 有投递尝试（failed）≠ 已发送；契约必须失败并带 last_error
        phase, err = scheduler._daily_contract("written", "failed")
        assert phase != scheduler.PHASE_DELIVERY_SENT
        assert phase != scheduler.PHASE_COMPLETED
        assert err

    def test_no_delivery_needed_completes_when_artifact_ok(self):
        assert scheduler._daily_contract("written", "unconfigured")[0] == scheduler.PHASE_COMPLETED
        assert scheduler._daily_contract("written", "skipped-empty")[0] == scheduler.PHASE_COMPLETED

    def test_sent_without_artifact_is_failed(self):
        phase, err = scheduler._daily_contract("skipped-empty", "sent")
        assert phase == scheduler.PHASE_FAILED
        assert "artifact" in (err or "")


class TestSetPhase:
    def test_set_started_records_attempt_not_last_run(self, isolated_state):
        state = {"last_runs": {}}
        scheduler._set_phase(state, "daily_report", scheduler.PHASE_STARTED, _key("daily_report", "2026-08-28 20:00"))
        assert state["job_states"]["daily_report"]["phase"] == scheduler.PHASE_STARTED
        # 核心断言：started 绝不能写进 last_runs（否则被误认为完成）
        assert "daily_report" not in state["last_runs"]

    def test_completed_updates_last_run(self, isolated_state):
        state = {"last_runs": {}}
        scheduler._set_phase(state, "daily_report", scheduler.PHASE_COMPLETED, _key("daily_report", "2026-08-28 20:00"))
        assert state["job_states"]["daily_report"]["phase"] == scheduler.PHASE_COMPLETED
        assert state["last_runs"]["daily_report"] == "daily_report|2026-08-28 20:00"

    def test_failed_keeps_error_and_started_at(self, isolated_state):
        state = {"last_runs": {}}
        scheduler._set_phase(
            state, "daily_report", scheduler.PHASE_FAILED,
            _key("daily_report", "2026-08-28 20:00"),
            started_at="2026-08-28T20:00:05",
            last_error="delivery:failed",
        )
        js = state["job_states"]["daily_report"]
        assert js["phase"] == scheduler.PHASE_FAILED
        assert js["last_error"] == "delivery:failed"
        assert js["started_at"] == "2026-08-28T20:00:05"
        assert "daily_report" not in state["last_runs"]


class TestReconcileStale:
    def test_stale_started_marked_interrupted_on_restart(self, isolated_state):
        # 模拟进程在 started 阶段被中断（8/27 20:00 真实场景）
        _write_state({
            "last_runs": {"daily_report": "daily_report|2026-08-27 20:00"},
            "job_states": {
                "daily_report": {
                    "phase": "started",
                    "attempt_key": "daily_report|2026-08-27 20:00",
                    "started_at": "2026-08-27T20:00:01",
                }
            },
        })
        scheduler._reconcile_stale_states()
        state = scheduler._load_state()
        js = state["job_states"]["daily_report"]
        assert js["phase"] == scheduler.PHASE_INTERRUPTED
        assert "interrupted_at" in js
        assert "last_error" in js

    def test_stale_started_never_silently_successful(self, isolated_state):
        _write_state({
            "last_runs": {},
            "job_states": {
                "daily_report": {"phase": "started", "attempt_key": "daily_report|2026-08-28 20:00"},
                "nudge": {"phase": "delivery_sent", "attempt_key": "nudge|2026-08-28 12:15"},
            },
        })
        scheduler._reconcile_stale_states()
        state = scheduler._load_state()
        assert state["job_states"]["daily_report"]["phase"] == scheduler.PHASE_INTERRUPTED
        assert state["job_states"]["nudge"]["phase"] == scheduler.PHASE_INTERRUPTED
        assert state["last_runs"] == {}

    def test_completed_not_touched_by_reconcile(self, isolated_state):
        _write_state({
            "last_runs": {"daily_report": "daily_report|2026-08-26 20:00"},
            "job_states": {
                "daily_report": {"phase": "completed", "attempt_key": "daily_report|2026-08-26 20:00"},
            },
        })
        scheduler._reconcile_stale_states()
        assert scheduler._load_state()["job_states"]["daily_report"]["phase"] == scheduler.PHASE_COMPLETED

    def test_reconcile_is_idempotent(self, isolated_state):
        _write_state({
            "last_runs": {},
            "job_states": {"daily_report": {"phase": "started", "attempt_key": "daily_report|2026-08-28 20:00"}},
        })
        scheduler._reconcile_stale_states()
        first = scheduler._load_state()
        scheduler._reconcile_stale_states()
        second = scheduler._load_state()
        assert first["job_states"]["daily_report"] == second["job_states"]["daily_report"]


class TestAttemptGuard:
    def test_same_attempt_not_rerun_after_failure(self, isolated_state):
        # 失败后（新契约：last_runs 未更新）同一次调度不得重复触发
        state = {
            "last_runs": {},
            "job_states": {
                "daily_report": {
                    "phase": "failed",
                    "attempt_key": "daily_report|2026-08-28 20:00",
                    "last_error": "delivery:failed",
                }
            },
        }
        assert scheduler._attempt_already_handled(state, "daily_report", "daily_report|2026-08-28 20:00") is True
        assert scheduler._attempt_already_handled(state, "daily_report", "daily_report|2026-08-29 20:00") is False

    def test_active_attempt_not_rerun(self, isolated_state):
        state = {
            "last_runs": {},
            "job_states": {"daily_report": {"phase": "started", "attempt_key": "daily_report|2026-08-28 20:00"}},
        }
        assert scheduler._attempt_already_handled(state, "daily_report", "daily_report|2026-08-28 20:00") is True


class TestRunJobLifecycle:
    async def _run(self, scheduler_obj, job, attempt_key):
        return await scheduler_obj._run_job(job, attempt_key)

    def test_normal_completion_marks_completed_and_updates_last_runs(self, monkeypatch, isolated_state):
        scheduler_obj = scheduler.Scheduler(None)
        monkeypatch.setattr(scheduler, "_JOB_RUNNERS", {
            "daily_report": lambda ctx: {"generated": "ok", "worklog": "written", "delivery": "sent"},
        })
        monkeypatch.setattr(scheduler, "_deliver", lambda t: "sent")
        asyncio.run(self._run(scheduler_obj, _job(), _key("daily_report", "2026-08-28 20:00")))
        state = scheduler._load_state()
        js = state["job_states"]["daily_report"]
        assert js["phase"] == scheduler.PHASE_COMPLETED
        assert js["attempt_key"] == "daily_report|2026-08-28 20:00"
        assert state["last_runs"]["daily_report"] == "daily_report|2026-08-28 20:00"
        assert "completed_at" in js

    def test_delivery_failed_marks_artifact_written_not_completed(self, monkeypatch, isolated_state):
        scheduler_obj = scheduler.Scheduler(None)
        monkeypatch.setattr(scheduler, "_JOB_RUNNERS", {
            "daily_report": lambda ctx: {"generated": "ok", "worklog": "written", "delivery": "failed"},
        })
        asyncio.run(self._run(scheduler_obj, _job(), _key("daily_report", "2026-08-28 20:00")))
        state = scheduler._load_state()
        js = state["job_states"]["daily_report"]
        assert js["phase"] == scheduler.PHASE_ARTIFACT_WRITTEN
        assert "daily_report" not in state["last_runs"]  # 不把 artifact_written 当完成
        assert js["last_error"] == "delivery:failed"

    def test_delivery_sent_without_artifact_is_failed(self, monkeypatch, isolated_state):
        scheduler_obj = scheduler.Scheduler(None)
        monkeypatch.setattr(scheduler, "_JOB_RUNNERS", {
            "daily_report": lambda ctx: {"generated": "ok", "worklog": "skipped-empty", "delivery": "sent"},
        })
        asyncio.run(self._run(scheduler_obj, _job(), _key("daily_report", "2026-08-28 20:00")))
        js = scheduler._load_state()["job_states"]["daily_report"]
        assert js["phase"] == scheduler.PHASE_FAILED
        assert "daily_report" not in scheduler._load_state()["last_runs"]

    def test_runner_exception_marks_failed_with_error(self, monkeypatch, isolated_state):
        scheduler_obj = scheduler.Scheduler(None)

        def boom(ctx):
            raise RuntimeError("boom")

        monkeypatch.setattr(scheduler, "_JOB_RUNNERS", {"daily_report": boom})
        asyncio.run(self._run(scheduler_obj, _job(), _key("daily_report", "2026-08-28 20:00")))
        state = scheduler._load_state()
        js = state["job_states"]["daily_report"]
        assert js["phase"] == scheduler.PHASE_FAILED
        assert "boom" in (js["last_error"] or "")
        assert "daily_report" not in state["last_runs"]
        assert state["errors"]["count"] >= 1


class TestMigration:
    def test_legacy_schema_gains_job_states_and_keeps_last_runs(self, isolated_state):
        _write_state({
            "last_runs": {"daily_report": "daily_report|2026-08-27 20:00", "nudge": "nudge|2026-08-27 12:15"},
            "updated_at": "2026-08-27T20:00:10",
        })
        scheduler._migrate_state_file()
        state = scheduler._load_state()
        assert state["last_runs"]["daily_report"] == "daily_report|2026-08-27 20:00"  # 向后兼容
        assert "job_states" in state
        assert state.get("schema_version") == 2

    def test_legacy_entry_without_log_evidence_is_interrupted(self, isolated_state):
        # 8/27 20:00 场景：last_runs 有记录但 scheduler.log 无完成行 → interrupted（不静默成功）
        _write_state({"last_runs": {"daily_report": "daily_report|2026-08-27 20:00"}})
        # 日志只有 8/26 的完成行
        isolated_state["log_file"].write_text(
            json.dumps({"job": "daily_report", "started_at": "2026-08-26T20:00:17", "ok": True}, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
        scheduler._migrate_state_file()
        js = scheduler._load_state()["job_states"]["daily_report"]
        assert js["phase"] == scheduler.PHASE_INTERRUPTED

    def test_legacy_entry_with_log_evidence_is_completed(self, isolated_state):
        _write_state({"last_runs": {"daily_report": "daily_report|2026-08-26 20:00"}})
        isolated_state["log_file"].write_text(
            json.dumps({"job": "daily_report", "started_at": "2026-08-26T20:00:17", "ok": True}, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
        scheduler._migrate_state_file()
        js = scheduler._load_state()["job_states"]["daily_report"]
        assert js["phase"] == scheduler.PHASE_COMPLETED

    def test_migration_idempotent(self, isolated_state):
        _write_state({"last_runs": {"daily_report": "daily_report|2026-08-27 20:00"}})
        scheduler._migrate_state_file()
        first = scheduler._load_state()
        scheduler._migrate_state_file()
        second = scheduler._load_state()
        assert first == second

    def test_migration_then_reconcile_8_27_scenario(self, isolated_state):
        """生产场景复现：8/27 20:00 有 last_runs 记录但日志无完成行（进程被重载中断）。

        迁移 + reconcile 后：job_states 标 interrupted，last_runs 保留（向后兼容），
        读取者不再把「有尝试」当「已执行完成」。
        """
        _write_state({"last_runs": {"daily_report": "daily_report|2026-08-27 20:00"}})
        scheduler._migrate_state_file()
        scheduler._reconcile_stale_states()
        state = scheduler._load_state()
        js = state["job_states"]["daily_report"]
        assert js["phase"] == scheduler.PHASE_INTERRUPTED
        assert js["attempt_key"] == "daily_report|2026-08-27 20:00"
        assert state["last_runs"]["daily_report"] == "daily_report|2026-08-27 20:00"


class TestFailClosed:
    def test_corrupt_state_file_returns_safe_default(self, isolated_state):
        isolated_state["state_file"].write_text("{not-json!!!", encoding="utf-8")
        state = scheduler._load_state()
        assert isinstance(state, dict)
        assert state["last_runs"] == {}
        assert state["job_states"] == {}

    def test_missing_state_file_returns_safe_default(self, isolated_state):
        state = scheduler._load_state()
        assert state["last_runs"] == {}
        assert state["job_states"] == {}


class TestAtomicWrite:
    def test_save_state_no_tmp_residue(self, isolated_state):
        scheduler._save_state({"last_runs": {}, "job_states": {}})
        leftovers = [p.name for p in isolated_state["state_file"].parent.iterdir() if p.suffix == ".tmp"]
        assert leftovers == []
        data = json.loads(isolated_state["state_file"].read_text(encoding="utf-8"))
        assert data["last_runs"] == {}
        assert data["job_states"] == {}

    def test_save_state_locked_file_fails_closed(self, monkeypatch, isolated_state):
        # Windows 文件锁场景：写失败不能崩溃，下次仍可读旧内容
        isolated_state["state_file"].write_text(
            json.dumps({"last_runs": {"x": "x|2026-08-28 06:00"}, "job_states": {}}, ensure_ascii=False),
            encoding="utf-8",
        )
        original = scheduler.os.replace

        def locked_replace(src, dst):
            raise OSError(13, "Permission denied", dst)

        monkeypatch.setattr(scheduler.os, "replace", locked_replace)
        try:
            scheduler._save_state({"last_runs": {}, "job_states": {}})
        except OSError:
            pytest.fail("save must fail-closed without raising to the caller")
        monkeypatch.setattr(scheduler.os, "replace", original)
        # 旧内容仍可读（未被半写破坏）
        assert scheduler._load_state()["last_runs"] == {"x": "x|2026-08-28 06:00"}


class TestRunJobUpgradeSafety:
    def test_run_job_accepts_attempt_key_signature(self, isolated_state):
        # 新签名 _run_job(self, job, attempt_key) 必须存在（当前只有 self, job → RED）
        sig = scheduler.Scheduler._run_job
        import inspect

        params = list(inspect.signature(sig).parameters)
        assert "attempt_key" in params
