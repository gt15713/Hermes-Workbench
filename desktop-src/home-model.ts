/**
 * Task 2 — Single HomeModel projection.
 *
 * 把「底层存储分区」(board.sections) 投影成用户可理解的四个工作区，
 * UI 三主区＝今日(today) / 待审核(inbox) / 需要注意(attention)，最近完成(recent)
 * 放在下方（CoderX §6.3 / workbench-v2-ui-state-contract.md L9-25）。
 * 唯一生产投影函数：Task 3 的首页 UI 从这里取数，禁止各视图自行
 * filter board.sections 出现第二套口径。
 *
 * 词表来源（全部实证，2026-08-27 后端源码）：
 * - wb_utils._parse_md L279: status = str(fm.get('status', '')) —— 自由文本；
 *   **'' 为合法缺省**＝刚收录尚未写入状态的「新进件」→ 待审核，不算未知；
 * - 项目历史别名：done/cleared/abandoned 为完成侧终态
 *   （auto_archive L56-57 归档判定 done→completed；trash abandon → abandoned）；
 * - 契约正式词表：completed/ingested/accepted/ignored（完成区）、
 *   waiting_user/failed（注意区）、active/processing（进行中别名）、
 *   pending/queued/todo（收件箱/待审核）；
 * - done 分区：board() L441-447 实证其来源 = complete/auto_archive 完成
 *   工作流搬运目标 → 分区内卡片一律映射「最近完成」（分区语义优先于
 *   frontmatter 自由文本，不属于猜测任务含义）；
 * - trash 分区整区跳过（同 board() L461 trash 不计 pending 的既有语义）；
 * - 空聚合壳（聚合分区 && entry_count===0 && entries 空）跳过——单卡文件
 *   entry_count 恒为 0，绝不能套用空壳规则（首个 GREEN 实测教训）；
 * - **未知状态 fail-closed**：非空且不在词表 → contractErrors，绝不就近塞，
 *   绝不被静默吞掉（契约 L16）。
 */
import type { WbBoard, WbCard } from './types'

/** UI 主区：今日 / 待审核(inbox 数据语义) / 需要注意 + 下方最近完成。 */
export type HomeRegionId = 'today' | 'inbox' | 'attention' | 'recent'

export interface HomeItem {
  card: WbCard
  /** WB-S1-035：来源侧 provenance —— 'done'=已归档到 done 分区；'active'=已完成但仍留在活动分区。 */
  side: 'done' | 'active'
}

export interface HomeRegion {
  id: HomeRegionId
  /** 可见计数恒等 items.length —— UI 只允许渲染这个计数。 */
  count: number
  items: HomeItem[]
}

export interface HomeContractError {
  card: WbCard
  reason: string
}

/** 跳过记录（审计对账用，不渲染为卡）。 */
export interface HomeSkipped {
  dir: string
  file: string
  why: 'trash-partition' | 'empty-shell'
}

export interface HomeAttentionCount {
  needsDecision: number
  failures: number
  total: number
}

export interface HomeModel {
  regions: HomeRegion[]
  /** Fail-closed 收容所：未知状态卡。非空时 UI 必须显示契约错误提示条。 */
  contractErrors: HomeContractError[]
  /** 对账辅助：因规则跳过的卡（trash 分区 / 空聚合壳）。 */
  skipped: HomeSkipped[]
  totals: {
    today: number
    inbox: number
    attention: HomeAttentionCount
    recent: number
    contractErrors: number
  }
}

/** WB-S1-036：HomeView 展开状态与实际可见输出的最小生产 seam。 */
export interface HomeViewState {
  showAllRegionId: HomeRegionId | null
}

export type HomeViewAction =
  | { type: 'show-all'; regionId: HomeRegionId }
  | { type: 'back' }

export const HOME_VIEW_INITIAL_STATE: HomeViewState = { showAllRegionId: null }

export interface HomeRegionPresentation extends HomeRegion {
  visibleItems: HomeItem[]
  canShowAll: boolean
}

