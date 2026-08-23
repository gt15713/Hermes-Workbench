# -*- coding: utf-8 -*-
"""内建调度器测试（55/57 号定义）：cron 匹配 / 租约 / 输出解析 / 工作日志 / 空跑安全。"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import scheduler  # noqa: E402


def _dt(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi)


class TestMatchCron:
    def test_every_ten_minutes(self):
        assert scheduler.match_cron("*/10 * * * *", _dt(2026, 8, 22, 10, 0)) is True
        assert scheduler.match_cron("*/10 * * * *", _dt(2026, 8, 22, 10, 10)) is True
        assert scheduler.match_cron("*/10 * * * *", _dt(2026, 8, 22, 10, 15)) is False

    def test_specific_time(self):
        assert scheduler.match_cron("30 12 * * *", _dt(2026, 8, 22, 12, 30)) is True
        assert scheduler.match_cron("30 12 * * *", _dt(2026, 8, 22, 12, 31)) is False
        assert scheduler.match_cron("30 12 * * *", _dt(2026, 8, 22, 11, 30)) is False

    def test_daily_report_2000(self):
        assert scheduler.match_cron("0 20 * * *", _dt(2026, 8, 22, 20, 0)) is True
        assert scheduler.match_cron("0 20 * * *", _dt(2026, 8, 22, 20, 1)) is False

    def test_month_and_dow(self):
        assert scheduler.match_cron("15 18 1 * *", _dt(2026, 9, 1, 18, 15)) is True
        assert scheduler.match_cron("15 18 1 * *", _dt(2026, 9, 2, 18, 15)) is False
        assert scheduler.match_cron("* * * * 0", _dt(2026, 8, 23, 9, 0)) is True  # 周日
        assert scheduler.match_cron("* * * * 0", _dt(2026, 8, 24, 9, 0)) is False  # 周一

    def test_range_and_list(self):
        assert scheduler.match_cron("0 9-11 * * *", _dt(2026, 8, 22, 10, 0)) is True
        assert scheduler.match_cron("0 9-11 * * *", _dt(2026, 8, 22, 12, 0)) is False
        assert scheduler.match_cron("0,30 * * * *", _dt(2026, 8, 22, 8, 30)) is True
        assert scheduler.match_cron("0,30 * * * *", _dt(2026, 8, 22, 8, 15)) is False

    def test_invalid_expr(self):
        assert scheduler.match_cron("bad expr", _dt(2026, 8, 22)) is False
        assert scheduler.match_cron("99 * * * *", _dt(2026, 8, 22)) is False


class TestFieldValues:
    def test_any(self):
        assert scheduler._field_values("*", 0, 59) is None

    def test_step(self):
        assert scheduler._field_values("*/10", 0, 59) == {0, 10, 20, 30, 40, 50}

    def test_range(self):
        assert scheduler._field_values("9-11", 0, 23) == {9, 10, 11}

    def test_list(self):
        assert scheduler._field_values("0,30", 0, 59) == {0, 30}


class TestSplitOutput:
    def test_markers(self):
        out = scheduler._split_output(
            "<WORKLOG>\n# 工作台日报\nbody\n</WORKLOG>\n<QQMSG>\n要点\n</QQMSG>"
        )
        assert out["worklog"] == "# 工作台日报\nbody"
        assert out["qq"] == "要点"

    def test_empty_markers(self):
        out = scheduler._split_output("<WORKLOG></WORKLOG><QQMSG></QQMSG>")
        assert out == {"worklog": "", "qq": ""}

    def test_fallback_plain_text(self):
        out = scheduler._split_output("普通文本")
        assert out["worklog"] == ""
        assert out["qq"] == "普通文本"

    def test_fallback_worklog_shape(self):
        out = scheduler._split_output("# 工作台日报 — 2026-08-22\n\n## 今日完成\n- x")
        assert out["worklog"].startswith("# 工作台日报")
        assert out["qq"].startswith("# 工作台日报")

    def test_empty_input(self):
        assert scheduler._split_output("") == {"worklog": "", "qq": ""}


class TestWriteDailyWorklog:
    def test_writes_when_missing(self, tmp_path):
        written = scheduler._write_daily_worklog("# 工作台日报 — 2026-08-22\n\n## 今日完成\n- x", vault=tmp_path)
        assert written == "written"
        files = list((tmp_path / "Hermes Agent" / "运维" / "工作日志").rglob("*工作台日报.md"))
        assert len(files) == 1

    def test_skips_when_exists(self, tmp_path):
        scheduler._write_daily_worklog("# 工作台日报 — 2026-08-22\n\n## 今日完成\n- x", vault=tmp_path)
        written = scheduler._write_daily_worklog("# 工作台日报 — 2026-08-22\n\n## 今日完成\n- y", vault=tmp_path)
        assert written == "skipped-exists"

    def test_skips_when_empty(self, tmp_path):
        assert scheduler._write_daily_worklog("", vault=tmp_path) == "skipped-empty"
        assert scheduler._write_daily_worklog("短", vault=tmp_path) == "skipped-empty"


class TestLease:
    def test_acquire_release_cycle(self, tmp_path):
        lease = scheduler._Lease(tmp_path / "scheduler.lock")
        assert lease.acquire() is True
        assert lease.path.exists()
        lease.heartbeat()
        lease.release()
        assert not lease.path.exists()

    def test_second_lease_denied_while_held(self, tmp_path):
        a = scheduler._Lease(tmp_path / "scheduler.lock")
        b = scheduler._Lease(tmp_path / "scheduler.lock")
        assert a.acquire() is True
        assert b.acquire() is False
        a.release()

    def test_stale_lease_reclaimed(self, tmp_path):
        path = tmp_path / "scheduler.lock"
        path.write_text(
            json.dumps({"pid": 999999, "started_at": "2026-08-22T00:00:00", "heartbeat_at": "2026-08-22T00:00:00"}),
            encoding="utf-8",
        )
        lease = scheduler._Lease(path)
        assert lease.acquire() is True
        assert lease._held is True
        lease.release()

    def test_fresh_lease_not_reclaimed(self, tmp_path):
        import os
        from datetime import datetime

        path = tmp_path / "scheduler.lock"
        now = datetime.now().isoformat(timespec="seconds")
        path.write_text(
            json.dumps({"pid": os.getpid(), "started_at": now, "heartbeat_at": now}),
            encoding="utf-8",
        )
        # 同进程 pid 存活 → 认为新鲜，不可抢占
        assert scheduler._Lease(path).acquire() is False


class TestJobRunners:
    def test_lifecycle_empty_root(self, monkeypatch, tmp_path):
        import auto_archive

        monkeypatch.setattr(auto_archive, "ROOT", tmp_path)
        result = scheduler._job_lifecycle(None)
        assert result == {"scanned": 0, "completed": 0, "failed": 0, "errors": 0}

    def test_maintenance_missing_script(self, monkeypatch, tmp_path):
        monkeypatch.setattr(scheduler, "_SCRIPTS_DIR", tmp_path)
        monkeypatch.setattr(scheduler, "_PLUGIN_SCRIPTS_DIR", tmp_path)  # 双源都指向空目录
        try:
            scheduler._job_maintenance(None)
            assert False, "should raise FileNotFoundError"
        except FileNotFoundError:
            pass

    def test_daily_report_no_ctx_is_safe(self, monkeypatch, tmp_path):
        monkeypatch.setattr(scheduler, "_SCRIPTS_DIR", tmp_path)
        monkeypatch.setattr(scheduler, "_generate", lambda ctx, p, d: "")
        result = scheduler._job_daily_report(None)
        assert result["generated"] == "empty"

    def test_deliver_empty_skips(self):
        assert scheduler._deliver("") == "skipped-empty"
        assert scheduler._deliver("   ") == "skipped-empty"


class TestDeliveryRetry:
    def test_queue_and_load(self, monkeypatch, tmp_path):
        monkeypatch.setattr(scheduler, "_STATE_FILE", tmp_path / "state.json")
        scheduler._queue_delivery("重试消息")
        state = scheduler._load_state()
        assert state["pending_delivery"]["text"] == "重试消息"
        assert state["pending_delivery"]["attempts"] == 0

    def test_retry_not_due(self, monkeypatch, tmp_path):
        monkeypatch.setattr(scheduler, "_STATE_FILE", tmp_path / "state.json")
        scheduler._queue_delivery("消息")
        assert scheduler._retry_pending_delivery() is False  # 未到期不重试

    def test_retry_success_clears(self, monkeypatch, tmp_path):
        monkeypatch.setattr(scheduler, "_STATE_FILE", tmp_path / "state.json")
        monkeypatch.setattr(scheduler, "_deliver", lambda t: "sent")
        scheduler._queue_delivery("消息")
        # 入队后 next_attempt_at 是未来 5 分钟；重置到过去才能立即重试（与 drops_after_max 同法）
        state = scheduler._load_state()
        state["pending_delivery"]["next_attempt_at"] = "2020-01-01T00:00:00"
        scheduler._save_state(state)
        assert scheduler._retry_pending_delivery() is True
        assert scheduler._load_state()["pending_delivery"] is None

    def test_retry_drops_after_max(self, monkeypatch, tmp_path):
        monkeypatch.setattr(scheduler, "_STATE_FILE", tmp_path / "state.json")
        monkeypatch.setattr(scheduler, "_deliver", lambda t: "failed")
        scheduler._queue_delivery("消息")
        for _ in range(3):
            # 每次失败后 next_attempt_at 会推迟 5 分钟；循环里重置为过去以连跑
            state = scheduler._load_state()
            state["pending_delivery"]["next_attempt_at"] = "2020-01-01T00:00:00"
            scheduler._save_state(state)
            scheduler._retry_pending_delivery()
        assert scheduler._load_state()["pending_delivery"] is None


class TestUnconfigured:
    def test_deliver_unconfigured_target(self, monkeypatch):
        import workbench_config

        monkeypatch.setattr(workbench_config, "get_deliver_target", lambda: "")
        assert scheduler._deliver("有内容") == "unconfigured"

    def test_worklog_unconfigured_vault(self, monkeypatch, tmp_path):
        import workbench_config

        monkeypatch.setattr(workbench_config, "get_vault", lambda: "")
        assert scheduler._write_daily_worklog(
            "# 工作台日报 — 2026-08-23\n\n## 今日完成\n- x"
        ) == "skipped-unconfigured"


class TestP0CVisibility:
    """P0-C 任务级可见性：empty/失败不再记 ok，错误计数可观测。"""

    def test_health_normal_ok(self):
        assert scheduler._result_health({"generated": "ok", "delivery": "sent"}) == (True, "")
        assert scheduler._result_health({"scanned": 0, "errors": 0}) == (True, "")
        assert scheduler._result_health({"exit": 0}) == (True, "")

    def test_health_empty_not_ok(self):
        ok, reason = scheduler._result_health({"generated": "empty"})
        assert ok is False and reason == "empty"

    def test_health_delivery_failed_unconfigured(self):
        assert scheduler._result_health({"delivery": "failed"})[0] is False
        assert scheduler._result_health({"delivery": "unconfigured"})[0] is False

    def test_health_errors_and_exit(self):
        assert scheduler._result_health({"errors": 2})[0] is False
        assert scheduler._result_health({"exit": 1})[0] is False

    def test_record_error_and_status(self, monkeypatch, tmp_path):
        monkeypatch.setattr(scheduler, "_STATE_FILE", tmp_path / "state.json")
        scheduler._record_error("daily_report", "2026-08-23T10:00:00", "empty")
        scheduler._record_error("nudge", "2026-08-23T10:10:00", "delivery:failed")
        state = scheduler._load_state()
        assert state["errors"]["count"] == 2
        assert state["errors"]["last"]["job"] == "nudge"
        status = scheduler.scheduler_status()
        assert status["error_count"] == 2
        assert status["last_error"]["reason"] == "delivery:failed"


class TestCatchUp:
    """A4 启动补跑（WB 纠正设计 + GT 复核确认：A4 先行）。"""

    def test_last_cron_fire_daily(self):
        # 12:00 前最近一次 "0 20 * * *" = 昨天 20:00
        last = scheduler._last_cron_fire("0 20 * * *", _dt(2026, 8, 23, 12, 0))
        assert last == _dt(2026, 8, 22, 20, 0)

    def test_last_cron_fire_ten_min(self):
        last = scheduler._last_cron_fire("*/10 * * * *", _dt(2026, 8, 23, 12, 15))
        assert last == _dt(2026, 8, 23, 12, 10)

    def test_parse_run_key(self):
        assert scheduler._parse_run_key("daily_report|2026-08-23 20:00") == _dt(2026, 8, 23, 20, 0)
        assert scheduler._parse_run_key("bad") is None
        assert scheduler._parse_run_key("") is None

    def test_catch_up_runs_missed_job(self, monkeypatch, tmp_path):
        import asyncio

        import workbench_config

        monkeypatch.setattr(scheduler, "_STATE_FILE", tmp_path / "state.json")
        monkeypatch.setattr(scheduler, "JOBS", [{"key": "daily_report", "expr": "0 20 * * *", "desc": ""}])
        monkeypatch.setattr(workbench_config, "get_catch_up_hours", lambda: 24)
        s = scheduler.Scheduler(None)
        ran: list[str] = []

        async def fake_run_job(job):
            ran.append(job["key"])

        monkeypatch.setattr(s, "_run_job", fake_run_job)
        asyncio.run(s._catch_up())
        assert ran == ["daily_report"]
        assert scheduler._load_state()["last_runs"]["daily_report"].startswith("daily_report|")

    def test_catch_up_skips_recent_run(self, monkeypatch, tmp_path):
        import asyncio

        import workbench_config

        monkeypatch.setattr(scheduler, "_STATE_FILE", tmp_path / "state.json")
        monkeypatch.setattr(scheduler, "JOBS", [{"key": "daily_report", "expr": "0 20 * * *", "desc": ""}])
        monkeypatch.setattr(workbench_config, "get_catch_up_hours", lambda: 24)
        # 已跑过今天 20:00 → 补跑判定 last_fire <= last_run → 跳过
        scheduler._save_state(
            {"last_runs": {"daily_report": "daily_report|2026-08-23 20:00"}, "errors": {"count": 0, "last": None}}
        )
        s = scheduler.Scheduler(None)
        ran: list[str] = []

        async def fake_run_job(job):
            ran.append(job["key"])

        monkeypatch.setattr(s, "_run_job", fake_run_job)
        asyncio.run(s._catch_up())
        assert ran == []

    def test_catch_up_disabled(self, monkeypatch, tmp_path):
        import asyncio

        import workbench_config

        monkeypatch.setattr(scheduler, "_STATE_FILE", tmp_path / "state.json")
        monkeypatch.setattr(scheduler, "JOBS", [{"key": "daily_report", "expr": "0 20 * * *", "desc": ""}])
        monkeypatch.setattr(workbench_config, "get_catch_up_hours", lambda: 0)
        s = scheduler.Scheduler(None)
        ran: list[str] = []

        async def fake_run_job(job):
            ran.append(job["key"])

        monkeypatch.setattr(s, "_run_job", fake_run_job)
        asyncio.run(s._catch_up())
        assert ran == []
