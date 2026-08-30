/**
 * WB-S1-047 / FR-020 A1+A3 — 精确收口新增 seam 测试（source/test only）。
 *
 * 覆盖 CoderX 081455 明确要求的三项：
 *  A1.1 board refresh 后原 selected ID 失效（missing/archived/unknown）——
 *        reducer→presentation→submission seam：原始选择保留到拒绝/反馈层并逐项显示原因，
 *        不得在 presentation 构建时静默丢失；可提交集仅剩仍可行动的条目。
 *  A1.2 /batch 响应缺 done 或缺 failed 数组 → protocol error，保留全部选择且不 invalidate。
 *  A3  done、failed、summary 全为必需字段；任一缺失/畸形均 protocol error；
 *       duplicate/identity/ok 真值表保持既有门禁。
 */
import { describe, expect, it } from 'vitest'

import { type WbCard } from './types'
import {
  HOME_VIEW_INITIAL_STATE,
  buildHomeBatchSubmission,
  buildHomeModel,
  buildHomeViewPresentation,
  computeBatchActionEligibility,
  homeViewStateReducer,
  settleBatchResponse,
} from './home-model'

function card(dir: string, file: string, status?: string): WbCard {
  return {
    dir,
    file,
    path: `${dir}/${file}`,
    title: file.replace(/\.md$/, ''),
    status: status ?? '',
    entries: [],
    entry_count: 0,
    priority: '',
    size: '',
    tags: [],
  }
}

function boardWith(ids: Array<[string, string, string]>) {
  return buildHomeModel({
    today: '2026-08-30',
    sections: [
      { key: '任务', files: ids.filter(([d]) => d === '任务').map(([d, f, s]) => card(d, f, s)) },
      { key: '待验证', files: ids.filter(([d]) => d === '待验证').map(([d, f, s]) => card(d, f, s)) },
    ],
  } as never)
}

