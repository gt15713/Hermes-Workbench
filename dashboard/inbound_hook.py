# -*- coding: utf-8 -*-
"""QQ 入站证据 Hook 与授权后收录 body 构造器。

背景：复测第二条（不带链接处理型「Workbench 是否还值得做」）agent 处理了但未落卡
——prompt 纪律依赖 agent 自觉，不可靠。本模块用官方 ``pre_gateway_dispatch`` hook
历史版本曾在 agent 授权前强制登记任务卡；该路径已因越权写入风险停用。

契约：hook 为同步回调，kwargs = event / gateway / session_store（见
hermes_cli/plugins.py VALID_HOOKS）。Hook 只记录无标识的事件类型证据并永远返回 None；
授权后的宿主调用可复用 ``build_ingest_body``，优先使用 QQ 官方 message_id 去重。
"""
from __future__ import annotations

import logging
import re

_log = logging.getLogger("workbench-view")

_KNOWN_QQ_EVENTS = {
    "C2C_MESSAGE_CREATE",
    "GROUP_AT_MESSAGE_CREATE",
    "GROUP_MESSAGE_CREATE",
    "INTERACTION_CREATE",
}


def _event_type_from_event(event) -> str:
    """Return a bounded event label without ever logging raw payload values."""
    raw = getattr(event, "raw_message", None)
    if not isinstance(raw, dict):
        return "UNKNOWN"
    candidate = str(raw.get("event_type") or raw.get("event_name") or "").strip().upper()
    return candidate if candidate in _KNOWN_QQ_EVENTS else "UNKNOWN"


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line
    return (text or "").strip()


def build_ingest_body(text: str, event_message_id: str | None = None) -> dict | None:
    """构造 ingest body；None = 无需登记。分区与判定复用 wb_utils（单一词表来源）。"""
    from wb_utils import _ANY_URL_RE, _VIDEO_URL_RE, auto_register_dir, should_auto_register

    t = (text or "").strip()
    if not t or t.startswith("/"):
        return None
    if not should_auto_register(t):
        return None
    target_dir = auto_register_dir(t)
    if target_dir is None:
        return None

    url_m = _VIDEO_URL_RE.search(t) or _ANY_URL_RE.search(t)
    title = re.sub(r"[\[\]【】#*`]", "", _first_line(t))[:40] or "QQ消息"
    official_id = str(event_message_id or "").strip()
    fingerprint = (
        f"qqbot:{official_id[:200]}"
        if official_id
        else (url_m.group(0).strip("，。") if url_m else title)[:100]
    )
    return {
        "message_id": fingerprint,
        "dir": target_dir,
        "title": title,
        "content": t,
    }


def _on_pre_gateway_dispatch(**kwargs) -> None:
    """Record privacy-safe QQ evidence; never mutate before Hermes authorization."""
    event = kwargs.get("event")
    if event is None:
        return None
    source = getattr(event, "source", None)
    platform = getattr(source, "platform", None)
    platform_value = getattr(platform, "value", platform)
    # P0-B：hook 触发信号（无内容，防隐私泄漏；文本不进日志）
    _log.info("workbench hook fired platform=%s", platform_value)
    if platform_value != "qqbot":
        return None
    _log.info("workbench qq event received type=%s", _event_type_from_event(event))
    return None


def register(ctx) -> None:
    """插件注册入口：挂载 pre_gateway_dispatch hook。"""
    ctx.register_hook("pre_gateway_dispatch", _on_pre_gateway_dispatch)
