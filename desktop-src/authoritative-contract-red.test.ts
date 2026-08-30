/**
 * WB-S1-046 / FR-020 A1 — 权威契约 RED（先于实现落地，断言即契约）。
 *
 * CoderX 073940 裁决的 7 项 blocker 全部在此还原为可复现失败断言：
 *  1. summary 缺失/null/字符串/NaN/Infinity/负数/小数 → 即使 done/failed 集合完整也必须 protocol error；
 *  2. ok=true + done=[] + failed=全部 → protocol error；完整真值表必须严格等于后端公式
 *     ok = (failed 空) 或 (done 非空)（plugin_api.py L962 实证）；
 *  3. 输入 ids 重复 → buildHomeBatchSubmission 必须返回 null 且不调用 transport（不得去重后继续）；
 *  4. resolve/to-task 对 queued/blank 一律 ineligible；状态规范化与生产 handler 精确一致
 *     （status: 精确小写，不 lower 化宽松；execution_result: strip().lower() 实证）；
 *  5. stale/mixed/duplicate 被拒时 UI 保留全部选择并显示逐项原因，不得 clear-selection；
 *  6. 机械 drift gate：从 dashboard/policy_matrix.json（后端可执行生成的权威矩阵）逐格对账
 *     computeBatchActionEligibility，禁止无人校验的第二套词表。
 */
import { describe, expect, it } from 'vitest'

import { type WbCard } from './types'
import policyMatrixRaw from '../dashboard/policy_matrix.json'
import {
  HOME_VIEW_INITIAL_STATE,
  buildHomeBatchSubmission,
  buildHomeModel,
  computeBatchActionEligibility,
  homeCardSelectionId,
  homeViewStateReducer,
  settleBatchResponse,
} from './home-model'

function card(dir: string, file: string, status?: string, executionResult?: string): WbCard {
  return {
    dir,
    file,
    path: `${dir}/${file}`,
    title: file.replace(/\.md$/, ''),
    status: status ?? '',
    execution_result: executionResult,
    entries: [],
    entry_count: 0,
    priority: '',
    size: '',
    tags: [],
  }
}

function fixtureBoard() {
  return {
    today: '2026-08-30',
    root: '/vault',
    sections: [
      { key: '任务', files: [card('任务', 'a.md', 'todo'), card('任务', 'b.md', 'in_progress', 'success'), card('任务', 'w.md', 'in_progress', 'waiting')] },
      { key: '待验证', files: [card('待验证', 'c.md', 'pending'), card('待验证', 'd2.md', 'todo'), card('待验证', 'q.md', 'queued'), card('待验证', 'blank.md', '')] },
    ],
  }
}

const model = () => buildHomeModel(fixtureBoard() as never)
const idsAB = ['任务|a.md', '任务|b.md']
const enter = () => homeViewStateReducer(HOME_VIEW_INITIAL_STATE, { type: 'enter-multiselect' } as never)

describe('046-RED-1 summary 必须存在且为 finite 非负整数（即使数组完整）', () => {
  it('summary 缺失（仅有完整数组）→ protocol error', () => {
    const s = settleBatchResponse(enter(), { ok: true, done: [{ dir: '任务', file: 'a.md' }], failed: [] } as never, idsAB)
    expect(s.settledCleanly).toBe(false)
    expect(s.keepOpen).toBe(true)
    expect(s.selectedIds).toEqual(idsAB)
    expect(s.overallError).not.toBeNull()
  })
  it('summary=null → protocol error', () => {
    const s = settleBatchResponse(enter(), { ok: true, done: [{ dir: '任务', file: 'a.md' }], failed: [], summary: null } as never, idsAB)
    expect(s.settledCleanly).toBe(false)
    expect(s.keepOpen).toBe(true)
    expect(s.overallError).not.toBeNull()
  })
  it('summary.ok 为字符串 → protocol error', () => {
    const s = settleBatchResponse(enter(), { ok: true, done: [{ dir: '任务', file: 'a.md' }], failed: [], summary: { ok: '1', fail: 0 } } as never, idsAB)
    expect(s.settledCleanly).toBe(false)
    expect(s.keepOpen).toBe(true)
    expect(s.overallError).not.toBeNull()
  })
  it('NaN → protocol error', () => {
    const s = settleBatchResponse(enter(), { ok: true, done: [{ dir: '任务', file: 'a.md' }], failed: [], summary: { ok: NaN, fail: 0 } } as never, idsAB)
    expect(s.settledCleanly).toBe(false)
    expect(s.keepOpen).toBe(true)
    expect(s.overallError).not.toBeNull()
  })
  it('Infinity → protocol error', () => {
    const s = settleBatchResponse(enter(), { ok: true, done: [{ dir: '任务', file: 'a.md' }], failed: [], summary: { ok: Infinity, fail: 0 } } as never, idsAB)
    expect(s.settledCleanly).toBe(false)
    expect(s.keepOpen).toBe(true)
    expect(s.overallError).not.toBeNull()
  })
  it('负数 → protocol error', () => {
    const s = settleBatchResponse(enter(), { ok: true, done: [{ dir: '任务', file: 'a.md' }], failed: [], summary: { ok: -1, fail: 0 } } as never, idsAB)
    expect(s.settledCleanly).toBe(false)
    expect(s.keepOpen).toBe(true)
    expect(s.overallError).not.toBeNull()
  })
  it('小数 → protocol error', () => {
    const s = settleBatchResponse(enter(), { ok: true, done: [{ dir: '任务', file: 'a.md' }], failed: [], summary: { ok: 1.5, fail: 0 } } as never, idsAB)
    expect(s.settledCleanly).toBe(false)
    expect(s.keepOpen).toBe(true)
    expect(s.overallError).not.toBeNull()
  })
})