export interface HomeViewPresentation {
  mode: 'home' | 'expanded'
  regions: HomeRegionPresentation[]
  expandedRegion: HomeRegionPresentation | null
  contractErrorBannerVisible: boolean
  /** 兼容入口在 Home 顶层渲染，预览与展开状态都必须可点击。 */
  legacyFallbackVisible: true
}

export function homeViewStateReducer(_state: HomeViewState, action: HomeViewAction): HomeViewState {
  return action.type === 'show-all'
    ? { showAllRegionId: action.regionId }
    : HOME_VIEW_INITIAL_STATE
}

/**
 * 从唯一 buildHomeModel 事实源导出 HomeView 的实际可见项。
 * 测试与 React 视图共同调用，避免测试复刻 slice/排序算法。
 */
export function buildHomeViewPresentation(
  model: HomeModel,
  state: HomeViewState,
  previewLimit = 8,
): HomeViewPresentation {
  const regions = model.regions.map(region => ({
    ...region,
    visibleItems: region.items.slice(0, previewLimit),
    canShowAll: region.items.length > previewLimit,
  }))
  const expandedSource = state.showAllRegionId
    ? model.regions.find(region => region.id === state.showAllRegionId) ?? null
    : null
  const expandedRegion = expandedSource
    ? { ...expandedSource, visibleItems: expandedSource.items, canShowAll: false }
    : null
  return {
    mode: expandedRegion ? 'expanded' : 'home',
    regions,
    expandedRegion,
    contractErrorBannerVisible: model.contractErrors.length > 0,
    legacyFallbackVisible: true,
  }
}

/** 聚合分区：按条目展开的待审核内容来源（board() L439）。 */
const REVIEWABLE_SECTIONS = new Set(['thought', 'video', 'psych', 'dream'])
const COMPLETED_STATUSES = new Set(['completed', 'ingested', 'accepted', 'ignored', 'done', 'abandoned', 'cleared'])
const ATTENTION_STATUSES = new Set(['waiting_user', 'failed'])
const ACTIVE_STATUSES = new Set(['in_progress', 'active', 'processing'])
const INBOX_STATUSES = new Set(['pending', 'queued', 'todo'])

/** Task 4（2026-08-27）：主操作映射复用同一份状态词表——导出只读视图，禁止第二词表。 */
export const HOME_STATUS_VOCAB = {
  inbox: INBOX_STATUSES,
  attention: ATTENTION_STATUSES,
  active: ACTIVE_STATUSES,
  completed: COMPLETED_STATUSES,
} as const

/** 「执行失败」组合态：execution_result=failure（auto_archive/plugin_api L1103 实证）。 */
export function isFailedExecution(card: { execution_result?: null | string }): boolean {
  return (card.execution_result || '').trim().toLowerCase() === 'failure'
}

/**
 * 非聚合分区普通卡的状态分类。
 * '' = 后端缺省（刚收录，未见 _parse_md 给出初始状态字段）→ 新进件 → 待审核。
 */
function classifyCard(sectionKey: string, card: WbCard): HomeRegionId | 'error' {
  // done 分区语义直通（complete/归档工作流的搬运终点）
  if (sectionKey === 'done') return 'recent'
  const status = (card.status || '').trim().toLowerCase()
  if (COMPLETED_STATUSES.has(status)) return 'recent'
  if (ATTENTION_STATUSES.has(status)) return 'attention'
  if (ACTIVE_STATUSES.has(status)) return isFailedExecution(card) ? 'attention' : 'today'
  if (INBOX_STATUSES.has(status) || status === '') return isFailedExecution(card) ? 'attention' : 'inbox'
  return 'error'
}

function keyOf(card: WbCard): string {
  return `${card.dir}/${card.file}`
}

/**
 * buildHomeModel(board, brief?, health?) → HomeModel
 *
 * brief/health 参与方式：brief 卡是「规则建议」独立区块（Task 4 已交付），
 * 不进四区；health 非 green 时「需要注意」的呈现由 Task 3 层负责。
 * 此处签名预留参数位以保证调用形稳定（未使用，标 _ 前缀）。
 */
