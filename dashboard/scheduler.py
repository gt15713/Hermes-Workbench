# -*- coding: utf-8 -*-
"""Workbench 内建调度器（55/57 号定义落地：定时任务 = 插件内部功能实现）。

定位：
- Workbench = 独立插件 = Hermes 消息平台的 QQ Bot 任务信息流平台；
- 定时任务（日报/提醒/维护/归档）= 本插件内部实现，不依赖 Hermes cron；
- 任务内容怎么处理 = Hermes Skill/宿主 LLM 的事，Workbench 只负责定时触发、
  数据采集、状态落盘与 QQ 投递。

实现要点：
- 常驻：daemon 线程 + 独立 asyncio 事件循环（register() 为同步调用，
  PluginContext.spawn_task 需要运行中的 loop，故用线程自持 loop）。
- 单实例：scheduler.lock（PID + 心跳）租约，同一时刻仅一个进程持有调度权；
  其余进程（CLI/worker/多实例）stand down，不重复触发。
- 任务表（与既有 cron 语义对齐，迁移式：实现一项 → 砍对应 cron 一项）：
    lifecycle      */10 * * * *   执行生命周期协调（auto_archive，进程内）
    maintenance    30 12 * * *    每日维护（归档巡检 + DB 收敛 + 回收站 TTL）
    daily_report   0 20 * * *     工作台每日日报（数据→LLM→工作日志→QQ）
    nudge          15 12 * * *    超期任务提醒（数据→LLM→QQ）
  （月度 Hermes/Obsidian 健康审计属 Hermes 全域审计，保留 Hermes cron。）
- 生成：日报/提醒文本由宿主 LLM 生成（ctx.llm，缺省模型，零新依赖）；
  投递走官方 ``hermes send``（QQ REST 直连，不依赖网关适配器）。
- 幂等：scheduler-state.json 记录每次执行开始时间；同一分钟不重复触发。
- 失败不静默：每次触发写 scheduler.log；投递失败记 DELIVERY-FAIL。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

_log = logging.getLogger("workbench-view.scheduler")

_PLUGIN_DIR = Path(__file__).resolve().parent.parent
_HERMES_HOME = Path(os.environ.get("HERMES_HOME", _PLUGIN_DIR.parent.parent))
_LOCK_FILE = _PLUGIN_DIR / "scheduler.lock"
_STATE_FILE = _PLUGIN_DIR / "scheduler-state.json"
_LOG_FILE = _HERMES_HOME / "logs" / "workbench-scheduler.log"
_SCRIPTS_DIR = _HERMES_HOME / "scripts"
_PLUGIN_SCRIPTS_DIR = _PLUGIN_DIR / "scripts"  # P0-A：插件包内脚本（OSS/新装兜底）

_TICK_SECONDS = 20          # 调度主循环节拍
_HEARTBEAT_SECONDS = 30     # 租约心跳间隔
_LEASE_STALE_SECONDS = 120  # 租约过期判定
_LLM_TIMEOUT = 180.0        # 日报/提醒 LLM 调用上限
_SCRIPT_TIMEOUT = 600       # 维护子进程上限
_SEND_TIMEOUT = 120         # QQ 投递子进程上限
_DELIVERY_RETRY_MAX = 3     # 投递失败重试上限
_DELIVERY_RETRY_MINUTES = 5  # 失败后重试间隔（分钟）

# 任务生命周期阶段（WB-S1-011：last_runs 只在 completed 时更新，不把尝试当完成）
PHASE_SCHEDULED = "scheduled"
PHASE_STARTED = "started"
PHASE_ARTIFACT_WRITTEN = "artifact_written"
PHASE_DELIVERY_SENT = "delivery_sent"
PHASE_COMPLETED = "completed"
PHASE_FAILED = "failed"
PHASE_INTERRUPTED = "interrupted"
_PHASE_ORDER = (
    PHASE_SCHEDULED,
    PHASE_STARTED,
    PHASE_ARTIFACT_WRITTEN,
    PHASE_DELIVERY_SENT,
    PHASE_COMPLETED,
    PHASE_FAILED,
    PHASE_INTERRUPTED,
)
_TERMINAL_PHASES = (PHASE_COMPLETED, PHASE_FAILED, PHASE_INTERRUPTED)
_NONTERMINAL_PHASES = (
    PHASE_SCHEDULED,
    PHASE_STARTED,
    PHASE_ARTIFACT_WRITTEN,
    PHASE_DELIVERY_SENT,
)


# ---------------------------------------------------------------------------
# cron 表达式（5 段：分 时 日 月 周；周日=0）——零依赖微型实现
# ---------------------------------------------------------------------------


def _field_values(field: str, lo: int, hi: int) -> Optional[set[int]]:
    """解析单字段：* / */n / a-b / a,b / n。None = 任意。"""
    field = field.strip()
    if field == "*":
        return None
    out: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        if part.startswith("*/"):
            step = int(part[2:])
            if step <= 0:
                return None
            out.update(range(lo, hi + 1, step))
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
            continue
        out.add(int(part))
    return out or None


def _in(vals: Optional[set[int]], v: int) -> bool:
    return vals is None or v in vals


def match_cron(expr: str, now: Optional[datetime] = None) -> bool:
    """匹配 5 段 cron 表达式；非法表达式恒 False。"""
    now = now or datetime.now()
    parts = [p for p in expr.split() if p.strip()]
    if len(parts) != 5:
        return False
    minute, hour, dom, month, dow = parts
    try:
        if not _in(_field_values(minute, 0, 59), now.minute):
            return False
        if not _in(_field_values(hour, 0, 23), now.hour):
            return False
        if not _in(_field_values(dom, 1, 31), now.day):
            return False
        if not _in(_field_values(month, 1, 12), now.month):
            return False
        # cron dow：0=周日…6=周六；Python weekday()：0=周一…6=周日。
        cron_dow = (now.weekday() + 1) % 7
        if not _in(_field_values(dow, 0, 6), cron_dow):
            return False
    except ValueError:
        return False
    return True


# ---------------------------------------------------------------------------
# 单实例租约
# ---------------------------------------------------------------------------


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    # ``os.kill(pid, 0)`` is a POSIX liveness idiom but is destructive on
    # Windows: CPython maps signal 0 to CTRL_C_EVENT and can terminate the
    # scheduler owner (and its whole console group).  Prefer psutil's
    # read-only process-table probe on every platform.  Hermes ships psutil;
    # the fallback remains for stripped standalone plugin test installs.
    try:
        import psutil

        try:
            return psutil.Process(int(pid)).status() != psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            return False
        except psutil.AccessDenied:
            return True
    except ImportError:
        pass

    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.WaitForSingleObject.restype = ctypes.c_uint
            process_query = 0x1000
            synchronize = 0x100000
            wait_timeout = 0x00000102
            handle = kernel32.OpenProcess(process_query | synchronize, False, int(pid))
            if not handle:
                # Access denied proves the PID exists; all other failures are
                # treated as absent so a genuinely stale lease can recover.
                return ctypes.get_last_error() == 5
            try:
                return kernel32.WaitForSingleObject(handle, 0) == wait_timeout
            finally:
                kernel32.CloseHandle(handle)
        except (OSError, AttributeError):
            return False

    try:
        os.kill(pid, 0)  # POSIX-only fallback
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


class _Lease:
    """文件租约（O_EXCL 原子抢占 + 心跳 + 过期回收）。"""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._held = False

    def acquire(self, tries: int = 2) -> bool:
        if self._held:
            return True
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if tries <= 0:
                return False
            if self._stale():
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    pass
                return self.acquire(tries - 1)
            return False
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(self._payload())
        self._held = True
        return True

    def _stale(self) -> bool:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            pid = int(data.get("pid") or 0)
            hb = data.get("heartbeat_at") or ""
            try:
                fresh = (datetime.now() - datetime.fromisoformat(hb)).total_seconds() < _LEASE_STALE_SECONDS
            except ValueError:
                fresh = False
            if _pid_alive(pid) and fresh:
                return False
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        return True

    def _payload(self, started_at: Optional[str] = None) -> str:
        now = datetime.now().isoformat(timespec="seconds")
        return json.dumps(
            {"pid": os.getpid(), "started_at": started_at or now, "heartbeat_at": now},
            ensure_ascii=False,
        )

    def heartbeat(self) -> None:
        if not self._held:
            return
        started_at: Optional[str] = None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            started_at = data.get("started_at")
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        try:
            self.path.write_text(self._payload(started_at), encoding="utf-8")
        except OSError as exc:
            _log.warning("workbench scheduler heartbeat failed: %s", exc)

    def release(self) -> None:
        if not self._held:
            return
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            _log.warning("workbench scheduler lease release failed: %s", exc)
        self._held = False


# ---------------------------------------------------------------------------
# 状态持久化（幂等：同分钟不重复触发）
# ---------------------------------------------------------------------------


def _load_state() -> dict:
    try:
        data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("last_runs"), dict):
            # WB-S1-011：惰性补全 v2 字段；历史迁移见 _migrate_state_file
            data.setdefault("job_states", {})
            data.setdefault("schema_version", 2)
            return data
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return {
        "last_runs": {},
        "job_states": {},
        "pending_delivery": None,
        "errors": {"count": 0, "last": None},
        "updated_at": None,
        "schema_version": 2,
    }


def _save_state(state: dict) -> None:
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    state.setdefault("job_states", {})
    state.setdefault("schema_version", 2)
    # 原子写：同目录临时文件 + os.replace（Windows 上避免读者读到半写内容/文件锁）；
    # 写失败 fail-closed：保留磁盘旧内容，不抛给调用方。
    tmp = _STATE_FILE.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, _STATE_FILE)
    except OSError as exc:
        _log.warning("workbench scheduler state write failed: %s", exc)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _append_log(job_key: str, started_at: str, ok: bool, summary: Any) -> None:
    line = json.dumps(
        {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "job": job_key,
            "started_at": started_at,
            "ok": ok,
            "summary": summary,
        },
        ensure_ascii=False,
    )
    try:
        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError as exc:
        _log.warning("workbench scheduler log append failed: %s", exc)


def _result_health(result: Any) -> tuple[bool, str]:
    """任务结果健康判定（P0-C 可见性）：empty/投递失败/未配置/执行错误/脚本退出非 0 → 非 ok。"""
    if not isinstance(result, dict):
        return True, ""
    if result.get("generated") == "empty":
        return False, "empty"
    delivery = result.get("delivery")
    if delivery in ("failed", "unconfigured"):
        return False, f"delivery:{delivery}"
    if int(result.get("errors", 0) or 0) > 0:
        return False, f"errors:{result.get('errors')}"
    if result.get("exit") not in (None, 0):
        return False, f"exit:{result.get('exit')}"
    return True, ""


def _record_error(job_key: str, started_at: str, reason: str) -> None:
    """累计错误计数 + 最近一次错误（P0-C：scheduler_status 可见，失败不再静默）。"""
    state = _load_state()
    errors = state.setdefault("errors", {"count": 0, "last": None})
    errors["count"] = int(errors.get("count", 0)) + 1
    errors["last"] = {"job": job_key, "at": started_at, "reason": reason}
    _save_state(state)


def _resolve_last_delivery_error(state: dict) -> None:
    """Clear the actionable health error once its queued delivery succeeds.

    ``errors.count`` predates per-attempt delivery retries and is surfaced by
    ``/health`` as a current fault count. Leaving the failed first attempt in
    place after a successful retry makes the UI permanently red even though
    ``pending_delivery`` is empty and the delivery chain recovered.
    """
    errors = state.get("errors") or {}
    last = errors.get("last") or {}
    if last.get("reason") != "delivery:failed":
        return
    remaining = max(0, int(errors.get("count", 0)) - 1)
    errors["count"] = remaining
    if remaining == 0:
        errors["last"] = None
    state["errors"] = errors


def _active_errors(state: dict) -> tuple[int, dict | None]:
    """Return unresolved health errors, excluding recovered legacy delivery state.

    Older schedulers cleared ``pending_delivery`` after a successful retry but
    left ``delivery:failed`` in the cumulative counter.  An exhausted retry is
    now recorded as ``delivery:dropped`` so it remains visible.
    """
    errors = state.get("errors") or {}
    count = int(errors.get("count", 0) or 0)
    last = errors.get("last")
    if (
        count > 0
        and isinstance(last, dict)
        and last.get("reason") == "delivery:failed"
        and not state.get("pending_delivery")
    ):
        return max(0, count - 1), None
    return count, last


# ---------------------------------------------------------------------------
# 任务生命周期状态机（WB-S1-011）
# 契约：last_runs 只在 completed 时更新；started/artifact_written/delivery_sent
#       均为中间态；失败/中断保留 last_error + 阶段 + 开始时间；重启识别 stale。
# ---------------------------------------------------------------------------


def _set_phase(
    state: dict,
    job_key: str,
    phase: str,
    attempt_key: str,
    started_at: str | None = None,
    last_error: str | None = None,
) -> None:
    """更新 job_states[job_key] 的生命周期阶段并持久化。

    - 仅 completed 阶段会同步写入 last_runs（“最近一次已完成调度”的向后兼容语义）；
    - started/artifact_written/delivery_sent/failed/interrupted 绝不写 last_runs，
      避免“有尝试”被误读为“已执行完成”（P0 根因修复）。
    """
    now = datetime.now().isoformat(timespec="seconds")
    js = state.setdefault("job_states", {}).setdefault(job_key, {})
    js["phase"] = phase
    js["attempt_key"] = attempt_key
    js["updated_at"] = now
    if started_at is not None:
        js["started_at"] = started_at
    if phase == PHASE_STARTED:
        js["started_at"] = now
    elif phase == PHASE_ARTIFACT_WRITTEN:
        js.setdefault("artifact_written_at", now)
    elif phase == PHASE_DELIVERY_SENT:
        js.setdefault("delivery_sent_at", now)
    elif phase == PHASE_COMPLETED:
        js["completed_at"] = now
        state.setdefault("last_runs", {})[job_key] = attempt_key
        js.pop("last_error", None)
    elif phase == PHASE_FAILED:
        js["failed_at"] = now
    elif phase == PHASE_INTERRUPTED:
        js["interrupted_at"] = now
    if last_error:
        js["last_error"] = last_error
    _save_state(state)


def _daily_contract(worklog: str, delivery: str) -> tuple[str, str | None]:
    """daily_report 契约判定：artifact + 必要投递均满足 → completed。

    - delivery=sent 且 artifact 满足 → delivery_sent（调用方随后转 completed，
      中间态时间戳保留在 job_states）；
    - artifact 满足但 delivery=failed → artifact_written（等投递重试队列，不是完成）；
    - 投递不必要（unconfigured/skipped-empty）且 artifact 满足 → completed；
    - 任何 artifact 缺失或异常组合 → failed（不伪造完成、不把尝试当 sent）。
    """
    artifact_ok = worklog in ("written", "skipped-exists", "skipped-disabled", "skipped-unconfigured")
    if delivery == "sent":
        if artifact_ok:
            return PHASE_DELIVERY_SENT, None
        return PHASE_FAILED, f"delivery sent but artifact missing (worklog={worklog})"
    if delivery == "failed":
        if artifact_ok:
            return PHASE_ARTIFACT_WRITTEN, "delivery:failed"
        return PHASE_FAILED, f"delivery:failed and artifact missing (worklog={worklog})"
    if delivery in ("unconfigured", "skipped-empty"):
        if artifact_ok:
            return PHASE_COMPLETED, None
        return PHASE_FAILED, f"no delivery and artifact missing (worklog={worklog})"
    return PHASE_FAILED, f"unexpected delivery={delivery!r}"


def _derive_phase(job_key: str, result: dict, ok: bool, reason: str) -> tuple[str, str | None]:
    """runner 结果 → 生命周期阶段（daily_report 走契约；其他 job 简化 ok/failed）。

    分层规则（不互相掩盖）：
    - artifact 已写但投递失败 → artifact_written（即使 _result_health 判非 ok）；
    - 其余非 ok（empty/errors/exit）→ failed；
    - daily_report 契约判定失败 → failed。
    """
    if not isinstance(result, dict):
        return PHASE_FAILED, "runner returned non-dict result"
    if job_key == "daily_report":
        phase, err = _daily_contract(str(result.get("worklog") or ""), str(result.get("delivery") or ""))
        if phase in (PHASE_FAILED, PHASE_ARTIFACT_WRITTEN):
            return phase, err
        if not ok:
            return PHASE_FAILED, reason or "failed"
        return phase, err
    if not ok:
        return PHASE_FAILED, reason or "failed"
    return PHASE_COMPLETED, None


def _attempt_already_handled(state: dict, job_key: str, attempt_key: str) -> bool:
    """同一次调度（attempt_key）是否已处理（进行中/终态均防重）。

    不依赖 last_runs（它在失败/中断时不更新）；job_states.attempt_key 覆盖
    一切已触发过的调度，避免失败/中断后同一分钟重复触发。
    """
    js = (state.get("job_states") or {}).get(job_key) or {}
    return js.get("attempt_key") == attempt_key


def _reconcile_stale_states() -> None:
    """进程启动时识别遗留非终态：上次进程中断留下的 scheduled/started/
    artifact_written/delivery_sent → interrupted/stale，绝不静默视为成功。"""
    state = _load_state()
    now = datetime.now().isoformat(timespec="seconds")
    changed = False
    for _job_key, js in (state.get("job_states") or {}).items():
        if js.get("phase") not in _NONTERMINAL_PHASES:
            continue
        js["phase"] = PHASE_INTERRUPTED
        js["interrupted_at"] = now
        js.setdefault("last_error", "interrupted: process restarted before completion")
        changed = True
    if changed:
        _save_state(state)


def _legacy_phase_from_log(job_key: str, run_key: str) -> str:
    """旧 schema 迁移辅助：从 scheduler.log 判定旧条目是 completed/failed/interrupted。

    - 日志有该调度 ok 行 → completed；
    - 日志有该调度非 ok 行 → failed（保留失败证据）；
    - 日志无该调度行 → interrupted（有 last_runs 记录但无完成/失败证据 = 中断遗留）。
    """
    run_dt = _parse_run_key(run_key)
    if run_dt is None:
        return PHASE_INTERRUPTED
    try:
        lines = _LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return PHASE_INTERRUPTED
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("job") != job_key:
            continue
        try:
            start = datetime.fromisoformat(rec.get("started_at", ""))
        except (ValueError, TypeError):
            continue
        if start.strftime("%Y-%m-%d %H:%M") != run_dt.strftime("%Y-%m-%d %H:%M"):
            continue
        return PHASE_COMPLETED if rec.get("ok") else PHASE_FAILED
    return PHASE_INTERRUPTED


def _migrate_state_file() -> None:
    """旧 schema（仅 last_runs，无 job_states）→ v2 迁移，向后兼容、幂等。

    - last_runs 原样保留（旧代码可读）；
    - 为每个 last_runs 条目创建 job_states 记录（legacy=True），阶段由日志证据判定；
    - schema_version=2 且有 job_states 时直接返回（幂等）。
    """
    state = _load_state()
    if state.get("schema_version") == 2 and state.get("job_states"):
        return
    job_states = state.setdefault("job_states", {})
    for job_key, run_key in (state.get("last_runs") or {}).items():
        if job_key in job_states:
            continue
        run_dt = _parse_run_key(run_key)
        job_states[job_key] = {
            "phase": _legacy_phase_from_log(job_key, run_key),
            "attempt_key": run_key,
            "started_at": run_dt.isoformat(timespec="seconds") if run_dt else None,
            "legacy": True,
        }
    state["schema_version"] = 2
    _save_state(state)


def _last_cron_fire(expr: str, before: datetime) -> datetime | None:
    """从 before 往前回溯最近一次 cron 命中（最多 24h；A4 catch-up 用）。"""
    t = before.replace(second=0, microsecond=0)
    for _ in range(1440):
        if match_cron(expr, t):
            return t
        t -= timedelta(minutes=1)
    return None


def _parse_run_key(key: str) -> datetime | None:
    """'daily_report|2026-08-23 20:00' → datetime；非法返回 None。"""
    if not key or "|" not in key:
        return None
    try:
        return datetime.strptime(key.split("|", 1)[1], "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def _queue_delivery(text: str) -> None:
    """把失败的投递加入重试队列（scheduler-state.json，最多 3 次）。"""
    state = _load_state()
    state["pending_delivery"] = {
        "text": (text or "").strip()[:4000],
        "attempts": 0,
        "next_attempt_at": (
            datetime.now() + timedelta(minutes=_DELIVERY_RETRY_MINUTES)
        ).isoformat(timespec="seconds"),
    }
    _save_state(state)
    _log.warning("workbench scheduler: delivery queued for retry")


def _retry_pending_delivery() -> bool:
    """重试队列投递；成功/达到上限 → 清队列。返回是否成功。"""
    state = _load_state()
    pending = state.get("pending_delivery")
    if not pending or not pending.get("text"):
        return False
    try:
        due = datetime.fromisoformat(pending["next_attempt_at"])
    except (ValueError, TypeError):
        due = datetime.min
    if datetime.now() < due:
        return False
    attempts = int(pending.get("attempts", 0)) + 1
    result = _deliver(pending["text"])
    if result == "sent":
        state["pending_delivery"] = None
        _resolve_last_delivery_error(state)
        _save_state(state)
        _log.info("workbench scheduler: queued delivery sent (attempt %s)", attempts)
        return True
    if attempts >= _DELIVERY_RETRY_MAX:
        state["pending_delivery"] = None
        errors = state.get("errors") or {}
        last = errors.get("last") or {}
        if last.get("reason") == "delivery:failed":
            last["reason"] = "delivery:dropped"
            errors["last"] = last
            state["errors"] = errors
        _save_state(state)
        _log.error("workbench scheduler: queued delivery dropped after %s attempts", attempts)
        return False
    pending["attempts"] = attempts
    pending["next_attempt_at"] = (
        datetime.now() + timedelta(minutes=_DELIVERY_RETRY_MINUTES)
    ).isoformat(timespec="seconds")
    state["pending_delivery"] = pending
    _save_state(state)
    _log.warning("workbench scheduler: queued delivery retry %s/%s", attempts, _DELIVERY_RETRY_MAX)
    return False


# ---------------------------------------------------------------------------
# 工具：子进程 / LLM / 投递
# ---------------------------------------------------------------------------


def _hermes_bin() -> Optional[Path]:
    exe = shutil.which("hermes")
    if exe:
        return Path(exe)
    cand = Path(sys.executable).resolve().parent / "hermes.exe"
    if cand.is_file():
        return cand
    return None


def _run_script(
    name: str,
    args: list[str],
    timeout: int = _SCRIPT_TIMEOUT,
    env: Optional[dict] = None,
) -> dict:
    """运行脚本（P0-A 收编完成：插件包 scripts/ 优先、HERMES_HOME/scripts 兜底）。"""
    script = _PLUGIN_SCRIPTS_DIR / name
    if not script.is_file():
        script = _SCRIPTS_DIR / name
    if not script.is_file():
        raise FileNotFoundError(f"workbench script missing: {script}")
    proc = subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
    )
    return {
        "exit": proc.returncode,
        "stdout": (proc.stdout or "")[:2000],
        "stderr": (proc.stderr or "")[:2000],
    }


def _script_data(name: str) -> Optional[dict]:
    try:
        r = _run_script(
            name,
            ["--data"],
            timeout=120,
            env=_script_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _log.warning("workbench scheduler data script %s failed: %s", name, exc)
        return None
    if r["exit"] != 0:
        _log.warning("workbench scheduler data script %s exit=%s", name, r["exit"])
        return None
    try:
        data = json.loads(r["stdout"])
    except json.JSONDecodeError:
        _log.warning("workbench scheduler data script %s produced invalid JSON", name)
        return None
    return data if isinstance(data, dict) else None


def _script_env() -> dict:
    """P0-A：统一注入 root/db/ttl 三键（脚本不再依赖个人默认值/环境残留）。"""
    from workbench_config import get_db_path, get_root, get_ttl

    ttl = get_ttl()
    env = dict(os.environ)
    env["WORKBENCH_ROOT"] = get_root()
    env["WORKBENCH_DB"] = get_db_path()
    env["WORKBENCH_TTL_DAYS"] = str(ttl["days"])
    env["WORKBENCH_TTL_MODE"] = ttl["mode"]
    return env


def _generate(ctx: Any, prompt_template: str, data: Optional[dict]) -> str:
    """宿主 LLM 生成（缺省模型；ctx 缺失/数据缺失 → 空，安全侧）。"""
    if ctx is None or data is None:
        return ""
    prompt = prompt_template + "\n\n【注入数据 JSON】\n" + json.dumps(data, ensure_ascii=False)
    try:
        result = ctx.llm.complete(
            [{"role": "user", "content": prompt}],
            timeout=_LLM_TIMEOUT,
            purpose="workbench-scheduler",
        )
    except Exception as exc:  # noqa: BLE001 - 生成失败记日志，不静默
        _log.error("workbench scheduler LLM generation failed: %s", exc)
        return ""
    return (result.text or "").strip()


def _deliver(text: str) -> str:
    """QQ 投递（官方 hermes send，REST 直连）。空文本 → skipped-empty。"""
    from workbench_config import get_deliver_target

    text = (text or "").strip()
    if not text:
        return "skipped-empty"
    target = get_deliver_target()
    if not target:
        # P0：投递目标未配置 = error 级显式状态（DELIVERY-UNCONFIGURED），不 crash 不静默
        _log.error("workbench scheduler DELIVERY-UNCONFIGURED: deliver_target 为空，请在设置面板配置")
        return "unconfigured"
    hermes = _hermes_bin()
    if hermes is None:
        return "error-no-hermes"
    try:
        proc = subprocess.run(
            [str(hermes), "send", "--to", target, text],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_SEND_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _log.error("workbench scheduler delivery failed: %s", exc)
        return "failed"
    if proc.returncode == 0:
        return "sent"
    _log.error(
        "workbench scheduler DELIVERY-FAIL code=%s err=%s",
        proc.returncode,
        (proc.stderr or proc.stdout or "")[:500],
    )
    return "failed"


_WORKLOG_RE = re.compile(r"<WORKLOG>(.*?)</WORKLOG>", re.S)
_QQ_RE = re.compile(r"<QQMSG>(.*?)</QQMSG>", re.S)


def _split_output(text: str) -> dict:
    """解析 LLM 输出：<WORKLOG>/<QQMSG> 两段；无标记 → 全文当 QQ，含日报标题则当工作日志。"""
    if not text:
        return {"worklog": "", "qq": ""}
    wm = _WORKLOG_RE.search(text)
    qm = _QQ_RE.search(text)
    if wm or qm:
        return {
            "worklog": (wm.group(1) if wm else "").strip(),
            "qq": (qm.group(1) if qm else "").strip(),
        }
    if text.startswith("# 工作台日报") or "## 今日完成" in text:
        return {"worklog": text, "qq": text}
    return {"worklog": "", "qq": text}


def _write_daily_worklog(text: str, vault: Optional[Path] = None) -> str:
    """写入 工作日志/YYYY-MM/DD-工作台日报.md；已存在或空 → 不写。"""
    from workbench_config import get_vault

    text = (text or "").strip()
    if len(text) < 20:
        return "skipped-empty"
    today = datetime.now()
    vault_path = vault or get_vault()
    if not vault_path:
        # P0：vault 未配置 = 跳过工作日志（面板可见状态），不落到当前目录
        return "skipped-unconfigured"
    log_dir = Path(vault_path) / "Hermes Agent" / "运维" / "工作日志" / today.strftime("%Y-%m")
    log_dir.mkdir(parents=True, exist_ok=True)
    fp = log_dir / f"{today:%d}-工作台日报.md"
    if fp.exists():
        return "skipped-exists"
    try:
        fp.write_text(text, encoding="utf-8")
    except OSError as exc:
        _log.error("workbench scheduler worklog write failed: %s", exc)
        return "failed"
    return "written"


# ---------------------------------------------------------------------------
# 任务实现
# ---------------------------------------------------------------------------


def _job_lifecycle(ctx: Any) -> dict:
    """执行生命周期协调（*/10）：扫描显式 execution_result → 完成归档/失败恢复。"""
    import auto_archive  # noqa: PLC0415 - 惰性导入，避免 import 期全栈

    tasks = auto_archive.scan_execution_results()
    completed = failed = errors = 0
    for filename, decision in tasks:
        try:
            r = auto_archive.reconcile(filename, decision)
            if r.get("ok"):
                if decision == "completed":
                    completed += 1
                else:
                    failed += 1
            else:
                errors += 1
                _log.warning("workbench scheduler reconcile failed %s: %s", filename, r.get("error"))
        except Exception as exc:  # noqa: BLE001
            errors += 1
            _log.warning("workbench scheduler reconcile exception %s: %s", filename, exc)
    return {"scanned": len(tasks), "completed": completed, "failed": failed, "errors": errors}


def _job_maintenance(ctx: Any) -> dict:
    """每日维护（12:30）：归档巡检 → DB 收敛(--fix) → 回收站 TTL。"""
    r = _run_script(
        "workbench_maintenance.py",
        ["--mode", "clean"],
        timeout=_SCRIPT_TIMEOUT,
        env=_script_env(),
    )
    summary = {"exit": r["exit"]}
    if r["exit"] != 0:
        summary["error"] = (r["stderr"] or r["stdout"])[:500]
        raise RuntimeError(f"workbench maintenance failed: {summary['error']}")
    return summary


_DAILY_PROMPT = """根据注入的 Workbench JSON 生成中文判断型日报。只保留用户需要做决策的信息，不复述调度器、脚本、文件路径、job id、执行耗时等系统细节。

