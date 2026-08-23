# -*- coding: utf-8 -*-
"""Workbench 执行生命周期协调器。

扫描 任务/ 区的显式 execution_result：success 自动完成并归档；failure
自动恢复待办；pending 或缺失保持不动。脚本不读取 Hermes state.db。

- cron：*/10 * * * *（10 分钟一次），local 投递；无处理 → 空输出静默
- 用法：
    python workbench_auto_archive.py              # 正常：扫描并协调
    python workbench_auto_archive.py --dry-run    # 试跑：只输出不写
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_DASHBOARD = Path(__file__).resolve().parent.parent / "dashboard"
sys.path.insert(0, str(_DASHBOARD))

from auto_archive import (  # noqa: E402
    reconcile,
    scan_execution_results,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="Workbench 执行生命周期协调")
    ap.add_argument("--dry-run", action="store_true", help="试跑：只输出不写")
    args = ap.parse_args()

    tasks = scan_execution_results()
    handled: list[str] = []
    failures: list[str] = []
    for filename, decision in tasks:
        if args.dry_run:
            handled.append(filename)
            print(f"[dry-run] {filename} → {decision}")
            continue
        try:
            r = reconcile(filename, decision)
            if r.get("ok"):
                handled.append(filename)
                action = "已归档" if decision == "completed" else "已恢复待办"
                print(f"{action}：{filename}")
            else:
                failures.append(filename)
                print(f"协调失败：{filename} → {r.get('error')}")
        except Exception as e:  # noqa: BLE001
            failures.append(filename)
            print(f"协调异常：{filename} → {e}")
    if handled:
        print(f"共处理 {len(handled)} 个任务")
    if failures:
        print(f"共失败 {len(failures)} 个任务", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
