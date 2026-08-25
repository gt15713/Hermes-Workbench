"""Privacy-safe index of authorized Workbench task conversations."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path


class ConversationIndex:
    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS conversation_refs (
                    ref_id TEXT PRIMARY KEY,
                    platform TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    resume_mode TEXT NOT NULL,
                    session_id TEXT,
                    updated_at TEXT NOT NULL
                )"""
            )

    def upsert_authorized(
        self,
        *,
        platform: str,
        message_id: str,
        summary: str,
        task_id: str,
        status: str,
        session_id: str = "",
    ) -> dict:
        official_id = str(message_id or "").strip()
        if not official_id:
            return {"ok": False, "error": "official message_id required"}
        raw_platform = str(platform or "").lower()
        if raw_platform in {"weixin", "wechat"}:
            source = "weixin"
        elif raw_platform in {"qq", "qqbot"}:
            source = "qq"
        else:
            source = "messaging"
        ref_id = hashlib.sha256(f"{source}\n{official_id}".encode()).hexdigest()
        resume_mode = "original" if session_id else "summary"
        updated_at = datetime.now().astimezone().isoformat(timespec="seconds")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO conversation_refs
                   (ref_id, platform, summary, task_id, status, resume_mode, session_id, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(ref_id) DO UPDATE SET
                     summary=excluded.summary, task_id=excluded.task_id,
                     status=excluded.status, resume_mode=excluded.resume_mode,
                     session_id=excluded.session_id, updated_at=excluded.updated_at""",
                (
                    ref_id,
                    source,
                    str(summary or "").strip()[:240],
                    str(task_id or "").strip(),
                    str(status or "active").strip(),
                    resume_mode,
                    str(session_id or "").strip() or None,
                    updated_at,
                ),
            )
        return {"ok": True, "ref_id": ref_id, "resume_mode": resume_mode}

    def update_by_task_id(
        self,
        task_id: str,
        *,
        status: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        public_task_id = str(task_id or "").strip()
        if not public_task_id:
            return {"ok": True, "updated": 0}

        assignments = []
        values = []
        if status is not None:
            assignments.append("status=?")
            values.append(str(status).strip())
        if session_id is not None:
            normalized_session_id = str(session_id).strip()
            assignments.extend(("session_id=?", "resume_mode=?"))
            values.extend(
                (
                    normalized_session_id or None,
                    "original" if normalized_session_id else "summary",
                )
            )
        assignments.append("updated_at=?")
        values.append(datetime.now().astimezone().isoformat(timespec="seconds"))
        values.append(public_task_id)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                f"UPDATE conversation_refs SET {', '.join(assignments)} WHERE task_id=?",
                values,
            )
        return {"ok": True, "updated": cursor.rowcount}

    def list_conversations(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT ref_id, platform, summary, task_id, status, resume_mode, session_id, updated_at "
                "FROM conversation_refs ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]
