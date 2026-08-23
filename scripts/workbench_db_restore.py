#!/usr/bin/env python3
"""workbench_db_restore.py — 应急重建：从 workbench.db 恢复缺失的任务文件。

用途：当任务文件意外丢失（磁盘误删/同步异常），从 DB tasks 表重建。
不入 cron，仅手动应急运行。

用法：
  python workbench_db_restore.py [--root ...] [--db ...] [--dry-run] [--force]

--dry-run  预览缺失清单，不写文件
--force    强制覆盖现有文件（默认跳过已存在）
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dashboard"))

from contract import PARTITION_NAMES  # noqa: E402
from repo import SqliteRepo  # noqa: E402
from workbench_config import get_root  # noqa: E402

DEFAULT_ROOT = Path(get_root())

def main() -> int:
    ap = argparse.ArgumentParser(description="从 workbench.db 恢复缺失的任务文件")
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--db", default=None, help="DB 路径（默认插件目录 workbench.db）")
    ap.add_argument("--dry-run", action="store_true", help="仅预览缺失清单，不写文件")
    ap.add_argument("--force", action="store_true", help="强制覆盖已有文件（默认跳过）")
    args = ap.parse_args()

    root = Path(args.root)
    db = SqliteRepo(args.db, root=root) if args.db else SqliteRepo(root=root)

    tasks = db._all_tasks()
    if not tasks:
        print("DB 无记录，无需恢复")
        return 0

    missing = []
    existing_skipped = []
    restored = 0

    for row in tasks:
        partition = row["partition"]
        filename = row["filename"]
        content = row["content"]

        if partition not in PARTITION_NAMES:
            continue

        target = root / partition / filename
        if target.exists():
            if args.force:
                existing_skipped.append(f"{partition}/{filename}（覆盖）")
            else:
                existing_skipped.append(f"{partition}/{filename}（跳过，已存在）")
                continue

        missing.append(f"{partition}/{filename}")

        if not args.dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            restored += 1

    if not missing:
        print("✅ 无缺失文件，无需恢复")
        if existing_skipped:
            print(f"已存在（跳过）：{len(existing_skipped)} 个")
            for x in existing_skipped:
                print(f"  - {x}")
        return 0

    print(f"{'[DRY-RUN] ' if args.dry_run else ''}缺失文件：{len(missing)} 个")
    for x in missing:
        print(f"  - {x}")

    if existing_skipped:
        print(f"已存在：{len(existing_skipped)} 个")
        for x in existing_skipped[:10]:
            print(f"  - {x}")
        if len(existing_skipped) > 10:
            print(f"  ...（共 {len(existing_skipped)} 个）")

    if not args.dry_run:
        print(f"✅ 已恢复 {restored}/{len(missing)} 个文件")
    return 0 if not args.dry_run else 0  # dry-run 也返回 0（信息性）

if __name__ == "__main__":
    # import os moved to top — 需要 os 用于 environ.get
    raise SystemExit(main())
