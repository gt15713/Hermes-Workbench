"""WB-S1-047 / FR-020 A1/A2 — /batch 动作资格后端权威镜像（derive，不重写字面量）。

CoderX 046/047 修正：
- 不再在测试体内重写分区/状态字面量并与自身比较；
- 全部从 batch_policy（可导入/可执行 authoritative seam）与 contract.py 派生；
- policy 资格范围 = plugin_api.py 单项 handler 实证行为（不再比单项更严，消除
  静默收窄 legacy /batch）：
    * resolve/to-task：仅分区白名单（不校验 status；queued/blank/大写/空白仍可归档）；
    * complete：todo(任意 exec) / in_progress+success / done+success(兼容) /
      completed(幂等重归档)；其余 fail closed；
    * trash：分区白名单（不校验 status）。
- 前端 home-model.ts computeBatchActionEligibility / buildHomeBatchSubmission
  镜像同一规则（文档化），本文件对账派生结果（含真实空串/大小写/前后空白状态）。
"""
import json

from batch_policy import (
    ALL_DIRS,
    BATCH_ACTIONS,
    REVIEWABLE_DIRS,
    ineligible_reason,
    is_eligible,
)
from contract import (
    STATUS_COMPLETED,
    STATUS_PENDING,
    STATUS_TODO,
    can_transition,
)


def test_batch_actions_set():
    """/batch 动作集合固定为四（policy seam 唯一词表）。"""
    assert BATCH_ACTIONS == {"resolve", "to-task", "trash", "complete"}


def test_reviewable_dirs_derived_from_contract_partitions():
    """收件箱目录由 contract.py PARTITIONS 派生（thought/video/psych/dream），不写死字面量。"""
    assert REVIEWABLE_DIRS == {"待验证", "待回看", "梦中的邮件", "心理学随想"}
    assert all(d in ALL_DIRS for d in REVIEWABLE_DIRS)


# ---------- complete 资格（精准 = 单项 handler L1130-1208 实证） -----------------

def test_complete_todo_always_legal():
    assert is_eligible("任务", "todo", "complete")
    assert is_eligible("任务", "todo", "complete", execution_result="failure")  # todo 不校验 exec
    assert ineligible_reason("任务", "todo", "complete") is None


def test_complete_in_progress_exact_success_only():
    """in_progress 仅 execution_result 精确 success；empty/waiting/unknown/failure fail closed。"""
    assert is_eligible("任务", "in_progress", "complete", execution_result="success")
    for bad in ("", "waiting", "unknown", "pending", "failure", None):
        assert not is_eligible("任务", "in_progress", "complete", execution_result=bad)
        assert ineligible_reason("任务", "in_progress", "complete", execution_result=bad) is not None


def test_complete_done_success_compat_and_completed_idempotent():
    """done+success（旧监测器/外部 Agent 兼容，L1177）与 completed（幂等重归档 L1179）合法。"""
    assert is_eligible("任务", "done", "complete", execution_result="success")
    assert not is_eligible("任务", "done", "complete", execution_result="failure")
    assert is_eligible("任务", STATUS_COMPLETED, "complete")  # 幂等重归档
    # done 大小写 / 前后空白（handler L1177 用 .strip().lower() 判 done）
    assert is_eligible("任务", " Done ", "complete", execution_result="success")
    assert is_eligible("任务", "DONE", "complete", execution_result="success")


def test_complete_other_statuses_fail_closed():
    """pending/queued/abandoned/cleared/converted/blank/大写 一律不可 complete。"""
    for bad in ("pending", "queued", "abandoned", "cleared", "converted", "", "TODO", "In_Progress"):
        assert not is_eligible("任务", bad, "complete", execution_result="success"), bad
        assert ineligible_reason("任务", bad, "complete", execution_result="success") is not None
    # 前后空白且 strip 后等于合法态（todo）→ 合法（与 handler `.strip()` 一致），
    # 但大写（TODO）不 lower → 仍 fail closed。
    assert is_eligible("任务", " todo ", "complete", execution_result="success")
    assert not is_eligible("任务", " TODO ", "complete", execution_result="success")


def test_in_progress_derives_from_contract_transition():
    """迁移表支持 in_progress→complete；policy 叠加 execution_result 精确门（endpoint 实证）。"""
    assert can_transition("in_progress", "complete")
    assert not can_transition("weird-status-xyz", "complete")


