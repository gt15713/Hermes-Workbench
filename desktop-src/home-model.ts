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
import { isGlobalBatchRejection, validateBatchResponse } from './batch-response'

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
  /** WB-S1-041：完整 done/trash 只读归档模型（聚合所有同 key sections，保持后端顺序与来源）。 */
  archive: ArchiveModel
}

/** WB-S1-036：HomeView 展开状态与实际可见输出的最小生产 seam。 */
/** WB-S1-041：archiveOpen 让 Home 生产 seam 支持「归档/回收站」完整浏览模式。 */
export interface HomeViewState {
  showAllRegionId: HomeRegionId | null
  /** WB-S1-041：true = 进入归档/回收站完整浏览模式（与展开互斥）。 */
  archiveOpen?: boolean
  /** WB-S1-043 / FR-020：true = 显式多选模式（仅 home/expanded 生效；archive 只读时强制关闭）。 */
  multiSelectOpen?: boolean
  /** FR-020：稳定选中 identity 集合（`${dir}|${file}`）。与可见性解耦，跨视图切换保留。 */
  selectedIds?: string[]
}

export type HomeViewAction =
  | { type: 'show-all'; regionId: HomeRegionId }
  | { type: 'open-archive' }
  | { type: 'back' }
  | { type: 'enter-multiselect' }
  | { type: 'exit-multiselect' }
  | { type: 'toggle-select'; id: string }
  | { type: 'select-all-visible'; ids: string[] }
  | { type: 'clear-selection' }
  | { type: 'batch-settled' }
  | { type: 'batch-settle'; multiSelectOpen: boolean; selectedIds: string[] }

export const HOME_VIEW_INITIAL_STATE: HomeViewState = { showAllRegionId: null }

export interface HomeRegionPresentation extends HomeRegion {
  visibleItems: HomeItem[]
  canShowAll: boolean
}

export interface HomeViewPresentation {
  mode: 'home' | 'expanded' | 'archive'
  regions: HomeRegionPresentation[]
  expandedRegion: HomeRegionPresentation | null
  contractErrorBannerVisible: boolean
  /** 兼容入口在 Home 顶层渲染，预览与展开状态都必须可点击。 */
  legacyFallbackVisible: true
  /** WB-S1-041：Home 顶层「归档 / 回收站」入口在 home/expanded 模式可见。 */
  archiveEntryVisible: boolean
  /** WB-S1-041：进入 archive 模式后的完整 done/trash 只读模型；非 archive 模式为 null。 */
  archive: ArchiveModel | null
  /** WB-S1-043 / FR-020：多选模式与选中呈现（fail-closed 剪枝后；archive 只读时恒 false）。 */
  multiSelectOpen: boolean
  /** 已选数量（identity 集合长度；未知/不可选卡已被剪除）。 */
  multiSelectCount: number
  /** 当前模式可见卡 identity 列表（「全选当前可见」的候选；archive 模式为空）。 */
  multiSelectVisibleIds: string[]
  /** 剪枝后的选中 identity 列表（提交时使用）。 */
  selectedIds: string[]
  /** open && 已选>0；UI 据此启用确认动作。 */
  canSubmitBatch: boolean
  /** WB-S1-044：当前模式可见但只读（archived done provenance）行数——多选时诚实提示，不静默隐藏。 */
  multiSelectReadonlyCount: number
  /** WB-S1-044：每个动作的资格摘要（eligible/ineligible + 原因）；多选关闭或未选时为 null。 */
  batchActionEligibility: Record<HomeBatchAction, { eligibleCount: number; ineligibleCount: number; ineligible: Array<{ id: string; dir: string; file: string; reason: string }> }> | null
  /** WB-S1-047 / A1.1：原始选中中已失效（missing/archived/unknown）的 identity + 原因；仅展示、绝不提交。 */
  staleSelection: Array<{ id: string; reason: string }>
}

/** FR-020：视图切换（show-all/open-archive/back）保留选中状态，preview/back 不串项。 */
function pickMulti(state: HomeViewState): Pick<HomeViewState, 'multiSelectOpen' | 'selectedIds'> {
  return { multiSelectOpen: state.multiSelectOpen, selectedIds: state.selectedIds }
}

