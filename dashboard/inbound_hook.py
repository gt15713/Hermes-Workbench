# -*- coding: utf-8 -*-
"""入站消息平台强制登记（P2-必做，2026-08-22）。

背景：复测第二条（不带链接处理型「Workbench 是否还值得做」）agent 处理了但未落卡
——prompt 纪律依赖 agent 自觉，不可靠。本模块用官方 ``pre_gateway_dispatch`` hook
在 agent 处理前由平台层强制登记任务卡，零依赖 agent 自觉。

契约：hook 为同步回调，kwargs = event / gateway / session_store（见
hermes_cli/plugins.py VALID_HOOKS）。登记绝不阻断 dispatch（永远返回 None）；
失败仅告警。message_id = 内容指纹（链接或标题），与 agent 侧收录语义一致，防双卡。
"""
from __future__ import annotations

import asyncio
import logging
import re

_log = logging.getLogger("workbench-view")


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
    fingerprint = (url_m.group(0).strip("，。") if url_m else title)[:100]
    return {
        "message_id": fingerprint,
        "dir": target_dir,
        "title": title,
        "content": t,
    }


async def _ingest_async(body: dict) -> None:
    import plugin_api  # noqa: PLC0415 - 同进程复用端点函数体

    try:
        result = await plugin_api.ingest_message(body)
    except Exception as exc:  # noqa: BLE001 - 登记失败仅告警，不阻断消息处理
        _log.warning("workbench inbound auto-register failed: %s", exc)
        return
    if result.get("duplicate"):
        _log.info("workbench inbound auto-register duplicate: %s", result.get("reason"))
    elif result.get("ok"):
        _log.info("workbench inbound auto-register ok: %s", result.get("file"))
    else:
        _log.warning("workbench inbound auto-register rejected: %s", result)


def _on_pre_gateway_dispatch(**kwargs) -> None:
    """pre_gateway_dispatch 回调：仅处理 QQ 入站消息，平台强制登记，永远返回 None。"""
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
    text = getattr(event, "text", "") or ""
    body = build_ingest_body(text, getattr(event, "message_id", None))
    if body is None:
        return None
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_ingest_async(body))
        else:
            asyncio.run(_ingest_async(body))
    except Exception as exc:  # noqa: BLE001
        _log.warning("workbench inbound auto-register schedule failed: %s", exc)
    return None


def register(ctx) -> None:
    """插件注册入口：挂载 pre_gateway_dispatch hook。"""
    ctx.register_hook("pre_gateway_dispatch", _on_pre_gateway_dispatch)