# ---------- resolve / to-task 资格（精准 = 单项 handler：仅分区白名单） -------------

def test_resolve_to_task_partition_whitelist_only():
    """resolve/to-task 仅分区白名单（不校验 status）；任务/已处理/回收站分区 fail closed。"""
    for action in ("resolve", "to-task"):
        assert is_eligible("待验证", STATUS_PENDING, action)
        assert is_eligible("待验证", STATUS_TODO, action)
        # queued/blank/大写/前后空白/未知状态也能归档（保留 legacy 成功请求，不再收紧）
        for st in ("queued", "", "PENDING", " pending ", "TODO", "weird-status-xyz"):
            assert is_eligible("待验证", st, action), (action, st)
            assert ineligible_reason("待验证", st, action) is None
        # 非收件箱分区 fail closed（目录原因）
        assert not is_eligible("任务", STATUS_PENDING, action)
        assert ineligible_reason("任务", STATUS_PENDING, action) is not None
        assert not is_eligible("已处理", STATUS_PENDING, action)
        assert not is_eligible("回收站", STATUS_PENDING, action)
        assert is_eligible("待验证", STATUS_PENDING, action)  # 白名单内合法


def test_trash_any_partition_dir():
    """trash 仅校验分区目录（active provenance 排除由前端负责）；unknown 分区 fail closed。"""
    assert is_eligible("任务", "todo", "trash")
    assert is_eligible("待验证", "pending", "trash")
    assert is_eligible("已处理", "completed", "trash")
    assert is_eligible("回收站", "abandoned", "trash")
    assert not is_eligible("不存在的分区", "todo", "trash")


def test_unknown_action_and_unknown_dir_fail_closed():
    assert not is_eligible("任务", "todo", "delete")
    assert ineligible_reason("任务", "todo", "delete") is not None
    assert not is_eligible("不存在的分区", "todo", "trash")
    assert not is_eligible("不存在的分区", "pending", "resolve")


# ---- WB-S1-047 / A1：真实 ""、PENDING/TODO、前后空白状态与 execution_result 变体 ----

def test_real_blank_state_is_distinct_matrix_cell():
    """真实空串 status 是独立矩阵单元（不是 'blank' 占位），且对 complete 必须 fail closed。"""
    assert not is_eligible("任务", "", "complete", execution_result="success")
    assert ineligible_reason("任务", "", "complete") is not None
    # 对 resolve（仅分区）空串合法
    assert is_eligible("待验证", "", "resolve")


def test_uppercase_and_surrounding_whitespace_status():
    """status 只 strip 不 lower：大写 fail closed，前后空白 strip 后合法（与 handler `str(...).strip()` 一致）。"""
    # 大写（strip 后仍非合法小写态）→ fail closed
    for bad in ("PENDING", "TODO", "IN_PROGRESS", "COMPLETED"):
        assert not is_eligible("任务", bad, "complete", execution_result="success"), bad
    # 前后空白 + 合法态 → strip 后合法
    assert is_eligible("任务", " todo ", "complete")
    assert is_eligible("任务", "  in_progress  ", "complete", execution_result="success")
    # resolve 仅分区，空白/大写 status 仍合法
    for st in (" pending ", "TODO", ""):
        assert is_eligible("待验证", st, "resolve"), st


# ---- WB-S1-046 / A2：机械双向 drift gate + 生产消费证明 ----------------------

def test_policy_matrix_json_matches_runtime_is_eligible():
    """反向 drift gate：policy_matrix.json（提供给 TS 对账的机械矩阵）必须与
    is_eligible 运行时逐格一致，防矩阵文件陈旧形成第二词表。"""
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    payload = json.loads((root / "policy_matrix.json").read_text(encoding="utf-8"))
    meta = payload["_meta"]
    rows = {k: v for k, v in payload.items() if k != "_meta"}
    assert len(rows) > 0
    for action in meta["actions"]:
        for d in meta["dirs"]:
            for st in meta["statuses"]:
                for er in meta["execution_results"]:
                    key = f"{action}|{d}|{st}|{er}"
                    assert key in rows, f"matrix 缺失 {key}"
                    expected = is_eligible(d, st, action, execution_result=(None if er == "None" else er))
                    assert rows[key] == expected, f"matrix 与 is_eligible 不一致 {key}: {rows[key]} != {expected}"


