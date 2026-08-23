#!/usr/bin/env python3
"""工作台维护任务（Phase 0-5：cron 5→3 合并）。

- --mode=clean   每日 1 次：归档巡检 + DB 一致性校验(收敛) + 回收站 TTL（三合一）
  （--mode=session 会话检测骨架已于 2026-08-19 D5 退役：职责由 workbench_auto_archive.py 协调器接管）

调用方式：subprocess 依次执行现有脚本（保留各自日志与语义），汇总输出。
"""  # noqa: D400

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent


def _run(script: str, args: list[str] | None = None) -> tuple[int, str]:
    """运行 scripts/ 下的兄弟脚本，返回 (exit_code, stdout)。"""
    cmd = [sys.executable, str(SCRIPTS_DIR / script), *(args or [])]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        return 1, f"[maintenance] {script} 超时（600s）"


def mode_clean(dry_run: bool = False) -> int:
    """每日维护：归档巡检 → DB 校验(--fix) → 回收站 TTL。"""
    steps = [
        ("workbench_archive.py", []),
        ("workbench_db_verify.py", ["--fix", "--no-backup"]),
        ("workbench_trash_ttl.py", []),
    ]
    all_ok = True
    out_lines: list[str] = []
    for script, args in steps:
        if dry_run:
            print(f"[maintenance] dry-run：{script} {' '.join(args)}".strip())
            continue
        code, out = _run(script, args)
        if out.strip():
            out_lines.append(f"[{script}] {out.strip()}")
        if code != 0:
            all_ok = False
            out_lines.append(f"[maintenance] ⚠ {script} 退出码 {code}")
    if not all_ok or sys.stdout.isatty():
        if out_lines:
            print("\n".join(out_lines))
        if not all_ok:
            print("[maintenance] clean 存在失败，请查上方日志")
    else:
        pass  # cron 全部成功 → 静默（不投递 QQ）
    return 0 if all_ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="工作台维护任务（合并 cron）")
    ap.add_argument("--mode", choices=["clean"], default="clean")
    ap.add_argument("--dry-run", action="store_true", help="试跑：只输出不执行")
    args = ap.parse_args()
    return mode_clean(args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
