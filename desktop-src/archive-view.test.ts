import { describe, expect, it } from 'vitest'

import {
  HOME_VIEW_INITIAL_STATE,
  buildArchiveModel,
  buildHomeModel,
  buildHomeViewPresentation,
  homeViewStateReducer,
} from './home-model'
import type { WbBoard, WbCard, WbSection } from './types'

// WB-S1-040 / FR-040：独立 done/trash 归档浏览（source/test only）。
// RED 证明：当前 Home（buildHomeModel + presentation seam）没有独立浏览完整
// done 与 trash partitions 的入口/视图 —— done 混入 recent 且预览截断；
// trash 整区被跳过。GREEN：buildArchiveModel 提供独立完整列表、来源与空态，
// 未知状态继续 fail-closed，顶层「完整数据（兼容）」fallback 保持可达。
//
// WB-S1-041：把 FR-040 升级为生产接线 —— Home 顶层「归档 / 回收站」入口、
// 生产 reducer 的 archive 模式、独立 done/trash 完整列表（计数 + 来源 +
// 诚实空态）与返回首页行为；buildArchiveModel 聚合所有同 key sections
// （/board schema 不保证 done/trash 各仅一个 section）。

const TODAY = '2026-08-30'

function card(overrides: Partial<WbCard> & Pick<WbCard, 'file'>): WbCard {
  return {
    dir: '任务',
    path: `C:/wb/${overrides.dir ?? '任务'}/${overrides.file}`,
    title: overrides.file.replace(/\.md$/, ''),
    status: '',
    entries: [],
    entry_count: 0,
    ...overrides,
  }
}

function section(key: string, files: WbCard[], dir = key): WbSection {
  return { dir, key, files }
}

function board(sections: WbSection[]): WbBoard {
  return {
    root: 'C:/wb',
    updated_at: '12:00:00',
    today: TODAY,
    totals: { pending: 0, total: 0 },
    sections,
  }
}

describe('FR-040 RED proof — 当前 Home 无独立 done/trash 完整浏览', () => {
  it('trash 分区在 buildHomeModel 四区与 contractErrors 中均不可见（只进 skipped）', () => {
    const t1 = card({ file: 't1.md', dir: 'trash', status: 'abandoned' })
    const t2 = card({ file: 't2.md', dir: 'trash', status: '' })
    const d1 = card({ file: 'd1.md', dir: '2026-08-01', status: 'done' })
    const m = buildHomeModel(board([
      section('trash', [t1, t2], '回收站'),
      section('done', [d1], '2026-08-01'),
    ]))
    const inRegions = m.regions.flatMap(r => r.items.map(i => `${i.card.dir}/${i.card.file}`))
    expect(inRegions).not.toContain('trash/t1.md')
    expect(inRegions).not.toContain('trash/t2.md')
    expect(m.contractErrors.map(e => `${e.card.dir}/${e.card.file}`)).not.toContain('trash/t1.md')
    expect(m.contractErrors.map(e => `${e.card.dir}/${e.card.file}`)).not.toContain('trash/t2.md')
    const skipped = m.skipped.map(s => `${s.dir}/${s.file}`)
    expect(skipped).toContain('trash/t1.md')
    expect(skipped).toContain('trash/t2.md')
    // 没有任何 region 以 trash 为独立视图
    expect(m.regions.map(r => r.id)).not.toContain('trash')
  })

  it('done 只在 recent 与 active 完成态混排，Home 预览截断后无独立完整入口', () => {
    // 7 个 recent（4 active 完成 + 3 done 归档）→ 预览 8 时全可见但混排；
    // 再加 6 个 active 完成 → 预览截断，部分 done 在 home 模式始终不可见，且无分区独立视图。
    const activeDone = Array.from({ length: 10 }, (_, i) => card({ file: `c${String(i).padStart(2, '0')}.md`, dir: '任务', status: 'completed' }))
    const doneArch = Array.from({ length: 4 }, (_, i) => card({ file: `a${i}.md`, dir: '2026-08-05', status: 'done' }))
    const m = buildHomeModel(board([
      section('task', activeDone),
      section('done', doneArch, '2026-08-05'),
    ]))
    const recent = m.regions.find(r => r.id === 'recent')!
    // recent 混排：active 完成 + done 归档同列表
    const sides = [...new Set(recent.items.map(i => i.side))]
    expect(sides).toEqual(expect.arrayContaining(['done', 'active']))
    // preview 截断：14 个 recent 只显示 8，Home 模式看不到完整 done 分区
    const p = buildHomeViewPresentation(m, HOME_VIEW_INITIAL_STATE)
    const preview = p.regions.find(r => r.id === 'recent')!
    expect(preview.visibleItems.length).toBe(8)
    expect(preview.visibleItems.filter(i => i.side === 'done').length).toBeLessThan(doneArch.length)
    // 展开后虽然完整，但仍混排 —— 没有独立 done 分区视图
    const expanded = buildHomeViewPresentation(m, homeViewStateReducer(HOME_VIEW_INITIAL_STATE, { type: 'show-all', regionId: 'recent' }))
    expect(expanded.expandedRegion?.visibleItems.length).toBe(14)
    const onlyDone = expanded.expandedRegion?.visibleItems.filter(i => i.side === 'done')
    expect(onlyDone?.length).toBe(4)
    // RED 核心：没有任何 seam 可以单独呈现 done 完整分区作为归档视图
    expect(p.mode).toBe('home')
  })

  it('unknown 状态继续 fail-closed，不因归档需求被塞进任何区域', () => {
    const unknown = card({ file: 'weird.md', dir: '任务', status: 'mystery-status' })
    const m = buildHomeModel(board([section('task', [unknown])]))
    const inRegions = m.regions.flatMap(r => r.items.map(i => i.card))
    expect(inRegions).not.toContain(unknown)
    expect(m.contractErrors.map(e => e.card)).toContain(unknown)
    expect(m.contractErrors[0].reason).toContain('未知状态')
  })
})