输出格式（两段，严格用标记包裹，不要输出其他内容）：
<WORKLOG>
工作日志 markdown 全文：首行为 # Workbench 日报 — YYYY-MM-DD（周X）；正文按 ## 今日推进 / ## 待处理 / ## 风险与阻塞 / ## 明日优先 组织，周日加 ## 本周复盘。合并重复项，每项写清结论与下一步；无内容的章节省略。当日无实质变更时输出空。
</WORKLOG>
<QQMSG>
控制在 900 个中文字符内，使用以下成品格式；没有内容的栏目直接省略：
📋 Workbench 日报 · MM.DD 周X
💡 一句话判断：今天最重要的进展或风险
✅ 今日推进（最多 3 条）
⏳ 待处理（最多 3 条）
⚠️ 风险与阻塞（仅确有风险时）
🎯 明日优先（最多 3 条，按优先级排序）
不要出现 Cronjob Response、job_id、管理任务提示、Auto-generated、内部标记或生成过程。无值得报告内容时输出空。
</QQMSG>"""

_NUDGE_PROMPT = """工作台 auto-nudge（Workbench 内建调度生成，宿主 LLM 判断）：根据注入 JSON（overdue/blocked/today_due/stale/duplicate）生成一条判断型提醒：超期任务（标题+超期天数）、被阻塞项、可交给 Agent 的建议，不超过 1 屏。
如果没有值得提醒的内容，输出 <QQMSG></QQMSG> 空（不发送，保持每日 ≤2 条聚合红线）。
只报告，不修改任何文件。严格用 <QQMSG>...</QQMSG> 包裹提醒文本，不要输出其他内容。"""


def _current_health_snapshot() -> dict:
    try:
        from plugin_api import health

        result = health()
        return result if isinstance(result, dict) else {}
    except Exception as exc:  # noqa: BLE001
        _log.warning("workbench daily report health snapshot failed: %s", exc)
        return {"status": "yellow", "label": "健康状态暂不可用"}


def _health_report_line(snapshot: dict) -> str:
    status = snapshot.get("status")
    if status not in {"yellow", "red"}:
        return ""
    icon = "🟡" if status == "yellow" else "🔴"
    label = str(snapshot.get("label") or ("链路待观察" if status == "yellow" else "链路故障"))
    return f"{icon} 链路状态：{label}"


def _validate_generated_text(text: str, data: Optional[dict]) -> dict:
    """Post-generation 事实校验：LLM 输出严格基于数据 allow-list。

    Returns {"ok": bool, "issues": [str]}.
    - 数据缺失/文本空 → 拒绝（不可证明即不发送）
    - 已处理/待处理数量与数据不一致 → 拒绝
    - 文本中的任何标题不在数据标题集（processed+pending）→ 拒绝（发明标题）
    - 同一标题重复出现 → 拒绝（重复）
    - 数据中每条 pending/processed 标题必须出现在文本 → 拒绝（遗漏）
    """
    issues: list[str] = []
    if not text or not isinstance(data, dict):
        return {"ok": False, "issues": ["缺少生成文本或数据"]}
    processed = data.get("processed", []) or []
    pending = data.get("pending", []) or []
    allowed: set[str] = set(str(x) for x in processed)
    for item in pending:
        if isinstance(item, dict):
            allowed.add(str(item.get("title") or ""))
        else:
            allowed.add(str(item))
    allowed.discard("")

    m = re.search(r"已处理（(\d+) 条）", text)
    if not m:
        issues.append("缺少 已处理 数量声明")
    elif int(m.group(1)) != len(processed):
        issues.append(f"已处理数量不匹配: 文本 {m.group(1)} vs 数据 {len(processed)}")
    m2 = re.search(r"待处理（(\d+) 条）", text)
    if not m2:
        issues.append("缺少 待处理 数量声明")
    elif int(m2.group(1)) != len(pending):
        issues.append(f"待处理数量不匹配: 文本 {m2.group(1)} vs 数据 {len(pending)}")

    # 标题级检查：逐行扫描非空、非统计行作为候选标题
    seen_in_text: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(("✅", "📌", "📋", "今天没有")):
            continue
        cand = re.sub(r"^\d+\.\s*", "", line)
        cand = re.sub(r"^【[^】]+】", "", cand)
        cand = cand.split("（截止")[0].strip()
        if cand and not cand.startswith(("✅", "📌")):
            seen_in_text.append(cand)
    dups = [t for t in seen_in_text if seen_in_text.count(t) > 1]
    if dups:
        issues.append(f"标题重复: {sorted(set(dups))[:5]}")
    invented = [t for t in seen_in_text if t not in allowed]
    if invented:
        issues.append(f"文本含数据外标题: {invented[:5]}")
    omitted = [t for t in sorted(allowed) if t not in seen_in_text]
    if omitted:
        issues.append(f"数据标题遗漏: {omitted[:5]}")
    return {"ok": not issues, "issues": issues}


def _build_daily_records(data: dict) -> dict:
    """Build canonical records with stable per-run opaque IDs.

    Each processed/pending/week_completed item gets a stable ID (D1, D2, P1, W1 etc.)
    paired with its user-readable title for downstream deterministic rendering.
    """
    processed = data.get("processed", []) or []
    pending = data.get("pending", []) or []
    week = data.get("week", {}) or {}

    # Deterministic display-limit rule (selects BEFORE the model): today's
    # processed is capped at 10, pending at 5, weekly highlights at 8 — the
    # same documented production maximums the parser enforces. After the cap,
    # every listed record is mandatory; the model cannot omit it.
    records = {
        "processed": [{"id": f"D{i+1}", "title": t} for i, t in enumerate(processed[:10])],
        "pending": [
            {
                "id": f"P{i+1}",
                "title": p["title"] if isinstance(p, dict) else str(p),
                "label": p.get("label", "") if isinstance(p, dict) else "",
                "due": p.get("due", "") if isinstance(p, dict) else "",
                "blocked": bool(p.get("blocked") if isinstance(p, dict) else False),
            }
            for i, p in enumerate(pending[:5])
        ],
        "week_completed": [{"id": f"W{i+1}", "title": t} for i, t in enumerate(week.get("completed", [])[:8])],
        "stats": {
            "week_new": week.get("new_count", 0),
            "week_remaining": week.get("remaining_count", 0),
            "week_blocked": week.get("blocked_count", 0),
            "week_due_next": week.get("due_next_week", 0),
            "week_completed_count": week.get("completed_count", 0),
        },
    }
    return records


_DAILY_STRUCTURED_PROMPT = """根据注入的 Workbench 记录生成结构化日报分析。

