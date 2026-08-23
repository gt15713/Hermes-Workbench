# -*- coding: utf-8 -*-
"""Workbench 执行生命周期协调。

只处理任务文件中的显式终态：
- execution_result: success → 复用 plugin_api.complete 完成并归档；
- execution_result: failure → 复用 plugin_api.reset_execution 恢复待办；
- pending / 缺失 / 未知 → 不动作。

本模块不读取 Hermes state.db；会话结束从来不等于任务成功。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from workbench_config import get_root  # noqa: E402

ROOT = Path(get_root())

_DASHBOARD = Path(__file__).resolve().parent
if str(_DASHBOARD) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD))

from session_watch import _fm, decide, scan_in_progress  # noqa: E402


def scan_execution_results(root: Path | None = None) -> list[tuple[str, str]]:
    """返回需要协调的 (filename, completed|failed)，忽略 pending。

    已经被旧会话监测器或 Agent 直接写成 ``completed``、但仍留在任务区
    的文件也必须进入同一正式归档入口，否则会永久滞留且没有可用按钮。
    """
    root = root or ROOT
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in scan_in_progress(root):
        decision = decide(item["text"])
        if decision in {"completed", "failed"}:
            out.append((item["path"].name, decision))
            seen.add(item["path"].name)

    task_dir = root / "任务"
    if task_dir.is_dir():
        for path in sorted(task_dir.glob("*.md")):
            if path.name in seen:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if _fm(text).get("status") == "completed":
                out.append((path.name, "completed"))
    return out


def reconcile(filename: str, decision: str, retries: int = 3) -> dict:
    """通过 Workbench 后端正式端点应用一个显式终态。"""
    import time as _time

    import plugin_api as api  # noqa: PLC0415
    from repo import WorkbenchConflictError  # noqa: PLC0415

    # 2026-08-20：归档/回写遇到 expected_mtime 并发冲突时自动重试（插件 on_session_end
    # 在任务 turn 结束触发，与 agent 写文件并发；冲突重读后重试，避免失败无兜底）。
    last_error = None
    for attempt in range(retries):
        try:
            if decision == "completed":
                return asyncio.run(api.complete({"dir": "任务", "file": filename}))
            if decision == "failed":
                return asyncio.run(
                    api.reset_execution(
                        {
                            "dir": "任务",
                            "file": filename,
                            "reason": "Agent 显式报告任务执行失败",
                        }
                    )
                )
            return {"ok": False, "error": f"unsupported decision: {decision}"}
        except WorkbenchConflictError as e:
            last_error = {"ok": False, "error": f"concurrent write conflict (attempt {attempt + 1}/{retries}): {e}"}
            if attempt < retries - 1:
                _time.sleep(3)
    return last_error
