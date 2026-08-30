/**
 * WB-S1-045 / FR-020 A1 — 可复现 RED：settleBatchResponse 身份完整性 + 资格/提交边界。
 *
 * 当前实现（044 后 home-model.ts L585-625 / L514-549 / L477-501）对以下反例
 * 全部或部分失败；本文件先于修复落地，断言即契约：
 *  合法响应 = done/failed 每项 identity 非空、各自唯一、均属于 submitted、
 *  两集合不相交、并集与去重后 submitted 完全相等、summary 与数组精确一致、
 *  顶层 ok 与后端语义一致（ok = (failed 空) 或 (done 非空)）。
 * 任何缺项/重复/外来/交集/畸形/计数矛盾 → protocol error：保留全部 submitted
 * identities、不推断成功、不 invalidate、保持多选、给可行动 overallError。
 * 资格：in_progress 仅 execution_result 精确等于 success 才可 complete。
 * 提交边界：buildHomeBatchSubmission 必须再次按同一 policy 校验全部 selected
 * 对本 action 合法，不合法/unknown/归档一律返回 null（不调用 transport）。
 */
import { describe, expect, it } from 'vitest'

import { type WbCard } from './types'
import {
  HOME_VIEW_INITIAL_STATE,
  buildHomeBatchSubmission,
  buildHomeModel,
  computeBatchActionEligibility,
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
      { key: '任务', files: [card('任务', 'a.md', 'todo'), card('任务', 'b.md', 'in_progress', 'success'), card('任务', 'w.md', 'in_progress', 'waiting'), card('任务', 'e.md', 'in_progress', '')] },
      { key: '待验证', files: [card('待验证', 'c.md', 'pending'), card('待验证', 'd2.md', 'todo')] },
    ],
  }
}

const model = () => buildHomeModel(fixtureBoard() as never)
const idsAB = ['任务|a.md', '任务|b.md']
const idsABC = ['任务|a.md', '任务|b.md', '待验证|c.md']
const enter = () => homeViewStateReducer(HOME_VIEW_INITIAL_STATE, { type: 'enter-multiselect' } as never)

describe('A1-RED-1 缺项分割（submitted [a,b] 只回 done [a]）', () => {
  it('缺失 identity 不得被静默当成功：protocol error，保留全部 submitted', () => {
    const s = settleBatchResponse(enter(), { ok: true, done: [{ dir: '任务', file: 'a.md' }], failed: [], summary: { ok: 1, fail: 0 } }, idsAB)
    expect(s.settledCleanly).toBe(false)
    expect(s.keepOpen).toBe(true)
    expect(s.selectedIds).toEqual(idsAB)
    expect(s.removedCount).toBe(0)
    expect(s.overallError).not.toBeNull()
  })
})

describe('A1-RED-2 空 identity', () => {
  it('done 含缺 dir/file 的空 identity → protocol error（不得计为成功并清空）', () => {
    const s = settleBatchResponse(enter(), { ok: true, done: [{ dir: '任务', file: 'a.md' }, { file: 'b.md' }], failed: [], summary: { ok: 2, fail: 0 } }, idsAB)
    expect(s.settledCleanly).toBe(false)
    expect(s.keepOpen).toBe(true)
    expect(s.selectedIds).toEqual(idsAB)
    expect(s.overallError).not.toBeNull()
  })
  it('failed 含空 identity → protocol error，整体可行动，不静默丢弃', () => {
    const s = settleBatchResponse(enter(), { ok: false, done: [], failed: [{ dir: '任务', file: 'a.md', error: 'x' }, { error: 'no identity' }], summary: { ok: 0, fail: 2 } }, idsAB)
    expect(s.keepOpen).toBe(true)
    expect(s.overallError).not.toBeNull()
    expect(s.selectedIds).toEqual(idsAB)
  })
})

describe('A1-RED-3 重复 / 外来 / 交集 identity', () => {
  it('done 重复 identity、外来 identity 未属 submitted → protocol error', () => {
    const s = settleBatchResponse(enter(), { ok: true, done: [{ dir: '任务', file: 'a.md' }, { dir: '任务', file: 'a.md' }, { dir: '外来', file: 'x.md' }], failed: [], summary: { ok: 3, fail: 0 } }, idsAB)
    expect(s.settledCleanly).toBe(false)
    expect(s.keepOpen).toBe(true)
    expect(s.selectedIds).toEqual(idsAB)
    expect(s.overallError).not.toBeNull()
  })
  it('done/failed 交集（同 identity 两边同时出现）→ protocol error', () => {
    const s = settleBatchResponse(enter(), { ok: true, done: [{ dir: '任务', file: 'a.md' }], failed: [{ dir: '任务', file: 'a.md', error: 'dup' }], summary: { ok: 1, fail: 1 } }, idsAB)
    expect(s.settledCleanly).toBe(false)
    expect(s.keepOpen).toBe(true)
    expect(s.overallError).not.toBeNull()
    expect(s.selectedIds).not.toEqual(['任务|a.md']) // 绝不能只保留交集失败项
  })
})

describe('A1-RED-4 done∪failed ≠ submitted', () => {
  it('外来 failed 替换缺失项（{a}∪{x}≠{a,b}）→ protocol error，不得把外来 x 当失败保留', () => {
    const s = settleBatchResponse(enter(), { ok: true, done: [{ dir: '任务', file: 'a.md' }], failed: [{ dir: '外来', file: 'x.md', error: 'foreign' }], summary: { ok: 1, fail: 1 } }, idsAB)
    expect(s.settledCleanly).toBe(false)
    expect(s.keepOpen).toBe(true)
    expect(s.selectedIds).toEqual(idsAB)
    expect(s.overallError).not.toBeNull()
  })
})

