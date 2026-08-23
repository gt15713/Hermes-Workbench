"""workbench-view 状态机契约（阶段 1，单一事实源）。

设计文档 v2 §3.1/3.2/3.3：状态集、合法迁移、标签映射、动作集合由本文件生成，
前端（plugin.js）与后端（plugin_api.py）共用，杜绝重复映射与死代码。

- 阶段 1：后端接入本契约；前端仍硬编码（阶段 3 前端体验时统一读契约）。
- 新增状态/迁移/标签必须改本文件 + 跑 test_contract.py 比对。
"""
from __future__ import annotations

from typing import Final

# ---------- 状态集（3.1：8 态 + 回收站保留状态字段） ----------

STATUS_PENDING: Final = "pending"        # 暂存/待确认（待验证/待回看/梦中的邮件）
STATUS_TODO: Final = "todo"              # 待办（任务区）
STATUS_IN_PROGRESS: Final = "in_progress"  # 执行中
STATUS_COMPLETED: Final = "completed"    # 已完成（归档）
STATUS_CLEARED: Final = "cleared"        # 已确认处理（归档）
STATUS_CONVERTED: Final = "converted"    # 已转任务（原文件保留标记）
STATUS_ABANDONED: Final = "abandoned"    # 已放弃（任务区滞留，灰色标记）

ALL_STATUSES: Final = frozenset({
    STATUS_PENDING,
    STATUS_TODO,
    STATUS_IN_PROGRESS,
    STATUS_COMPLETED,
    STATUS_CLEARED,
    STATUS_CONVERTED,
    STATUS_ABANDONED,
})

# ---------- 状态标签（3.2：由契约生成，前端展示用） ----------

STATUS_LABEL: Final = {
    STATUS_PENDING: "待处理",
    STATUS_TODO: "待办",
    STATUS_IN_PROGRESS: "执行中…",
    STATUS_COMPLETED: "已完成",
    STATUS_CLEARED: "已清",
    STATUS_CONVERTED: "已转",
    STATUS_ABANDONED: "已放弃",
}

# ---------- 分区（3.2：目录 key → 状态语义） ----------

PARTITIONS: Final = (
    ("待验证", "thought"),
    ("待回看", "video"),
    ("任务", "task"),
    ("心理学随想", "psych"),
    ("梦中的邮件", "dream"),
    ("已处理", "done"),
    ("回收站", "trash"),
)

# 分区名集合（_safe_resolve / 端点白名单用）
PARTITION_NAMES: Final = frozenset(d for d, _ in PARTITIONS)

# ---------- 合法迁移表（3.1：唯一事实源） ----------

# 迁移: (from_status, action) → to_status
_TRANSITIONS: Final = {
    (STATUS_PENDING, "resolve"): STATUS_CLEARED,
    (STATUS_PENDING, "to-task"): STATUS_CONVERTED,
    (STATUS_PENDING, "taskify"): STATUS_TODO,
    (STATUS_TODO, "execute"): STATUS_IN_PROGRESS,
    (STATUS_TODO, "complete"): STATUS_COMPLETED,
    (STATUS_TODO, "defer"): STATUS_TODO,
    (STATUS_TODO, "abandon"): STATUS_ABANDONED,
    (STATUS_ABANDONED, "reopen"): STATUS_TODO,
    (STATUS_IN_PROGRESS, "reset-execution"): STATUS_TODO,
    (STATUS_IN_PROGRESS, "complete"): STATUS_COMPLETED,
}

# 动作名集合（端点/前端可执行动作清单）
ALL_ACTIONS: Final = frozenset(a for _, a in _TRANSITIONS)


def is_valid_status(status: str) -> bool:
    """校验状态合法性。"""
    return status in ALL_STATUSES


def can_transition(from_status: str, action: str) -> bool:
    """校验 (from_status, action) 是否合法迁移。"""
    return (from_status, action) in _TRANSITIONS


def next_status(from_status: str, action: str) -> str | None:
    """返回迁移后的目标状态；非法迁移返回 None。"""
    return _TRANSITIONS.get((from_status, action))


def status_label(status: str) -> str:
    """状态 → 展示标签（未知状态原样返回）。"""
    return STATUS_LABEL.get(status, status)


# ---------- 类型标签（3.2 死代码清理后的唯一来源） ----------

TYPE_LABEL: Final = {
    "queued": "暂存",
    "task": "任务",
    "dream_mail": "梦中邮件",
    "psych": "心理学随想",
}

# ---------- schema 版本（3.3/阶段 1：迁移框架） ----------

SCHEMA_VERSION: Final = 1
SCHEMA_VERSION_FIELD: Final = "schema_version"