describe('FR-040 GREEN — buildArchiveModel 独立完整 done/trash 只读浏览', () => {
  it('独立完整列表：done 与 trash 各自完整、来源标签正确，不做分区语义猜测', () => {
    const doneFiles = Array.from({ length: 12 }, (_, i) => card({ file: `a${i}.md`, dir: '2026-08-05', status: 'done' }))
    const trashFiles = Array.from({ length: 9 }, (_, i) => card({ file: `t${i}.md`, dir: 'trash', status: 'abandoned' }))
    const model = buildArchiveModel(board([
      section('done', doneFiles, '2026-08-05'),
      section('trash', trashFiles, '回收站'),
    ]))
    expect(model.done.count).toBe(12)
    expect(model.trash.count).toBe(9)
    expect(model.done.entries.length).toBe(12)
    expect(model.trash.entries.length).toBe(9)
    expect(model.done.entries.every(e => e.partition === 'done')).toBe(true)
    expect(model.trash.entries.every(e => e.partition === 'trash')).toBe(true)
    // 不截断：即使 > 8 也全量列出（归档视图不是 Home 预览）
    expect(model.done.entries[11].card.file).toBe('a11.md')
    expect(model.trash.entries[8].card.file).toBe('t8.md')
  })

  it('空态：分区缺失或为空时返回空列表与 count 0，不抛错', () => {
    const model = buildArchiveModel(board([section('task', [card({ file: 'x.md', dir: '任务', status: '' })])]))
    expect(model.done.count).toBe(0)
    expect(model.done.entries).toEqual([])
    expect(model.trash.count).toBe(0)
    expect(model.trash.entries).toEqual([])
  })

  it('buildArchiveModel 不修改输入 board，与 Home 预览共存且互不影响', () => {
    const d1 = card({ file: 'd1.md', dir: '2026-08-01', status: 'done' })
    const sections = [section('done', [d1], '2026-08-01')]
    const before = JSON.stringify(sections)
    buildArchiveModel(board(sections))
    expect(JSON.stringify(sections)).toBe(before)
    // Home 仍按既有语义投影 done → recent（预览顺序不变）
    const m = buildHomeModel(board(sections))
    const recent = m.regions.find(r => r.id === 'recent')!
    expect(recent.items.map(i => i.card.file)).toEqual(['d1.md'])
  })

  it('fail-closed 保持：未知状态仍在 buildHomeModel 的 contractErrors，归档模型不吞掉', () => {
    const unknown = card({ file: 'weird.md', dir: '任务', status: 'mystery-status' })
    const m = buildHomeModel(board([section('task', [unknown])]))
    expect(m.contractErrors.map(e => e.card)).toContain(unknown)
    // 归档模型只读分区数据，不重新分类任务状态
    const arch = buildArchiveModel(board([section('task', [unknown])]))
    expect(arch.done.count).toBe(0)
    expect(arch.trash.count).toBe(0)
  })
})

// ── WB-S1-041：生产接线 —— RED 证据与持久不变量 ────────────────
// RED（实现前 2026-08-30 02:00 vitest 实测：8 failed | 11 passed，证据见
// work/evidence/workbench/）：Home 生产 seam ①无 archive 投影 ②无
// archiveEntryVisible ③open-archive 被 reducer 回落（mode 停留 home）
// ④buildArchiveModel 用 find 只取第一个同 key section（多分区剩余丢失）。
// 实现后 absence 断言不再成立，由下方 GREEN describe 验证生产行为；
// 此处只保留跨实现持久的不变量，并记录 RED 追溯。
// HomeView 生产代码（home.tsx L215/L224）就使用 homeViewStateReducer +
// buildHomeViewPresentation，因此 GREEN 断言就是生产组件/状态 seam。

