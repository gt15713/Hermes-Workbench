"""Privacy-safe lifecycle synchronization shared by endpoints and scripts."""

from __future__ import annotations

import re
import sqlite3
import time

from conversation_index import ConversationIndex

_TASK_ID_RE = re.compile(r"(?m)^task_id:\s*(WB-[0-9A-Fa-f]{8})\s*$")


def sync_by_task_text(
    db_path,
    task_text: str,
    *,
    status: str | None = None,
    session_id: str | None = None,
) -> dict:
    match = _TASK_ID_RE.search(task_text)
    if not match:
        return {"ok": True, "updated": 0}
    changes = {}
    if status is not None:
        changes["status"] = status
    if session_id is not None:
        changes["session_id"] = session_id
    for attempt in range(3):
        try:
            return ConversationIndex(db_path).update_by_task_id(
                match.group(1).upper(), **changes
            )
        except sqlite3.OperationalError as exc:
            transient_lock = any(
                marker in str(exc).lower() for marker in ("locked", "busy")
            )
            if not transient_lock or attempt == 2:
                break
            time.sleep(0.05 * (attempt + 1))
        except Exception:
            break
    return {"ok": False, "updated": 0, "error": "conversation index unavailable"}
