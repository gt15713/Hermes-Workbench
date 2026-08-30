"""WB-S1-046 / FR-020 A2 — 机械生成 authoritative policy matrix（单一事实源）。

从 batch_policy.is_eligible 可执行派生完整矩阵：action × dir × status × execution_result。
输出 dashboard/policy_matrix.json，供 TS 侧（authoritative-contract-red.test.ts）机械对账；
dashboard/test_batch_eligibility.py 反向断言本 JSON 与 is_eligible 逐格一致（双向 drift gate）。

用法：python gen_policy_matrix.py [--out ../policy_matrix.json]  （默认 {repo}/dashboard/policy_matrix.json）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from batch_policy import (
    ALL_DIRS,
    BATCH_ACTIONS,
    REVIEWABLE_DIRS,
    is_eligible,
)
from contract import ALL_STATUSES

# 状态枚举：契约全状态 + 前端可能出现的扩展态（queued/blank/大小写/空白/done 兼容）——
# done 是 COMPLETED_STATUSES 前端词表 + /complete L1180 done+success 兼容实证，必须进矩阵。
STATUSES: tuple[str, ...] = tuple(sorted(ALL_STATUSES)) + ("queued", "", "PENDING", "TODO", " pending ", "TODO ", "Queued", "done", "DONE")
EXECUTION_RESULTS: tuple[str, ...] = ("success", "failure", "waiting", "", None)

# 未知目录也要进入矩阵（drift gate 必须证明 unknown fail closed）
DIRS: tuple[str, ...] = tuple(sorted(ALL_DIRS)) + ("unknown-dir",)


def build_matrix() -> dict[str, bool]:
    m: dict[str, bool] = {}
    for action in sorted(BATCH_ACTIONS):
        for d in DIRS:
            for st in STATUSES:
                for er in EXECUTION_RESULTS:
                    key = contract_key(action, d, st, er)
                    m[key] = is_eligible(d, st, action, execution_result=er)
    m["_meta"] = {
        "actions": sorted(BATCH_ACTIONS),
        "dirs": list(DIRS),
        "statuses": list(STATUSES),
        "reviewable_dirs": sorted(REVIEWABLE_DIRS),
        "execution_results": ["success", "failure", "waiting", "", "None"],
        "generator": "gen_policy_matrix.py",
        "source": "batch_policy.is_eligible",
    }
    return m


def contract_key(action: str, d: str, st: str, er: str | None) -> str:
    """矩阵行 key：action|dir|status|execution_result（None → 'None'；空串 status 原样保留）。"""
    return f"{action}|{d}|{st}|{'None' if er is None else er}"


def main() -> int:
    out = Path(__file__).resolve().parent / "policy_matrix.json"
    if len(sys.argv) > 2 and sys.argv[1] == "--out" and sys.argv[2]:
        out = Path(sys.argv[2]).resolve()
    matrix = build_matrix()
    out.write_text(json.dumps(matrix, ensure_ascii=False, sort_keys=True, indent=1), encoding="utf-8")
    print(f"wrote {out} ({len(matrix)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
