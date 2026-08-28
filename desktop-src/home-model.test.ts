/**
 * Task 2 — Single HomeModel projection (RED first).
 *
 * Fixture 全覆盖矩阵（CoderX §6.2 指令）：
 *  - pending/queued → 收件箱
 *  - active(in_progress)/processing → 进行中
 *  - waiting_user/failed → 需要注意（含 in_progress+execution_result=failure 组合）
 *  - completed/ingested/accepted/ignored（+项目历史别名 done/abandoned/cleared） → 最近完成
 *  - reviewable content（thought 聚合卡）→ 待审核
 *  - 空聚合壳（entry_count===0）→ 不成卡
 *  - 未知状态 → fail-closed：contractErrors，不入任何区域
 *  - trash 分区 → 跳过
 * 断言纪律：
 *  - 每张卡恰好进入一个去向（区域 | 契约错误 | 跳过）；
 *  - 每个区域的可见计数恒等于其 items 数组长度；
 *  - 空区域仍然存在于输出中（length 0），供 UI 显示专属空状态；
 *  - 未知的 section key / status 不污染任何区域，也不被吞掉。
 */
import { describe, expect, it } from 'vitest'

import { buildHomeModel } from './home-model'
import type { WbBoard, WbCard, WbSection } from './types'

const TODAY = '2026-08-27'