export function buildHomeModel(
  board: Pick<WbBoard, 'sections' | 'today'>,
  _brief?: unknown,
  _health?: unknown,
): HomeModel {
  const todayRegion: HomeRegion = { id: 'today', count: 0, items: [] }
  const inboxRegion: HomeRegion = { id: 'inbox', count: 0, items: [] }
  const attentionItems: HomeItem[] = []
  const recentRegion: HomeRegion = { id: 'recent', count: 0, items: [] }
  const contractErrors: HomeContractError[] = []
  const skipped: HomeSkipped[] = []

  for (const section of board.sections ?? []) {
    // trash 整区跳过
    if (section.key === 'trash') {
      for (const f of section.files ?? []) skipped.push({ dir: f.dir, file: f.file, why: 'trash-partition' })
      continue
    }
    const isReviewable = REVIEWABLE_SECTIONS.has(section.key)

    // 聚合分区先做行内排序（保持 board.sections 原有顺序（mtime 倒序），此处不改序，仅分流）
    for (const card of section.files ?? []) {
      // 空聚合壳：仅聚合分区适用（单卡文件 entry_count 恒 0，见首轮 RED/GREEN 教训）
      if (isReviewable && (card.entry_count ?? 0) === 0 && (card.entries?.length ?? 0) === 0) {
        skipped.push({ dir: card.dir, file: card.file, why: 'empty-shell' })
        continue
      }

      if (isReviewable) {
        // 聚合卡＝待审核内容本体（新进来 / 已入库沉底除外）
        const verdict = classifyCard(section.key, card)
        if (verdict === 'error') {
          contractErrors.push({ card, reason: `未知状态 "${card.status}"（分区 ${section.key}）` })
          continue
        }
        if (verdict === 'recent') {
          // 聚合分区均为活动分区（thought/video/psych/dream），不可能来自 done 分区
          recentRegion.items.push({ card, side: 'active' })
        } else {
          // today/attention 语义理论上不出现在聚合分区，但若出现按原语义落位
          ;(verdict === 'attention' ? attentionItems : verdict === 'today' ? todayRegion.items : inboxRegion.items).push({ card, side: 'active' })
        }
        continue
      }

      const dest = classifyCard(section.key, card)
      if (dest === 'error') {
        contractErrors.push({ card, reason: `未知状态 "${card.status}"` })
        continue
      }
      if (dest === 'inbox') {
        // 今日到期（due===today）的待办升级进「今日」；其余新进/待办留在待审核
        inboxRegion.items.push({ card, side: 'active' })
        continue
      }
      if (dest === 'today') {
        todayRegion.items.push({ card, side: 'active' })
        continue
      }
      if (dest === 'attention') {
        attentionItems.push({ card, side: 'active' })
        continue
      }
      recentRegion.items.push({ card, side: section.key === 'done' ? 'done' : 'active' })
    }
  }

  // 特例提升：今日到期任务（due 精确等于 today）从收件箱提入今日区
  const promoted: WbCard[] = []
  for (const item of inboxRegion.items) {
    if (item.card.due && /^\d{4}-\d{2}-\d{2}$/.test(item.card.due) && item.card.due === board.today) {
      promoted.push(item.card)
    }
  }
  if (promoted.length > 0) {
    const promotedSet = new Set(promoted.map(keyOf))
    inboxRegion.items = inboxRegion.items.filter(i => !promotedSet.has(keyOf(i.card)))
    for (const c of promoted) todayRegion.items.push({ card: c, side: 'active' })
  }

  const needsDecision = attentionItems.filter(({ card }) => {
    const s = (card.status || '').trim().toLowerCase()
    return s === 'waiting_user' || (!ATTENTION_STATUSES.has(s) && !isFailedExecution(card))
  }).length
  const failures = attentionItems.length - needsDecision

  const regions: HomeRegion[] = [
    todayRegion,
    inboxRegion,
    { id: 'attention', count: attentionItems.length, items: attentionItems },
    recentRegion,
  ]
  for (const r of regions) r.count = r.items.length

  return {
    regions,
    contractErrors,
    skipped,
    totals: {
      today: todayRegion.count,
      inbox: inboxRegion.count,
      attention: { needsDecision, failures, total: attentionItems.length },
      recent: recentRegion.count,
      contractErrors: contractErrors.length,
    },
  }
}
