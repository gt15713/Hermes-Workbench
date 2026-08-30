/**
 * WB-S1-043 / FR-020 多选批处理等价（source/test only）
 *
 * RED→GREEN 纪律：先以「生产 seam」（buildHomeModel / buildHomeViewPresentation /
 * homeViewStateReducer）证明当前 Home 主视图/完整列表/归档界面均无多选能力；
 * 实现后同一 seam 输出 multiSelectOpen/selectedIds/canSubmitBatch 与
 * buildHomeBatchSubmission，全部 GREEN。
 *
 * 范围边界（最小、可回退）：
 * - 默认界面每卡一个主动作，多选控件仅用户显式进入后出现；
 * - 选中 identity = `${dir}|${file}`，跨 preview/back/archive 视图切换稳定；
 * - 视图/筛选变化规则：selection 是 identity 集合，与可见性解耦；
 *   「全选当前可见」替换选中集合；显式退出/提交成功清空；
 * - unknown/fail-closed 卡（contractErrors）永不可选、永不被纳入 batch payload；
 * - 归档/回收站保持只读（S1-041 边界）：archive 模式下不显示多选控件，
 *   不新增 delete/restore；batch 仅复用既有 /batch 四种允许操作；
 * - 并发/重复提交由 UI busy 门 fail-closed（见 home.tsx 接线）。
 */
import { describe, expect, it } from 'vitest'

import * as homeModel from './home-model'
import { type WbCard } from './types'

import {
  HOME_VIEW_INITIAL_STATE,
  buildHomeModel,
  buildHomeViewPresentation,
  homeViewStateReducer,
} from './home-model'

// ── 夹具 ─────────────────────────────────────────────────────────────
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
      { key: '收件箱', files: [card('收件箱', 'c.md', 'pending'), card('收件箱', 'unknown.md', 'weird-status-xyz')] },
      { key: 'done', files: [card('done', 'd.md', 'done')] },
      { key: 'trash', files: [card('trash', 't.md', 'abandoned')] },
    ],
  }
}

const init = HOME_VIEW_INITIAL_STATE
const seam = (state = init) => {
  const model = buildHomeModel(fixtureBoard() as never)
  return { model, p: buildHomeViewPresentation(model, state) }
}

// ── RED 捕获（历史证据，实现前 2026-08-30 06:36 实跑：9 failed | 4 passed）──
// 实现前本文件完整含 4 条 RED 断言（multiSelectOpen/multiSelectCount/
// canSubmitBatch/multiSelectVisibleIds 均 toBeUndefined + RED 证明 describe），
// 实现后 mirror 翻转失败，按 RED→GREEN 纪律移除；真实捕获记录在
// work/evidence/workbench/WB-S1-043-FR020-multiselect-red-green-20260830.md。