// ── A1.1：board refresh 后 stale selection 保留到反馈层 ───────────────────
describe('047-A1.1 原始 selectedId 失效时保留到拒绝/反馈层，不静默丢失', () => {
  it('reducer→presentation→submission→settlement→reducer：valid 全成功后 stale 仍保留并保持多选', () => {
    let state = homeViewStateReducer(HOME_VIEW_INITIAL_STATE, { type: 'enter-multiselect' } as never)
    state = homeViewStateReducer(state, { type: 'toggle-select', id: '任务|valid.md' } as never)
    state = homeViewStateReducer(state, { type: 'toggle-select', id: '任务|stale.md' } as never)
    const model = boardWith([['任务', 'valid.md', 'todo']])
    const presentation = buildHomeViewPresentation(model, state)
    expect(presentation.selectedIds).toEqual(['任务|valid.md'])
    expect(presentation.staleSelection.map(s => s.id)).toEqual(['任务|stale.md'])
    const submission = buildHomeBatchSubmission(presentation.selectedIds, 'complete', model)
    expect(submission?.items).toEqual([{ dir: '任务', file: 'valid.md' }])
    const settlement = settleBatchResponse(
      state,
      { ok: true, done: [{ dir: '任务', file: 'valid.md' }], failed: [], summary: { ok: 1, fail: 0 } },
      presentation.selectedIds,
    )
    expect(settlement.settledCleanly).toBe(false)
    expect(settlement.keepOpen).toBe(true)
    expect(settlement.selectedIds).toEqual(['任务|stale.md'])
    expect(settlement.overallError).toContain('明确清理')
    state = homeViewStateReducer(state, {
      type: 'batch-settle',
      multiSelectOpen: settlement.keepOpen,
      selectedIds: settlement.selectedIds,
    } as never)
    expect(state.multiSelectOpen).toBe(true)
    expect(state.selectedIds).toEqual(['任务|stale.md'])
  })

  it('reducer→presentation：刷新后原选中变 missing，staleSelection 列出原因，可提交集不含失效项', () => {
    // 第一次 board：选中 a.md + c.md
    const stateA = homeViewStateReducer(HOME_VIEW_INITIAL_STATE, { type: 'enter-multiselect' } as never)
    const stateB = homeViewStateReducer(stateA, { type: 'toggle-select', id: '任务|a.md' } as never)
    const stateC = homeViewStateReducer(stateB, { type: 'toggle-select', id: '待验证|c.md' } as never)
    // board refresh：a.md 已归档（done）、c.md 已不存在
    const modelAfterRefresh = boardWith([['任务', 'b.md', 'todo'], ['待验证', 'd2.md', 'pending']])
    const p = buildHomeViewPresentation(modelAfterRefresh, stateC)
    expect(p.multiSelectOpen).toBe(true)
    // 可提交集只保留仍可行动的条目；两个失效项都不在其中
    expect(p.selectedIds).toEqual([])
    expect(p.canSubmitBatch).toBe(false)
    // 但失效原因被逐项保留到反馈层
    expect(p.staleSelection).toHaveLength(2)
    const reasons = new Map(p.staleSelection.map(s => [s.id, s.reason]))
    expect(reasons.has('任务|a.md')).toBe(true)
    expect(reasons.has('待验证|c.md')).toBe(true)
    expect(reasons.get('任务|a.md')).toBe('条目已不在当前事实源（可能已在其他会话处理）')
    expect(reasons.get('待验证|c.md')).toBe('条目已不在当前事实源（可能已在其他会话处理）')
  })

  it('刷新后原选中变 archived（done provenance，同 identity）→ stale 原因标注已归档', () => {
    const stateA = homeViewStateReducer(HOME_VIEW_INITIAL_STATE, { type: 'enter-multiselect' } as never)
    const stateB = homeViewStateReducer(stateA, { type: 'toggle-select', id: '任务|a.md' } as never)
    // 刷新后该 identity 仍存在，但已落入 done provenance（side='done'，仅对归档分区构建的模型场景）
    const modelAfterRefresh = buildHomeModel({
      today: '2026-08-30',
      sections: [
        { key: 'done', files: [card('任务', 'a.md', 'completed')] },
      ],
    } as never)
    const p = buildHomeViewPresentation(modelAfterRefresh, stateB)
    expect(p.selectedIds).toEqual([])
    expect(p.staleSelection).toEqual([{ id: '任务|a.md', reason: '已归档，只读不可批处理' }])
  })

  it('刷新后原选中变 unknown（contractErrors）→ stale 原因标注状态未知', () => {
    const stateA = homeViewStateReducer(HOME_VIEW_INITIAL_STATE, { type: 'enter-multiselect' } as never)
    const stateB = homeViewStateReducer(stateA, { type: 'toggle-select', id: '任务|a.md' } as never)
    const modelAfterRefresh = buildHomeModel({
      today: '2026-08-30',
      sections: [
        { key: '任务', files: [card('任务', 'a.md', 'weird-status-xyz')] },
      ],
    } as never)
    const p = buildHomeViewPresentation(modelAfterRefresh, stateB)
    expect(p.selectedIds).toEqual([])
    expect(p.staleSelection).toEqual([{ id: '任务|a.md', reason: '状态未知，不可批处理' }])
  })

  it('失效项绝不进入 submission（buildHomeBatchSubmission 不含 stale id）', () => {
    const model = boardWith([['任务', 'b.md', 'todo']])
    // 已失效的 a.md 不在模型 active 集 → submission 对全部失效返回 null
    expect(buildHomeBatchSubmission(['任务|a.md'], 'complete', model)).toBeNull()
    // 混合：一个可提交 + 一个失效 → null（fail closed，不 transport）
    expect(buildHomeBatchSubmission(['任务|b.md', '任务|a.md'], 'complete', model)).toBeNull()
  })
})

