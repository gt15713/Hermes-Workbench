#!/usr/bin/env python3
"""workbench_db_verify.py — 工作台文件 vs SQLite 镜像一致性校验（阶段 1.5，每日 cron）。

职责：
1. 扫描 工作台/ 7 分区 *.md，与 workbench.db tasks 表逐项比对；
2. 差异分类：missing_in_db（文件有 DB 无）/ orphan_in_db（DB 有文件无）/ mtime_mismatch（内容可能变）/
   moved（文件被移动到其他分区——归档闭环等手工文件操作常见，DB 行待收敛）；
3. 有差异 → 追加到工作台 日志/YYYY-MM-DD.md（随日报可见）+ stdout 输出（非空即投递）；
4. 备份 workbench.db → Obsidian 备份目录（进 git，每日一份）。

--fix 收敛语义（2026-08-15 补「移动收敛」）：
- missing → 新增 DB 行；
- mismatch → 用文件内容刷新 DB 行；
- moved（同文件名 + 同内容出现在其他分区）→ DB 行迁移到新分区并刷新 status/mtime；
- 真 orphan（文件确实不存在）→ 保持不动（孤儿守卫；永久删除走删除端点显式清 DB）。
用法：python workbench_db_verify.py [--root ...] [--db ...] [--fix] [--no-backup]
"""
import argparse
import os
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dashboard"))

from contract import PARTITION_NAMES  # noqa: E402
from repo import SqliteRepo  # noqa: E402
from workbench_config import get_root  # noqa: E402

DEFAULT_ROOT = Path(get_root())
# P0-A（P0 最危险行）：备份目录参数化，默认 root.parent/workbench-backups
BACKUP_DIR = Path(
    os.environ.get("WORKBENCH_BACKUP_DIR", str(DEFAULT_ROOT.parent / "workbench-backups"))
)


def scan_files(root: Path) -> dict[tuple[str, str], tuple[float, str]]:
    """返回 {(partition, filename): (mtime, text)}。"""
    out = {}
    for partition in sorted(PARTITION_NAMES):
        d = root / partition
        if not d.is_dir():
            continue
        for p in d.glob("*.md"):
            try:
                out[(partition, p.name)] = (p.stat().st_mtime, p.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
    return out


def verify(root: Path, db: SqliteRepo, fix: bool) -> tuple[list[str], list[str], list[str], list[str], int]:
    files = scan_files(root)
    # 展平 DB 记录：{(partition, filename): row}
    dbmap = {(r["partition"], r["filename"]): r for r in db._all_tasks()}

    missing, orphan, mismatch, moved = [], [], [], []
    fixed = 0
    for key, (mtime, text) in files.items():
        row = dbmap.get(key)
        if row is None:
            if fix:
                p = root / key[0] / key[1]
                db.write_text(p, text)
                fixed += 1
            else:
                missing.append(f"{key[0]}/{key[1]}")
        elif abs(row["mtime"] - mtime) > 0.01 or row["content"] != text:
            if fix:
                db.write_text(root / key[0] / key[1], text)
                fixed += 1
            else:
                mismatch.append(f"{key[0]}/{key[1]}（DB mtime={row['mtime']:.1f} vs 文件 {mtime:.1f}）")
    for key in dbmap:
        if key not in files:
            # 移动收敛：同文件名出现在其他分区 → 视为被移动（归档闭环会改写内容：
            # status/completed_at/完成记录，实体身份按文件名；同内容优先，多候选歧义时保持孤儿）
            same_name = [k for k in files if k[1] == key[1]]
            identical = [k for k in same_name if files[k][1] == dbmap[key]["content"]]
            cands = identical or same_name
            if len(cands) == 1 and cands[0] != key:
                nk = cands[0]
                if fix:
                    src = root / key[0] / key[1]
                    dst = root / nk[0] / nk[1]
                    db.move(src, dst)          # DB 行迁移（含 moved 事件）
                    db.write_text(dst, files[nk][1])  # 刷新 status/mtime/content
                    fixed += 1
                else:
                    moved.append(f"{key[0]}/{key[1]} -> {nk[0]}/{nk[1]}")
                continue
            if fix:
                p = root / key[0] / key[1]
                if p.exists():
                    db.delete(p)
                    fixed += 1
                else:
                    # 真孤儿守卫：文件确实不存在，不动（永久删除走删除端点显式清 DB）
                    orphan.append(f"{key[0]}/{key[1]}")
            else:
                orphan.append(f"{key[0]}/{key[1]}")
    return missing, orphan, mismatch, moved, fixed


def main() -> int:
    ap = argparse.ArgumentParser(description="workbench 文件 vs DB 一致性校验")
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--db", default=None)
    ap.add_argument("--fix", action="store_true", help="把 DB 向文件收敛（默认只报告）")
    ap.add_argument("--no-backup", action="store_true", help="跳过 DB 备份")
    args = ap.parse_args()

    root = Path(args.root)
    db = SqliteRepo(args.db, root=root) if args.db else SqliteRepo(root=root)

    missing, orphan, mismatch, moved, fixed = verify(root, db, args.fix)
    problems = missing + orphan + mismatch + moved

    if args.fix and fixed:
        print(f"✅ 已收敛 {fixed} 处差异（DB 镜像同步完成）")

    # 备份 DB（默认开；Obsidian git 每日 02:00 提交）
    if not args.no_backup and db.db_path.exists():
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        dst = BACKUP_DIR / f"workbench.db.{date.today():%Y-%m-%d}"
        try:
            shutil.copy2(db.db_path, dst)
        except OSError as e:
            print(f"[workbench_db_verify] 备份失败：{e}")

    if not problems:
        # cron（非 TTY）场景无差异静默 → no_agent cron 不投递；手动跑显示 ✅
        if sys.stdout.isatty():
            print(f"✅ workbench 一致性 OK（文件 {len(scan_files(root))} 个 / DB {len(db._all_tasks())} 条），DB 已备份")
        return 0

    lines = [f"⚠️ workbench 一致性差异（{len(problems)} 处）", ""]
    if missing:
        lines.append(f"文件有 DB 无（{len(missing)}）：")
        lines += [f"  - {x}" for x in missing]
        lines.append("")
    if orphan:
        lines.append(f"DB 有文件无（{len(orphan)}）：")
        lines += [f"  - {x}" for x in orphan]
        lines.append("")
    if mismatch:
        lines.append(f"内容/mtime 不一致（{len(mismatch)}）：")
        lines += [f"  - {x}" for x in mismatch]
        lines.append("")
    if moved:
        lines.append(f"文件已移动（{len(moved)}）：DB 行待收敛——运行 --fix")
        lines += [f"  - {x}" for x in moved]
        lines.append("")

    # 追加工作台日志（随日报可见）
    try:
        log_dir = root / "日志"
        log_dir.mkdir(exist_ok=True)
        log = log_dir / f"{date.today():%Y-%m-%d}.md"
        text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else f"# 工作台日志 {date.today():%Y-%m-%d}\n"
        entry = f"\n## {datetime.now():%H:%M} ⚠️ 一致性校验\n\n- 发现 {len(problems)} 处差异（{'已收敛' if args.fix else '待处理'}）\n"
        for x in problems[:20]:
            entry += f"  - {x}\n"
        if len(problems) > 20:
            entry += f"  - …（共 {len(problems)} 处）\n"
        log.write_text(text + entry, encoding="utf-8")
    except OSError as e:
        print(f"[workbench_db_verify] 日志写入失败：{e}")

    print("\n".join(lines))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
