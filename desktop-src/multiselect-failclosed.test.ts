/**
 * WB-S1-044 / FR-020 fail-closed 修正（source/test only）
 *
 * 043 被 CoderX CHANGES_REQUIRED 的三个 blocker 的 RED→GREEN：
 *  Blocker 1 (A1)：归档 done/trash provenance 被加入 selectable/summission。
 *  Blocker 2 (A3)：runBatch 遇 HTTP 成功响应一律 batch-settled 清空——部分/全部失败
 *                  会退出多选并销毁失败选择；只显示数量不显示逐项原因。
 *  Blocker 3 (A2)：四动作对所有选择全量开放，提交只查 ID 存在，无状态迁移资格。
 *
 * 先写 RED（当前 043 工作树按本文件断言应失败），再实现 home-model/home.tsx 修正，
 * 再跑 GREEN。资格词表唯一来源：dashboard/contract.py 迁移表 + plugin_api.py /batch
 * 单条 handler（dashboard/test_batch_eligibility.py 镜像断言）。
 */
import { describe, expect, it } from 'vitest'

import { type WbCard } from './types'
import {
  HOME_VIEW_INITIAL_STATE,
  BatchGate,
  buildHomeBatchSubmission,
  buildHomeModel,
  buildHomeViewPresentation,
  computeBatchActionEligibility,
  guardedSubmit,
  homeViewStateReducer,
  settleBatchResponse,
  type HomeBatchAction,
} from './home-model'

// ── 夹具：真实分区语义（任务/待验证 活动；done 归档；trash 跳过）─────────────
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

function fixtureBoard() {
  return {
    today: '2026-08-30',
    root: '/vault',
    sections: [
      { key: '任务', files: [card('任务', 'a.md', 'todo'), card('任务', 'b.md', 'in_progress')] },
      { key: '待验证', files: [card('待验证', 'c.md', 'pending'), card('待验证', 'unknown.md', 'weird-status-xyz')] },
      { key: 'done', files: [card('done', 'd.md', 'done')] },
      { key: 'trash', files: [card('trash', 't.md', 'abandoned')] },
    ],
  }
}

const model = () => buildHomeModel(fixtureBoard() as never)
const enter = () => homeViewStateReducer(HOME_VIEW_INITIAL_STATE, { type: 'enter-multiselect' } as never)
const select = (ids: string[]) => homeViewStateReducer(enter(), { type: 'select-all-visible', ids } as never)

// ── A1：归档只读资格 ─────────────────────────────────────────────────────
describe('A1 archive read-only eligibility (RED before 044 fix)', () => {
  it('done provenance 卡即使投影进 Home recent 也不得进入 multiSelectVisibleIds', () => {
    const p = buildHomeViewPresentation(model(), enter())
    expect(p.multiSelectVisibleIds).not.toContain('done|d.md')
    expect(p.multiSelectVisibleIds).not.toContain('trash|t.md')
  })

  it('done provenance 卡通过 toggle/select-all 均不可入选（计数不增）', () => {
    const s1 = homeViewStateReducer(enter(), { type: 'toggle-select', id: 'done|d.md' } as never)
    expect(buildHomeViewPresentation(model(), s1).multiSelectCount).toBe(0)
    const vis = buildHomeViewPresentation(model(), enter()).multiSelectVisibleIds
    const s2 = homeViewStateReducer(enter(), { type: 'select-all-visible', ids: vis } as never)
    expect(buildHomeViewPresentation(model(), s2).multiSelectCount).toBe(vis.length)
    expect(buildHomeViewPresentation(model(), s2).selectedIds).not.toContain('done|d.md')
  })

  it('Home recent 中 archived done 行保持可见但给出诚实只读提示（不静默隐藏）', () => {
    const p = buildHomeViewPresentation(model(), enter())
    expect(p.multiSelectReadonlyCount).toBe(1) // done|d.md 仍可见但只读
  })

  it('buildHomeBatchSubmission：archive/trash/done provenance 永不入选；混合含归档 → 整个提交 fail closed 返回 null（WB-S1-045 A3）', () => {
    expect(buildHomeBatchSubmission(['done|d.md'], 'complete', model())).toBeNull()
    expect(buildHomeBatchSubmission(['trash|t.md'], 'trash', model())).toBeNull()
    expect(buildHomeBatchSubmission(['任务|a.md', 'done|d.md', 'trash|t.md'], 'complete', model())).toBeNull()
    expect(buildHomeBatchSubmission(['任务|a.md'], 'complete', model())?.items).toEqual([{ dir: '任务', file: 'a.md' }])
  })

  it('submission 重复 identity：fail-closed，返回 null 不 transport（WB-S1-046 收紧）', () => {
    const dup = buildHomeBatchSubmission(['任务|a.md', '任务|a.md'], 'complete', model())
    expect(dup).toBeNull()
  })
})

