"""Authorized Hermes slash-command bridge for Workbench messaging capture."""

from __future__ import annotations

import uuid
from collections import OrderedDict, deque
from threading import Lock
from time import monotonic

_PENDING_IDS: OrderedDict[str, deque[tuple[str, str, float]]] = OrderedDict()
_PENDING_LOCK = Lock()
_PENDING_TTL_SECONDS = 120.0
_PENDING_MAX_KEYS = 256


def _invocation_id() -> str:
    """Use a fresh ID because Hermes slash handlers expose no message/chat ID."""
    return f"plugin-command:{uuid.uuid4().hex}"


def remember_inbound_command(text: str, message_id: str, platform: str) -> None:
    """Bridge official pre-dispatch identity to the authorized slash handler."""
    normalized = str(text or "").strip()
    if not normalized.lower().startswith("/wb") or not str(message_id or "").strip():
        return
    args = normalized[3:].strip()
    with _PENDING_LOCK:
        _prune_pending_locked()
        queue = _PENDING_IDS.setdefault(args, deque())
        queue.append((str(platform or "messaging"), str(message_id).strip(), monotonic()))
        _PENDING_IDS.move_to_end(args)
        while len(queue) > 32:
            queue.popleft()
        while len(_PENDING_IDS) > _PENDING_MAX_KEYS:
            _PENDING_IDS.popitem(last=False)


def _prune_pending_locked() -> None:
    cutoff = monotonic() - _PENDING_TTL_SECONDS
    for key in list(_PENDING_IDS):
        queue = _PENDING_IDS[key]
        while queue and queue[0][2] < cutoff:
            queue.popleft()
        if not queue:
            _PENDING_IDS.pop(key, None)


def _consume_inbound_identity(args: str) -> tuple[str, str]:
    with _PENDING_LOCK:
        _prune_pending_locked()
        queue = _PENDING_IDS.get(args)
        if queue:
            # Latest wins so a stale pre-auth event from a rejected sender
            # cannot shadow a later authorized invocation with identical text.
            platform, message_id, _created_at = queue.pop()
            if not queue:
                _PENDING_IDS.pop(args, None)
            return platform, message_id
    return "messaging", _invocation_id()


async def _handle_workbench_command(raw_args: str) -> str:
    from plugin_api import qq_command

    args = str(raw_args or "").strip()
    platform, message_id = _consume_inbound_identity(args)
    result = await qq_command(
        {
            "text": f"/wb {args}".rstrip(),
            "message_id": message_id,
            "platform": platform,
        }
    )
    if result.get("ok") and result.get("task_id"):
        from conversation_index import ConversationIndex
        from plugin_api import file_repo

        summary = str(result.get("summary") or "").strip()
        if not summary:
            summary = args.split(maxsplit=1)[1] if len(args.split(maxsplit=1)) == 2 else args
        ConversationIndex(file_repo.db.db_path).upsert_authorized(
            platform=platform,
            message_id=message_id,
            summary=summary,
            task_id=str(result["task_id"]),
            status="active",
        )
    return str(result.get("reply") or result.get("error") or "Workbench 命令未处理。")


def register_workbench_command(ctx) -> None:
    """Register the post-authorization command on every Hermes gateway platform."""
    ctx.register_command(
        "wb",
        handler=_handle_workbench_command,
        description="登记、查看、续接或归档 Workbench 任务。",
        args_hint="<命令> [内容或任务编号]",
    )