// ── A1.2 + A3：done / failed / summary 全必需字段 ─────────────────────────
describe('047-A1.2/A3 /batch 响应 done、failed、summary 全为必需字段', () => {
  const ids = ['任务|a.md']
  const enter = () => homeViewStateReducer(HOME_VIEW_INITIAL_STATE, { type: 'enter-multiselect' } as never)

  it('缺 done 数组（failed+summary 完整）→ protocol error，保留全部选择', () => {
    const s = settleBatchResponse(enter(), { ok: false, failed: [{ dir: '任务', file: 'a.md', error: 'e' }], summary: { ok: 0, fail: 1 } } as never, ids)
    expect(s.settledCleanly).toBe(false)
    expect(s.keepOpen).toBe(true)
    expect(s.selectedIds).toEqual(ids)
    expect(s.removedCount).toBe(0)
    expect(s.overallError).not.toBeNull()
  })

  it('缺 failed 数组（done+summary 完整）→ protocol error，不推断成功', () => {
    const s = settleBatchResponse(enter(), { ok: true, done: [{ dir: '任务', file: 'a.md' }], summary: { ok: 1, fail: 0 } } as never, ids)
    expect(s.settledCleanly).toBe(false)
    expect(s.keepOpen).toBe(true)
    expect(s.selectedIds).toEqual(ids)
    expect(s.removedCount).toBe(0)
    expect(s.overallError).not.toBeNull()
  })

  it('done 为 null（failed+summary 完整）→ protocol error', () => {
    const s = settleBatchResponse(enter(), { ok: false, done: null, failed: [{ dir: '任务', file: 'a.md', error: 'e' }], summary: { ok: 0, fail: 1 } } as never, ids)
    expect(s.settledCleanly).toBe(false)
    expect(s.selectedIds).toEqual(ids)
  })

  it('failed 为 null（done+summary 完整）→ protocol error', () => {
    const s = settleBatchResponse(enter(), { ok: true, done: [{ dir: '任务', file: 'a.md' }], failed: null, summary: { ok: 1, fail: 0 } } as never, ids)
    expect(s.settledCleanly).toBe(false)
    expect(s.selectedIds).toEqual(ids)
  })

  it('缺 summary 但 done/failed 完整 → protocol error（既有门禁保持）', () => {
    const s = settleBatchResponse(enter(), { ok: true, done: [{ dir: '任务', file: 'a.md' }], failed: [] } as never, ids)
    expect(s.settledCleanly).toBe(false)
    expect(s.selectedIds).toEqual(ids)
  })

  it('三者齐全且合法 → 全成功 clean settle（既有门禁保持）', () => {
    const s = settleBatchResponse(enter(), { ok: true, done: [{ dir: '任务', file: 'a.md' }], failed: [], summary: { ok: 1, fail: 0 } }, ids)
    expect(s.settledCleanly).toBe(true)
    expect(s.removedCount).toBe(1)
    expect(s.selectedIds).toEqual([])
  })

  it('ok=false + error 但缺 mandatory arrays/summary 仍是 protocol error，不走业务旁路', () => {
    const s = settleBatchResponse(enter(), { ok: false, error: 'items required' }, ids)
    expect(s.settledCleanly).toBe(false)
    expect(s.selectedIds).toEqual(ids)
    expect(s.removedCount).toBe(0)
    expect(s.overallError).toContain('协议错误')
  })
})

// ── A3：complete 四态 eligibility（done+success 兼容 / completed 幂等）───
describe('047-A3 computeBatchActionEligibility complete 四态', () => {
  function erCard(dir: string, file: string, status: string, er?: string): WbCard {
    const c = card(dir, file, status)
    c.execution_result = er ?? null
    return c
  }
  it('done+success / DONE+success / completed 可 complete；done+非success 不可', () => {
    const m = buildHomeModel({
      today: '2026-08-30',
      sections: [
        { key: '任务', files: [
          erCard('任务', 'd.md', 'done', 'success'),
          erCard('任务', 'c.md', 'completed'),
          erCard('任务', 'dc.md', 'DONE', 'success'),
          erCard('任务', 'df.md', 'done', 'failure'),
        ] },
      ],
    } as never)
    const r = computeBatchActionEligibility(m, ['任务|d.md', '任务|c.md', '任务|dc.md', '任务|df.md'], 'complete')
    expect(r.eligible).toEqual(['任务|d.md', '任务|c.md', '任务|dc.md'])
    expect(r.ineligible.map(i => i.id)).toEqual(['任务|df.md'])
  })
})