export function homeViewStateReducer(_state: HomeViewState, action: HomeViewAction): HomeViewState {
  switch (action.type) {
    case 'show-all':
      return { showAllRegionId: action.regionId, ...pickMulti(_state) }
    case 'open-archive':
      return { showAllRegionId: null, archiveOpen: true, ...pickMulti(_state) }
    case 'back':
      return { ...HOME_VIEW_INITIAL_STATE, ...pickMulti(_state) }
    case 'enter-multiselect':
      return { ..._state, multiSelectOpen: true }
    case 'exit-multiselect':
      return { ..._state, multiSelectOpen: false, selectedIds: [] }
    case 'toggle-select': {
      const ids = _state.selectedIds ?? []
      return {
        ..._state,
        selectedIds: ids.includes(action.id) ? ids.filter(id => id !== action.id) : [...ids, action.id],
      }
    }
    case 'select-all-visible':
      return { ..._state, selectedIds: action.ids }
    case 'clear-selection':
      return { ..._state, selectedIds: [] }
    case 'batch-settled':
      return { ..._state, multiSelectOpen: false, selectedIds: [] }
    case 'batch-settle':
      return { ..._state, multiSelectOpen: action.multiSelectOpen, selectedIds: action.selectedIds }
    default:
      return _state
  }
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
  const archiveOpen = state.archiveOpen === true

  // WB-S1-044 / FR-020 fail-closed：可选集只来自 active provenance（四区 items 中 side==='active'）。
  // done 分区归档卡（含投影进 recent 的 side==='done' 行）与 trash/archive entries 永不 selectable——
  // 归档只读边界由「可选集」强制，不靠隐藏控件（043 Blocker 1）。未知卡已收敛 contractErrors，天然不在。
  const selectableIds = new Set<string>()
  for (const region of model.regions) {
    for (const item of region.items) {
      if (item.side !== 'active') continue
      selectableIds.add(homeCardSelectionId(item.card))
    }
  }

  const multiSelectActive = state.multiSelectOpen === true && !archiveOpen
  // fail-closed 剪枝：只有模型已知 active provenance 卡能留在选中集（未知卡即使被塞进 state 也不计数、不入提交）
  const selectedIds = (state.selectedIds ?? []).filter(id => selectableIds.has(id))
  // WB-S1-047 / A1.1：保留「原始选中 → 当前可提交」的失效差集，供 UI 展示原因（board refresh 后
  // 原 selected ID 变 missing/archived/unknown）。差异项只显示、绝不进入 selectedIds 提交集。
  const staleSelectionVisible = multiSelectActive
    ? (state.selectedIds ?? []).filter(id => !selectableIds.has(id)).map(id => {
        const found = findCardById(model, id)
        const reason = found === 'contract-error'
          ? '状态未知，不可批处理'
          : found === null
            ? '条目已不在当前事实源（可能已在其他会话处理）'
            : found.side === 'done'
              ? '已归档，只读不可批处理'
              : '状态未知，不可批处理'
        return { id, reason }
      })
    : []
  // WB-S1-044：可见候选只含 active provenance；archived done 行保持可见但只读（诚实提示，不静默隐藏）。
  const visibleIds: string[] = []
  let readonlyVisibleCount = 0
  if (!archiveOpen) {
    const source = expandedRegion ? [expandedRegion] : regions
    for (const region of source) {
      for (const item of region.visibleItems) {
        if (item.side === 'active') visibleIds.push(homeCardSelectionId(item.card))
        else readonlyVisibleCount += 1
      }
    }
  }
  // WB-S1-044 / A2：单一资格映射（派生自 dashboard/contract.py 迁移表 + plugin_api.py /batch
  // 单条 handler；不在 UI 发明第二套状态词表；unknown/归档/已移除 identity 一律 fail closed）
  const batchActionEligibility: HomeViewPresentation['batchActionEligibility'] =
    multiSelectActive && selectedIds.length > 0
      ? Object.fromEntries(
          HOME_BATCH_ACTIONS.map(action => [
            action,
            summarizeEligibility(computeBatchActionEligibility(model, selectedIds, action)),
          ]),
        ) as HomeViewPresentation['batchActionEligibility']
      : null

  return {
    mode: archiveOpen ? 'archive' : expandedRegion ? 'expanded' : 'home',
    regions,
    expandedRegion: archiveOpen ? null : expandedRegion,
    contractErrorBannerVisible: model.contractErrors.length > 0,
    legacyFallbackVisible: true,
    archiveEntryVisible: true,
    archive: archiveOpen ? model.archive : null,
    multiSelectOpen: multiSelectActive,
    multiSelectCount: selectedIds.length,
    multiSelectVisibleIds: visibleIds,
    selectedIds,
    canSubmitBatch: multiSelectActive && selectedIds.length > 0,
    multiSelectReadonlyCount: multiSelectActive ? readonlyVisibleCount : 0,
    batchActionEligibility,
    staleSelection: staleSelectionVisible,
  }
}

