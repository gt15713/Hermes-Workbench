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
    try:
        os.kill(pid, 0)
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
            return data
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return {"last_runs": {}, "pending_delivery": None, "errors": {"count": 0, "last": None}, "updated_at": None}


def _save_state(state: dict) -> None:
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    try:
        _STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        _log.warning("workbench scheduler state write failed: %s", exc)


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
        _save_state(state)
        _log.info("workbench scheduler: queued delivery sent (attempt %s)", attempts)
        return True
    if attempts >= _DELIVERY_RETRY_MAX:
        state["pending_delivery"] = None
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
    """运行脚本（P0-A 双源：HERMES_HOME/scripts 优先、插件包 scripts/ 兜底）。"""
    script = _SCRIPTS_DIR / name
    if not script.is_file():
        script = _PLUGIN_SCRIPTS_DIR / name
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


_DAILY_PROMPT = """工作台每日日报（Workbench 内建调度生成，宿主 LLM 判断）：根据注入 JSON 生成中文判断型日报。
包含今日完成/新增/遗留、明日关注、超期与阻塞，QQ 段不超过一屏；周日输出本周完成/遗留/模式/下周建议。

输出格式（两段，严格用标记包裹，不要输出其他内容）：
<WORKLOG>
工作日志 markdown 全文：首行为 # 工作台日报 — YYYY-MM-DD（周X），第二行 > [Auto-generated] 数据来源：Workbench 预运行脚本；正文按 ## 今日完成 / ## 今日新增 / ## 遗留待回看 / ## 待验证 / ## 阻塞 / 超期 / ## 判断与明日关注 组织（周日加 ## 周进度）。当日无实质变更时输出空 <WORKLOG></WORKLOG>。
</WORKLOG>
<QQMSG>
一屏中文要点（标题 + 今日完成/新增/遗留简况 + 明日关注）；无值得报告内容时输出空 <QQMSG></QQMSG>。
</QQMSG>"""

_NUDGE_PROMPT = """工作台 auto-nudge（Workbench 内建调度生成，宿主 LLM 判断）：根据注入 JSON（overdue/blocked/today_due/stale/duplicate）生成一条判断型提醒：超期任务（标题+超期天数）、被阻塞项、可交给 Agent 的建议，不超过 1 屏。
如果没有值得提醒的内容，输出 <QQMSG></QQMSG> 空（不发送，保持每日 ≤2 条聚合红线）。
只报告，不修改任何文件。严格用 <QQMSG>...</QQMSG> 包裹提醒文本，不要输出其他内容。"""


def _job_daily_report(ctx: Any) -> dict:
    """工作台每日日报（20:00）：数据 → LLM → 工作日志 → QQ。"""
    from workbench_config import get_write_worklog

    data = _script_data("workbench_daily_report.py")
    text = _generate(ctx, _DAILY_PROMPT, data)
    if not text:
        return {"generated": "empty", "worklog": "skipped-empty", "delivery": "skipped-empty"}
    parts = _split_output(text)
    worklog = (
        _write_daily_worklog(parts.get("worklog") or "")
        if get_write_worklog()
        else "skipped-disabled"
    )
    delivery = _deliver(parts.get("qq") or "")
    if delivery == "failed" and parts.get("qq"):
        _queue_delivery(parts["qq"])
    return {
        "generated": "ok",
        "worklog": worklog,
        "delivery": delivery,
        "queued_retry": delivery == "failed" and bool(parts.get("qq")),
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
                if state["last_runs"].get(job["key"]) == key:
                    continue
                state["last_runs"][job["key"]] = key
                _save_state(state)
                await self._run_job(job)
            await asyncio.sleep(_TICK_SECONDS)

    async def _catch_up(self) -> None:
        """启动补跑（WB A4 / GT 复核确认）：重启后补跑 catch_up_hours 内错过的任务。

        lifecycle 不补（每 10 分钟，重启后自然跑）；空结果/失败照常走可见性统计。
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
            age_hours = (now - last_fire).total_seconds() / 3600
            if age_hours > catch_hours:
                continue
            _log.info(
                "workbench catch-up: %s missed at %s (age %.1fh), running now",
                job["key"], last_fire, age_hours,
            )
            state["last_runs"][job["key"]] = f"{job['key']}|{last_fire:%Y-%m-%d %H:%M}"
            _save_state(state)
            await self._run_job(job)

    async def _run_job(self, job: dict) -> None:
        started_at = datetime.now().isoformat(timespec="seconds")
        _log.info("workbench scheduler: run %s at %s", job["key"], started_at)
        try:
            result = await asyncio.to_thread(_JOB_RUNNERS[job["key"]], self._ctx)
            ok, reason = _result_health(result)
            if not ok:
                _record_error(job["key"], started_at, reason)
            _append_log(job["key"], started_at, ok, result)
            _log.info(
                "workbench scheduler: %s ok=%s reason=%s %s",
                job["key"], ok, reason or "-", json.dumps(result, ensure_ascii=False),
            )
        except Exception as exc:  # noqa: BLE001
            _record_error(job["key"], started_at, f"exception:{str(exc)[:200]}")
            _append_log(job["key"], started_at, False, {"error": str(exc)[:500]})
            _log.error("workbench scheduler: %s failed: %s", job["key"], exc)


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
    """可观测性：当前租约/状态/最近触发/错误计数。"""
    state = _load_state()
    errors = state.get("errors") or {}
    return {
        "running": _SCHEDULER is not None and _SCHEDULER._thread is not None and _SCHEDULER._thread.is_alive(),
        "pid": os.getpid(),
        "lease_holder": (
            _LOCK_FILE.read_text(encoding="utf-8", errors="replace").strip()
            if _LOCK_FILE.exists()
            else None
        ),
        "last_runs": state.get("last_runs", {}),
        "error_count": int(errors.get("count", 0)),
        "last_error": errors.get("last"),
    }