// ── GREEN 目标（实现后必须全绿）──────────────────────────────────────
describe('FR-020 GREEN —— 多选/批处理等价（生产 seam 输出）', () => {
  it('enter-multiselect 打开并展示已选数量 0', () => {
    const next = homeViewStateReducer(init, { type: 'enter-multiselect' } as never)
    const { p } = seam(next)
    expect(p.multiSelectOpen).toBe(true)
    expect(p.canSubmitBatch).toBe(false)
    expect(p.multiSelectCount).toBe(0)
  })

  it('toggle-select 增减稳定 identity（dir|file），计数随动', () => {
    const a = homeViewStateReducer(init, { type: 'enter-multiselect' } as never)
    const b = homeViewStateReducer(a, { type: 'toggle-select', id: '任务|a.md' } as never)
    const c = homeViewStateReducer(b, { type: 'toggle-select', id: '任务|b.md' } as never)
    const d = homeViewStateReducer(c, { type: 'toggle-select', id: '任务|a.md' } as never)
    expect(seam(b).p.multiSelectCount).toBe(1)
    expect(seam(c).p.multiSelectCount).toBe(2)
    expect(seam(d).p.multiSelectCount).toBe(1)
    expect(seam(d).p.selectedIds).toEqual(['任务|b.md'])
  })

  it('全选当前可见替换选中集合（视图规则：可见集替换，不追加）', () => {
    const a = homeViewStateReducer(init, { type: 'enter-multiselect' } as never)
    const t = homeViewStateReducer(a, { type: 'toggle-select', id: '任务|a.md' } as never)
    const vis = seam(t).p.multiSelectVisibleIds
    expect(vis).toContain('任务|a.md')
    expect(vis).toContain('收件箱|c.md')
    const s = homeViewStateReducer(t, { type: 'select-all-visible', ids: vis } as never)
    expect(seam(s).p.multiSelectCount).toBe(vis.length)
  })

  it('unknown/fail-closed 卡永不可选：visible/selectable 均不含未知状态卡', () => {
    const a = homeViewStateReducer(init, { type: 'enter-multiselect' } as never)
    const { p } = seam(a)
    expect(p.multiSelectVisibleIds).not.toContain('收件箱|unknown.md')
    // 未知卡即使被塞进 state，也不计入计数、不进入可选集（fail-closed 剪枝）
    const bad = homeViewStateReducer(a, { type: 'toggle-select', id: '收件箱|unknown.md' } as never)
    const { p: p2 } = seam(bad)
    expect(p2.multiSelectCount).toBe(0)
    expect(p2.canSubmitBatch).toBe(false)
  })

  it('preview/back 不串项：home→expanded→back 选中集合保持', () => {
    const a = homeViewStateReducer(init, { type: 'enter-multiselect' } as never)
    const s1 = homeViewStateReducer(a, { type: 'toggle-select', id: '任务|a.md' } as never)
    const s2 = homeViewStateReducer(s1, { type: 'show-all', regionId: 'today' } as never)
    const s3 = homeViewStateReducer(s2, { type: 'back' } as never)
    expect(seam(s2).p.multiSelectCount).toBe(1)
    expect(seam(s3).p.multiSelectCount).toBe(1)
  })

  it('归档只读边界：archive 模式下控件关闭、选中保留、返回后恢复', () => {
    const a = homeViewStateReducer(init, { type: 'enter-multiselect' } as never)
    const s1 = homeViewStateReducer(a, { type: 'toggle-select', id: '任务|a.md' } as never)
    const s2 = homeViewStateReducer(s1, { type: 'open-archive' } as never)
    expect(seam(s2).p.multiSelectOpen).toBe(false) // 归档只读，无多选控件
    const s3 = homeViewStateReducer(s2, { type: 'back' } as never)
    expect(seam(s3).p.multiSelectOpen).toBe(true)
    expect(seam(s3).p.multiSelectCount).toBe(1) // 未串项
  })

  it('显式退出 / 提交成功清空选中', () => {
    const a = homeViewStateReducer(init, { type: 'enter-multiselect' } as never)
    const s1 = homeViewStateReducer(a, { type: 'toggle-select', id: '任务|a.md' } as never)
    const e1 = homeViewStateReducer(s1, { type: 'exit-multiselect' } as never)
    expect(seam(e1).p.multiSelectOpen).toBe(false)
    const s2 = homeViewStateReducer(a, { type: 'toggle-select', id: '任务|a.md' } as never)
    const e2 = homeViewStateReducer(s2, { type: 'batch-settled' } as never)
    expect(seam(e2).p.multiSelectOpen).toBe(false)
    expect(seam(e2).p.multiSelectCount).toBe(0)
  })

  it('buildHomeBatchSubmission：仅复用既有 /batch 四种动作，禁止 delete；全合法放行', () => {
    const b = homeModel.buildHomeBatchSubmission
    const res = b(['任务|a.md'], 'complete', seam().model)
    expect(res).not.toBeNull()
    if (res) {
      expect(res.action).toBe('complete')
      expect(res.items).toEqual([{ dir: '任务', file: 'a.md' }])
    }
  })

  it('buildHomeBatchSubmission：任一不合法/unknown identity（含混合）→ 整个提交 fail closed 返回 null（WB-S1-045 A3）', () => {
    const b = homeModel.buildHomeBatchSubmission
    expect(b(['任务|a.md', '任务|NOEXIST.md'], 'complete', seam().model)).toBeNull()
    expect(b(['待验证|c.md'], 'complete', seam().model)).toBeNull()
    expect(b(['done|d.md'], 'trash', seam().model)).toBeNull()
  })

  it('buildHomeBatchSubmission：无可选时 fail-closed 返回 null，不静默空批', () => {
    const b = homeModel.buildHomeBatchSubmission
    expect(b(['任务|NOEXIST.md'], 'trash', seam().model)).toBeNull()
  })
})