describe('046-RED-2 顶层 ok 真值表严格等于后端公式 ok = (failed 空) 或 (done 非空)', () => {
  it('ok=true + done=[] + failed=全部 → protocol error（后端对全失败返回 ok=false）', () => {
    const s = settleBatchResponse(
      enter(),
      { ok: true, done: [], failed: [{ dir: '任务', file: 'a.md', error: 'ea' }, { dir: '任务', file: 'b.md', error: 'eb' }], summary: { ok: 0, fail: 2 } },
      idsAB,
    )
    expect(s.settledCleanly).toBe(false)
    expect(s.keepOpen).toBe(true)
    expect(s.overallError).not.toBeNull()
    expect(s.removedCount).toBe(0)
  })
  it('ok=true + done 非空 + failed 非空（部分成功）→ 合法（后端 bool(done)=true）', () => {
    const s = settleBatchResponse(
      enter(),
      { ok: true, done: [{ dir: '任务', file: 'a.md' }], failed: [{ dir: '任务', file: 'b.md', error: 'eb' }], summary: { ok: 1, fail: 1 } },
      idsAB,
    )
    expect(s.settledCleanly).toBe(false)
    expect(s.keepOpen).toBe(true)
    expect(s.selectedIds).toEqual(['任务|b.md'])
  })
  it('ok=false + done=[] + failed=全部 → 合法（全失败）', () => {
    const s = settleBatchResponse(
      enter(),
      { ok: false, done: [], failed: [{ dir: '任务', file: 'a.md', error: 'ea' }, { dir: '任务', file: 'b.md', error: 'eb' }], summary: { ok: 0, fail: 2 } },
      idsAB,
    )
    expect(s.settledCleanly).toBe(false)
    expect(s.keepOpen).toBe(true)
    expect(s.selectedIds).toEqual(idsAB)
  })
})

describe('046-RED-3 输入 ids 重复 → submission 必须 null，不 transport，不得去重后继续', () => {
  it('ids 含重复（[a, a]）→ 返回 null', () => {
    const sub = buildHomeBatchSubmission(['任务|a.md', '任务|a.md'], 'complete', model())
    expect(sub).toBeNull()
  })
  it('ids 含重复但整体合法集合（[a, b, b]）→ 返回 null', () => {
    const sub = buildHomeBatchSubmission(['任务|a.md', '任务|b.md', '任务|b.md'], 'complete', model())
    expect(sub).toBeNull()
  })
})

describe('046-RED-4 queued/blank 资格精确一致（WB-S1-047 A2 纠正：resolve/to-task 仅分区白名单，不校验 status）', () => {
  // WB-S1-047 / A2：现行单项 handler 实证（plugin_api.py L1221/L1301）resolve/to-task 只校验
  // 分区白名单、不校验 status——queued/blank/大写/空白在收件箱分区内仍可归档（保留 legacy 成功请求）。
  // policy 不得再比单项 handler 更严，否则静默收窄旧 /batch 请求（CoderX 081455 Blocker2）。
  it('queued 状态对 resolve → eligible（保留 legacy 归档）', () => {
    const r = computeBatchActionEligibility(model(), ['待验证|q.md'], 'resolve')
    expect(r.eligible).toEqual(['待验证|q.md'])
    expect(r.ineligible).toHaveLength(0)
  })
  it('blank 状态对 resolve → eligible（保留 legacy 归档）', () => {
    const r = computeBatchActionEligibility(model(), ['待验证|blank.md'], 'resolve')
    expect(r.eligible).toEqual(['待验证|blank.md'])
    expect(r.ineligible).toHaveLength(0)
  })
  it('queued 对 to-task → eligible（保留 legacy 转任务）', () => {
    const r = computeBatchActionEligibility(model(), ['待验证|q.md'], 'to-task')
    expect(r.eligible).toEqual(['待验证|q.md'])
  })
  it('queued/blank 对 complete → ineligible（complete 精确四态，非 todo/in_progress/done+success/completed 一律拒绝）', () => {
    expect(computeBatchActionEligibility(model(), ['待验证|q.md'], 'complete').eligible).toEqual([])
    expect(computeBatchActionEligibility(model(), ['待验证|blank.md'], 'complete').eligible).toEqual([])
  })
  it('pending/todo 对 resolve 保持合法（正向守门）', () => {
    const r = computeBatchActionEligibility(model(), ['待验证|c.md', '待验证|d2.md'], 'resolve')
    expect(r.eligible.sort()).toEqual(['待验证|c.md', '待验证|d2.md'])
    expect(r.ineligible).toHaveLength(0)
  })
})