function findCardById(model: HomeModel, id: string): { side: 'done' | 'active' } | 'contract-error' | null {
  for (const region of model.regions) {
    for (const item of region.items) {
      if (homeCardSelectionId(item.card) === id) return { side: item.side }
    }
  }
  for (const err of model.contractErrors) {
    if (homeCardSelectionId(err.card) === id) return 'contract-error'
  }
  return null
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
    // WB-S1-041：完整 done/trash 只读归档模型（复用同一 /board sections，
    // 聚合所有同 key sections；不在 HomeModel 中复制数据库/新增 schema/API）。
    archive: buildArchiveModel(board),
  }
}

/**
 * WB-S1-040 / FR-040：独立归档只读浏览（source/test only）。
 *
 * buildHomeModel 把 done 分区语义直通为 recent、trash 整区跳过 —— 这是 Home
 * 的投影口径，不是完整归档视图。FR-040 要求独立浏览**完整** done 与 trash
 * partitions（旧版 Board 的完整分区列表能力）。本函数提供最小只读 archive
 * surface：复用同一 /board sections，不复制数据库、不新增 schema/API，
 * 不修改输入，不做分区语义猜测（状态分类仍只由 buildHomeModel 负责）。
 */
export interface ArchiveEntry {
  card: WbCard
  /** 来源分区：'done' = 完成归档分区；'trash' = 回收站分区。 */
  partition: 'done' | 'trash'
}

export interface ArchivePartition {
  count: number
  entries: ArchiveEntry[]
}

export interface ArchiveModel {
  done: ArchivePartition
  trash: ArchivePartition
}

export function buildArchiveModel(board: Pick<WbBoard, 'sections'>): ArchiveModel {
  // WB-S1-041：/board 每一 section 来自一个配置分区（key=type），配置允许
  // 用户自定义分区且不保证 done/trash 各只有一节 —— 聚合所有同 key sections，
  // 保持后端顺序（sections 顺序 + 分区内 files 顺序）与来源（card.dir 可溯源）。
  const collect = (partition: 'done' | 'trash'): ArchivePartition => {
    const entries: ArchiveEntry[] = []
    for (const section of board.sections ?? []) {
      if (section.key !== partition) continue
      for (const card of section.files ?? []) entries.push({ card, partition })
    }
    return { count: entries.length, entries }
  }
  return { done: collect('done'), trash: collect('trash') }
}

// ── WB-S1-043 / FR-020：多选/批处理等价（source/test-only）────────────
/** 既有 /batch 端点允许的四类动作（dashboard/plugin_api.py L917-924 实证）。禁止新增 delete。 */
export const HOME_BATCH_ACTIONS = ['complete', 'resolve', 'to-task', 'trash'] as const
export type HomeBatchAction = (typeof HOME_BATCH_ACTIONS)[number]
export const HOME_BATCH_ACTION_LABEL: Record<HomeBatchAction, string> = {
  complete: '完成',
  resolve: '处理',
  'to-task': '移入任务',
  trash: '回收站',
}

/** 稳定选择 identity：`${dir}|${file}`。dir/file 不含 '|'（分区目录/文件名），首 '|' 分隔可逆。 */
export function homeCardSelectionId(card: { dir: string; file: string }): string {
  return `${card.dir}|${card.file}`
}

/** identity → {dir,file}；非法 identity 抛错（调用方应先经可选集校验）。 */
export function homeSelectionIdToParts(id: string): { dir: string; file: string } {
  const sep = id.indexOf('|')
  if (sep <= 0 || sep === id.length - 1) throw new Error(`invalid selection id: ${id}`)
  return { dir: id.slice(0, sep), file: id.slice(sep + 1) }
}

