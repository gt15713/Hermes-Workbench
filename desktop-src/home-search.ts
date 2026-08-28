/**
 * Task 6 — 首页顶部搜索 + 健康/反馈统一口径（2026-08-27）。
 *
 * - 搜索复用既有 /search API 与索引（不建第二索引）；
 *   本模块只做结果 → 卡片映射与五类反馈分支。
 * - 健康三色收敛：绿=正常、黄=等待/降级、红=失败/阻塞；灰只允许出现在
 *   弹窗明细行（未开始/忽略的检查项），不再作为整体状态色。
 * - 平台来源永远用文字/图标表达，不用状态色承载语义。
 */

import type { WbCard, WbSearchResult } from './types'

/** /search 结果 → 打开详情用的规范卡片形（board.toCard 的公共化）。 */
export function searchResultToCard(r: WbSearchResult, root: string): WbCard {
  return {
    dir: r.dir,
    file: r.file,
    path: `${root.replace(/\/+$/, '')}/${r.dir}/${r.file}`,
    title: r.title,
    status: r.status,
    entries: [],
    entry_count: r.entry_count,
    priority: r.priority,
    size: r.size,
    tags: r.tags,
  }
}

export type HomeSearchFeedback = {
  kind: 'idle' | 'loading' | 'timeout' | 'failure' | 'unreachable' | 'empty' | 'results'
  text: string
  retry?: boolean
}

/**
 * 五类反馈互异（禁止一切错误统一显示「后端不可达」）：
 * loading / 请求超时 / 单条失败 / 后端不可达 / 空结果 —— 文案与恢复动作各不同。
 */
export function homeSearchFeedback(input: {
  hasQuery: boolean
  isLoading?: boolean
  error?: unknown
  data?: { results: unknown[] } | null
}): HomeSearchFeedback {
  if (!input.hasQuery) return { kind: 'idle', text: '' }

  const err = input.error
  const msg = err instanceof Error ? err.message : typeof err === 'string' ? err : ''

  if (err === 'unreachable') {
    return {
      kind: 'unreachable',
      text: '后端暂时不可达——请稍候重试；若持续出现请检查 Gateway 状态。',
      retry: true,
    }
  }
  if (err) {
    if (msg.includes('超时')) {
      return { kind: 'timeout', text: `搜索超时：${msg}。可再试一次或缩短关键词。`, retry: true }
    }
    return { kind: 'failure', text: `搜索失败：${msg || '未知错误'}。可重试。`, retry: true }
  }
  if (input.isLoading) return { kind: 'loading', text: '正在搜索…' }
  if (input.data && input.data.results.length === 0) {
    return { kind: 'empty', text: '没有匹配的结果。换个关键词，或用「旧版数据」里的筛选器试试。' }
  }
  return { kind: 'results', text: '' }
}

export type HealthStatus = 'green' | 'yellow' | 'red'

/** 三色收敛：整体状态只用这三档；gray(disabled) 不再是合法整体态。 */
export function healthSemanticFor(status: HealthStatus): { tone: string; label: string } {
  switch (status) {
    case 'green': return { tone: '#34d399', label: '一切正常' }
    case 'yellow': return { tone: '#fbbf24', label: '有点状况' }
    case 'red': return { tone: '#f87171', label: '暂时不可用' }
    default:
      // fail-closed：未知/灰色档不允许再当整体状态渲染
      throw new Error(`fail-closed: unexpected health status "${String(status)}"`)
  }
}

/** 明细行内允许灰色（未开始/忽略的检查项）。 */
export function healthCheckTone(status: string): string {
  return ({
    green: '#34d399',
    yellow: '#fbbf24',
    red: '#f87171',
    disabled: '#94a3b8', // 仅限弹窗明细行
  } as Record<string, string>)[status] ?? '#94a3b8'
}

export const HEALTH_POPOVER_TESTID = 'wb-health-popover'

/** 弹窗关闭契约：外部点击与 Escape 双路径；样式沿用 Workbench token（wb-health-popover）。 */
export function healthPopoverClosesOn(): Array<'outside-click' | 'escape'> {
  return ['outside-click', 'escape']
}

export function healthPopverA11y(): { testid: string; className: string; closesOn: Array<'outside-click' | 'escape'> } {
  return { testid: HEALTH_POPOVER_TESTID, className: 'wb-health-popover', closesOn: healthPopoverClosesOn() }
}
