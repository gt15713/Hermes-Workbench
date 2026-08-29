/**
 * Workbench 默认首页 —— HomeView 与首页区域组件（Task 3 v2 · 2026-08-27 结构纠偏）。
 *
 * 从 board.tsx 逐字搬移（纯重构，渲染行为零变更）：
 * - HomeView：唯一数据口径 buildHomeModel(board) 四区投影；
 * - 宽屏 今日/待审核/需要注意 三主区 + 最近完成在下方，窄屏单列；
 * - BriefCardView / TodayCardRow / HomeRegionCardList / HOME_EMPTY_HINTS 为首页专属组件与文案；
 * - BRIEF_TYPE_META 为规则建议卡类型图标映射（首页专用）。
 * board.tsx 只保留数据加载、路由状态与 callbacks 传递。
 */

import { cn, Codicon, host, useQuery } from '@hermes/plugin-sdk'
import { useEffect, useMemo, useReducer, useState } from 'react'

import { fetchBrief, fetchHealth, fetchSearch, ingestMessage, invalidateBoard, type WbBriefCard } from './api'
import { homeCardPrimaryAction } from './card-action'
import {
  HOME_VIEW_INITIAL_STATE,
  buildHomeModel,
  buildHomeViewPresentation,
  homeViewStateReducer,
  type HomeRegionId,
  type HomeRegionPresentation,
} from './home-model'
import { healthCheckTone, healthSemanticFor, homeSearchFeedback, searchResultToCard } from './home-search'
import { isOverdue, priorityMeta, STATUS_TONE, type WbBoard, type WbCard } from './types'

// ── Today view（P0-1，B4）─────────────────────────────────────────────
// UX Spec S1 v2（Task 3，2026-08-27）：默认首页 = buildHomeModel 四区投影。
// 宽屏 今日/待审核/需要注意 三主区 + 最近完成在下方；窄屏 flex-wrap 单列。
// 唯一数据口径：home-model.buildHomeModel —— 视图不再自行 filter board.sections。
// 旧横向七列看板/表格移入「旧版数据」二级入口（showLegacy 分支），实现与数据不删。

const BRIEF_TYPE_META: Record<string, { icon: string; label: string }> = {
  new_task: { icon: 'lightbulb', label: '新任务' },
  duplicate: { icon: 'warning', label: '重复' },
  blocked: { icon: 'stop', label: '阻塞' },
  overdue: { icon: 'calendar', label: '过期重估' },
  decision: { icon: 'question', label: '需决策' },
}

function TodayCardRow({ card, onPreview }: { card: WbCard; onPreview: (c: WbCard) => void }) {
  const tone = STATUS_TONE[card.status] || 'var(--ui-text-tertiary)'
  const prio = priorityMeta(card.priority || '')
  // Task 4（2026-08-27）：一卡一主操作——统一映射给标签；具体动作枢纽在抽屉。
  const primary = homeCardPrimaryAction(card)
  return (
    <div
      className="flex w-full items-center gap-2 rounded-md border border-(--ui-stroke-secondary) px-2.5 py-1.5 transition-colors hover:border-(--ui-accent)"
      onClick={() => onPreview(card)}
      role="button"
      tabIndex={0}
      onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onPreview(card) } }}
    >
      <span className="size-1.5 shrink-0 rounded-full" style={{ background: tone }} />
      {prio && <span className="h-3 w-0.5 shrink-0 rounded" style={{ background: prio.fg }} />}
      <span className="min-w-0 flex-1 truncate text-[0.75rem] font-medium text-(--ui-text-primary)">
        {card.title || card.file.replace(/\.md$/, '')}
      </span>
      {card.due && (
        <span className={cn('shrink-0 text-[0.75rem]', isOverdue(card.due) ? 'font-semibold text-(--ui-red)' : 'text-(--ui-text-tertiary)')}>
          {card.due}
        </span>
      )}
      {primary && (
        <button
          type="button"
          data-wb-primary={primary.kind}
          title={primary.reason}
          className="shrink-0 rounded border border-(--ui-accent)/40 bg-(--ui-accent)/10 px-2 py-0.5 text-[0.75rem] font-medium text-(--ui-accent) hover:bg-(--ui-accent)/20"
          onClick={e => { e.stopPropagation(); onPreview(card) }}
        >
          {primary.label}
          <span className="ml-1 hidden text-[0.6875rem] font-normal text-(--ui-text-quaternary) sm:inline">为什么</span>
        </button>
      )}
    </div>
  )
}

