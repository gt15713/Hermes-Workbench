import { describe, expect, it } from 'vitest'

import {
  HOME_VIEW_INITIAL_STATE,
  buildHomeModel,
  buildHomeViewPresentation,
  homeViewStateReducer,
} from './home-model'
import type { WbBoard, WbCard, WbSection } from './types'

// WB-S1-035 行为测试（替换上一轮仅作源码正则的 WB-S1-034 验收）：
// 1) recent 的 done 分区归档对象与 active 分区已完成对象必须保留可验证的 side provenance；
// 2) 首页预览与「查看全部」必须复用同一排序结果（前 8 项顺序一致，不得从 reversed 切回 raw）；
// 3) 溢出（>8）触发 show-all；4) 未知状态 fail-closed；5) 旧版数据 fallback 不受影响；6) legacy 面板保留。
// 全部走 buildHomeModel 行为断言，不使用源码文本 regex 作为新增验收。

const TODAY = '2026-08-29'

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

function audit(m: ReturnType<typeof buildHomeModel>, inputCards: WbCard[]) {
  const inRegions = m.regions.flatMap(r => r.items.map(i => i.card))
  const accounted = [...inRegions, ...m.contractErrors.map(e => e.card)]
  for (const c of inputCards) {
    expect(accounted.includes(c)).toBe(true)
  }
  const known = new Set([...inRegions.map(c => `${c.dir}/${c.file}`), ...m.contractErrors.map(e => `${e.card.dir}/${e.card.file}`)])
  for (const c of inputCards) {
    expect(known.has(`${c.dir}/${c.file}`)).toBe(true)
  }
}

