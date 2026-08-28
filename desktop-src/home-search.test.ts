import { describe, expect, it } from 'vitest'

import {
  healthPopverA11y,
  healthPopoverClosesOn,
  healthSemanticFor,
  HEALTH_POPOVER_TESTID,
  homeSearchFeedback,
  searchResultToCard,
} from './home-search'

/**
 * Task 6 — 顶部搜索 + 真实健康/反馈状态（统一口径，双消费方 board/home）。
 *
 * 搜索映射以 /search 后端为源（标题/文件名/正文/tags 子串、mtime 排序），
 * 本模块只负责 UI 映射：结果 → WbCard（打开详情/原会话入口共用 toCard 行为）。
 */

describe('searchResultToCard', () => {
  const root = 'M:/wb-test-vault'
  const sample = {
    dir: '待验证', key: 'thought', file: 'a.md', title: 'T', status: 'pending',
    mtime: '2026-08-27T10:00:00', priority: undefined as string | undefined,
    size: undefined as string | undefined, tags: [] as string[],
    entry_count: 0, events: [],
  }

  it('maps a result into the canonical card shape used by the preview drawer', () => {
    const card = searchResultToCard(sample, root)
    expect(card).toMatchObject({ dir: '待验证', file: 'a.md', title: 'T', status: 'pending' })
    expect(card.path).toBe('M:/wb-test-vault/待验证/a.md')
    expect(card.entries).toEqual([])
    expect(card.entry_count).toBe(0)
    expect(card.tags).toEqual([])
  })
})

describe('homeSearchFeedback — 五类反馈互异（CoderX §6）', () => {
  it('idle: query below threshold', () => {
    expect(homeSearchFeedback({ hasQuery: false }).kind).toBe('idle')
  })

  it('loading while request in flight', () => {
    expect(homeSearchFeedback({ hasQuery: true, isLoading: true }).kind).toBe('loading')
  })

  it('timeout carries recovery action wording distinct from generic failure', () => {
    const timeout = homeSearchFeedback({ hasQuery: true, error: new Error('请求超时，请重试') })
    expect(timeout.kind).toBe('timeout')
    expect(timeout.text).toContain('超时')

    const fail = homeSearchFeedback({ hasQuery: true, error: new Error('磁盘读失败') })
    expect(fail.kind).toBe('failure')
    expect(fail.text).not.toContain('超时')
  })

  it('backend unreachable is its own branch, not the umbrella for all errors', () => {
    const unreachable = homeSearchFeedback({ hasQuery: true, error: 'unreachable' })
    expect(unreachable.kind).toBe('unreachable')
    // 单条失败 ≠ 后端不可达
    expect(homeSearchFeedback({ hasQuery: true, error: new Error('x') }).kind).not.toBe('unreachable')
  })

  it('empty results after a successful request', () => {
    expect(homeSearchFeedback({ hasQuery: true, data: { results: [] } }).kind).toBe('empty')
    expect(homeSearchFeedback({ hasQuery: true, data: { results: [{ id: 1 }] } }).kind).toBe('results')
  })
})

describe('health semantics — 三色收敛 + 弹窗关闭契约', () => {
  it('collapses to green/yellow/red; gray only for not-started/ignored checks inside detail rows', () => {
    expect(healthSemanticFor('green')).toEqual({ tone: '#34d399', label: '一切正常' })
    expect(healthSemanticFor('yellow')).toEqual({ tone: '#fbbf24', label: '有点状况' })
    expect(healthSemanticFor('red')).toEqual({ tone: '#f87171', label: '暂时不可用' })
    // disabled（灰）不再作为整体状态色
    expect(() => healthSemanticFor('disabled' as never)).toThrow(/fail-closed/)
  })

  it('popover closes on outside click AND Escape, with Workbench styling tokens', () => {
    const a11y = healthPopverA11y()
    expect(a11y.testid).toBe(HEALTH_POPOVER_TESTID)
    expect(a11y.className).toContain('wb-health-popover') // Workbench 背景/边框 token
    expect(a11y.closesOn).toEqual(['outside-click', 'escape'])
  })
})
