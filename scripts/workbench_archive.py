#!/usr/bin/env python3
"""
workbench_archive.py — 工作台自动归档巡检（v2 4.1 契约）

扫描 工作台/任务/ 目录，任何 frontmatter status: completed 但仍在任务区的文件
→ 自动归档三步闭环：移入 已处理/（保留实体）+ 追加当日索引（指针+摘要）+ 写工作台日志。

4.1 契约要求：产出物 = 「实体 + 索引」双记录，缺一不可。
- 实体文件：从 任务/ 移入 已处理/，保留完整内容和 frontmatter
- 索引日志：在 已处理/YYYY-MM-DD.md 追加一行指针 + 摘要，不复制正文

回收站 TTL 不属于本脚本职责；统一由 `workbench_trash_ttl.py` 处理，默认归档保留实体。

触发：no_agent cron 每小时（毫秒级，零 token）。
"""
import os
import re
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dashboard"))
from workbench_config import get_root  # noqa: E402

WORKBENCH = Path(get_root())
TASK_DIR = WORKBENCH / "任务"
DONE_DIR = WORKBENCH / "已处理"
LOG_DIR = WORKBENCH / "日志"

# 阶段 1.5：接入插件 DualRepo 双写（DB 镜像）。import 失败 → 降级纯文件（原行为）。
_dual = None
try:
    from conversation_sync import sync_by_task_text  # noqa: E402
    from repo import DualRepo, FileRepo, SqliteRepo  # noqa: E402

    _dual = DualRepo(
        FileRepo(root=WORKBENCH),
        SqliteRepo(root=WORKBENCH),
    )
except Exception as _e:  # noqa: BLE001
    print(f"[workbench_archive] dual-repo 不可用，降级纯文件：{_e}")

_STATUS_RE = re.compile(r"^status:\s*(.+?)\s*$", re.M)

# 写操作全局锁（脚本单进程，文件级原子写兜底）
import threading

_WRITE_LOCK = threading.Lock()


def _atomic_write(path: Path, text: str) -> None:
    """原子写：临时文件 + os.replace（Windows 同卷原子）。接入双写时同步 DB 镜像。"""
    if _dual is not None:
        _dual.write_text(path, text)
        return
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _append_done_log(task_stem: str, task_title: str) -> None:
    """追加已处理索引日志（4.1 契约：一行指针 + 摘要，不复制正文）。

    格式：- [[<实体文件名>|<任务标题>]] — <一句话摘要>
    去重：同一实体只记一次。
    """
    today = date.today()
    with _WRITE_LOCK:
        log = DONE_DIR / f"{today.isoformat()}.md"
        entry = f"[[{task_stem}|{task_title}]] — 标记完成（巡检归档）"
        if _dual is not None:
            _dual.append_done_log(log, "任务（1 条）", entry)
            return
        text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else f"# 已处理 {today.isoformat()}\n"
        if f"[[{task_stem}|" not in text:
            text += f"\n## 任务（1 条）\n\n- {entry}\n"
            _atomic_write(log, text)


def _log_action(action: str, detail: str) -> None:
    """追加工作台日志到 日志/YYYY-MM-DD.md（原子写 + 加锁）。"""
    with _WRITE_LOCK:
        try:
            if _dual is not None:
                _dual.append_action_log(action, detail)
                return
            LOG_DIR.mkdir(exist_ok=True)
            log = LOG_DIR / f"{date.today().isoformat()}.md"
            line = f"\n## {datetime.now():%H:%M} {action}\n\n- {detail}\n"
            text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else f"# 工作台日志 {date.today().isoformat()}\n"
            _atomic_write(log, text + line)
        except OSError as e:
            print(f"[workbench_archive] log action failed: {e}")


def main() -> int:
    archived = []
    errors = []

    if not TASK_DIR.is_dir():
        print("任务目录不存在，跳过")
        return 0

    for f in sorted(TASK_DIR.glob("*.md")):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            errors.append(f"{f.name}: 读取失败 {e}")
            continue

        m = _STATUS_RE.search(text)
        status = m.group(1).strip() if m else ""
        if status != "completed":
            continue

        # 获取任务标题（# 标题行）
        title_m = re.search(r"^# (.+)$", text, re.M)
        task_title = title_m.group(1).strip() if title_m else f.stem

        # 三步闭环：移入已处理（保留实体）+ 写索引 + 写工作台日志
        dest = DONE_DIR / f.name
        if dest.exists():
            errors.append(f"{f.name}: 已处理/ 下已存在同名文件，跳过")
            continue

        DONE_DIR.mkdir(exist_ok=True)
        if _dual is not None:
            _dual.move(f, dest)
            sync_by_task_text(_dual.db.db_path, text, status="completed")
        else:
            shutil.move(str(f), str(dest))
        _append_done_log(dest.stem, task_title)
        archived.append(f.name)

    if archived:
        _log_action(
            "自动归档巡检",
            f"归档 {len(archived)} 个已完成任务：{'、'.join(archived)}（status: completed 但滞留任务区）",
        )

    print(f"巡检完成：归档 {len(archived)} 个，错误 {len(errors)} 个")
    for name in archived:
        print(f"  ✅ {name} → 已处理/")
    for e in errors:
        print(f"  ⚠️ {e}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
