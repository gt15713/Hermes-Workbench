#!/usr/bin/env python3
"""workbench_db_migrate.py — 工作台 SQLite 镜像迁移（阶段 1.5）。

把 工作台/ 现有 Markdown 全量导入 workbench.db（tasks 表），幂等可重跑。
触发：阶段 1.5 一次性迁移；后续由 plugin_api / cron 双写自动维护。

用法：python workbench_db_migrate.py [--root <工作台根>] [--db <path>]
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
    ap = argparse.ArgumentParser(description="workbench.db 全量迁移")
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--db", default=None, help="DB 路径（默认插件目录 workbench.db）")
    ap.add_argument("--dry-run", action="store_true", help="只统计不写入")
    args = ap.parse_args()

    root = Path(args.root)
    db = SqliteRepo(args.db, root=root) if args.db else SqliteRepo(root=root)

    total = 0
    for partition in sorted(PARTITION_NAMES):
        d = root / partition
        if not d.is_dir():
            continue
        files = sorted(d.glob("*.md"))
        if not files:
            continue
        for p in files:
            text = p.read_text(encoding="utf-8", errors="replace")
            if not args.dry_run:
                db.write_text(p, text)
            total += 1
        print(f"  {partition}: {len(files)} 个")

    print(f"迁移完成：共 {total} 个文件 → {'DRY-RUN' if args.dry_run else db.db_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