describe('WB-S1-035 recent provenance & order（行为验收）', () => {
  it('recent 同时含 done 归档对象与 active 已完成对象时，side 来源边界可验证', () => {
    // 9 项 fixture：6 个 active 已完成（completed/ingested/accepted）+ 2 个 done 分区归档 + 1 个普通活动卡
    const completed = card({ file: 'c1.md', dir: '任务', status: 'completed' })
    const ingested = card({ file: 'c2.md', dir: '阅读', status: 'ingested' })
    const accepted = card({ file: 'c3.md', dir: '任务', status: 'accepted' })
    const ignored = card({ file: 'c4.md', dir: '待回看', status: 'ignored' })
    const abandoned = card({ file: 'c5.md', dir: '任务', status: 'abandoned' })
    const cleared = card({ file: 'c6.md', dir: '任务', status: 'cleared' })
    const arch1 = card({ file: 'a1.md', dir: '2026-07-31', status: 'whatever-archive' })
    const arch2 = card({ file: 'a2.md', dir: '2026-08-15', status: 'done' })
    const active = card({ file: 'live.md', dir: '任务', status: 'in_progress' })
    const input = [completed, ingested, accepted, ignored, abandoned, cleared, arch1, arch2, active]
    const m = buildHomeModel(board([
      section('task', [active, completed, accepted, abandoned, cleared]),
      section('阅读', [ingested]),
      section('待回看', [ignored]),
      section('done', [arch1, arch2]),
    ]))
    audit(m, input)

    const recent = m.regions.find(r => r.id === 'recent')!
    // 6 个 active 已完成 + 2 个 done 分区归档 = 8
    expect(recent.items.length).toBe(8)
    // 来源边界：done 分区 → side 'done'；active 分区已完成 → side 'active'
    const sides = [...new Set(recent.items.map(i => i.side))]
    expect(sides).toContain('done')
    expect(sides).toContain('active')
    const doneSide = recent.items.filter(i => i.side === 'done').map(i => i.card)
    const activeSide = recent.items.filter(i => i.side === 'active').map(i => i.card)
    expect(doneSide.map(c => c.file)).toEqual(['a1.md', 'a2.md'])
    expect(activeSide.map(c => c.file).sort()).toEqual(['c1.md', 'c2.md', 'c3.md', 'c4.md', 'c5.md', 'c6.md'])
    // 不做无条件 done 侧投影
    expect(activeSide.length).toBeGreaterThan(0)
  })

  it('真实 show-all 状态转换保持 recent 顺序，并在展开态保留 unknown 横幅与可点击旧版 fallback', () => {
    // 11 个 mixed-provenance recent + 1 个 unknown，确保预览溢出并触发展开状态。
    const files = Array.from({ length: 10 }, (_, i) => card({ file: `r${String(i).padStart(2, '0')}.md`, dir: '任务', status: 'completed' }))
    const arch = card({ file: 'arch.md', dir: '2026-08-01', status: 'done' })
    const unknown = card({ file: 'unknown.md', dir: '任务', status: 'mystery-status' })
    const active = card({ file: 'live.md', dir: '任务', status: 'in_progress' })
    const input = [...files, arch, unknown, active]
    const m = buildHomeModel(board([section('task', [...files, unknown, active]), section('done', [arch])]))
    audit(m, input)

    const before = buildHomeViewPresentation(m, HOME_VIEW_INITIAL_STATE)
    const preview = before.regions.find(r => r.id === 'recent')!
    expect(before.mode).toBe('home')
    expect(preview.canShowAll).toBe(true)
    expect(preview.visibleItems.map(i => `${i.side}:${i.card.file}`)).toEqual([
      'active:r00.md', 'active:r01.md', 'active:r02.md', 'active:r03.md',
      'active:r04.md', 'active:r05.md', 'active:r06.md', 'active:r07.md',
    ])

    // 生产 HomeView 的 onShowAll 使用同一 reducer；此处驱动真实状态转换，而非重写排序算法。
    const expandedState = homeViewStateReducer(HOME_VIEW_INITIAL_STATE, { type: 'show-all', regionId: 'recent' })
    const expanded = buildHomeViewPresentation(m, expandedState)
    expect(expanded.mode).toBe('expanded')
    expect(expanded.expandedRegion?.visibleItems.map(i => `${i.side}:${i.card.file}`)).toEqual([
      'active:r00.md', 'active:r01.md', 'active:r02.md', 'active:r03.md',
      'active:r04.md', 'active:r05.md', 'active:r06.md', 'active:r07.md',
      'active:r08.md', 'active:r09.md', 'done:arch.md',
    ])
    expect(expanded.expandedRegion?.visibleItems.slice(0, 8)).toEqual(preview.visibleItems)
    expect(expanded.contractErrorBannerVisible).toBe(true)
    expect(expanded.legacyFallbackVisible).toBe(true)

    // WB-S1-037：同一 mixed-provenance fixture 驱动生产 back reducer 与 presentation seam。
    const restoredState = homeViewStateReducer(expandedState, { type: 'back' })
    const restored = buildHomeViewPresentation(m, restoredState)
    const restoredPreview = restored.regions.find(r => r.id === 'recent')!
    expect(restored.mode).toBe('home')
    expect(restored.expandedRegion).toBeNull()
    expect(restoredPreview.visibleItems).toEqual(preview.visibleItems)
    expect(restored.contractErrorBannerVisible).toBe(true)
    expect(restored.legacyFallbackVisible).toBe(true)
  })

  it('未知状态 fail-closed：进入 contractErrors，不进入任何区域', () => {
    const unknown = card({ file: 'weird.md', dir: '任务', status: 'mystery-status' })
    const ok = card({ file: 'ok.md', dir: '任务', status: 'completed' })
    const m = buildHomeModel(board([section('task', [ok, unknown])]))
    audit(m, [ok, unknown])
    const inRegions = m.regions.flatMap(r => r.items.map(i => i.card))
    expect(inRegions).not.toContain(unknown)
    expect(m.contractErrors.map(e => e.card)).toContain(unknown)
  })

  it('旧版数据 fallback：buildHomeModel 不改动输入 board，旧分区数据仍完整存在', () => {
    const legacy = card({ file: 'legacy.md', dir: '旧看板', status: 'todo' })
    const done = card({ file: 'd.md', dir: '2026-08-01', status: 'done' })
    const sections = [section('legacy-board', [legacy]), section('done', [done])]
    const before = JSON.stringify(sections)
    buildHomeModel(board(sections))
    expect(JSON.stringify(sections)).toBe(before)
    expect(sections[0].key).toBe('legacy-board')
    expect(sections[0].files[0].file).toBe('legacy.md')
    // legacy 分区按模型分类不进入四区（或进入收件箱），但输入 data 不被改
    expect(sections[1].files[0].file).toBe('d.md')
  })
})