【记录】
{records_json}

要求：
1. 从 processed 中选有价值的完成项放进 "processed" 数组（只放 ID，如 ["D1", "D2"]）；最多 10 条，没有则为空列表 []。
2. 从 pending 中选需要提醒的待办放进 "pending" 数组（只放 ID）；最多 5 条，没有则为空列表 []。
3. 从 week_completed 中选本周值得汇报的完成项放进 "week_completed" 数组（只放 ID，如 ["W1", "W2"]）；最多 8 条，没有则为空列表 []。

输出严格 JSON（只引用记录中存在的 ID，不能发明新 ID，不要输出其他键）：
{{"processed": ["D1", "D2"], "pending": ["P1"], "week_completed": ["W1"]}}

没有值得报告的内容时输出：{{"processed": [], "pending": [], "week_completed": []}}"""


def _parse_structured_output(text: str, records: dict) -> dict:
    """Parse and validate structured model output against canonical records.

    Returns {"ok": bool, "issues": [str], "parsed": dict|None}.
    Only "processed", "pending", "week_completed" arrays of allowed IDs are accepted.
    No free-text judgement/recommendation — those are generated deterministically.
    Rejects unknown keys, duplicate IDs, unknown IDs, and over-limit arrays.
    """
    issues: list[str] = []
    parsed: dict | None = None

    if not text or not text.strip():
        return {"ok": False, "issues": ["模型输出为空"], "parsed": None}

    # Extract JSON from markdown code block or try whole text
    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if json_match:
        json_str = json_match.group(1).strip()
    else:
        json_str = text.strip()

    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError as exc:
        return {"ok": False, "issues": [f"无效 JSON 格式: {exc}"], "parsed": None}

    if not isinstance(parsed, dict):
        return {"ok": False, "issues": ["输出不是 JSON 对象"], "parsed": None}

    # Reject unknown keys (prevents smuggling prose through extra fields)
    ALLOWED_KEYS = {"processed", "pending", "week_completed"}
    unknown_keys = set(parsed.keys()) - ALLOWED_KEYS
    if unknown_keys:
        issues.append(f"未知键: {sorted(unknown_keys)}")

    # Build allowed ID sets
    allowed_processed = {r["id"] for r in records.get("processed", [])}
    allowed_pending = {r["id"] for r in records.get("pending", [])}
    allowed_week = {r["id"] for r in records.get("week_completed", [])}

    # Validate processed IDs
    selected_processed = parsed.get("processed")
    if not isinstance(selected_processed, list):
        issues.append("processed 不是数组")
    else:
        if len(selected_processed) > 10:
            issues.append(f"processed 超过上限 (10): {len(selected_processed)} 条")
        seen: set[str] = set()
        for pid in selected_processed:
            if not isinstance(pid, str):
                issues.append(f"processed 含非字符串值: {pid}")
            elif pid in seen:
                issues.append(f"processed 含重复 ID: {pid}")
            elif pid not in allowed_processed:
                issues.append(f"processed 含未知 ID: {pid}")
            else:
                seen.add(pid)

    # Validate pending IDs
    selected_pending = parsed.get("pending")
    if not isinstance(selected_pending, list):
        issues.append("pending 不是数组")
    else:
        if len(selected_pending) > 5:
            issues.append(f"pending 超过上限 (5): {len(selected_pending)} 条")
        seen_p: set[str] = set()
        for pid in selected_pending:
            if not isinstance(pid, str):
                issues.append(f"pending 含非字符串值: {pid}")
            elif pid in seen_p:
                issues.append(f"pending 含重复 ID: {pid}")
            elif pid not in allowed_pending:
                issues.append(f"pending 含未知 ID: {pid}")
            else:
                seen_p.add(pid)

    # Validate week_completed IDs
    selected_week = parsed.get("week_completed", [])
    if not isinstance(selected_week, list):
        issues.append("week_completed 不是数组")
    else:
        if len(selected_week) > 8:
            issues.append(f"week_completed 超过上限 (8): {len(selected_week)} 条")
        seen_w: set[str] = set()
        for pid in selected_week:
            if not isinstance(pid, str):
                issues.append(f"week_completed 含非字符串值: {pid}")
            elif pid in seen_w:
                issues.append(f"week_completed 含重复 ID: {pid}")
            elif pid not in allowed_week:
                issues.append(f"week_completed 含未知 ID: {pid}")
            else:
                seen_w.add(pid)

    # Mandatory current-day records: today's processed/pending facts cannot be
    # omitted — the deterministic display-limit rule already selected them
    # before the model, so every listed processed/pending ID must be present.
    if isinstance(selected_processed, list) and not any(
        i.startswith(("processed", "pending")) for i in issues
    ):
        missing_d = sorted(allowed_processed - set(selected_processed))
        if missing_d:
            issues.append(f"遗漏今日完成项: {missing_d}")

    if isinstance(selected_pending, list) and not any(
        i.startswith(("processed", "pending")) for i in issues
    ):
        missing_p = sorted(allowed_pending - set(selected_pending))
        if missing_p:
            issues.append(f"遗漏今日待办: {missing_p}")

    return {"ok": not issues, "issues": issues, "parsed": parsed if not issues else None}


def _generate_deterministic_judgement(records: dict, parsed: dict, data: dict | None = None) -> tuple[str, str]:
    """Generate judgement and recommendation deterministically from validated source fields.

    Args:
        records: Canonical records with IDs, titles, due dates.
        parsed: Validated parsed output with ID arrays only.
        data: Optional top-level data dict (stats, link_health).

    Returns:
        (judgement, recommendation) — both derived from source fields, never invented.
    """
    # Counts come from collector records when present; fall back to validated
    # parsed selection only in unit-test style calls without the real data dict.
    data_processed = (data or {}).get("processed")
    data_pending = (data or {}).get("pending")
    week_stats = (data or {}).get("week") or {}
    processed_count = len(data_processed) if isinstance(data_processed, list) else len(parsed.get("processed", []))
    pending_count = len(data_pending) if isinstance(data_pending, list) else len(parsed.get("pending", []))
    if week_stats.get("completed_count"):
        week_count = int(week_stats["completed_count"])
    else:
        week_count = len(parsed.get("week_completed", []))

    judgement_parts = []
    if processed_count > 0:
        judgement_parts.append(f"今日推进 {processed_count} 项")
    if pending_count > 0:
        judgement_parts.append(f"待处理 {pending_count} 项")
    if week_count > 0:
        judgement_parts.append(f"本周完成 {week_count} 项")

    # Check for due items from pending records
    pending_records = {r["id"]: r for r in records.get("pending", [])}
    due_items = []
    for pid in parsed.get("pending", []):
        p = pending_records.get(pid)
        if p and p.get("due"):
            due_items.append(f"{p['title']} 到期 {p['due']}")
    if due_items:
        judgement_parts.append(f"到期 {len(due_items)} 项")
        judgement_parts.extend(due_items[:2])

    # Stats from collector records
    stats = records.get("stats", {}) or {}
    if data and (data.get("week") or {}):
        stats = {**stats, **{k: v for k, v in data["week"].items() if k in ("blocked_count", "remaining_count", "due_next_week", "new_count")}}
    blocked_count = stats.get("week_blocked", stats.get("blocked_count", 0))
    if blocked_count > 0:
        judgement_parts.append(f"阻塞 {blocked_count} 项")

    judgement = "，".join(judgement_parts) if judgement_parts else ""

    # Recommendation: only from actionable source fields
    recommendation_parts = []
    if due_items:
        due_names = [d.split(" 到期")[0] for d in due_items[:2]]
        recommendation_parts.append(f"到期项需处理: {'、'.join(due_names)}")
    elif pending_count > 0:
        remaining = stats.get("week_remaining", stats.get("remaining_count", 0))
        if remaining > 0:
            recommendation_parts.append(f"本周剩余 {remaining} 项待办")
    if blocked_count > 0:
        recommendation_parts.append(f"阻塞 {blocked_count} 项待解除")
    health = (data or {}).get("link_health", {}) or {}
    if isinstance(health, dict) and health.get("status") == "red":
            recommendation_parts.append("链路状态需排查")

    recommendation = "；".join(recommendation_parts) if recommendation_parts else ""

    return judgement, recommendation


def _render_worklog(records: dict, parsed: dict, today: str, data: dict | None = None) -> str:
    """Render WORKLOG markdown from validated structured output."""
    title_map: dict[str, str] = {}
    for r in records.get("processed", []):
        title_map[r["id"]] = r["title"]
    for r in records.get("pending", []):
        title_map[r["id"]] = r["title"]
    for r in records.get("week_completed", []):
        title_map[r["id"]] = r["title"]

    try:
        dt_parsed = datetime.fromisoformat(today) if "T" in today else datetime.strptime(today, "%Y-%m-%d")
        weekday_cn = "一二三四五六日"[dt_parsed.weekday()]
        header = f"# Workbench 日报 — {today} 周{weekday_cn}"
    except (ValueError, IndexError):
        header = f"# Workbench 日报 — {today}"

    lines = [header, ""]

    selected_processed = [title_map.get(pid, pid) for pid in parsed.get("processed", []) if pid in title_map]
    if selected_processed:
        lines.append("## 今日推进")
        for title in selected_processed:
            lines.append(f"- {title}")
        lines.append("")

    selected_pending = [title_map.get(pid, pid) for pid in parsed.get("pending", []) if pid in title_map]
    if selected_pending:
        lines.append("## 待处理")
        for title in selected_pending:
            lines.append(f"- {title}")
        lines.append("")

    # Deterministic judgement from source fields
    judgement, recommendation = _generate_deterministic_judgement(records, parsed, data)
    if judgement:
        lines.append(f"**判断：** {judgement}")
        lines.append("")

    if recommendation:
        lines.append(f"**建议：** {recommendation}")
        lines.append("")

    selected_week = [title_map.get(pid, pid) for pid in parsed.get("week_completed", []) if pid in title_map]
    if selected_week:
        lines.append("## 本周完成")
        for title in selected_week:
            lines.append(f"- {title}")
        lines.append("")

    if not selected_processed and not selected_pending and not selected_week and not judgement and not recommendation:
        lines.append("今天没有实质变更。")

    return "\n".join(lines).strip()


def _render_qqmsg(records: dict, parsed: dict, today: str, data: dict | None = None) -> str:
    """Render QQMSG from validated structured output."""
    title_map: dict[str, str] = {}
    for r in records.get("processed", []):
        title_map[r["id"]] = r["title"]
    for r in records.get("pending", []):
        title_map[r["id"]] = r["title"]
    for r in records.get("week_completed", []):
        title_map[r["id"]] = r["title"]

    try:
        dt_parsed = datetime.fromisoformat(today) if "T" in today else datetime.strptime(today, "%Y-%m-%d")
        weekday_cn = "一二三四五六日"[dt_parsed.weekday()]
        header = f"📋 Workbench 日报 · {dt_parsed.month:02d}.{dt_parsed.day:02d} 周{weekday_cn}"
    except (ValueError, IndexError):
        header = "📋 Workbench 日报"

    lines = [header]

    # Deterministic judgement from source fields
    judgement, recommendation = _generate_deterministic_judgement(records, parsed, data)
    if judgement:
        lines.append(f"💡 {judgement}")

    if recommendation:
        lines.append(f"➡️ {recommendation}")

    selected_processed = [title_map.get(pid, pid) for pid in parsed.get("processed", []) if pid in title_map]
    if selected_processed:
        lines.append("✅ 今日推进")
        for title in selected_processed:
            lines.append(f"  · {title}")

    selected_pending = [title_map.get(pid, pid) for pid in parsed.get("pending", []) if pid in title_map]
    if selected_pending:
        lines.append("⏳ 待处理")
        for title in selected_pending:
            lines.append(f"  · {title}")

    selected_week = [title_map.get(pid, pid) for pid in parsed.get("week_completed", []) if pid in title_map]
    if selected_week:
        lines.append("📊 本周完成")
        for title in selected_week:
            lines.append(f"  · {title}")

    if not selected_processed and not selected_pending and not selected_week and not judgement and not recommendation:
        lines.append("今天没有收录和待办事项。")

    return "\n".join(lines)


def _deterministic_daily_text() -> str:
    """确定性回退：脚本无参模式（模板输出），不依赖 LLM。"""
    try:
        r = _run_script(
            "workbench_daily_report.py",
            [],
            timeout=120,
            env=_script_env(),
        )
        if r["exit"] == 0:
            return (r["stdout"] or "").strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return ""


def _job_daily_report(ctx: Any) -> dict:
    """工作台每日日报（20:00）：数据 → LLM → 工作日志 → QQ。

    事实闸门：数据必须经 data_validated（schema+事实），LLM 正文必须
    通过 allow-list 校验（数量/标题集合/发明/重复/遗漏）；任一失败 →
    确定性回退，绝不投递事实无效内容。
    """
    from workbench_config import get_write_worklog

    data = _script_data("workbench_daily_report.py")
    health_snapshot = _current_health_snapshot()
    if isinstance(data, dict):
        data["link_health"] = health_snapshot
    data_validated = bool(isinstance(data, dict) and data.get("data_validated") is True)
    data_facts = data.get("factual_validation") if isinstance(data, dict) else None

    text = ""
    generated = "empty"
    factual = {"ok": False, "issues": ["数据未通过事实校验"]}

    if data_validated and data:
        records = _build_daily_records(data)
        prompt = _DAILY_STRUCTURED_PROMPT.format(records_json=json.dumps(records, ensure_ascii=False))
        data_with_records = dict(data)
        data_with_records["_records"] = records
        model_raw = _generate(ctx, prompt, data_with_records)
        if model_raw:
            parsed = _parse_structured_output(model_raw, records)
            if parsed["ok"]:
                generated = "ok"
                factual = {"ok": True, "issues": []}
                wl = _render_worklog(records, parsed["parsed"], data["today"], data)
                qq = _render_qqmsg(records, parsed["parsed"], data["today"], data)
                text = f"<WORKLOG>\n{wl}\n</WORKLOG>\n<QQMSG>\n{qq}\n</QQMSG>"
            else:
                generated = "invalid"
                factual = {"ok": False, "issues": parsed["issues"]}

    if not text or not factual["ok"]:
        # 无效/缺失生成 → 确定性回退（事实无效内容绝不因生成成功而发送）
        text = _deterministic_daily_text()
        text = _split_output(text).get("qq") or text
        if not text:
            return {
                "generated": generated or "empty",
                "data_validated": data_validated,
                "factual_validation": factual,
                "worklog": "skipped-empty",
                "delivery": "skipped-empty",
            }
        generated = "fallback-invalid" if generated == "invalid" else "fallback"
        factual = {"ok": True, "issues": [], "note": "deterministic fallback"}

    parts = _split_output(text)
    worklog = (
        _write_daily_worklog(parts.get("worklog") or "")
        if get_write_worklog()
        else "skipped-disabled"
    )
    qq_message = parts.get("qq") or ""
    health_line = _health_report_line(health_snapshot)
    if qq_message and health_line:
        qq_message = f"{qq_message.rstrip()}\n\n{health_line}"
    delivery = _deliver(qq_message)
    if delivery == "failed" and qq_message:
        _queue_delivery(qq_message)
    return {
        "generated": generated,
        "data_validated": data_validated,
        "factual_validation": {**data_facts, **factual} if isinstance(data_facts, dict) else factual,
        "worklog": worklog,
        "delivery": delivery,
        "queued_retry": delivery == "failed" and bool(qq_message),
    }

def _job_nudge(ctx: Any) -> dict:
    """超期任务提醒（12:15）：数据 → LLM → QQ；无内容不发送。"""
    data = _script_data("workbench_auto_nudge.py")
    text = _generate(ctx, _NUDGE_PROMPT, data)
    if not text:
        return {"generated": "empty", "delivery": "skipped-empty"}
    parts = _split_output(text)
    delivery = _deliver(parts.get("qq") or "")
    if delivery == "failed" and parts.get("qq"):
        _queue_delivery(parts["qq"])
    return {"generated": "ok", "delivery": delivery, "queued_retry": delivery == "failed" and bool(parts.get("qq"))}


_JOB_RUNNERS = {
    "lifecycle": _job_lifecycle,
    "maintenance": _job_maintenance,
    "daily_report": _job_daily_report,
    "nudge": _job_nudge,
}

JOBS = [
    {"key": "lifecycle", "expr": "*/10 * * * *", "desc": "执行生命周期协调"},
    {"key": "maintenance", "expr": "30 12 * * *", "desc": "每日维护"},
    {"key": "daily_report", "expr": "0 20 * * *", "desc": "工作台每日日报"},
    {"key": "nudge", "expr": "15 12 * * *", "desc": "超期任务提醒"},
]


# ---------------------------------------------------------------------------
# 调度器主体
# ---------------------------------------------------------------------------


class Scheduler:
    """内建调度器：单实例租约 + 后台线程事件循环 + 20s 节拍。"""

    def __init__(self, ctx: Any) -> None:
        self._ctx = ctx
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lease = _Lease(_LOCK_FILE)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="workbench-scheduler",
            daemon=True,
        )
        self._thread.start()
        _log.info("workbench scheduler thread started (pid=%s)", os.getpid())

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._lease.release()

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            if not self._lease.acquire():
                _log.info("workbench scheduler: another process holds the lease; standing down")
                return
            _log.info("workbench scheduler: lease acquired pid=%s", os.getpid())
            loop.run_until_complete(self._loop())
        except Exception as exc:  # noqa: BLE001
            _log.exception("workbench scheduler loop crashed: %s", exc)
        finally:
            self._lease.release()
            loop.close()

    async def _loop(self) -> None:
        from workbench_config import get_schedule

        await asyncio.to_thread(_migrate_state_file)  # WB-S1-011：旧 schema → v2（幂等）
        await asyncio.to_thread(_reconcile_stale_states)  # WB-S1-011：重启先标 stale，不静默成功
        await self._catch_up()  # A4：启动补跑（重启错过的日报/提醒/维护）
        last_heartbeat = time.monotonic()
        while not self._stop.is_set():
            now = datetime.now()
            if time.monotonic() - last_heartbeat >= _HEARTBEAT_SECONDS:
                self._lease.heartbeat()
                last_heartbeat = time.monotonic()
            state = _load_state()
            await asyncio.to_thread(_retry_pending_delivery)
            schedule = get_schedule()
            for job in JOBS:
                job_cfg = schedule.get(job["key"], {})
                if not job_cfg.get("enabled", True):
                    continue
                expr = job_cfg.get("expr") or job["expr"]
                if not match_cron(expr, now):
                    continue
                key = f"{job['key']}|{now:%Y-%m-%d %H:%M}"
                # WB-S1-011：防重走 job_states.attempt_key（覆盖进行中/失败/中断），
                # last_runs 仅兜底旧 schema 语义（已完成）
                if _attempt_already_handled(state, job["key"], key):
                    continue
                if state["last_runs"].get(job["key"]) == key:
                    continue
                _set_phase(state, job["key"], PHASE_SCHEDULED, key)  # 先标排定
                await self._run_job(job, key)
            await asyncio.sleep(_TICK_SECONDS)

    async def _catch_up(self) -> None:
        """启动补跑（WB A4 / GT 复核确认）：重启后补跑 catch_up_hours 内错过的任务。

        lifecycle 不补（每 10 分钟，重启后自然跑）；空结果/失败照常走可见性统计。
        WB-S1-011：已被尝试过（完成/失败/中断）的调度不重复补跑。
        """
        from workbench_config import get_catch_up_hours, get_schedule

        catch_hours = get_catch_up_hours()
        if catch_hours <= 0:
            return
        state = _load_state()
        now = datetime.now()
        schedule = get_schedule()
        for job in JOBS:
            if job["key"] == "lifecycle":
                continue
            job_cfg = schedule.get(job["key"], {})
            if not job_cfg.get("enabled", True):
                continue
            expr = job_cfg.get("expr") or job["expr"]
            last_fire = _last_cron_fire(expr, now)
            if last_fire is None:
                continue
            last_run = _parse_run_key(state["last_runs"].get(job["key"], ""))
            if last_run and last_fire <= last_run:
                continue
            js_attempt = _parse_run_key(
                (state.get("job_states") or {}).get(job["key"], {}).get("attempt_key", "")
            )
            if js_attempt and js_attempt >= last_fire:
                continue
            age_hours = (now - last_fire).total_seconds() / 3600
            if age_hours > catch_hours:
                continue
            _log.info(
                "workbench catch-up: %s missed at %s (age %.1fh), running now",
                job["key"], last_fire, age_hours,
            )
            attempt_key = f"{job['key']}|{last_fire:%Y-%m-%d %H:%M}"
            _set_phase(state, job["key"], PHASE_SCHEDULED, attempt_key)
            await self._run_job(job, attempt_key)

    async def _run_job(self, job: dict, attempt_key: str) -> None:
        """执行一次调度并推进生命周期状态机。

        - started → (daily_report) artifact_written → delivery_sent → completed；
        - 失败/异常 → failed（保留 last_error + started_at）；
        - 仅 completed 更新 last_runs（P0 根因：尝试不再冒充完成）。
        """
        job_key = job["key"]
        started_at = datetime.now().isoformat(timespec="seconds")
        state = _load_state()
        _set_phase(state, job_key, PHASE_STARTED, attempt_key, started_at=started_at)
        _log.info("workbench scheduler: run %s at %s (attempt %s)", job_key, started_at, attempt_key)
        try:
            result = await asyncio.to_thread(_JOB_RUNNERS[job_key], self._ctx)
            ok, reason = _result_health(result)
            phase, phase_error = _derive_phase(job_key, result, ok, reason)
            if phase == PHASE_DELIVERY_SENT:
                # 中间态可观察：先落 delivery_sent（时间戳），确认契约后转 completed
                _set_phase(state, job_key, PHASE_DELIVERY_SENT, attempt_key, started_at=started_at)
                phase = PHASE_COMPLETED
                phase_error = None
            _set_phase(state, job_key, phase, attempt_key, started_at=started_at, last_error=phase_error)
            if not ok:
                _record_error(job_key, started_at, reason)
            _append_log(job_key, started_at, ok, result)
            _log.info(
                "workbench scheduler: %s ok=%s phase=%s reason=%s %s",
                job_key, ok, phase, reason or "-", json.dumps(result, ensure_ascii=False),
            )
        except Exception as exc:  # noqa: BLE001
            err = f"exception:{str(exc)[:200]}"
            _set_phase(state, job_key, PHASE_FAILED, attempt_key, started_at=started_at, last_error=err)
            _record_error(job_key, started_at, err)
            _append_log(job_key, started_at, False, {"error": str(exc)[:500]})
            _log.error("workbench scheduler: %s failed: %s", job_key, exc)


_SCHEDULER: Optional[Scheduler] = None


def start_scheduler(ctx: Any) -> Scheduler:
    """启动内建调度器（幂等：进程内只启动一次；卸载时自动停止）。"""
    global _SCHEDULER
    if _SCHEDULER is not None:
        return _SCHEDULER
    _SCHEDULER = Scheduler(ctx)
    _SCHEDULER.start()
    try:
        ctx.on_unload(_SCHEDULER.stop)
    except Exception as exc:  # noqa: BLE001
        _log.warning("workbench scheduler on_unload registration failed: %s", exc)
    return _SCHEDULER


def stop_scheduler() -> None:
    """停止本进程持有的调度器（测试/卸载兜底）。"""
    global _SCHEDULER
    if _SCHEDULER is not None:
        _SCHEDULER.stop()
        _SCHEDULER = None


def scheduler_status() -> dict:
    """可观测性：当前租约/状态/最近触发/生命周期阶段/错误计数。"""
    state = _load_state()
    error_count, last_error = _active_errors(state)
    job_states = {
        k: {
            "phase": v.get("phase"),
            "attempt_key": v.get("attempt_key"),
            "started_at": v.get("started_at"),
            "artifact_written_at": v.get("artifact_written_at"),
            "delivery_sent_at": v.get("delivery_sent_at"),
            "completed_at": v.get("completed_at"),
            "failed_at": v.get("failed_at"),
            "interrupted_at": v.get("interrupted_at"),
            "last_error": v.get("last_error"),
            "legacy": v.get("legacy", False),
        }
        for k, v in (state.get("job_states") or {}).items()
    }
    return {
        "running": _SCHEDULER is not None and _SCHEDULER._thread is not None and _SCHEDULER._thread.is_alive(),
        "pid": os.getpid(),
        "lease_holder": (
            _LOCK_FILE.read_text(encoding="utf-8", errors="replace").strip()
            if _LOCK_FILE.exists()
            else None
        ),
        "last_runs": state.get("last_runs", {}),
        "job_states": job_states,
        "error_count": error_count,
        "last_error": last_error,
    }