describe('A1-RED-5 summary 与数组计数不一致', () => {
  it('done=[a] 但 summary.ok=2 → 计数矛盾 → protocol error', () => {
    const s = settleBatchResponse(enter(), { ok: true, done: [{ dir: '任务', file: 'a.md' }], failed: [], summary: { ok: 2, fail: 0 } }, idsAB)
    expect(s.settledCleanly).toBe(false)
    expect(s.keepOpen).toBe(true)
    expect(s.overallError).not.toBeNull()
    expect(s.selectedIds).toEqual(idsAB)
  })
})

describe('A1-RED-6 有效 failed + malformed failed 不得静默丢另一条', () => {
  it('一条有效 + 一条畸形 failed → protocol error，保留全部 submitted', () => {
    const s = settleBatchResponse(enter(), { ok: false, done: [], failed: [{ dir: '任务', file: 'a.md', error: 'real' }, { error: 'malformed' }], summary: { ok: 0, fail: 2 } }, idsAB)
    expect(s.keepOpen).toBe(true)
    expect(s.settledCleanly).toBe(false)
    expect(s.overallError).not.toBeNull()
    expect(s.selectedIds).toEqual(idsAB)
    expect(s.failedDetail.length).toBe(2)
  })
})

describe('A1-RED-7 全失败 ok=false 带完整数组 + ok 语义', () => {
  it('ok=false + 完整 failed 数组：全部失败身份+原因必须完整保留（044 已覆盖的正向守门）', () => {
    const s = settleBatchResponse(enter(), { ok: false, done: [], failed: [{ dir: '任务', file: 'a.md', error: 'ea' }, { dir: '任务', file: 'b.md', error: 'eb' }], summary: { ok: 0, fail: 2 } }, idsAB)
    expect(s.keepOpen).toBe(true)
    expect(s.removedCount).toBe(0)
    expect(s.selectedIds).toEqual(idsAB)
    expect(s.failedDetail.map(f => f.id)).toEqual(idsAB)
    expect(s.failedDetail.map(f => f.reason)).toEqual(['ea', 'eb'])
  })
  it('ok=false 却带 done 数组（与后端语义矛盾）→ protocol error，不 infer 成功', () => {
    const s = settleBatchResponse(enter(), { ok: false, done: [{ dir: '任务', file: 'a.md' }], failed: [{ dir: '任务', file: 'b.md', error: 'x' }], summary: { ok: 1, fail: 1 } }, idsAB)
    expect(s.settledCleanly).toBe(false)
    expect(s.keepOpen).toBe(true)
    expect(s.selectedIds).toEqual(idsAB)
    expect(s.removedCount).toBe(0)
    expect(s.overallError).not.toBeNull()
  })
})

describe('A1-RED-8 in_progress 完成资格：仅 exact success', () => {
  it('in_progress + execution_result=success 可 complete', () => {
    const r = computeBatchActionEligibility(model(), ['任务|b.md'], 'complete')
    expect(r.eligible).toEqual(['任务|b.md'])
    expect(r.ineligible).toHaveLength(0)
  })
  it('in_progress + execution_result=waiting → ineligible（fail closed）', () => {
    const r = computeBatchActionEligibility(model(), ['任务|w.md'], 'complete')
    expect(r.eligible).toEqual([])
    expect(r.ineligible.map(i => i.id)).toEqual(['任务|w.md'])
  })
  it('in_progress + execution_result 空 → ineligible（fail closed）', () => {
    const r = computeBatchActionEligibility(model(), ['任务|e.md'], 'complete')
    expect(r.eligible).toEqual([])
    expect(r.ineligible.map(i => i.id)).toEqual(['任务|e.md'])
  })
  it('in_progress + execution_result=failure → ineligible（既有一致）', () => {
    const r = computeBatchActionEligibility(model(), ['任务|a.md'], 'complete') // todo
    expect(r.eligible).toEqual(['任务|a.md'])
    const board2 = buildHomeModel({ today: '2026-08-30', sections: [{ key: '任务', files: [card('任务', 'f.md', 'in_progress', 'failure')] }] } as never)
    const r2 = computeBatchActionEligibility(board2, ['任务|f.md'], 'complete')
    expect(r2.eligible).toEqual([])
  })
})

describe('A1-RED-9 提交边界：stale/direct 混合不合法选择不得调用 transport', () => {
  it('对 complete 提交含 pending 的混合选择 → 返回 null（不构造 transport 载荷）', () => {
    const sub = buildHomeBatchSubmission(idsABC, 'complete', model())
    expect(sub).toBeNull()
  })
  it('对 resolve 提交含任务分区卡的混合选择 → 返回 null', () => {
    const sub = buildHomeBatchSubmission(idsABC, 'resolve', model())
    expect(sub).toBeNull()
  })
  it('单个不合法 selection（in_progress waiting）也 fail closed → null', () => {
    const sub = buildHomeBatchSubmission(['任务|w.md'], 'complete', model())
    expect(sub).toBeNull()
  })
  it('全部合法才放行：complete 仅 todo+success 两卡 → 非 null 且 items 精确', () => {
    const sub = buildHomeBatchSubmission(['任务|a.md', '任务|b.md'], 'complete', model())
    expect(sub?.items).toEqual([{ dir: '任务', file: 'a.md' }, { dir: '任务', file: 'b.md' }])
  })
})