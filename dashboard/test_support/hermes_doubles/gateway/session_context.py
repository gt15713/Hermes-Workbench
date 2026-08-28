# -*- coding: utf-8 -*-
"""`gateway.session_context` 的最小忠实替身（仅测试目录，WB-S1-021）。

镜像真实宿主（hermes-agent/gateway/session_context.py）被插件与其测试依赖的
语义，签名与解析顺序逐条对齐：

- ContextVar 任务局部性：asyncio.create_task 经 copy_context 快照上下文，
  并发轮次互不串扰（并发身份测试依赖此性质）；
- 三态：`_UNSET`（从未绑定 → 回落 os.environ）/ `""`（显式清空，压制 os.environ
  回落）/ 非空值；get_session_env 依此顺序解析；
- set_session_vars(...) -> list tokens；clear_session_vars(tokens) 把所有变量
  置 `""`（而非 reset(token)），async-delivery 位回 `_UNSET`；
- 返回 tokens 仅为 API 兼容，与真实宿主一致。

不含子进程环境桥接（session_context_engaged / runtime_cwd）——插件与测试
不消费这些路径；缺失属有意最小化，接口面漂移由契约测试把关。
"""

import os
from contextvars import ContextVar
from typing import Any

_UNSET: Any = object()

# 真实宿主 _VAR_MAP 的键集（本替身覆盖其字符串型会话身份键）。
_VAR_MAP: dict = {
    "HERMES_SESSION_PLATFORM": ContextVar("HERMES_SESSION_PLATFORM", default=_UNSET),
    "HERMES_SESSION_SOURCE": ContextVar("HERMES_SESSION_SOURCE", default=_UNSET),
    "HERMES_SESSION_CHAT_ID": ContextVar("HERMES_SESSION_CHAT_ID", default=_UNSET),
    "HERMES_SESSION_CHAT_TYPE": ContextVar("HERMES_SESSION_CHAT_TYPE", default=_UNSET),
    "HERMES_SESSION_CHAT_NAME": ContextVar("HERMES_SESSION_CHAT_NAME", default=_UNSET),
    "HERMES_SESSION_THREAD_ID": ContextVar("HERMES_SESSION_THREAD_ID", default=_UNSET),
    "HERMES_SESSION_USER_ID": ContextVar("HERMES_SESSION_USER_ID", default=_UNSET),
    "HERMES_SESSION_USER_ID_ALT": ContextVar("HERMES_SESSION_USER_ID_ALT", default=_UNSET),
    "HERMES_SESSION_USER_NAME": ContextVar("HERMES_SESSION_USER_NAME", default=_UNSET),
    "HERMES_SESSION_SCOPE_ID": ContextVar("HERMES_SESSION_SCOPE_ID", default=_UNSET),
    "HERMES_SESSION_KEY": ContextVar("HERMES_SESSION_KEY", default=_UNSET),
    "HERMES_SESSION_ID": ContextVar("HERMES_SESSION_ID", default=_UNSET),
    "HERMES_UI_SESSION_ID": ContextVar("HERMES_UI_SESSION_ID", default=_UNSET),
    "HERMES_SESSION_MESSAGE_ID": ContextVar("HERMES_SESSION_MESSAGE_ID", default=_UNSET),
    "HERMES_SESSION_PROFILE": ContextVar("HERMES_SESSION_PROFILE", default=_UNSET),
    "HERMES_BROWSER_CONTROL_PRINCIPAL": ContextVar(
        "HERMES_BROWSER_CONTROL_PRINCIPAL", default=_UNSET
    ),
    "HERMES_BROWSER_CONTROL_TRANSPORT_FAMILY": ContextVar(
        "HERMES_BROWSER_CONTROL_TRANSPORT_FAMILY", default=_UNSET
    ),
    "HERMES_CRON_SESSION": ContextVar("HERMES_CRON_SESSION", default=_UNSET),
}

_ASYNC_DELIVERY: ContextVar = ContextVar(
    "HERMES_SESSION_ASYNC_DELIVERY", default=_UNSET
)