function BriefCardView({ card, onAccept, onIgnore }: { card: WbBriefCard; onAccept?: () => void; onIgnore: () => void }) {
  const meta = BRIEF_TYPE_META[card.type] ?? { icon: 'info', label: card.type }
  return (
    <div className="flex items-start gap-2 rounded-md border border-(--ui-stroke-secondary) px-2.5 py-2">
      <Codicon name={meta.icon} size="0.8rem" className="mt-0.5 shrink-0" style={{ color: 'var(--ui-accent)' }} />
      <div className="min-w-0 flex-1">
        <div className="text-[0.8125rem] font-semibold text-(--ui-text-primary)">{card.title}</div>
        <div className="mt-0.5 text-[0.75rem] text-(--ui-text-tertiary)">{card.reason}</div>
        <div className="mt-0.5 text-[0.6875rem] font-medium text-(--ui-accent)">建议动作：查看右侧主按钮；其余操作在详情抽屉</div>
        <details className="mt-1 text-[0.75rem] text-(--ui-text-quaternary)">
          <summary className="cursor-pointer">查看依据</summary>
          <ul className="mt-1 list-disc pl-4">
            {card.evidence.map(item => <li key={item}>{item}</li>)}
          </ul>
        </details>
        <div className="mt-1 flex items-center gap-1">
          {onAccept && (
            <button
              className="rounded bg-(--ui-accent)/15 px-2 py-1 text-[0.75rem] text-(--ui-accent) hover:bg-(--ui-accent)/25"
              onClick={onAccept}
              type="button"
            >
              采纳
            </button>
          )}
          <button
            className="rounded px-2 py-1 text-[0.75rem] text-(--ui-text-tertiary) hover:bg-(--ui-stroke-secondary)"
            onClick={onIgnore}
            type="button"
          >
            忽略
          </button>
        </div>
      </div>
      <span className="shrink-0 rounded bg-(--ui-bg-quinary) px-1 py-0.5 text-[0.75rem] text-(--ui-text-quaternary)">
        规则建议
      </span>
    </div>
  )
}

function HomeRegionCardList({ items, totalCount, canShowAll, onPreview, onShowAll }: {
  items: { card: WbCard }[]
  totalCount: number
  canShowAll: boolean
  onPreview: (c: WbCard) => void
  onShowAll: () => void
}) {
  return (
    <>
      {items.map(({ card }) => (
        <TodayCardRow key={`${card.dir}/${card.file}`} card={card} onPreview={onPreview} />
      ))}
      {canShowAll && (
        <button
          type="button"
          data-wb-show-all
          className="self-start rounded border border-(--ui-accent)/40 bg-(--ui-accent)/10 px-2 py-1 text-[0.75rem] font-medium text-(--ui-accent) hover:bg-(--ui-accent)/20"
          onClick={onShowAll}
        >
          查看全部 {totalCount} 项 →
        </button>
      )}
    </>
  )
}

/** WB-S1-034/036：全量列表二级视图（FR-040/FR-020 完整列表切片，归档等价仍未关闭）。
 *  复用同一 buildHomeModel + buildHomeViewPresentation 投影（唯一事实源）；
 *  首页保持 limit=8 克制，仅在用户点击「查看全部」后由 reducer 进入完整密度。
 *  recent 诚实混合 done 归档与 active 已完成来源，不把完成误称为已归档；
 *  未知状态仍 fail-closed 收敛到 contractErrors，由 HomeView 顶层横幅提示。 */
function HomeAllRegionList({ region, onBack, onPreview }: {
  region: HomeRegionPresentation
  onBack: () => void
  onPreview: (c: WbCard) => void
}) {
  const title = region.id === 'today' ? '今日'
    : region.id === 'inbox' ? '待审核'
      : region.id === 'attention' ? '需要注意' : '最近完成'
  const archivedCount = region.id === 'recent' ? region.visibleItems.filter(i => i.side === 'done').length : 0
  const activeDoneCount = region.id === 'recent' ? region.visibleItems.filter(i => i.side === 'active').length : 0
  return (
    <div className="flex flex-1 flex-col gap-2 overflow-y-auto px-3 pb-3">
      <div className="flex items-center gap-2 pt-2">
        <button
          type="button"
          data-wb-show-all-back
          className="rounded border border-(--ui-stroke-secondary) px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary)"
          onClick={onBack}
        >
          ← 返回首页
        </button>
        <span className="text-[0.8125rem] font-semibold text-(--ui-text-primary)">{title} · 全部</span>
        <span className="text-[0.75rem] tabular-nums text-(--ui-text-quaternary)">{region.count} 项</span>
        <span className="rounded bg-(--ui-bg-quinary) px-1 py-0.5 text-[0.6875rem] text-(--ui-text-quaternary)">
          {region.id === 'recent'
            ? region.visibleItems.length === 0
              ? '最近完成（混合投影）'
              : `已归档 ${archivedCount} · 已完成未归档 ${activeDoneCount}`
            : '活动任务（active 侧投影）'}
        </span>
      </div>
      <div className="flex flex-col gap-1.5">
        {region.visibleItems.map(({ card }) => (
          <TodayCardRow key={`${card.dir}/${card.file}`} card={card} onPreview={onPreview} />
        ))}
      </div>
    </div>
  )
}