describe('046-RED-5 stale/mixed 拒绝时结算保留全部选择（不 clear-selection）', () => {
  it('协议错误保留全部 submitted ids（selectedIds 不得被清空）', () => {
    const s = settleBatchResponse(enter(), { ok: true, done: [], failed: [{ dir: '任务', file: 'a.md', error: 'x' }], summary: { ok: 0, fail: 1 } }, idsAB)
    expect(s.keepOpen).toBe(true)
    expect(s.selectedIds).toEqual(idsAB)
  })
})

describe('046-RED-6 机械 drift gate：policy_matrix.json 与 TS 资格逐格一致', () => {
  const matrixRaw = policyMatrixRaw as Record<string, unknown>
  const meta = matrixRaw['_meta'] as { actions: string[]; dirs: string[]; statuses: string[]; execution_results: string[] }
  const matrix = {
    actions: meta?.actions ?? [],
    dirs: meta?.dirs ?? [],
    statuses: meta?.statuses ?? [],
    execution_results: meta?.execution_results ?? [],
    matrix: Object.fromEntries(Object.entries(matrixRaw).filter(([k]) => k !== '_meta')) as Record<string, boolean>,
  }

  function buildSectionedBoard() {
    return buildHomeModel({
      today: '2026-08-30',
      sections: matrix.dirs.map(dir => ({ key: dir, files: matrix.statuses.flatMap(st => matrix.execution_results.map(er => card(dir, `${encodeURIComponent(dir)}-${encodeURIComponent(st || 'blank')}-${er}.md`, st, er === 'None' ? undefined : er))) })),
    } as never)
  }

  // 机械 drift gate 断言统一语义（A2.3）：
  //  - 矩阵 False（后端拒绝）→ TS 必须 ineligible（前端不得宽松于后端）；
  //  - 矩阵 True（后端允许）→ TS 对「可见 active 卡」必须 eligible；对「不可见卡
  //    （unknown/已归档 provenance）→ 允许 fail-closed 收紧（安全方向，非第二词表）。
  function assertMatrixCell(
    key: string,
    expected: boolean,
    r: ReturnType<typeof computeBatchActionEligibility>,
    board: ReturnType<typeof buildHomeModel>,
    id: string,
  ) {
    const got = r.eligible.length === 1
    if (expected === false) {
      expect(got, `矩阵拒绝 ${key}，前端必须拒绝`).toBe(false)
      return
    }
    if (got) return
    const visible = board.regions.some(region => region.items.some(item => homeCardSelectionId(item.card) === id && item.side === 'active'))
    expect(visible, `后端允许 ${key} 且卡可见 active，前端必须允许`).toBe(false)
  }

  it('矩阵文件可读且 schema 完整', () => {
    expect(matrix.actions.length).toBeGreaterThan(0)
    expect(matrix.dirs.length).toBeGreaterThan(0)
    expect(matrix.statuses.length).toBeGreaterThan(0)
    expect(matrix.execution_results.length).toBeGreaterThan(0)
    expect(Object.keys(matrix.matrix).length).toBeGreaterThan(0)
  })
  for (const action of ['resolve', 'to-task', 'complete', 'trash'] as const) {
    it(`${action} 矩阵每格与 computeBatchActionEligibility 一致`, () => {
      const board = buildSectionedBoard()
      for (const dir of matrix.dirs) {
        for (const st of matrix.statuses) {
          for (const er of matrix.execution_results) {
            const file = `${encodeURIComponent(dir)}-${encodeURIComponent(st || 'blank')}-${er}.md`
            const key = `${action}|${dir}|${st ?? 'blank'}|${er}`
            const expected = matrix.matrix[key] ?? false
            const r = computeBatchActionEligibility(board, [`${dir}|${file}`], action)
            assertMatrixCell(key, expected, r, board, `${dir}|${file}`)
          }
        }
      }
    })
  }
})