# set_session_vars 形参 → 环境变量名 的固定映射（签名与真实宿主一致）。
_PARAM_TO_ENV: dict = {
    "platform": "HERMES_SESSION_PLATFORM",
    "source": "HERMES_SESSION_SOURCE",
    "chat_id": "HERMES_SESSION_CHAT_ID",
    "chat_type": "HERMES_SESSION_CHAT_TYPE",
    "chat_name": "HERMES_SESSION_CHAT_NAME",
    "thread_id": "HERMES_SESSION_THREAD_ID",
    "user_id": "HERMES_SESSION_USER_ID",
    "user_id_alt": "HERMES_SESSION_USER_ID_ALT",
    "user_name": "HERMES_SESSION_USER_NAME",
    "scope_id": "HERMES_SESSION_SCOPE_ID",
    "session_key": "HERMES_SESSION_KEY",
    "session_id": "HERMES_SESSION_ID",
    "message_id": "HERMES_SESSION_MESSAGE_ID",
    "profile": "HERMES_SESSION_PROFILE",
    "browser_control_principal": "HERMES_BROWSER_CONTROL_PRINCIPAL",
    "browser_control_transport_family": "HERMES_BROWSER_CONTROL_TRANSPORT_FAMILY",
    "ui_session_id": "HERMES_UI_SESSION_ID",
    "cron_session": "HERMES_CRON_SESSION",
}


def set_session_vars(
    platform: str = "",
    source: str = "",
    chat_id: str = "",
    chat_type: str = "",
    chat_name: str = "",
    thread_id: str = "",
    user_id: str = "",
    user_id_alt: str = "",
    user_name: str = "",
    scope_id: str = "",
    session_key: str = "",
    session_id: str = "",
    message_id: str = "",
    profile: str = "",
    browser_control_principal: str = "",
    browser_control_transport_family: str = "",
    cwd: str = "",
    async_delivery: bool = True,
    ui_session_id: str = "",
    cron_session: Any = _UNSET,
) -> list:
    """绑定全部会话变量并返回重置 tokens（与真实宿主同构；tokens 仅为兼容）。"""
    del cwd  # 替身不桥接 runtime_cwd（插件不消费）。
    values = {
        "platform": platform,
        "source": source,
        "chat_id": chat_id,
        "chat_type": chat_type,
        "chat_name": chat_name,
        "thread_id": thread_id,
        "user_id": user_id,
        "user_id_alt": user_id_alt,
        "user_name": user_name,
        "scope_id": scope_id,
        "session_key": session_key,
        "session_id": session_id,
        "message_id": message_id,
        "profile": profile,
        "browser_control_principal": browser_control_principal,
        "browser_control_transport_family": browser_control_transport_family,
        "ui_session_id": ui_session_id,
        "cron_session": cron_session,
    }
    tokens = [_VAR_MAP[_PARAM_TO_ENV[k]].set(v) for k, v in values.items()]
    tokens.append(_ASYNC_DELIVERY.set(bool(async_delivery)))
    return tokens


def clear_session_vars(tokens: list) -> None:
    """把所有会话变量显式置 `""`（压制 os.environ 回落）；async 位回 `_UNSET`。

    `tokens` 与真实宿主一致仅为 API 兼容，实际用 var.set("") 保证
    「显式清空」与「从未绑定（_UNSET）」可区分。
    """
    del tokens
    for var in _VAR_MAP.values():
        var.set("")
    _ASYNC_DELIVERY.set(_UNSET)


def get_session_env(name: str, default: str = "") -> str:
    """按真实宿主解析顺序读取会话变量。

    1. ContextVar：曾被显式 set（含置 `""`）即权威，不回落 os.environ；
    2. 从未绑定（_UNSET）→ 回落 os.environ（CLI/cron/裸测试进程语义）；
    3. 仍无 → *default*。
    """
    var = _VAR_MAP.get(name)
    if var is None and name == "HERMES_SESSION_ASYNC_DELIVERY":
        var = _ASYNC_DELIVERY
    if var is not None:
        value = var.get()
        if value is not _UNSET:
            return value
    return os.getenv(name, default)