// ── A2：动作/状态迁移资格（唯一词表派生自 contract.py + /batch handler）─────
describe('A2 action/status transition eligibility (RED before 044 fix)', () => {
  const both = ['任务|a.md', '待验证|c.md']

  it('complete 仅 todo/in_progress；对 pending 给出 ineligible + 原因', () => {
    const r = computeBatchActionEligibility(model(), both, 'complete')
    expect(r.eligible).toEqual(['任务|a.md'])
    expect(r.ineligible).toHaveLength(1)
    expect(r.ineligible[0].id).toBe('待验证|c.md')
    expect(r.ineligible[0].reason).toContain('pending')
  })

  it('resolve/to-task 仅收件箱分区目录；任务分区卡 ineligible + 目录原因', () => {
    const r = computeBatchActionEligibility(model(), both, 'resolve')
    expect(r.eligible).toEqual(['待验证|c.md'])
    expect(r.ineligible[0].id).toBe('任务|a.md')
    const t = computeBatchActionEligibility(model(), both, 'to-task')
    expect(t.eligible).toEqual(['待验证|c.md'])
  })

  it('unknown / archive / 已从事实源移除的 identity 一律 fail closed', () => {
    const r = computeBatchActionEligibility(model(), ['待验证|unknown.md', 'done|d.md', '任务|NOEXIST.md'], 'trash')
    expect(r.eligible).toHaveLength(0)
    expect(r.ineligible.map(i => i.id)).toEqual(['待验证|unknown.md', 'done|d.md', '任务|NOEXIST.md'])
    for (const i of r.ineligible) expect(i.reason.length).toBeGreaterThan(0)
  })

  it('trash 对全部 active 卡可用（archive 已被 A1 排除）', () => {
    const r = computeBatchActionEligibility(model(), both, 'trash')
    expect(r.eligible).toEqual(both)
    expect(r.ineligible).toHaveLength(0)
  })
})

