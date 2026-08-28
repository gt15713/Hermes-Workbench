# -*- coding: utf-8 -*-
"""工作台日报：确定性模板输出 + P0-4（B5）数据采集模式（JSON 供 Agent cron prompt 消费）。

- --data：输出 {today, data_validated, factual_validation, processed, pending} JSON
- 无参数：保持确定性模板（no_agent 回退）
- --date YYYY-MM-DD：固定日期 dry-run / 历史回放（不冻结 TODAY 于 import）
"""

import argparse
import datetime as dt
import json
import os
import re
from pathlib import Path

# P0-A：env 注入优先；手动运行回落中立默认
ROOT = Path(os.environ.get("WORKBENCH_ROOT", str(Path.home() / "Workbench")))

# 分类标题模式（如 `任务（1 条）`）不是条目标题
_CATEGORY_HEADING = re.compile(r"^[^（）()]+\s*[（(]\s*\d+\s*条\s*[）)]$")
# 日期文件名模式（空壳回退产生的伪条目）
_DATE_TITLE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# 已知日期前缀（文件名搬运残留）：2026-08-23-xxx → xxx
_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}[-—\s]")
# B站/传输后缀残留：-哔哩哔哩-https-b23. / -哔哩哔哩-https://www.bilibili.com/video/xxx
_BILI_TRANSPORT_SUFFIX = re.compile(r"[-—]\s*(?:哔哩哔哩|bilibili)\s*[-—]\s*https?[:/.A-Za-z0-9_-]*\.?$", re.I)
# 裸 URL 标题：不发明页面标题，中性标记为链接
_URL_ONLY = re.compile(r"^https?://\S+$")


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


def normalize_title(title: str) -> str:
    """用户可见标题规范化（有测试的确定性规则，不截断任意中文）。

    优先级（CoderX S1-008 定义）：
    1. 已由调用方按「非 URL 别名 > 条目标题 > 任务 frontmatter title > 文件名清理」选择；
    2. 已知日期前缀（YYYY-MM-DD-…）剥离；
    3. B站传输后缀残留（-哔哩哔哩-https-b23. 等）剥离；
    4. 剥离后若为裸 URL → 不发明页面标题，中性前缀「链接：」。
    """
    title = _DATE_PREFIX.sub("", title.strip())
    title = _BILI_TRANSPORT_SUFFIX.sub("", title.strip())
    title = title.rstrip(" .，,")
    if _URL_ONLY.match(title):
        return f"链接：{title}"
    return title


def list_items(text: str) -> list[str]:
    """`-`/`*` 列表行中的真实条目标题（用户可见别名优先）。

    从 `- [[target|显示名]] — 标记完成` 提取**显示名**（| 后别名）；
    无别名时回退 target；普通 `- 文本` 行也计入。
    分类标题（如 `任务（1 条）`）由 headings() 提供，不属于本函数。
    返回前经 normalize_title()：剥离已知日期前缀/传输后缀；裸 URL 标记「链接：」。
    """
    items: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not (line.startswith("- ") or line.startswith("* ")):
            continue
        title = line[2:].strip()
        m = re.match(r"^\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", title)
        if m:
            # m.group(2)=别名（用户可见），m.group(1)=wiki target
            title = (m.group(2) or m.group(1)).strip()
        # 去掉「— 标记完成 / — 条目级，来自 …」等后缀
        title = re.sub(r"\s*—\s*.*$", "", title).strip()
        if title:
            items.append(normalize_title(title))
    return items


def _entry_titles(text: str) -> list[str]:
    """聚合文件内的真实条目标题（规范条目：## 标题 + 列表行，别名优先）。

    空壳日期文件（只有日期标题/frontmatter）→ []。
    分类标题（`任务（1 条）`）、日期标题、`原始消息`/`备注` 前缀不入条目。
    去重保序，保证同一文件内同一文本只计一次。
    """
    titles: list[str] = []
    for h in headings(text):
        h = h.strip()
        if h.startswith(("原始消息", "备注")):
            continue
        if _CATEGORY_HEADING.match(h) or _DATE_TITLE.match(h):
            continue
        titles.append(h)
    titles.extend(list_items(text))
    seen: set[str] = set()
    uniq: list[str] = []
    for t in titles:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


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
                completed.extend(list_items(text))

    # 本周新增 / 遗留 / 被阻塞：待回看 + 待验证 + 任务 —— 按真实条目计数（非文件数）
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
            status = fm.get("status", "")
            if dirname == "任务":
                # 任务卡 = 1 条（文件即任务），仅活动状态计数
                if status not in {"todo", "pending", "in_progress"}:
                    continue
                entry_count = 1
                item_remaining = bool(status not in {"done", "completed", "archived"})
                item_blocked = bool(_is_blocked(fm))
            else:
                # 聚合文件：条目 = 文件内真实条目数（## 标题 + 列表行）
                entries = _entry_titles(text)
                if not entries or status not in {"pending", "todo"}:
                    continue
                entry_count = len(entries)
                item_remaining = True
                item_blocked = False
            created = _created_date(path, fm)
            if created is None or not (monday <= created <= sunday):
                continue
            new_count += entry_count
            if item_remaining:
                remaining_count += entry_count
            if dirname == "任务" and item_blocked:
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