/** 各区域专属空状态文案 —— 空 ≠ 加载 ≠ 失败，四种反馈互不复用。 */
const HOME_EMPTY_HINTS: Record<string, string> = {
  today: '今天没有安排 🎉 手机转发到 QQ 群会自动收录进工作台',
  inbox: '待审核是空的——手机收进来的内容会先出现在这里等你过目',
  attention: '没有需要你拍板或修复的事情',
  recent: '还没有完成记录——处理完的第一件事会出现在这里',
}

/**
 * Task 3：默认首页。唯一数据口径 buildHomeModel(board)；brief/health 经
 * 同名 queryKey 共享缓存（页头已建立连接，不产生第二份请求）。
 * - 宽屏（lg+）：今日/待审核/需要注意 三主区横排；窄屏单列堆叠；
 * - 「最近完成」在主区下方；
 * - 未知状态 fail-closed 条：contractErrors 非空时可见提示，绝不静默吞卡；
 * - 健康降级作为独立反馈条呈现在注意区之下（loading/empty/unreachable 三态互异）。
 */
export function HomeView({ board, onPreview, onOpenLegacy }: {
  board: WbBoard
  onPreview: (c: WbCard) => void
  onOpenLegacy: () => void
}) {
  const [ignored, setIgnored] = useState<Set<string>>(new Set())
  const [viewState, dispatchView] = useReducer(homeViewStateReducer, HOME_VIEW_INITIAL_STATE)
  const { data: brief } = useQuery({
    queryKey: ['workbench', 'brief'],
    queryFn: fetchBrief,
    staleTime: 30 * 60 * 1000,
  })
  const health = useQuery({ queryKey: ['workbench', 'health'], queryFn: fetchHealth, refetchInterval: 30_000 })

  const model = useMemo(() => buildHomeModel(board), [board])
  const presentation = useMemo(() => buildHomeViewPresentation(model, viewState), [model, viewState])

  const acceptBrief = async (card: WbBriefCard) => {
    if (card.type !== 'new_task') return
    try {
      const res = await ingestMessage(`brief-${Date.now()}`, '待验证', card.title)
      if (res.ok) {
        host.notify({ kind: 'success', message: '已加入待验证' })
        invalidateBoard()
        setIgnored(prev => new Set(prev).add(card.title))
      } else {
        host.notify({ kind: 'warning', message: res.error || '采纳失败' })
      }
    } catch (err) {
      host.notify({ kind: 'error', message: String(err) })
    }
  }

  const visibleCards = (brief?.cards ?? []).filter(c => !ignored.has(c.title)).slice(0, 5)

  // Task 6（2026-08-27）：顶部常驻搜索——复用既有 /search，不建第二索引
  const [searchQ, setSearchQ] = useState('')
  const [debouncedQ, setDebouncedQ] = useState('')
  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedQ(searchQ.trim()), 250)
    return () => window.clearTimeout(t)
  }, [searchQ])
  const { data: searchData, isLoading: searchLoading, error: searchError } = useQuery({
    queryKey: ['workbench', 'home-search', debouncedQ],
    queryFn: () => fetchSearch(debouncedQ),
    enabled: debouncedQ.length > 0,
    retry: 1,
  })
  const searchFeedback = homeSearchFeedback({
    hasQuery: debouncedQ.length > 0,
    isLoading: searchLoading,
    error: searchError,
    data: searchData ?? null,
  })
  const openResult = (r: ReturnType<typeof searchResultToCard>) => {
    onPreview(r)
    setSearchQ(''); setDebouncedQ('')
  }

  const todayRegion = presentation.regions.find(r => r.id === 'today')!
  const inboxRegion = presentation.regions.find(r => r.id === 'inbox')!
  const attentionRegion = presentation.regions.find(r => r.id === 'attention')!
  const recentRegion = presentation.regions.find(r => r.id === 'recent')!
  const mainRegions = [todayRegion, inboxRegion, attentionRegion]
  const showAllRegion = presentation.expandedRegion
  const openShowAll = (regionId: HomeRegionId) => dispatchView({ type: 'show-all', regionId })

  // 健康反馈（Task 6 统一口径）：三色收敛 + unreachable 独立分支
  const healthState: 'loading' | 'ok' | 'degraded' | 'unreachable'
    = health.isLoading ? 'loading'
      : health.error ? 'unreachable'
        : !health.data || health.data.status === 'green' || health.data.status === 'disabled' ? 'ok'
          : 'degraded'

  return (
    <div className="flex flex-1 flex-col overflow-y-auto px-3 pb-3">
      <p className="mt-2 px-1 text-[0.8125rem] text-(--ui-text-tertiary)">
        手机收进来的东西，在这里审核、继续、沉淀。
      </p>

      {/* Task 6：顶部常驻搜索（复用既有 /search 与索引） */}
      <div className="relative mt-1 px-1">
        <input
          type="text"
          data-wb-home-search
          value={searchQ}
          onChange={e => setSearchQ(e.target.value)}
          onKeyDown={e => { if (e.key === 'Escape') { setSearchQ(''); setDebouncedQ('') } }}
          placeholder="搜索任务、内容、标签…"
          className="h-8 w-full rounded-md border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) px-3 text-[0.8125rem] text-(--ui-text-primary) placeholder:text-(--ui-text-quaternary) focus:border-(--ui-accent) focus:outline-none"
        />
        {debouncedQ.length > 0 && searchFeedback.kind !== 'idle' && (
          <div className="absolute left-1 right-1 top-full z-40 mt-1 max-h-80 overflow-y-auto rounded-lg border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated) p-1 text-[0.8125rem] shadow-lg">
            {searchFeedback.kind === 'results' && searchData ? (
              searchData.results.map(r => (
                <button
                  key={`${r.dir}:${r.file}`}
                  type="button"
                  className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left hover:bg-(--ui-stroke-secondary)"
                  onClick={() => openResult(searchResultToCard(r, board.root))}
                >
                  <span className="shrink-0 text-[0.75rem] text-(--ui-text-tertiary)">
                    {r.dir}
                  </span>
                  <span className="min-w-0 flex-1 truncate font-medium text-(--ui-text-primary)">{r.title}</span>
                  {r.tags.slice(0, 2).map(t => (
                    <span key={t} className="shrink-0 rounded bg-(--ui-accent)/10 px-1 text-[0.75rem] text-(--ui-accent)">
                      {t}
                    </span>
                  ))}
                </button>
              ))
            ) : (
              <div className={cn(
                'px-2 py-2 text-[0.8125rem]',
                searchFeedback.kind === 'unreachable' || searchFeedback.kind === 'failure' || searchFeedback.kind === 'timeout'
                  ? 'text-[#f87171]'
                  : 'text-(--ui-text-tertiary)',
              )}>
                {searchFeedback.text}
                {searchFeedback.retry && (
                  <button
                    type="button"
                    className="ml-2 rounded border border-(--ui-stroke-secondary) px-1.5 py-0.5 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary)"
                    onClick={() => setSearchQ(q => q)}
                  >
                    重试
                  </button>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {presentation.contractErrorBannerVisible && (
        <div className="mt-1 rounded-md border border-[#f87171]/40 bg-[#f87171]/10 px-3 py-1.5 text-[0.75rem] text-[#f87171]">
          <Codicon name="warning" size="0.75rem" className="mr-1 inline" />
          有 {model.contractErrors.length} 个条目的状态无法识别，已按契约隔离未显示在任何区。
          请通过「旧版数据」查看原始状态并修正 frontmatter status 字段。
        </div>
      )}

      {presentation.legacyFallbackVisible && (
        <div className="mt-1 flex justify-end px-1">
          <button data-wb-legacy-fallback className="text-[0.75rem] text-(--ui-accent) hover:underline" onClick={onOpenLegacy} type="button">
            旧版数据 →
          </button>
        </div>
      )}

      {presentation.mode === 'expanded' && showAllRegion ? (
        <HomeAllRegionList region={showAllRegion} onBack={() => dispatchView({ type: 'back' })} onPreview={onPreview} />
      ) : (
      <div className="grid grid-cols-1 gap-3 py-3 lg:grid-cols-3">
        {mainRegions.map(region => (
          <section key={region.id} className="flex min-w-0 flex-col gap-1.5 rounded-lg border border-(--ui-stroke-secondary) p-2.5">
            <div className="flex items-center gap-1.5">
              <span className="text-[0.8125rem] font-semibold text-(--ui-text-primary)">
                {region.id === 'today' ? '今日' : region.id === 'inbox' ? '待审核' : '需要注意'}
              </span>
              <span className="text-[0.75rem] tabular-nums text-(--ui-text-quaternary)">{region.count}</span>
              {region.id === 'attention' && model.totals.attention.failures > 0 && (
                <span className="rounded bg-[#f87171]/15 px-1 text-[0.6875rem] text-[#f87171]">
                  失败 {model.totals.attention.failures}
                </span>
              )}
            </div>
            {region.visibleItems.length === 0 ? (
              <div className="rounded-md border border-dashed border-(--ui-stroke-tertiary) px-3 py-4 text-center text-[0.75rem] text-(--ui-text-quaternary)">
                {HOME_EMPTY_HINTS[region.id]}
              </div>
            ) : (
              <HomeRegionCardList
                items={region.visibleItems}
                totalCount={region.items.length}
                canShowAll={region.canShowAll}
                onPreview={onPreview}
                onShowAll={() => openShowAll(region.id)}
              />
            )}
          </section>
        ))}

        {healthState !== 'ok' && (
          <div
            className={
              healthState === 'unreachable'
                ? 'rounded-md border border-[#f87171]/40 bg-[#f87171]/10 px-3 py-1.5 text-[0.75rem] text-[#f87171]'
                : 'rounded-md border border-[#fbbf24]/40 bg-[#fbbf24]/10 px-3 py-1.5 text-[0.75rem] text-[#fbbf24]'
            }
          >
            {healthState === 'loading' && '链路健康检查中…'}
            {healthState === 'unreachable' && '后端暂时不可达，健康状态与数据可能不是最新（稍后自动重试）。'}
            {healthState === 'degraded' && `链路有点状况：${health.data?.label ?? '部分检查未通过'}${health.data?.last_error ? ` · 最近错误：${health.data.last_error.reason}` : ''}`}
          </div>
        )}

        <section className="flex min-w-0 flex-col gap-1.5 rounded-lg border border-(--ui-stroke-secondary) p-2.5 lg:col-span-3">
          <div className="flex items-center gap-1.5">
            <span className="text-[0.8125rem] font-semibold text-(--ui-text-primary)">最近完成</span>
            <span className="text-[0.75rem] tabular-nums text-(--ui-text-quaternary)">{recentRegion.count}</span>
          </div>
          {recentRegion.visibleItems.length === 0 ? (
            <div className="rounded-md border border-dashed border-(--ui-stroke-tertiary) px-3 py-4 text-center text-[0.75rem] text-(--ui-text-quaternary)">
              {HOME_EMPTY_HINTS.recent}
            </div>
          ) : (
            <HomeRegionCardList
              items={recentRegion.visibleItems}
              totalCount={recentRegion.items.length}
              canShowAll={recentRegion.canShowAll}
              onPreview={onPreview}
              onShowAll={() => openShowAll('recent')}
            />
          )}
        </section>

        <section className="flex flex-col gap-1.5 lg:col-span-3">
          <div className="flex items-center gap-1.5">
            <span className="text-[0.8125rem] font-semibold text-(--ui-text-secondary)">✨ 规则建议</span>
            <span className="text-[0.75rem] text-(--ui-text-quaternary)">依据任务状态、截止日期和最近结果生成</span>
          </div>
          {brief?.degraded ? (
            <div className="rounded-md border border-(--ui-stroke-tertiary) px-2.5 py-2 text-[0.75rem] text-(--ui-text-quaternary)">
              规则建议暂不可用，请稍后重试
            </div>
          ) : visibleCards.length === 0 ? (
            <div className="px-1 text-[0.75rem] text-(--ui-text-quaternary)">暂无建议</div>
          ) : (
            visibleCards.map(c => (
              <BriefCardView
                key={c.title}
                card={c}
                onAccept={c.type === 'new_task' ? () => void acceptBrief(c) : undefined}
                onIgnore={() => setIgnored(prev => new Set(prev).add(c.title))}
              />
            ))
          )}
        </section>
      </div>
      )}
    </div>
  )
}