function card(overrides: Partial<WbCard> & Pick<WbCard, 'file'>): WbCard {
  return {
    dir: '待验证',
    path: `C:/wb/${overrides.dir ?? '待验证'}/${overrides.file}`,
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

/** 总账：所有输入卡都能对账（区域 + 契约错误 + 跳过 = 全部）。 */
function audit(m: ReturnType<typeof buildHomeModel>, inputCards: WbCard[]) {
  const inRegions = m.regions.flatMap(r => r.items.map(i => i.card))
  const accounted = [...inRegions, ...m.contractErrors.map(e => e.card)]
  expect(accounted.length + m.skipped.length).toBe(inputCards.length)
  // 卡对象身份守恒（不允许复制/丢失）
  const ids = (c: Pick<WbCard, 'dir' | 'file'>) => `${c.dir}/${c.file}`
  const accountedIds = new Set(accounted.map(ids))
  expect(accountedIds.size).toBe(accounted.length)
  for (const c of inputCards) {
    if (!m.skipped.some(s => ids(s) === ids(c))) {
      expect(accountedIds.has(ids(c))).toBe(true)
    }
  }
}

describe('HomeModel 区域映射', () => {
  it('pending/queued/todo 进入收件箱', () => {
    const cards = [
      card({ file: 'a.md', dir: '待验证', status: 'pending', entry_count: 2, entries: ['x', 'y'] }),
      card({ file: 't1.md', dir: '任务', status: 'queued' }),
      card({ file: 't2.md', dir: '任务', status: 'todo' }),
    ]
    const m = buildHomeModel(board([section('thought', [cards[0]]), section('task', cards.slice(1))]))
    audit(m, cards)
    const inbox = m.regions.find(r => r.id === 'inbox')!
    expect(inbox.items.map(i => i.card)).toEqual(cards)
    expect(inbox.items.length).toBe(3)
  })

  it('in_progress 进入进行中；in_progress+failure 进入需要注意', () => {
    const active = card({ file: 'run.md', dir: '任务', status: 'in_progress' })
    const failed = card({ file: 'boom.md', dir: '任务', status: 'in_progress', execution_result: 'failure' })
    const m = buildHomeModel(board([section('task', [active, failed])]))
    audit(m, [active, failed])
    expect(m.regions.find(r => r.id === 'today')!.items.map(i => i.card)).toEqual([active])
    expect(m.regions.find(r => r.id === 'attention')!.items.map(i => i.card)).toEqual([failed])
  })

  it('waiting_user/failed 进入需要注意', () => {
    const w = card({ file: 'w.md', dir: '任务', status: 'waiting_user' })
    const f = card({ file: 'f.md', dir: '任务', status: 'failed' })
    const m = buildHomeModel(board([section('task', [w, f])]))
    audit(m, [w, f])
    expect(m.regions.find(r => r.id === 'attention')!.items.map(i => i.card)).toEqual([w, f])
  })

  it('completed/ingested/accepted/ignored（含别名 done/abandoned）与 done 分区进入最近完成', () => {
    const cards = [
      card({ file: 'd.md', dir: '任务', status: 'completed' }),
      card({ file: 'i.md', dir: '任务', status: 'ingested' }),
      card({ file: 'ac.md', dir: '任务', status: 'accepted' }),
      card({ file: 'ig.md', dir: '任务', status: 'ignored' }),
      card({ file: 'hist.md', dir: '任务', status: 'done' }),
      card({ file: 'ab.md', dir: '任务', status: 'abandoned' }),
      card({ file: 'arch.md', dir: '2026-08-27', status: 'whatever-archive' }),
    ]
    const m = buildHomeModel(board([section('task', cards.slice(0, 6)), section('done', [cards[6]])]))
    audit(m, cards)
    const recent = m.regions.find(r => r.id === 'recent')!
    expect(recent.items.map(i => i.card)).toEqual(cards)
    expect(recent.items.length).toBe(7)
  })

  it('reviewable content：thought/video/psych/dream 聚合卡整体进入待审核（inbox 区，UI 标签「待审核」）', () => {
    const v = card({ file: 'clip.md', dir: '待回看', status: '', entry_count: 3, entries: ['a', 'b', 'c'] })
    const th = card({ file: 'n.md', dir: '待验证', status: 'pending', entry_count: 1, entries: ['n'] })
    const m = buildHomeModel(board([section('thought', [th]), section('video', [v])]))
    audit(m, [th, v])
    const review = m.regions.find(r => r.id === 'inbox')!
    expect(review.items.map(i => i.card)).toEqual([th, v])
  })

  it('trash 分区整区跳过，不计入任何区域', () => {
    const t = card({ file: 'x.md', dir: '回收站', status: 'todo' })
    const m = buildHomeModel(board([section('trash', [t])]))
    audit(m, [t])
    expect(m.skipped.map(s => `${s.dir}/${s.file}`)).toEqual(['回收站/x.md'])
    for (const r of m.regions) expect(r.items.length).toBe(0)
  })
})

describe('HomeModel fail-closed 与不变式', () => {
  it('未知 status 产生契约错误，不进任何区域', () => {
    const weird = card({ file: 'z.md', dir: '任务', status: 'transporting-to-mars' })
    const m = buildHomeModel(board([section('task', [weird])]))
    audit(m, [weird])
    expect(m.contractErrors.length).toBe(1)
    expect(m.contractErrors[0]).toMatchObject({ card: weird, reason: expect.stringContaining('transporting-to-mars') })
    for (const r of m.regions) expect(r.items.length).toBe(0)
  })

  it('空聚合壳不成卡（跳过）且各区域仍存在、计数为 0', () => {
    const shell = card({ file: 'old-day.md', dir: '待回看', status: 'pending', entries: [], entry_count: 0 })
    const m = buildHomeModel(board([section('video', [shell])]))
    audit(m, [shell])
    expect(m.skipped.length).toBe(1)
    expect(m.regions.find(r => r.id === 'inbox')!.items.length).toBe(0)
    for (const r of m.regions) {
      expect(typeof r.count).toBe('number')
      expect(r.count).toBe(r.items.length)
    }
  })

  it('四个固定区域齐全且每区可见计数 === items.length', () => {
    const m = buildHomeModel(board([]))
    expect(m.regions.map(r => r.id)).toEqual(['today', 'inbox', 'attention', 'recent'])
    for (const r of m.regions) expect(r.count).toBe(r.items.length)
  })

  it('今日到期任务进入今日区（due === board.today）', () => {
    const t = card({ file: 'due.md', dir: '任务', status: 'todo', due: TODAY })
    const m = buildHomeModel(board([section('task', [t])]))
    audit(m, [t])
    expect(m.regions.find(r => r.id === 'today')!.items.map(i => i.card)).toEqual([t])
    // 同一张卡不得同时出现在收件箱（互斥由唯一去向保证）
    expect(m.regions.find(r => r.id === 'inbox')!.items.length).toBe(0)
  })

  it('混合场景总账平衡：9 张输入卡 = 区域 + 错误 + 跳过', () => {
    const cards = [
      card({ file: '1.md', dir: '任务', status: 'todo' }),
      card({ file: '2.md', dir: '任务', status: 'in_progress' }),
      card({ file: '3.md', dir: '任务', status: 'waiting_user' }),
      card({ file: '4.md', dir: '任务', status: 'failed' }),
      card({ file: '5.md', dir: '任务', status: 'completed' }),
      card({ file: '6.md', dir: '待验证', status: '', entry_count: 2, entries: ['p', 'q'] }),
      card({ file: '7.md', dir: '任务', status: 'wat' }),
      card({ file: '8.md', dir: '回收站', status: 'todo' }),
      card({ file: '9.md', dir: '任务', status: 'todo', due: '2026-08-20' }), // 超期待办仍归收件箱语义组
    ]
    const m = buildHomeModel(
      board([
        section('task', [cards[0], cards[1], cards[2], cards[3], cards[4], cards[6], cards[8]]),
        section('thought', [cards[5]]),
        section('trash', [cards[7]]),
      ]),
    )
    audit(m, cards)
    expect(m.contractErrors.length).toBe(1)
    expect(m.skipped.length).toBe(1)
    const total = m.regions.reduce((n, r) => n + r.count, 0)
    expect(total).toBe(7)
  })
})
