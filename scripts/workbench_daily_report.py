# -*- coding: utf-8 -*-
"""工作台日报：确定性模板输出 + P0-4（B5）数据采集模式（JSON 供 Agent cron prompt 消费）。

- --data：输出 {today, is_sunday（SUNDAY_REVIEW=on 已拍板）, processed, pending} JSON
- 无参数：保持确定性模板（no_agent 回退）
"""

import argparse
import datetime as dt
import json
import os
import re
from pathlib import Path

# P0-A：env 注入优先；手动运行回落中立默认
ROOT = Path(os.environ.get("WORKBENCH_ROOT", str(Path.home() / "Workbench")))
TODAY = dt.date.today().isoformat()


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


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


def headings(text: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"^## (.+)$", text, re.M)]


# ---------- D2（P2-2）周聚合 ----------


def _monday(today: dt.date) -> dt.date:
    """ISO 周一起点。"""
    return today - dt.timedelta(days=today.weekday())


def _created_date(path: Path, fm: dict) -> dt.date | None:
    """条目创建日期：created frontmatter（YYYY-MM-DD），缺失用文件 mtime。"""
    created = fm.get("created")
    if created and re.match(r"^\d{4}-\d{2}-\d{2}$", created):
        try:
            return dt.date.fromisoformat(created)
        except ValueError:
            return None
    try:
        return dt.datetime.fromtimestamp(path.stat().st_mtime).date()
    except OSError:
        return None


def _is_blocked(fm: dict) -> bool:
    """tags 含 #阻塞/#blocked（与 nudge scan_blocked 同口径）。"""
    raw = str(fm.get("tags") or "")
    raw = raw.strip().lstrip("[").rstrip("]")
    tags = [t.strip() for t in raw.split(",") if t.strip()]
    return "#阻塞" in tags or "#blocked" in tags


def collect_week(today: dt.date | None = None) -> dict:
    """D2（P2-2）周聚合：本周完成 / 新增 / 遗留 / 下周到期 / 被阻塞。周起点=ISO 周一。"""
    today = today or dt.date.today()
    monday = _monday(today)
    sunday = monday + dt.timedelta(days=6)
    if today > sunday:  # 防御：跨周异常兜底
        sunday = today

    # 本周完成：已处理/ 周一~周日 7 个文件 headings
    completed: list[str] = []
    done_dir = ROOT / "已处理"
    if done_dir.is_dir():
        for i in range((sunday - monday).days + 1):
            day = monday + dt.timedelta(days=i)
            f = done_dir / f"{day.isoformat()}.md"
            if f.exists():
                text = read(f)
                completed.extend(
                    x for x in headings(text) if not x.startswith(("原始消息", "备注"))
                )

    # 本周新增 / 遗留 / 被阻塞：待回看 + 待验证 + 任务
    new_count = 0
    remaining_count = 0
    blocked_count = 0
    for dirname in ("待回看", "待验证", "任务"):
        folder = ROOT / dirname
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.md")):
            text = read(path)
            fm = frontmatter(text)
            created = _created_date(path, fm)
            if created is not None and monday <= created <= sunday:
                new_count += 1
                status = fm.get("status", "")
                if status not in {"done", "completed", "archived"}:
                    remaining_count += 1
            if dirname == "任务" and _is_blocked(fm):
                blocked_count += 1

    # 下周到期：任务区 status 未完成 + due ∈ (today, today+7]
    due_next_week = 0
    task_dir = ROOT / "任务"
    if task_dir.is_dir():
        for path in sorted(task_dir.glob("*.md")):
            fm = frontmatter(read(path))
            if fm.get("status") not in {"todo", "pending", "in_progress"}:
                continue
            due = fm.get("due", "")
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", due):
                continue
            due_date = dt.date.fromisoformat(due)
            if today < due_date <= today + dt.timedelta(days=7):
                due_next_week += 1

    return {
        "monday": monday.isoformat(),
        "completed_count": len(completed),
        "completed": completed,
        "new_count": new_count,
        "remaining_count": remaining_count,
        "due_next_week": due_next_week,
        "blocked_count": blocked_count,
    }


