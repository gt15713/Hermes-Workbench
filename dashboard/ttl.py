# -*- coding: utf-8 -*-
"""回收站 TTL（A3）：扫描 回收站/ 超期文件 → 物理删除 + task_events 埋点。

R4 阶段 4 已拍板「还原 + 30 天 TTL 双出口」——本模块补上 TTL 出口：
- 判定：frontmatter `trashed_at: YYYY-MM-DD` < today - ttl_days
  （缺失 trashed_at 的文件不动——保守，避免误删无时间戳的旧文件）
- 动作：物理删除（Path.unlink）+ task_events 写 kind=trash_ttl
- 默认 TTL 30 天，环境变量 WORKBENCH_TTL_DAYS 可覆盖
"""

from __future__ import annotations

import datetime as dt
import os
import re
import sqlite3
from pathlib import Path

from workbench_config import get_db_path, get_root, get_ttl  # noqa: E402

ROOT = Path(get_root())
# P0-B：DB 路径参数化（env 覆盖，默认插件目录）
DB_PATH = Path(get_db_path())
DEFAULT_TTL_DAYS = 30
# Phase 0-6 [PENDING TTL_MODE]：默认 archive（归档保留）；delete 维持物理删除。env WORKBENCH_TTL_MODE 覆盖。
def get_ttl_mode() -> str:
    m = (os.environ.get("WORKBENCH_TTL_MODE") or "").strip().lower()
    if not m:
        m = get_ttl().get("mode", "archive")
    return m if m in ("archive", "delete") else "archive"


def trashed_at_from(text: str) -> str:
    """frontmatter trashed_at → 'YYYY-MM-DD'；缺失/非法 → ''。"""
    m = re.search(r"^trashed_at:\s*(\d{4}-\d{2}-\d{2})", text, re.M)
    return m.group(1) if m else ""


def scan_trash_overdue(
    ttl_days: int = DEFAULT_TTL_DAYS, root: Path | None = None
) -> list[tuple[str, str, int]]:
    """返回 [(文件名, trashed_at, 超期天数)]，按超期天数倒序。

    trashed_at 缺失/非法 → 跳过（保守）。今天为基准，trashed_at <= cutoff 即超期。
    """
    root = root or ROOT
    trash_dir = root / "回收站"
    if not trash_dir.is_dir():
        return []
    cutoff = dt.date.today() - dt.timedelta(days=ttl_days)
    overdue: list[tuple[str, str, int]] = []
    for p in sorted(trash_dir.glob("*.md")):
        text = p.read_text(encoding="utf-8", errors="replace")
        ta = trashed_at_from(text)
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", ta):
            continue
        ta_date = dt.date.fromisoformat(ta)
        if ta_date > cutoff:
            continue
        overdue.append((p.name, ta, (dt.date.today() - ta_date).days))
    return sorted(overdue, key=lambda x: x[2], reverse=True)


def delete_overdue(
    overdue: list[tuple[str, str, int]], root: Path | None = None
) -> list[str]:
    """物理删除超期文件（TTL_MODE=delete），返回实际删除的文件名列表（OSError 跳过不中断）。"""
    root = root or ROOT
    trash_dir = root / "回收站"
    deleted: list[str] = []
    for filename, _, _ in overdue:
        try:
            (trash_dir / filename).unlink()
            deleted.append(filename)
        except OSError:
            continue
    return deleted


def archive_overdue(
    overdue: list[tuple[str, str, int]], root: Path | None = None
) -> list[str]:
    """TTL_MODE=archive：把超期文件从 回收站/ 移入 已处理/ 并标记 status: deleted。

    - 保留实体与 trashed_at（不物理删除）；已处理/ 同名冲突 → 文件名加 '-2'/'−3' 后缀
    - frontmatter：status 行替换为 deleted；缺失则插入；追加一行 TTL 归档说明
    - 返回实际归档的目标文件名列表（OSError 跳过不中断）
    """
    root = root or ROOT
    trash_dir = root / "回收站"
    done_dir = root / "已处理"
    done_dir.mkdir(exist_ok=True)
    archived: list[str] = []
    for filename, trashed_at, days in overdue:
        src = trash_dir / filename
        if not src.is_file():
            continue
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
            if re.search(r"^status:\s*\S+\s*$", text, re.M):
                text = re.sub(r"^status:\s*\S+\s*$", "status: deleted", text, count=1, flags=re.M)
            elif re.search(r"(^|\n)---[ \t]*\r?\n", text):
                text = re.sub(r"(^|\n)---[ \t]*\r?\n", r"\1---\nstatus: deleted\n", text, count=1)
            if not re.search(r"^archived_at:", text, re.M):
                text = text.rstrip() + f"\n\n> TTL 归档保留（原 trashed_at: {trashed_at}，超期 {days} 天）\n"
            dst = done_dir / filename
            n = 2
            while dst.exists():
                dst = done_dir / f"{Path(filename).stem}-{n}.md"
                n += 1
            tmp = dst.with_suffix(".tmp")
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, dst)
            src.unlink()
            archived.append(dst.name)
        except OSError:
            continue
    return archived


def record_events(
    overdue: list[tuple[str, str, int]],
    db_path: Path | None = None,
    payload_mode: str = "delete",
) -> None:
    """写 task_events 埋点（kind=trash_ttl，partition=回收站）。失败不中断处理。"""
    try:
        conn = sqlite3.connect(str(db_path or DB_PATH), timeout=10.0)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS task_events ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "partition TEXT, filename TEXT, kind TEXT, payload TEXT, created_at TEXT)"
        )
        now = dt.datetime.now().isoformat(timespec="seconds")
        for filename, trashed_at, days in overdue:
            conn.execute(
                "INSERT INTO task_events (partition, filename, kind, payload, created_at)"
                " VALUES (?, ?, 'trash_ttl', ?, ?)",
                (
                    "回收站",
                    filename,
                    f"超期 {days} 天自动处理（trashed_at={trashed_at}，mode={payload_mode}）",
                    now,
                ),
            )
        conn.commit()
    except Exception:  # noqa: BLE001
        pass
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
