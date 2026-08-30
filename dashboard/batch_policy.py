"""WB-S1-047 / FR-020 A2 — authoritative batch-action eligibility policy seam.

本模块是 /batch 动作资格的唯一可导入/可执行 policy seam（CoderX 046/047 Blocker2 修正）：
- 状态集与分区目录：派生自 contract.py（ALL_STATUSES / PARTITIONS）；
- 动作集合：/batch endpoint 实证（plugin_api.py @router.post("/batch") L920-991）；
- 资格范围 = 单项 handler 的实证行为（不再比单项更严，消除静默收窄 legacy /batch）：

  1. resolve / to-task：单项 handler（plugin_api.py L1221/L1301 实证）分区白名单
     {待验证, 待回看, 梦中的邮件, 心理学随想}，不校验 status。文件级 pending→cleared/todo→cleared
     的替换是不命中就不改（status 保持原样归档）；条目级直接拆条目不校验 status。
     因此 policy 对齐为「仅分区白名单」，queued/blank/大写/空白一律可归档（保留旧成功请求）。
  2. complete：单项 handler（plugin_api.py L1130-1208 实证）精确接受
     todo(任意 exec) / in_progress+execution_result=success / done+success(兼容 L1177) /
     completed(幂等重归档 L1179-1182)；其余（pending/queued/blank/abandoned/cleared/converted/
     in_progress 非 success/done 非 success/大写/空白）一律 fail closed。
  3. trash：单项 handler（plugin_api.py L1371-1397 实证）分区白名单(d in PARTITIONS)，
     不校验 status。

前端 desktop-src/home-model.ts computeBatchActionEligibility / buildHomeBatchSubmission
按本 policy 的同一规则镜像实现（TS 侧无法 import Python；规则以本模块 + plugin_api.py
单项 handler 实证为权威，前端镜像与 dashboard/test_batch_eligibility.py 双向机械对账）。
状态规范化：status 只 strip 不 lower（与 /complete `str(...).strip()` 一致）；execution_result
strip+lower（与 /complete `.strip().lower()` 一致）。
"""
from __future__ import annotations

from typing import Final

from contract import (
    PARTITIONS,
    STATUS_COMPLETED,
    STATUS_IN_PROGRESS,
    STATUS_TODO,
)

# /batch endpoint 允许的动作集合（plugin_api.py L934 实证）
BATCH_ACTIONS: Final = frozenset({"resolve", "to-task", "trash", "complete"})

# resolve/to-task 单项 handler 的收件箱分区白名单 —— 由 contract.py PARTITIONS 派生
# （key ∈ {thought, video, psych, dream}），不重复字面量。注意：不校验 status。
_INBOX_KEYS: Final = frozenset({"thought", "video", "psych", "dream"})
REVIEWABLE_DIRS: Final = frozenset(d for d, k in PARTITIONS if k in _INBOX_KEYS)

# 所有分区目录（trash 的 dir 白名单；已处理/回收站由前端 active-provenance 排除）
ALL_DIRS: Final = frozenset(d for d, _ in PARTITIONS)


def is_eligible(dir_: str, status: str, action: str, execution_result: str | None = None) -> bool:
    """按权威 policy（= 单项 handler 实证行为）判定 (dir, status, execution_result) 对 action 是否合法。

    WB-S1-047：资格范围忠实镜像 plugin_api.py 单项 handler，不再比单项更严——
    - resolve/to-task：仅分区白名单（不校验 status；queued/blank/大写/空白仍可归档，保留 legacy）；
    - complete：todo(任意 exec) / in_progress+success / done+success(兼容) / completed(幂等)；
      status 只 strip 不 lower（/complete 实证），execution_result strip+lower；
    - trash：分区白名单（不校验 status）。
    """
    if action not in BATCH_ACTIONS:
        return False
    status_norm = (status or "").strip()
    if action == "complete":
        if status_norm == STATUS_TODO:
            return True
        exec_norm = (execution_result or "").strip().lower()
        if status_norm == STATUS_IN_PROGRESS:
            return exec_norm == "success"
        # 兼容旧监测器/外部 Agent 直接写 done：handler L1177 用 .strip().lower() 判 done，
        # 故此处同样 lower（与 handler 精确一致）。
        if status_norm.lower() == "done":
            return exec_norm == "success"
        if status_norm == STATUS_COMPLETED:  # 幂等重归档（L1179-1182 精确实证）
            return True
        return False
    if action in ("resolve", "to-task"):
        return dir_ in REVIEWABLE_DIRS
    if action == "trash":
        return dir_ in ALL_DIRS
    return False


def ineligible_reason(dir_: str, status: str, action: str, execution_result: str | None = None) -> str | None:
    """不合法时给出可展示原因；合法返回 None。status 只 strip 不 lower（见 is_eligible）。"""
    if action not in BATCH_ACTIONS:
        return f"未知动作 {action}——/batch 仅 resolve|to-task|trash|complete"
    status_norm = (status or "").strip()
    if action == "complete":
        if status_norm == STATUS_TODO:
            return None
        exec_norm = (execution_result or "").strip().lower()
        if status_norm == STATUS_IN_PROGRESS:
            if exec_norm == "success":
                return None
            return f"执行中但 execution_result={execution_result or '（空）'}——仅精确 success 可「完成」"
        if status_norm.lower() == "done":
            if exec_norm == "success":
                return None
            return f"状态 done 但 execution_result={execution_result or '（空）'}——仅 done+success 可「完成」（兼容）"
        if status_norm == STATUS_COMPLETED:
            return None
        return f"状态 {status or '（空）'}——仅 todo、执行中(execution_result=success)、done+success、completed 可「完成」"
    if action in ("resolve", "to-task"):
        verb = "确认处理" if action == "resolve" else "转任务"
        if dir_ not in REVIEWABLE_DIRS:
            return f"仅收件箱分区（{sorted(REVIEWABLE_DIRS)}）可{verb}"
        return None
    if action == "trash":
        return None if dir_ in ALL_DIRS else f"分区 {dir_ or '（空）'} 不在当前事实源"
    return None


def contract_semantics_note() -> str:
    """resolve/to-task 兼容语义契约说明：contract.py 迁移表 vs 单项 handler vs policy。"""
    return (
        "contract.py _TRANSITIONS：仅声明 (pending,resolve)→cleared、(pending,to-task)→converted，"
        "以及 (todo,complete)/(in_progress,complete)。"
        "单项 handler 实证（plugin_api.py）：resolve/to-task 分区白名单、不校验 status"
        "（文件级 pending→cleared/todo→cleared 不命中即原样归档，queued/blank 也可归档）；"
        "complete 精确接受 todo / in_progress+success / done+success(兼容) / completed(幂等)。"
        "本 policy 忠实镜像上述行为（resolve/to-task 仅分区；complete 精确四态）。"
        "迁移表是形式基线；本 policy（可执行 seam）+ 前端镜像 = 运行时权威。"
        "unknown/归档/已移出事实源/重复/畸形 identity 一律 fail closed，不调用 transport。"
    )
