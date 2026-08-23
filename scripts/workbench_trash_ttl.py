# -*- coding: utf-8 -*-
"""工作台回收站 TTL 清理（A3）：扫描 回收站/ 超期文件 → 物理删除 + 埋点。

- 判定：frontmatter trashed_at < today - WORKBENCH_TTL_DAYS（默认 30 天）
- cron 模式：stdout 汇报清理结果；无超期 → 静默（空输出）
- 用法：
    python workbench_trash_ttl.py              # 正常：删除超期 + 写埋点
    python workbench_trash_ttl.py --dry-run    # 试跑：只输出不删
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# 复用 dashboard/ttl.py 的逻辑（同一模块，测试/脚本同源）
_DASHBOARD = Path(__file__).resolve().parent.parent / "dashboard"
sys.path.insert(0, str(_DASHBOARD))

from ttl import (  # noqa: E402
    DEFAULT_TTL_DAYS,
    archive_overdue,
    delete_overdue,
    get_ttl_mode,
    record_events,
    scan_trash_overdue,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="回收站 TTL 清理")
    ap.add_argument("--dry-run", action="store_true", help="试跑：只输出不处理")
    ap.add_argument(
        "--mode",
        choices=["archive", "delete"],
        default=None,
        help="archive=移入已处理保留实体（默认，受 WORKBENCH_TTL_MODE 覆盖）；delete=物理删除",
    )
    ap.add_argument(
        "--ttl-days",
        type=int,
        default=int(os.environ.get("WORKBENCH_TTL_DAYS", DEFAULT_TTL_DAYS)),
        help="超期阈值（天），默认 30",
    )
    args = ap.parse_args()

    mode = args.mode or get_ttl_mode()
    overdue = scan_trash_overdue(args.ttl_days)
    if not overdue:
        return 0  # 无超期 → 空输出静默（cron 不打扰）

    for filename, trashed_at, days in overdue:
        print(f"{filename} trashed_at={trashed_at} 超期 {days} 天")

    if not args.dry_run:
        if mode == "archive":
            archived = archive_overdue(overdue)
            record_events(overdue, payload_mode="archive")
            print(f"已归档保留 {len(archived)} 个超期文件（移入 已处理/，status: deleted）")
        else:
            deleted = delete_overdue(overdue)
            record_events(overdue, payload_mode="delete")
            print(f"已删除 {len(deleted)} 个超期文件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