/**
 * 构造 /batch 提交（FR-020 确认动作）：只复用既有允许动作；只纳入模型已知状态卡；
 * 未知/fail-closed 卡与不存在 identity 一律剔除；结果为空 → null（fail-closed，不静默空批）。
 */
export function buildHomeBatchSubmission(
  ids: string[],
  action: HomeBatchAction,
  model: HomeModel,
): { action: HomeBatchAction; items: Array<{ dir: string; file: string }> } | null {
  // WB-S1-044：批处理候选只来自 active provenance（043 Blocker 1）；去重后逐项 fail-closed。
  const selectable = new Set<string>()
  for (const region of model.regions) {
    for (const item of region.items) {
      if (item.side !== 'active') continue
      selectable.add(homeCardSelectionId(item.card))
    }
  }
  // WB-S1-046 / A1-RED-3：输入 ids 重复本身即 fail-closed——不得去重后继续提交。
  // stale/direct duplicate 集合必须不调用 transport（CoderX Blocker2 字面语义）。
  if (new Set(ids).size !== ids.length) return null
  const items: Array<{ dir: string; file: string }> = []
  for (const id of ids) {
    if (!selectable.has(id)) continue // fail-closed：未知/不可选不纳入
    try {
      const { dir, file } = homeSelectionIdToParts(id)
      items.push({ dir, file })
    } catch {
      continue
    }
  }
  if (items.length === 0) return null
  // WB-S1-045 / A3：transport 边界用同一 policy 复核「全部 selected 对本 action 合法」。
  // stale presentation / direct call 的任意不合法/unknown/归档/已移除 identity
  // （混合选择也照此）→ fail closed，返回 null，绝不调用 transport。
  const eligibility = computeBatchActionEligibility(model, ids, action)
  if (eligibility.ineligible.length > 0 || eligibility.eligible.length !== new Set(ids).size) return null
  return { action, items }
}

// ── WB-S1-044 / FR-020 fail-closed：资格映射 + 响应结算（可测试 seam）────────
/** 收件箱分区目录（resolve/to-task 的 /batch 单条 handler 硬��码集合，plugin_api.py 实证）。 */
const BATCH_INBOX_DIRS = new Set(['待验证', '待回看', '梦中的邮件', '心理学随想'])

/** WB-S1-046：trash 分区目录白名单 = dashboard/contract.py PARTITIONS 全量 dir 镜像
 *  （后端 /trash 实证：dirname 必须在分区目录集合）。未知 dir → 一律 ineligible（drift gate）。 */
const BATCH_TRASH_DIRS = new Set(['待验证', '待回看', '任务', '心理学随想', '梦中的邮件', '已处理', '回收站'])

export interface BatchIneligibility { id: string; dir: string; file: string; reason: string }

/** A2 单一资格映射（唯一词表）：规则派生自 dashboard/contract.py _TRANSITIONS 与 plugin_api.py
 *  /batch 单条 handler（resolve/to_task/complete/trash）；dashboard/test_batch_eligibility.py
 *  镜像断言同一规则。unknown / 归档 provenance / 已从当前事实源移除的 identity 一律 fail closed；
 *  输入去重（重复 identity 只评估一次）。 */
