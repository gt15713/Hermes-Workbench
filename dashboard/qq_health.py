"""Read-only QQ path diagnostics for the Workbench health endpoint.

The diagnostic intentionally returns no message content or identifiers.  It
uses the gateway state file for transport health and only timestamp/route
shape from INFO logs for recent intake evidence.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

_INBOUND_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ .*"
    r"inbound message: platform=qqbot user=(?P<user>\S+) chat=(?P<chat>\S+)"
)


def _platform_connected(state_path: Path) -> bool:
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        return state.get("platforms", {}).get("qqbot", {}).get("state") == "connected"
    except (OSError, ValueError, TypeError):
        return False


def _recent_intake(
    log_path: Path, *, now: datetime, recent_hours: int
) -> tuple[datetime | None, datetime | None]:
    c2c_seen = None
    group_seen = None
    cutoff = now - timedelta(hours=recent_hours)
    try:
        with log_path.open("rb") as stream:
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(max(0, size - 2_000_000))
            raw = stream.read().decode("utf-8", errors="replace")
    except OSError:
        return None, None

    for line in raw.splitlines():
        match = _INBOUND_RE.search(line)
        if not match:
            continue
        try:
            seen_at = datetime.strptime(match.group("ts"), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if seen_at < cutoff or seen_at > now + timedelta(minutes=5):
            continue
        if match.group("user") == match.group("chat"):
            c2c_seen = max(c2c_seen or seen_at, seen_at)
        else:
            group_seen = max(group_seen or seen_at, seen_at)
    return c2c_seen, group_seen


def _supports_full_group(adapter_path: Path) -> bool:
    try:
        source = adapter_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    # A compatible adapter must accept the event in both WebSocket dispatch
    # and message routing. One occurrence is insufficient and risks false green.
    return source.count('"GROUP_MESSAGE_CREATE"') >= 2


def _intake_result(kind: str, seen_at: datetime | None, recent_hours: int) -> dict[str, str]:
    if seen_at is None:
        return {"status": "yellow", "detail": f"近 {recent_hours} 小时无{kind}摄取证据"}
    return {"status": "green", "detail": f"最近{kind}摄取：{seen_at:%Y-%m-%d %H:%M:%S}"}


def assess_qq_health(
    *,
    state_path: Path,
    log_path: Path,
    adapter_path: Path,
    now: datetime | None = None,
    recent_hours: int = 24,
) -> dict:
    """Return a privacy-safe QQ transport/intake compatibility verdict."""
    checked_at = now or datetime.now()
    connected = _platform_connected(state_path)
    c2c_seen, group_seen = _recent_intake(log_path, now=checked_at, recent_hours=recent_hours)
    supports_full_group = _supports_full_group(adapter_path)

    transport = {
        "status": "green" if connected else "red",
        "detail": "QQ WebSocket 已连接" if connected else "QQ WebSocket 未连接",
    }
    c2c = _intake_result("私聊", c2c_seen, recent_hours)
    group = _intake_result("群聊", group_seen, recent_hours)
    full_group = {
        "status": "green" if supports_full_group else "yellow",
        "detail": (
            "适配器已识别普通群消息事件"
            if supports_full_group
            else "当前适配器仅确认群 @ 消息；普通群消息等待上游兼容"
        ),
    }
    statuses = {transport["status"], c2c["status"], group["status"], full_group["status"]}
    status = "red" if "red" in statuses else ("yellow" if "yellow" in statuses else "green")
    return {
        "status": status,
        "transport": transport,
        "c2c": c2c,
        "group": group,
        "full_group": full_group,
    }
