# -*- coding: utf-8 -*-
"""工作台 auto-nudge（Task 5.2 批次 4）：扫描 任务/ 区超期任务 → QQ 推送 + task_events 埋点。

- 判定：status: todo 且 due: YYYY-MM-DD < 今天（未动 = 状态仍 todo）
- cron 模式：no_agent=True（stdout 即推送内容；无超期 → 空 stdout → 静默不打扰）
- 用法：
    python workbench_auto_nudge.py              # 正常：写埋点 + 输出推送文本
    python workbench_auto_nudge.py --dry-run    # 试跑：只输出不写 DB
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sqlite3
import sys
from pathlib import Path

# P0-A：env 注入优先（scheduler 统一注入 root/db/ttl）；手动运行回落中立默认
ROOT = Path(os.environ.get("WORKBENCH_ROOT", str(Path.home() / "Workbench")))
DB_PATH = Path(
    os.environ.get("WORKBENCH_DB", str(Path.home() / ".workbench" / "workbench.db"))
)
TODAY = dt.date.today()


def frontmatter(text: str) -> dict[str, str]:
    m = re.search(r"(^|\n)---[ \t]*\r?\n(.*?)\r?\n---", text, re.S)
    if not m:
        return {}
    result = {}
    for line in m.group(2).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip()
    return result


def first_h1(text: str) -> str:
    m = re.search(r"^# (.+)$", text, re.M)
    return m.group(1).strip() if m else ""


def scan_overdue() -> list[tuple[str, str, str, int]]:
    """返回 [(文件名, 标题, due, 超期天数)]，按超期天数倒序。"""
    overdue = []
    task_dir = ROOT / "任务"
    if not task_dir.is_dir():
        return overdue
    for path in sorted(task_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        fm = frontmatter(text)
        if fm.get("status") != "todo":
            continue
        due = fm.get("due", "")
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", due):
            continue
        due_date = dt.date.fromisoformat(due)
        if due_date >= TODAY:
            continue
        title = fm.get("title") or first_h1(text) or path.stem
        overdue.append((path.name, title, due, (TODAY - due_date).days))
    return sorted(overdue, key=lambda x: x[3], reverse=True)


def record_events(overdue: list[tuple[str, str, str, int]]) -> None:
    """写 task_events 埋点（kind=nudge，partition=任务）。失败不中断推送。"""
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=10.0)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS task_events ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "partition TEXT, filename TEXT, kind TEXT, payload TEXT, created_at TEXT)"
        )
        now = dt.datetime.now().isoformat(timespec="seconds")
        for filename, title, due, days in overdue:
            conn.execute(
                "INSERT INTO task_events (partition, filename, kind, payload, created_at) "
                "VALUES (?, ?, 'nudge', ?, ?)",
                ("任务", filename, f"超期提醒：{title}（due {due}，超期 {days} 天）", now),
            )
        conn.commit()
        conn.close()
    except Exception as e:  # noqa: BLE001 埋点失败不能阻断推送
        sys.stderr.write(f"event record failed: {e}\n")


def _parse_tags(fm: dict) -> list[str]:
    raw = str(fm.get("tags") or "")
    raw = raw.strip().lstrip("[").rstrip("]")
    return [t.strip() for t in raw.split(",") if t.strip()]


def scan_blocked() -> list[tuple[str, str]]:
    """任务区 status=todo 且 tags 含 #阻塞 → [(文件名, 标题)]。"""
    blocked = []
    task_dir = ROOT / "任务"
    if not task_dir.is_dir():
        return blocked
    for path in sorted(task_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        fm = frontmatter(text)
        if fm.get("status") != "todo":
            continue
        if "#阻塞" not in _parse_tags(fm) and "#blocked" not in _parse_tags(fm):
            continue
        blocked.append((path.name, fm.get("title") or first_h1(text) or path.stem))
    return blocked


def scan_today_due() -> list[tuple[str, str, str]]:
    """任务区 status=todo 且 due == 今天 → [(文件名, 标题, due)]。"""
    today_due = []
    task_dir = ROOT / "任务"
    if not task_dir.is_dir():
        return today_due
    for path in sorted(task_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        fm = frontmatter(text)
        if fm.get("status") != "todo":
            continue
        due = fm.get("due", "")
        if due == TODAY.isoformat():
            today_due.append((path.name, fm.get("title") or first_h1(text) or path.stem, due))
    return today_due


def validate_nudge_data(d: dict) -> bool:
    """P0-4（B5）+ D1（P2-1）：输出契约 schema 校验（PRD §4.5）。stale/duplicate 为 D1 扩展字段（旧字段保留）。"""
    return (
        isinstance(d, dict)
        and isinstance(d.get("date"), str)
        and isinstance(d.get("overdue"), list)
        and isinstance(d.get("blocked"), list)
        and isinstance(d.get("today_due"), list)
        and isinstance(d.get("stale"), list)
        and isinstance(d.get("duplicate"), list)
    )


# ---------- D1（P2-1）Task Intelligence ----------

STALE_DAYS = 7  # 陈旧阈值：最近更新 > 7 天（严格大于；正好 7 天不算）


def _updated_days(path: Path, fm: dict, today: dt.date) -> int | None:
    """最近更新距今天数：优先 updated_at frontmatter（YYYY-MM-DD），缺失用文件 mtime。"""
    updated = fm.get("updated_at") or fm.get("updated")
    if updated and re.match(r"^\d{4}-\d{2}-\d{2}$", updated):
        try:
            return (today - dt.date.fromisoformat(updated)).days
        except ValueError:
            return None
    try:
        mtime = dt.datetime.fromtimestamp(path.stat().st_mtime).date()
        return (today - mtime).days
    except OSError:
        return None


def scan_stale() -> list[dict]:
    """任务区 status∈{todo,in_progress} 且最近更新 > STALE_DAYS 天 → [{file,title,days}]，按天数倒序。"""
    stale = []
    task_dir = ROOT / "任务"
    if not task_dir.is_dir():
        return stale
    for path in sorted(task_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        fm = frontmatter(text)
        if fm.get("status") not in {"todo", "in_progress"}:
            continue
        days = _updated_days(path, fm, TODAY)
        if days is None or days <= STALE_DAYS:
            continue
        title = fm.get("title") or first_h1(text) or path.stem
        stale.append({"file": path.name, "title": title, "days": days})
    return sorted(stale, key=lambda x: x["days"], reverse=True)


def _normalize(title: str) -> str:
    """标题归一化：小写、去空白、去 markdown 符号、去标记性前缀（保守——仅「待办」这类纯标记词）。"""
    t = re.sub(r"\s+", "", title.lower())
    t = re.sub(r"^[#\-*>（(【\s]+", "", t)
    if t.startswith("待办") and len(t) > 2:
        t = t[2:]
    return t


def _edit_distance(a: str, b: str) -> int:
    """朴素编辑距离（归一化后短标题足够）。"""
    if a == b:
        return 0
    if not a or not b:
        return max(len(a), len(b))
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def scan_duplicates(max_groups: int = 3) -> list[dict]:
    """任务区 status∈{todo,in_progress} 标题相似度检测（保守阈值：编辑距离 ≤2 或归一化包含）。
    输出 ≤max_groups 组 [{a:{file,title}, b:{file,title}}]；已配对条目不再参与后续组。"""
    task_dir = ROOT / "任务"
    if not task_dir.is_dir():
        return []
    items = []
    for path in sorted(task_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        fm = frontmatter(text)
        if fm.get("status") not in {"todo", "in_progress"}:
            continue
        title = fm.get("title") or first_h1(text) or path.stem
        items.append({"file": path.name, "title": title, "norm": _normalize(title)})

    groups = []
    used = set()
    for i in range(len(items)):
        if items[i]["file"] in used:
            continue
        for j in range(i + 1, len(items)):
            if items[j]["file"] in used:
                continue
            a, b = items[i]["norm"], items[j]["norm"]
            if not a or not b:
                continue
            similar = _edit_distance(a, b) <= 2
            # 包含关系：一方含另一方（短 ≥3 字符才判，防空泛词误报）
            contained = (min(len(a), len(b)) >= 3) and (a in b or b in a)
            if similar or contained:
                groups.append(
                    {
                        "a": {"file": items[i]["file"], "title": items[i]["title"]},
                        "b": {"file": items[j]["file"], "title": items[j]["title"]},
                    }
                )
                used.add(items[i]["file"])
                used.add(items[j]["file"])
                break
        if len(groups) >= max_groups:
            break
    return groups


def main() -> int:
    parser = argparse.ArgumentParser(description="工作台 auto-nudge 超期任务提醒")
    parser.add_argument("--dry-run", action="store_true", help="试跑：只输出不写 DB")
    parser.add_argument(
        "--data",
        action="store_true",
        help="P0-4（B5）数据采集模式：输出 JSON（overdue/blocked/today_due）供 Agent cron prompt 消费，不推送",
    )
    args = parser.parse_args()

    if args.data:
        data = {
            "date": TODAY.isoformat(),
            "overdue": [
                {"file": f, "title": t, "due": d, "days": n}
                for f, t, d, n in scan_overdue()
            ],
            "blocked": [{"file": f, "title": t} for f, t in scan_blocked()],
            "today_due": [{"file": f, "title": t, "due": d} for f, t, d in scan_today_due()],
            # D1（P2-1）：Task Intelligence——陈旧/重复检测（nudge 内嵌文字段；无新推送）
            "stale": scan_stale(),
            "duplicate": scan_duplicates(),
        }
        if not validate_nudge_data(data):
            sys.stderr.write("schema invalid\n")
            return 1
        import json
        print(json.dumps(data, ensure_ascii=False))
        return 0

    overdue = scan_overdue()
    if not overdue:
        # 空 stdout → cron no_agent 静默（不打扰）
        return 0

    lines = [f"⏰ 工作台超期任务提醒（{len(overdue)} 项，截至 {TODAY.isoformat()}）", ""]
    for filename, title, due, days in overdue:
        lines.append(f"- {title}（due {due}，超期 {days} 天）")
    blocked = scan_blocked()
    if blocked:
        lines.append("")
        lines.append("🚧 被阻塞任务（#阻塞）：")
        for filename, title in blocked:
            lines.append(f"- {title}")
    output = "\n".join(lines)

    if not args.dry_run:
        record_events(overdue)

    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