export function computeBatchActionEligibility(
  model: HomeModel,
  ids: string[],
  action: HomeBatchAction,
): { eligible: string[]; ineligible: BatchIneligibility[] } {
  const byId = new Map<string, { card: WbCard; side: 'done' | 'active' }>()
  for (const region of model.regions) {
    for (const item of region.items) byId.set(homeCardSelectionId(item.card), { card: item.card, side: item.side })
  }
  const eligible: string[] = []
  const ineligible: BatchIneligibility[] = []
  for (const id of new Set(ids)) {
    const found = byId.get(id)
    if (!found || found.side !== 'active') {
      const parts = safeIdParts(id)
      ineligible.push({ id, dir: parts.dir, file: parts.file, reason: '已归档 / 未知状态 / 已不在当前事实源，批处理不适用' })
      continue
    }
    const card = found.card
    // WB-S1-046 / A1-RED-4/7：状态规范化与生产 handler 精确一致——/complete 实证
    // `current_status = str(frontmatter.get("status") or "").strip()`（不 lower）；file 级
    // resolve/complete 用 `_replace_frontmatter_status` 精确小写匹配；execution_result 实证
    // `.strip().lower()`。因此 status 只 trim 不 lower（大写/空白一律 fail closed），
    // execution_result 才 trim+lower。前端任何宽松化都会 pre-authorize 后端拒绝的请求。
    const status = (card.status || '').trim()
    const execResult = (card.execution_result || '').trim().toLowerCase()
    let reason: string | null = null
    if (action === 'complete') {
      // WB-S1-047 / A2：与 dashboard/batch_policy.is_eligible 逐格一致（机械 drift gate）——
      // 精确镜像 plugin_api.py /complete 实证四态：
      //   todo(任意 exec) / in_progress+success / done+success(兼容，lower 比较) / completed(幂等)。
      const isTodo = status === 'todo'
      const isInProgressSuccess = status === 'in_progress' && execResult === 'success'
      const isDoneSuccess = status.toLowerCase() === 'done' && execResult === 'success'
      const isCompleted = status === 'completed'
      if (!isTodo && !isInProgressSuccess && !isDoneSuccess && !isCompleted) {
        reason = `状态 ${status || '（空）'}——仅 todo、执行中(execution_result=success)、done+success、completed 可「完成」`
      }
    } else if (action === 'trash') {
      // WB-S1-046：trash 镜像后端 dir 白名单；未知分区一律 fail closed。
      if (!BATCH_TRASH_DIRS.has(card.dir)) reason = `分区 ${card.dir || '（空）'} 不在当前事实源分区白名单`
    } else if (action === 'resolve' || action === 'to-task') {
      // WB-S1-047 / A2：resolve/to-task 镜像单项 handler 实证——仅分区白名单，不校验 status
      // （queued/blank/大写/空白均可归档，保留 legacy 成功请求；不得静默收窄）。
      if (!BATCH_INBOX_DIRS.has(card.dir)) reason = `仅收件箱分区（待验证/待回看/梦中的邮件/心理学随想）可${action === 'resolve' ? '确认处理' : '转任务'}`
    }
    // trash：对任何 active provenance 卡可用（后端仅校验分区目录；archive 已被可选集排除）
    if (reason) ineligible.push({ id, dir: card.dir, file: card.file, reason })
    else eligible.push(id)
  }
  return { eligible, ineligible }
}

function safeIdParts(id: string): { dir: string; file: string } {
  try { return homeSelectionIdToParts(id) } catch { return { dir: '', file: id } }
}

function summarizeEligibility(r: { eligible: string[]; ineligible: BatchIneligibility[] }) {
  return { eligibleCount: r.eligible.length, ineligibleCount: r.ineligible.length, ineligible: r.ineligible }
}

// ── A3：busy/concurrency guard（可测试；第二次提交不调用 transport，非仅注释）──
export class BatchGate {
  private held = false
  tryAcquire(): boolean { if (this.held) return false; this.held = true; return true }
  release(): void { this.held = false }
}

export async function guardedSubmit<T>(gate: BatchGate, transport: () => Promise<T>): Promise<T | null> {
  if (!gate.tryAcquire()) return null
  try { return await transport() } finally { gate.release() }
}

// ── A3：response settlement seam（全成功/部分/全失败/ok=false/畸形/transport）──
export interface BatchFailedItem { id: string; dir: string; file: string; reason: string }
export type BatchSettleInput =
  | { transportError: string }
  | { ok: boolean; done?: Array<{ dir?: string; file?: string; entry?: string }>; failed?: Array<{ dir?: string; file?: string; entry?: string; error?: string }>; summary?: { ok?: number; fail?: number }; error?: string }
export interface BatchSettlement {
  settledCleanly: boolean
  keepOpen: boolean
  selectedIds: string[]
  removedCount: number
  failedDetail: BatchFailedItem[]
  overallError: string | null
}