def collect(data_date: str | None = None) -> dict:
    """数据采集：日报的 Agent prompt 输入。

    data_date 可注入（YYYY-MM-DD）；缺失时用当前本地日期，
    不在 import 时冻结，避免午夜漂移。
    """
    today = dt.date.fromisoformat(data_date) if data_date else dt.date.today()
    today_s = today.isoformat()
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
                entries = _entry_titles(text)
                # 空壳 aggregate 文件（如 `待回看/2026-08-18.md` 只有标题）不算条目：
                # 不把日期文件名回退成伪待办。
                pending.extend({"label": label, "title": x, "due": "", "blocked": False} for x in entries)

    done = ROOT / "已处理" / f"{today_s}.md"
    if done.exists():
        text = read(done)
        # 已处理 = 分类标题下的链接/列表行（绝不把 `任务（1 条）` 分类标题当完成项）
        processed = list_items(text)

    # G9（2026-08-17 R6 补强）：注入 top N 限额（超期 top10 + 阻塞 top5 + 其他 20），超限截断防上下文超载
    overdue = [q for q in pending if q.get("due") and q["due"] < today_s][:10]
    blocked = [q for q in pending if q.get("blocked")][:5]
    seen_ids = {id(q) for q in overdue + blocked}
    others = [q for q in pending if id(q) not in seen_ids][:20]
    pending = overdue + blocked + others

    return {
        "today": today_s,
        "is_sunday": today.weekday() == 6,  # SUNDAY_REVIEW=on：周日日报变体（本周完成/遗留/模式/下周建议）
        "processed": processed,
        "pending": pending,
        # D2（P2-2）：周聚合（is_sunday=true 时 Agent 消费；结构稳定始终输出）
        "week": collect_week(today),
    }


def validate_report_data(d: dict) -> dict:
    """P0-4（B5）+ D2（P2-2）：输出契约 schema 校验 + 事实校验。

    Returns {"schema_ok": bool, "facts_ok": bool, "issues": [str]}.
    """
    week = d.get("week")
    schema_ok = (
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
    issues: list[str] = []
    for item in d.get("pending", []):
        if not isinstance(item, dict):
            issues.append("pending 项不是对象")
            continue
        title = str(item.get("title") or "")
        if _DATE_TITLE.match(title):
            issues.append(f"pending 含日期文件名伪条目: {title}")
        if _CATEGORY_HEADING.match(title):
            issues.append(f"pending 含分类标题伪条目: {title}")
    for title in d.get("processed", []):
        if _CATEGORY_HEADING.match(str(title)):
            issues.append(f"processed 含分类标题伪条目: {title}")
    if isinstance(week, dict):
        for title in week.get("completed", []):
            if _CATEGORY_HEADING.match(str(title)):
                issues.append(f"week.completed 含分类标题伪条目: {title}")
    return {"schema_ok": schema_ok, "facts_ok": not issues, "issues": issues}


def main() -> int:
    ap = argparse.ArgumentParser(description="工作台日报（确定性模板 / P0-4 数据采集）")
    ap.add_argument(
        "--data",
        action="store_true",
        help="P0-4（B5）数据采集模式：输出 JSON 供 Agent cron prompt 消费（判断型生成），不输出模板",
    )
    ap.add_argument(
        "--date",
        help="固定日期 YYYY-MM-DD（dry-run / 历史回放；不冻结 TODAY 于 import）",
    )
    args = ap.parse_args()

    data = collect(args.date)
    today_s = str(data["today"])
    validation = validate_report_data(data)
    if args.data:
        if not validation["schema_ok"] or not validation["facts_ok"]:
            return 1
        data["data_validated"] = validation["schema_ok"] and validation["facts_ok"]
        data["factual_validation"] = {
            "ok": validation["facts_ok"],
            "issues": validation["issues"],
        }
        print(json.dumps(data, ensure_ascii=False))
        return 0

    processed = data["processed"]
    pending = data["pending"]
    lines = [f"📋 今日处理日报（{today_s}）", ""]
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