def test_production_batch_consumes_policy_and_rejects_ineligible():
    """A2 生产消费证明：/batch handler 在生产路径调用 authoritative policy；
    对非法状态（如 complete 遇非 todo 且非 in_progress+success）直接 failed，不调用单项 handler。"""
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    import plugin_api as api

    b = api.batch
    assert callable(b)
    import asyncio
    from unittest.mock import AsyncMock, patch

    async def run():
        with patch("plugin_api.resolve", new=AsyncMock(return_value={"ok": False, "error": "not found"})) as mock_resolve:
            out = await b(
                {
                    "action": "resolve",
                    "items": [{"dir": "待验证", "file": "missing.md"}],
                }
            )
            return out, mock_resolve

    out, mock_resolve = asyncio.run(run())
    assert out["ok"] is False
    # 文件不存在：policy 预检跳过（p is None → 不判定），交由单项 handler 返回 not found
    assert mock_resolve.await_count == 1

    # 非法状态：文件存在但 status=queued + action=complete → policy 层拒绝（非 todo/in_progress+success），
    # 绝不调用单项 handler（fail closed）
    from wb_utils import WORKBENCH_ROOT as _WB_ROOT

    try:
        d = _WB_ROOT / "任务"
        d.mkdir(parents=True, exist_ok=True)
        f = d / "queued-probe.md"
        f.write_text("---\ntype: queued\nstatus: queued\n---\n\n# probe\n", encoding="utf-8")
        import asyncio as _a

        async def run2():
            with patch("plugin_api.complete", new=AsyncMock(return_value={"ok": True, "file": "x.md"})) as mock2:
                out2 = await b(
                    {
                        "action": "complete",
                        "items": [{"dir": "任务", "file": "queued-probe.md"}],
                    }
                )
                return out2, mock2

        out2, mock2 = _a.run(run2())
        assert out2["ok"] is False
        assert mock2.await_count == 0  # policy 层拒绝 → 单项 handler 从未被调用
        assert any("complete" in (it.get("error") or "") for it in out2["failed"])
    finally:
        try:
            (_WB_ROOT / "任务" / "queued-probe.md").unlink()
        except OSError:
            pass


def test_batch_all_returns_have_mandatory_schema():
    """A1.2: 业务早退也必须返回严格统一的 done/failed/summary schema。"""
    import asyncio

    import plugin_api as api

    for body in ({"action": "bad", "items": []}, {"action": "trash", "items": []}):
        out = asyncio.run(api.batch(body))
        assert isinstance(out["done"], list)
        assert isinstance(out["failed"], list)
        assert out["summary"] == {"ok": 0, "fail": 0}
        assert isinstance(out.get("error"), str) and out["error"]


def test_batch_prevalidates_all_items_before_any_handler_or_side_effect(tmp_path):
    """A1.3: 前一项合法、后一项 malformed，整体 fail closed 且 handler/副作用均为零。"""
    import asyncio
    from unittest.mock import AsyncMock, patch

    import plugin_api as api

    marker = tmp_path / "handler-called"

    async def mutate(_item):
        marker.write_text("called", encoding="utf-8")
        return {"ok": True, "file": "valid.md"}

    handler = AsyncMock(side_effect=mutate)
    with patch("plugin_api.trash", new=handler):
        out = asyncio.run(api.batch({"action": "trash", "items": [
            {"dir": "任务", "file": "valid.md"},
            "malformed",
        ]}))
    assert out["ok"] is False
    assert out["done"] == []
    assert handler.await_count == 0
    assert not marker.exists()


def test_batch_rejects_duplicate_identity_before_any_handler_or_side_effect(tmp_path):
    """A1.3: 前一项合法、后一项 duplicate，整体 fail closed 且 handler/副作用均为零。"""
    import asyncio
    from unittest.mock import AsyncMock, patch

    import plugin_api as api

    marker = tmp_path / "handler-called"

    async def mutate(_item):
        marker.write_text("called", encoding="utf-8")
        return {"ok": True, "file": "valid.md"}

    handler = AsyncMock(side_effect=mutate)
    duplicate = {"dir": "任务", "file": "valid.md"}
    with patch("plugin_api.trash", new=handler):
        out = asyncio.run(api.batch({"action": "trash", "items": [duplicate, dict(duplicate)]}))
    assert out["ok"] is False
    assert out["done"] == []
    assert handler.await_count == 0
    assert not marker.exists()