export function settleBatchResponse(
  _state: HomeViewState,
  input: BatchSettleInput,
  submittedIds: string[],
): BatchSettlement {
  const submitted = uniq(submittedIds)
  const submittedSet = new Set(submitted)
  const originalSelected = uniq(_state.selectedIds ?? submitted)
  const staleIds = originalSelected.filter(id => !submittedSet.has(id))
  const preserveWithStale = (ids: string[]) => uniq([...ids, ...staleIds])
  if ('transportError' in input) {
    return { settledCleanly: false, keepOpen: true, selectedIds: preserveWithStale(submitted), removedCount: 0, failedDetail: [], overallError: input.transportError }
  }
  const { ok, done, failed, summary, error } = input
  const wire = validateBatchResponse(input)
  if (!wire.valid) {
    return { settledCleanly: false, keepOpen: true, selectedIds: preserveWithStale(submitted), removedCount: 0, failedDetail: protocolFailedDetails(failed), overallError: `${wire.error}${error ? `；后端错误：${error}` : ''}。未移除任何条目，保留全部所选` }
  }
  if (isGlobalBatchRejection(wire.response)) {
    return { settledCleanly: false, keepOpen: true, selectedIds: preserveWithStale(submitted), removedCount: 0, failedDetail: [], overallError: wire.response.error }
  }
  const doneItems = Array.isArray(done) ? done : null
  const failedItems = Array.isArray(failed) ? failed : null
  // WB-S1-046 / A1-RED-1/2：summary 是协议强制字段——缺失/null/字符串/NaN/Infinity/
  // 负数/小数一律 protocol error；且 ok/fail 必须为 finite 非负整数并与数组严格相等。
  // 合法响应定义（后端 /batch 实证 L962）：{ok: not failed or bool(done), summary:{ok:len(done), fail:len(failed)}}。
  const summaryRequired =
    summary !== undefined &&
    summary !== null &&
    typeof summary.ok === 'number' &&
    typeof summary.fail === 'number' &&
    Number.isFinite(summary.ok) &&
    Number.isFinite(summary.fail) &&
    Number.isInteger(summary.ok) &&
    Number.isInteger(summary.fail) &&
    summary.ok >= 0 &&
    summary.fail >= 0
  if (!summaryRequired) {
    return { settledCleanly: false, keepOpen: true, selectedIds: preserveWithStale(submitted), removedCount: 0, failedDetail: [], overallError: `批量响应协议错误：summary 缺失或畸形（必须为 finite 非负整数 ok/fail）${error ? `；后端错误：${error}` : ''}。未移除任何条目，保留全部所选` }
  }
  // WB-S1-047 / A1.2：done 与 failed 都是合法 /batch 响应的必需数组——任一缺失
  // （即使 summary 或另一数组完整）都是 protocol error，保留全部选择且不 invalidate、不推断成功。
  if (doneItems === null || failedItems === null) {
    return { settledCleanly: false, keepOpen: true, selectedIds: preserveWithStale(submitted), removedCount: 0, failedDetail: [], overallError: '批量响应协议错误：done 或 failed 数组缺失（二者均为必需字段），未移除任何条目，保留全部所选' }
  }

  // ── WB-S1-045 / A2 精确身份对账（合法响应定义）──────────────────────────
  // done/failed 每项 identity 非空、各自唯一、均属于 submitted；集合不相交；
  // 并集与去重后 submitted 完全相等；summary 数字与数组长度精确一致；
  // 顶层 ok 必须兼容后端语义 ok = (failed 空) 或 (done 非空)。
  const doneParsed: string[] = []
  const failedParsed: BatchFailedItem[] = []
  const problems: string[] = []

  for (const raw of doneItems ?? []) {
    const p = ident(raw)
    if (!p) { problems.push('done 含空 identity'); continue }
    doneParsed.push(p.id)
    if (!submittedSet.has(p.id)) problems.push(`done 含外来 identity「${p.id}」`)
  }
  for (const raw of failedItems ?? []) {
    const p = ident(raw)
    if (!p) {
      problems.push('failed 含空 identity')
      // 逐项可安全展示的信息仍保留（无 dir/file 的畸形行以空 identity 标记）
      failedParsed.push({ id: '', dir: raw?.dir ?? '', file: raw?.file ?? '', reason: raw?.error ?? '（无 dir/file 的畸形行）' })
      continue
    }
    failedParsed.push({ id: p.id, dir: p.dir, file: p.file, reason: raw?.error ?? 'failed' })
    if (!submittedSet.has(p.id)) problems.push(`failed 含外来 identity「${p.id}」`)
  }
  if (new Set(doneParsed).size !== doneParsed.length) problems.push('done 含重复 identity')
  const failedIds = failedParsed.filter(f => f.id !== '').map(f => f.id)
  if (new Set(failedIds).size !== failedIds.length) problems.push('failed 含重复 identity')
  const doneSet = new Set(doneParsed)
  const failedSet = new Set(failedIds)
  const overlap = [...doneSet].filter(id => failedSet.has(id))
  if (overlap.length > 0) problems.push(`done/failed 交集「${overlap.join('、')}」`)
  const union = new Set([...doneSet, ...failedSet])
  if (union.size !== submitted.length || !submitted.every(id => union.has(id))) {
    problems.push('done∪failed 与 submitted 不完全相等（缺项或多余）')
  }
  if (summaryRequired) {
    const okCount = summary!.ok
    const failCount = summary!.fail
    if (okCount !== doneParsed.length || failCount !== failedIds.length) {
      problems.push(`summary 计数与数组不一致（ok=${okCount}≠done=${doneParsed.length}；fail=${failCount}≠failed=${failedIds.length}）`)
    }
  }
  // WB-S1-046 / A1-RED-2：顶层 ok 必须与后端公式 ok = (failed 空) 或 (done 非空) 完全一致。
  // ok=true + done=[] + failed=全部：后端 all-failed 时 ok=false，此处必须 protocol error（不能降级为部分成功）。
  const backendOkFormula = failedIds.length === 0 || doneParsed.length > 0
  if (ok !== backendOkFormula) {
    problems.push(`顶层 ok=${ok} 与后端真值表矛盾（failed=${failedIds.length} 项、done=${doneParsed.length} 项；后端公式 ok=(failed空)或(done非空) → 期望 ${backendOkFormula}）`)
  }

  if (problems.length > 0) {
    // protocol error：保留全部 submitted identities、不推断任何成功、不 invalidate、
    // 保持多选、显示可行动总体错误与可安全展示的逐项信息。
    return {
      settledCleanly: false,
      keepOpen: true,
      selectedIds: preserveWithStale(submitted),
      removedCount: 0,
      failedDetail: failedParsed,
      overallError: `批量响应协议错误：${problems.join('；')}。未移除任何条目、不推断成功，保留全部所选可重试`,
    }
  }

  if (failedIds.length > 0 || ok === false) {
    // 部分成功：只保留精确 failed identities；全失败：保留全部失败 identities。
    return { settledCleanly: false, keepOpen: true, selectedIds: preserveWithStale(failedIds), removedCount: doneParsed.length, failedDetail: failedParsed, overallError: staleIds.length > 0 ? '仍有未提交的失效选择；请逐项取消选择、点击 Clear 或退出多选以明确清理' : null }
  }
  if (doneParsed.length > 0) {
    if (staleIds.length > 0) {
      return { settledCleanly: false, keepOpen: true, selectedIds: staleIds, removedCount: doneParsed.length, failedDetail: [], overallError: '可提交项已成功；仍有未提交的失效选择，请逐项取消选择、点击 Clear 或退出多选以明确清理' }
    }
    // 全成功：才退出多选并清空。
    return { settledCleanly: true, keepOpen: false, selectedIds: [], removedCount: doneParsed.length, failedDetail: [], overallError: null }
  }
  return { settledCleanly: false, keepOpen: true, selectedIds: preserveWithStale(submitted), removedCount: 0, failedDetail: [], overallError: '批量结果无法判定（无成功项），选择保留，可重试' }
}

function protocolFailedDetails(value: unknown): BatchFailedItem[] {
  if (!Array.isArray(value)) return []
  return value.map(raw => {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
      return { id: '', dir: '', file: '', reason: '（畸形 failed 行）' }
    }
    const row = raw as { dir?: unknown; file?: unknown; error?: unknown }
    const dir = typeof row.dir === 'string' ? row.dir : ''
    const file = typeof row.file === 'string' ? row.file : ''
    const reason = typeof row.error === 'string' && row.error.length > 0 ? row.error : '（畸形 failed 行）'
    return { id: dir && file ? `${dir}|${file}` : '', dir, file, reason }
  })
}

/** 解析响应行 identity；dir/file 任一缺失 → null（畸形/空 identity）。 */
function ident(raw?: { dir?: string; file?: string }): { id: string; dir: string; file: string } | null {
  if (!raw || !raw.dir || !raw.file) return null
  return { id: `${raw.dir}|${raw.file}`, dir: raw.dir, file: raw.file }
}
function uniq<T>(xs: T[]): T[] { return [...new Set(xs)] }