def collect() -> dict:
    """数据采集：日报的 Agent prompt 输入。"""
    processed: list[str] = []
    pending: list[dict] = []
    for dirname, label in (("待回看", "待回看"), ("待验证", "待验证"), ("任务", "待办")):
        folder = ROOT / dirname
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.md")):
            text = read(path)
            fm = frontmatter(text)
            status = fm.get("status", "")
            if dirname == "任务":
                if status not in {"todo", "pending", "in_progress"}:
                    continue
                titles = [re.sub(r"^# +", "", x).strip() for x in text.splitlines() if x.startswith("# ")]
                title = titles[0] if titles else path.stem
                due = fm.get("due", "")
                fm_tags = fm.get("tags", "")
                is_blk = "#阻塞" in fm_tags or "#blocked" in fm_tags
                pending.append({"label": label, "title": title, "due": due, "blocked": is_blk})
            else:
                if status not in {"pending", "todo"}:
                    continue
                entries = [x for x in headings(text) if not x.startswith(("原始消息", "备注"))]
                pending.extend({"label": label, "title": x, "due": "", "blocked": False} for x in (entries or [path.stem]))

    done = ROOT / "已处理" / f"{TODAY}.md"
    if done.exists():
        text = read(done)
        processed = [x for x in headings(text) if not x.startswith(("原始消息", "备注"))]

    # G9（2026-08-17 R6 补强）：注入 top N 限额（超期 top10 + 阻塞 top5 + 其他 20），超限截断防上下文超载
    overdue = [q for q in pending if q.get("due") and q["due"] < TODAY][:10]
    blocked = [q for q in pending if q.get("blocked")][:5]
    seen_ids = {id(q) for q in overdue + blocked}
    others = [q for q in pending if id(q) not in seen_ids][:20]
    pending = overdue + blocked + others

    return {
        "today": TODAY,
        "is_sunday": dt.date.today().weekday() == 6,  # SUNDAY_REVIEW=on：周日日报变体（本周完成/遗留/模式/下周建议）
        "processed": processed,
        "pending": pending,
        # D2（P2-2）：周聚合（is_sunday=true 时 Agent 消费；结构稳定始终输出）
        "week": collect_week(),
    }


def validate_report_data(d: dict) -> bool:
    """P0-4（B5）+ D2（P2-2）：输出契约 schema 校验（PRD §4.5）。week 为 D2 扩展字段（旧字段保留）。"""
    week = d.get("week")
    return (
        isinstance(d, dict)
        and isinstance(d.get("today"), str)
        and isinstance(d.get("is_sunday"), bool)
        and isinstance(d.get("processed"), list)
        and isinstance(d.get("pending"), list)
        and isinstance(week, dict)
        and isinstance(week.get("monday"), str)
        and isinstance(week.get("completed_count"), int)
        and isinstance(week.get("completed"), list)
        and isinstance(week.get("new_count"), int)
        and isinstance(week.get("remaining_count"), int)
        and isinstance(week.get("due_next_week"), int)
        and isinstance(week.get("blocked_count"), int)
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="工作台日报（确定性模板 / P0-4 数据采集）")
    ap.add_argument(
        "--data",
        action="store_true",
        help="P0-4（B5）数据采集模式：输出 JSON 供 Agent cron prompt 消费（判断型生成），不输出模板",
    )
    args = ap.parse_args()

    data = collect()
    if args.data:
        if not validate_report_data(data):
            return 1
        print(json.dumps(data, ensure_ascii=False))
        return 0

    processed = data["processed"]
    pending = data["pending"]
    lines = [f"📋 今日处理日报（{TODAY}）", ""]
    lines.append(f"✅ 已处理（{len(processed)} 条）")
    for i, title in enumerate(processed, 1):
        lines.append(f"  {i}. {title}")
    lines.append("")
    lines.append(f"📌 待处理（{len(pending)} 条）")
    for item in pending:
        suffix = f"（截止 {item['due']}）" if item["due"] else ""
        lines.append(f"  【{item['label']}】{item['title']}{suffix}")
    if not processed and not pending:
        lines.append("今天没有收录和待办事项。")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
