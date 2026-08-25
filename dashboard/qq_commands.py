"""Pure QQ Workbench command parsing.

This module performs no authorization, I/O, or mutation.  Hermes must finish
sender authorization before a parsed command is passed to a Workbench action.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class QQCommand:
    name: str
    argument: str = ""
    extra: str = ""
    mutating: bool = False
    error: str = ""


_ALIASES = {
    "help": "help",
    "帮助": "help",
    "today": "today",
    "今日": "today",
    "status": "health",
    "health": "health",
    "状态": "health",
    "add": "add",
    "任务": "add",
    "review": "review",
    "待回看": "review",
    "verify": "verify",
    "待验证": "verify",
    "note": "note",
    "随想": "note",
    "show": "show",
    "查看": "show",
    "continue": "append",
    "append": "append",
    "继续": "append",
    "reopen": "reopen",
    "重开": "reopen",
    "done": "complete",
    "complete": "complete",
    "完成": "complete",
    "archive": "archive",
    "归档": "archive",
    "defer": "defer",
    "延期": "defer",
}

_ARG_LABELS = {
    "add": "任务命令需要任务内容",
    "complete": "完成命令需要任务标题",
    "archive": "归档命令需要任务标题",
    "defer": "延期命令需要任务标题和 YYYY-MM-DD 日期",
    "review": "待回看命令需要内容或链接",
    "verify": "待验证命令需要内容",
    "note": "随想命令需要内容",
    "show": "查看命令需要任务编号或标题",
    "append": "继续命令需要任务编号和补充内容",
    "reopen": "重开命令需要任务编号或标题",
}


def parse_qq_command(text: str) -> QQCommand | None:
    """Parse the explicit ``/wb`` or ``工作台`` command namespace."""
    raw = (text or "").strip()
    match = re.match(r"^(?:/wb|工作台)(?:\s+|$)(.*)$", raw, re.IGNORECASE)
    if not match:
        return None
    payload = match.group(1).strip()
    if not payload:
        return QQCommand("help")
    verb, _, remainder = payload.partition(" ")
    name = _ALIASES.get(verb.lower()) or _ALIASES.get(verb)
    if name is None:
        return QQCommand(
            "invalid",
            error="未知工作台命令；发送 /wb 帮助 查看可用命令",
        )
    if name in {"help", "today", "health"}:
        return QQCommand(name)
    remainder = remainder.strip()
    if not remainder:
        return QQCommand("invalid", error=_ARG_LABELS[name])
    if name == "defer":
        task, separator, due = remainder.rpartition(" ")
        if not separator or not task.strip() or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", due):
            return QQCommand("invalid", error=_ARG_LABELS[name])
        try:
            date.fromisoformat(due)
        except ValueError:
            return QQCommand("invalid", error=_ARG_LABELS[name])
        return QQCommand(name, task.strip(), due, True)
    if name == "append":
        task_ref, separator, note = remainder.partition(" ")
        if not separator or not task_ref.strip() or not note.strip():
            return QQCommand("invalid", error=_ARG_LABELS[name])
        return QQCommand(name, task_ref.strip(), note.strip(), True)
    if name == "show":
        return QQCommand(name, remainder, mutating=False)
    return QQCommand(name, remainder, mutating=True)