describe('WB-S1-041 生产 seam 持久不变量（RED 追溯见上方注释）', () => {
  it('返回行为语义：back 恒回到初始 Home 状态，进入归档态后 expanded 区域为空', () => {
    const m = buildHomeModel(board([section('task', [card({ file: 'x.md', dir: '任务', status: '' })])]))
    const opened = homeViewStateReducer(HOME_VIEW_INITIAL_STATE, { type: 'open-archive' } as never)
    const back = homeViewStateReducer(opened, { type: 'back' })
    expect(back).toEqual(HOME_VIEW_INITIAL_STATE)
    expect(buildHomeViewPresentation(m, back).mode).toBe('home')
    // archive 模式与展开模式互斥：进入归档态后不存在 expanded region
    expect(buildHomeViewPresentation(m, opened).expandedRegion).toBeNull()
  })
})

// ── WB-S1-041：生产接线 GREEN（期望行为，实现前失败）─────────────────
describe('WB-S1-041 GREEN — Home 归档入口 → 完整 done/trash 可见 → 返回首页', () => {
  it('home 预览态：archiveEntryVisible=true 且四区预览与现状一致（不改变既有投影）', () => {
    const files = Array.from({ length: 10 }, (_, i) => card({ file: `r${String(i).padStart(2, '0')}.md`, dir: '任务', status: 'completed' }))
    const m = buildHomeModel(board([section('task', files), section('done', [card({ file: 'a.md', dir: '2026-08-01', status: 'done' })])]))
    const p = buildHomeViewPresentation(m, HOME_VIEW_INITIAL_STATE)
    expect(p.mode).toBe('home')
    expect(Object.prototype.hasOwnProperty.call(p, 'archiveEntryVisible')).toBe(true)
    expect(p.archiveEntryVisible).toBe(true)
    const recent = p.regions.find(r => r.id === 'recent')!
    expect(recent.visibleItems.length).toBe(8)
    // 10 个 active 已完成先于 done 归档：预览 8 全为 active（预览截断语义不变，
    // 完整 done 需通过归档入口查看 —— 这正是 FR-040 的入口价值）
    expect(recent.visibleItems.filter(i => i.side === 'done').length).toBe(0)
    expect(p.legacyFallbackVisible).toBe(true)
  })

  it('open-archive：mode=archive，production seam 返回完整 done/trash（计数、来源、不截断）', () => {
    const doneFiles = Array.from({ length: 12 }, (_, i) => card({ file: `a${String(i).padStart(2, '0')}.md`, dir: '已处理', status: 'done' }))
    const trashFiles = Array.from({ length: 9 }, (_, i) => card({ file: `t${String(i).padStart(2, '0')}.md`, dir: '回收站', status: 'abandoned' }))
    const m = buildHomeModel(board([
      section('task', [card({ file: 'live.md', dir: '任务', status: 'in_progress' })]),
      section('done', doneFiles, '已处理'),
      section('trash', trashFiles, '回收站'),
    ]))
    const opened = homeViewStateReducer(HOME_VIEW_INITIAL_STATE, { type: 'open-archive' } as never)
    const p = buildHomeViewPresentation(m, opened)
    expect(p.mode).toBe('archive')
    expect(p.expandedRegion).toBeNull()
    expect(p.archive).not.toBeNull()
    expect(p.archive?.done.count).toBe(12)
    expect(p.archive?.trash.count).toBe(9)
    expect(p.archive?.done.entries.length).toBe(12)
    expect(p.archive?.trash.entries.length).toBe(9)
    // 来源 provenance 保留：每条 entry 的 card.dir 是真实分区目录
    expect(p.archive?.done.entries[0].card.dir).toBe('已处理')
    expect(p.archive?.trash.entries[0].card.dir).toBe('回收站')
    expect(p.archive?.done.entries.every(e => e.partition === 'done')).toBe(true)
    expect(p.archive?.trash.entries.every(e => e.partition === 'trash')).toBe(true)
    // 不截断：归档视图非 Home 预览（9 条 trash 全部可见，末条 t08 可访问）
    expect(p.archive?.done.entries[11].card.file).toBe('a11.md')
    expect(p.archive?.trash.entries[8].card.file).toBe('t08.md')
    // fail-closed 与兼容 fallback 在 archive 模式保持
    expect(p.contractErrorBannerVisible).toBe(false)
    expect(p.legacyFallbackVisible).toBe(true)
  })

  it('back：从 archive 返回 home，四区预览顺序与进入前完全一致', () => {
    const files = Array.from({ length: 10 }, (_, i) => card({ file: `r${String(i).padStart(2, '0')}.md`, dir: '任务', status: 'completed' }))
    const doneFiles = Array.from({ length: 5 }, (_, i) => card({ file: `a${i}.md`, dir: '已处理', status: 'done' }))
    const trashFiles = [card({ file: 't0.md', dir: '回收站', status: 'abandoned' })]
    const m = buildHomeModel(board([
      section('task', files),
      section('done', doneFiles, '已处理'),
      section('trash', trashFiles, '回收站'),
    ]))
    const before = buildHomeViewPresentation(m, HOME_VIEW_INITIAL_STATE)
    const opened = homeViewStateReducer(HOME_VIEW_INITIAL_STATE, { type: 'open-archive' } as never)
    expect(buildHomeViewPresentation(m, opened).mode).toBe('archive')
    const back = homeViewStateReducer(opened, { type: 'back' })
    const restored = buildHomeViewPresentation(m, back)
    expect(restored.mode).toBe('home')
    expect(restored.expandedRegion).toBeNull()
    // 四区顺序与预览内容不变：today → inbox → attention → recent
    expect(restored.regions.map(r => r.id)).toEqual(['today', 'inbox', 'attention', 'recent'])
    expect(restored.regions.map(r => r.visibleItems)).toEqual(before.regions.map(r => r.visibleItems))
    // 返回后 archive 数据仍完整可再次进入
    const reopened = homeViewStateReducer(back, { type: 'open-archive' } as never)
    expect(buildHomeViewPresentation(m, reopened).mode).toBe('archive')
  })

  it('多 section 同 key 聚合：buildArchiveModel 全量保留并保持后端顺序与来源', () => {
    const d1 = card({ file: 'd1.md', dir: '已处理', status: 'done' })
    const d2 = card({ file: 'd2.md', dir: '已处理-历史', status: 'done' })
    const t1 = card({ file: 't1.md', dir: '回收站', status: 'abandoned' })
    const t2 = card({ file: 't2.md', dir: '回收站-历史', status: 'abandoned' })
    const d3 = card({ file: 'd3.md', dir: '已处理', status: 'done' })
    const t3 = card({ file: 't3.md', dir: '回收站', status: 'abandoned' })
    const arch = buildArchiveModel(board([
      section('done', [d1, d3], '已处理'),
      section('trash', [t1, t3], '回收站'),
      section('done', [d2], '已处理-历史'),
      section('trash', [t2], '回收站-历史'),
    ]))
    expect(arch.done.count).toBe(3)
    expect(arch.trash.count).toBe(3)
    // 后端顺序保持：section 顺序 + 分区内文件顺序
    expect(arch.done.entries.map(e => e.card.file)).toEqual(['d1.md', 'd3.md', 'd2.md'])
    expect(arch.trash.entries.map(e => e.card.file)).toEqual(['t1.md', 't3.md', 't2.md'])
    // 来源 provenance：同一 key 合并后仍可追溯到各自目录
    expect(arch.done.entries.map(e => e.card.dir)).toEqual(['已处理', '已处理', '已处理-历史'])
    expect(arch.trash.entries.map(e => e.card.dir)).toEqual(['回收站', '回收站', '回收站-历史'])
  })

  it('诚实空态：done/trash 为空时 count=0、entries=[]，UI 语义不伪造', () => {
    const m = buildHomeModel(board([section('task', [card({ file: 'x.md', dir: '任务', status: '' })])]))
    const opened = homeViewStateReducer(HOME_VIEW_INITIAL_STATE, { type: 'open-archive' } as never)
    const p = buildHomeViewPresentation(m, opened)
    expect(p.mode).toBe('archive')
    expect(p.archive?.done.count).toBe(0)
    expect(p.archive?.done.entries).toEqual([])
    expect(p.archive?.trash.count).toBe(0)
    expect(p.archive?.trash.entries).toEqual([])
  })

  it('fail-closed 保持：archive 模式不吞 unknown，横幅仍在，兼容入口仍可达', () => {
    const unknown = card({ file: 'weird.md', dir: '任务', status: 'mystery-status' })
    const m = buildHomeModel(board([section('task', [unknown])]))
    const opened = homeViewStateReducer(HOME_VIEW_INITIAL_STATE, { type: 'open-archive' } as never)
    const p = buildHomeViewPresentation(m, opened)
    expect(p.mode).toBe('archive')
    expect(p.contractErrorBannerVisible).toBe(true)
    expect(p.legacyFallbackVisible).toBe(true)
    // 归档列表本身不包含 unknown（不重新分类任务状态）
    expect(p.archive?.done.entries).toEqual([])
    expect(p.archive?.trash.entries).toEqual([])
    expect(m.contractErrors.map(e => e.card)).toContain(unknown)
  })

})