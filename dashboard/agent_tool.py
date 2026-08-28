"""Authorized Agent-tool bridge from a live Hermes turn to Workbench."""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

_SCHEMA = {
    "name": "workbench_capture",
    "description": (
        "Create or continue a Workbench task only when the user explicitly asks "
        "to save work. Conversation identity is supplied internally by Hermes."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["task", "continue"]},
            "content": {"type": "string"},
            "task_ref": {"type": "string"},
        },
        "required": ["action", "content"],
        "additionalProperties": False,
    },
}


_STATE_DB_PATH: str | None = None  # override for tests


def _resolve_state_db_message_id(session_id: str) -> str:
    """Resolve a namespaced opaque identity from Hermes state.db.

    Binds the NEWEST persisted user row of the current session (the row for
    the turn that is executing right now), not the oldest/first row.

    Lifecycle-order proof held by Hermes core (S1-007 review ground):
    1. The gateway passes the inbound user message to the agent run via
       ``persist_user_message`` (gateway/run.py apply path); the agent applies
       it at conversation-build time (run_agent._apply_persist_user_message_override)
       BEFORE the model/tool loop executes, so the current user row exists
       before any tool call.
    2. A same-session turn lease serializes turns on the conversation lineage
       root (hermes_state.acquire_session_turn_lease, held/refreshed/released
       around the whole turn in run_agent turn prologue/finalizer). A newer
       turn in the same session blocks/fails on the lease, so no competing
       newer user row can land while this turn's tools run.
    Real-store evidence: the S1-005 QQ turn's user row (id=339467) was
    persisted before the workbench_capture tool row (id=339471).
    Therefore ``newest user row in the session`` == ``current turn row``:
    deterministic on tool retry within the turn, unique per turn, scoped to
    the session, and safe across concurrent QQ/Weixin sessions (separate
    session_ids never share rows).

    Raises RuntimeError only when no user row exists (fail closed).
    """
    db_path = _STATE_DB_PATH or os.environ.get(
        "HERMES_HOME",
        str(Path.home() / "AppData" / "Local" / "hermes"),
    )
    state_db = Path(db_path) / "state.db"
    if not state_db.exists():
        raise RuntimeError("当前会话数据库不可访问")

    conn = sqlite3.connect(str(state_db))
    try:
        cursor = conn.execute(
            "SELECT id FROM messages WHERE session_id = ? AND role = 'user' ORDER BY id DESC LIMIT 1",
            (session_id,),
        )
        rows = cursor.fetchall()
        if len(rows) == 0:
            raise RuntimeError("当前会话未找到用户消息记录")
        return f"wb-msg:{session_id}:{rows[0][0]}"
    finally:
        conn.close()


def _command_from_args(args: dict) -> str:
    action = str(args.get("action") or "").strip().lower()
    content = str(args.get("content") or "").strip()
    task_ref = str(args.get("task_ref") or "").strip()
    if not content:
        raise ValueError("content required")
    if action == "task":
        return f"/wb 任务 {content}"
    if action == "continue":
        if not task_ref:
            raise ValueError("task_ref required for continue")
        return f"/wb 继续 {task_ref} {content}"
    raise ValueError("unsupported action")


async def handle_workbench_capture(args: dict, **kwargs) -> str:
    """Run one Workbench mutation with identity from the authorized turn."""
    from gateway.session_context import get_session_env

    message_id = get_session_env("HERMES_SESSION_MESSAGE_ID", "").strip()

    session_id = (kwargs.get("session_id") or "").strip()
    if not session_id:
        session_id = get_session_env("HERMES_SESSION_ID", "").strip()
    if not session_id:
        return "未执行：当前消息尚未建立可续接的 Hermes 原会话，请改用 /wb 命令。"

    platform = get_session_env("HERMES_SESSION_PLATFORM", "").strip()
    if platform not in {"qqbot", "qq", "weixin"}:
        return "未执行：当前消息平台不支持 Workbench 原会话绑定。"

    if not message_id:
        try:
            message_id = _resolve_state_db_message_id(session_id)
        except RuntimeError as exc:
            return f"未执行：{exc}，请改用 /wb 命令。"

    try:
        command_text = _command_from_args(args)
    except ValueError as exc:
        return f"未执行：{exc}。"

    from plugin_api import file_repo, qq_command

    result = await qq_command(
        {
            "text": command_text,
            "message_id": message_id,
            "platform": platform,
            "privacy_safe_log": True,
        }
    )
    task_id = str(result.get("task_id") or "").strip()
    if result.get("ok") and not task_id:
        action = str(args.get("action") or "").strip().lower()
        if action == "continue":
            candidate = str(args.get("task_ref") or "").strip().upper()
            if re.fullmatch(r"WB-[0-9A-F]{8}", candidate):
                task_id = candidate
        elif action == "task":
            from plugin_api import _normalized_message_source, _task_id_for_message

            normalized_platform = _normalized_message_source(platform)
            operation_id = f"qq-command:{normalized_platform}:{message_id}"
            task_id = _task_id_for_message(operation_id)
    if result.get("ok") and task_id:
        from conversation_index import ConversationIndex

        summary = str(result.get("summary") or "").strip()
        if not summary:
            summary = str(args.get("content") or "").strip()[:160]
        ConversationIndex(file_repo.db.db_path).upsert_authorized(
            platform=platform or "messaging",
            message_id=message_id,
            summary=summary,
            task_id=task_id,
            status="active",
            session_id=session_id,
        )
    return str(result.get("reply") or result.get("error") or "Workbench 命令未处理。")


def register_workbench_tool(ctx) -> None:
    ctx.register_tool(
        name="workbench_capture",
        toolset="skills",
        schema=_SCHEMA,
        handler=handle_workbench_capture,
        is_async=True,
        description=_SCHEMA["description"],
        emoji="🗂️",
        override=False,
    )