// ── A3：响应结算 seam ────────────────────────────────────────────────────
describe('A3 response settlement (RED before 044 fix)', () => {
  const ids = ['任务|a.md', '任务|b.md']

  it('全成功：invalidate 语义 → 退出多选并清空', () => {
    const s = settleBatchResponse(enter(), { ok: true, done: [{ dir: '任务', file: 'a.md' }, { dir: '任务', file: 'b.md' }], failed: [], summary: { ok: 2, fail: 0 } }, ids)
    expect(s.settledCleanly).toBe(true)
    expect(s.keepOpen).toBe(false)
    expect(s.selectedIds).toEqual([])
    expect(s.removedCount).toBe(2)
  })

  it('部分成功：保持多选，只保留 failed[] 对应 identity，逐项带 file/reason', () => {
    const s = settleBatchResponse(
      enter(),
      { ok: true, done: [{ dir: '任务', file: 'a.md' }], failed: [{ dir: '待验证', file: 'c.md', error: 'bad dir: 待验证 is not a reviewable dir' }], summary: { ok: 1, fail: 1 } },
      ['任务|a.md', '待验证|c.md'],
    )
    expect(s.settledCleanly).toBe(false)
    expect(s.keepOpen).toBe(true)
    expect(s.selectedIds).toEqual(['待验证|c.md'])
    expect(s.removedCount).toBe(1)
    expect(s.failedDetail).toHaveLength(1)
    expect(s.failedDetail[0].file).toBe('c.md')
    expect(s.failedDetail[0].reason).toContain('bad dir')
  })

  it('全部失败：不清空不退出；只有后端明确成功的条目才移除', () => {
    const s = settleBatchResponse(
      enter(),
      { ok: true, done: [], failed: [{ dir: '任务', file: 'a.md', error: 'x' }, { dir: '任务', file: 'b.md', error: 'y' }], summary: { ok: 0, fail: 2 } },
      ids,
    )
    expect(s.keepOpen).toBe(true)
    expect(s.removedCount).toBe(0)
    expect(s.selectedIds).toEqual(ids)
    expect(s.failedDetail.map(f => f.id)).toEqual(ids)
  })

  it('字段完整 ok=false（总体错误）：原样保留可行动错误，不伪造成功', () => {
    const s = settleBatchResponse(enter(), { ok: false, done: [], failed: [], summary: { ok: 0, fail: 0 }, error: 'bad action' }, ids)
    expect(s.keepOpen).toBe(true)
    expect(s.removedCount).toBe(0)
    expect(s.selectedIds).toEqual(ids)
    expect(s.overallError).toBe('bad action')
  })

  it('schema-less ok=false 仍是 protocol error，不恢复旧 bypass', () => {
    const s = settleBatchResponse(enter(), { ok: false, error: 'bad action' }, ids)
    expect(s.keepOpen).toBe(true)
    expect(s.removedCount).toBe(0)
    expect(s.selectedIds).toEqual(ids)
    expect(s.overallError).toContain('协议错误')
  })

  it('summary 缺失/畸形：不退出不清空，标记 malformed 可行动', () => {
    const s = settleBatchResponse(enter(), { ok: true, done: [], failed: [], summary: { ok: '2', fail: '0' } } as never, ids)
    expect(s.keepOpen).toBe(true)
    expect(s.selectedIds).toEqual(ids)
    expect(s.overallError).not.toBeNull()
  })

  it('transport exception：选择不变，总体错误可行动', () => {
    const s = settleBatchResponse(enter(), { transportError: 'network down' }, ids)
    expect(s.keepOpen).toBe(true)
    expect(s.selectedIds).toEqual(ids)
    expect(s.overallError).toBe('network down')
  })

  it('reducer batch-settle 应用结算结果（部分失败后保持多选与 failed 集合）', () => {
    const next = homeViewStateReducer(select(ids), { type: 'batch-settle', multiSelectOpen: true, selectedIds: ['待验证|c.md'] } as never)
    expect(next.multiSelectOpen).toBe(true)
    expect(next.selectedIds).toEqual(['待验证|c.md'])
  })
})

// ── A3：busy/concurrency guard（第二次提交不调用 transport）──────────────
describe('A3 batch busy gate (RED before 044 fix)', () => {
  it('BatchGate：held 时 tryAcquire 返回 false，release 后恢复', () => {
    const gate = new BatchGate()
    expect(gate.tryAcquire()).toBe(true)
    expect(gate.tryAcquire()).toBe(false)
    gate.release()
    expect(gate.tryAcquire()).toBe(true)
  })

  it('guardedSubmit：gate 被持有时代理不调用 transport', async () => {
    let calls = 0
    const g = new BatchGate()
    g.tryAcquire()
    const result = await guardedSubmit(g, async () => { calls += 1; return 'ok' })
    expect(result).toBeNull()
    expect(calls).toBe(0)
    g.release()
    const r2 = await guardedSubmit(g, async () => { calls += 1; return 'ok' })
    expect(r2).toBe('ok')
    expect(calls).toBe(1)
  })
})