/**
 * Workbench drawer — file content preview + run history tabs.
 * Task 5.2 批次 1: adds "运行历史" tab reading task_events via /recent?dir=&file=.
 */
import { Button, cn, host, useMutation, useQuery } from '@hermes/plugin-sdk'
import { useState } from 'react'
import { bindSession, CONTENT_ITEM_KEY, executeTask, fetchContentItem, fetchFile, fetchRecentEvents, FILE_KEY, invalidateBoard, RECENT_EVENTS_KEY, resetExecution, retryExtraction, reviewContent } from './api'
import { friendlyApiError } from './api-errors'
import { contentReceiptSteps, contentReviewModel, launchQueuedContentItem, type WbContentReviewAction } from './content-review'
import type { WorkbenchExecutionDeps } from './execution'
import type { WbCard } from './types'

const contentExecutionDeps: WorkbenchExecutionDeps = {
  prepare: input => executeTask(input.dir, input.file, { launch: false }),
  createSession: input => host.request('session.create', input),
  bind: bindSession,
  submit: (sessionId, text) => host.request('prompt.submit', { session_id: sessionId, text }),
  rollback: (dir, file, reason) => resetExecution(dir, file, reason),
}


// 2026-08-21：预览过滤 frontmatter 块（type/schema_version/category/status/received_at/source
// 等不展示）；聚合文件有焦点条目时只显示该 ## 小节（不再全文累积重复）。
function stripFrontmatter(content: string): string {
  return content.replace(/---\r?\n[\s\S]*?\r?\n---\r?\n?/g, '')
}

function extractEntry(content: string, focusTitle: string): string {
  const lines = content.split('\n')
  let start = -1
  for (let i = 0; i < lines.length; i++) {
    const t = lines[i].trim()
    if (t.startsWith('## ') && t.slice(3).trim() === focusTitle.trim()) {
      start = i
      break
    }
  }
  if (start === -1) return content
  let end = lines.length
  for (let i = start + 1; i < lines.length; i++) {
    if (lines[i].trim().startsWith('## ')) {
      end = i
      break
    }
  }
  return lines.slice(start, end).join('\n')
}

function PreviewBody({ content, focusTitle }: { content: string; focusTitle: string | null }) {
  let text = stripFrontmatter(content)
  if (focusTitle) text = extractEntry(text, focusTitle)
  const lines = text.split('\n')
  return (
    <>
      {lines.map((line, i) => {
        const trimmed = line.trim()
        const isFocus = !!focusTitle && trimmed.startsWith('## ') && trimmed.slice(3).trim() === focusTitle.trim()
        return (
          <span
            key={i}
            className={isFocus ? 'rounded bg-(--ui-accent)/15 font-semibold' : undefined}
          >
            {line}
            {i < lines.length - 1 ? '\n' : ''}
          </span>
        )
      })}
    </>
  )
}

export function WbPreviewDrawer({
  card,
  onClose,
}: {
  card: WbCard
  onClose: () => void
}) {
  const [tab, setTab] = useState<'preview' | 'history'>('preview')
  // P0（2026-08-27）：自绘沉淀确认（window.confirm 被 bundled 环境吞掉）
  const [pendingSinkConfirm, setPendingSinkConfirm] = useState(false)
  const isReviewedContent = card.dir === '待验证' && card.file.startsWith('content-') && !card.entry_title

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: FILE_KEY(card.dir, card.file),
    queryFn: () => fetchFile(card.dir, card.file),
    enabled: true,
    retry: 1,
  })

  const { data: events, isLoading: evLoading, error: evError, refetch: refetchEvents } = useQuery({
    queryKey: RECENT_EVENTS_KEY(card.dir, card.file),
    queryFn: () => fetchRecentEvents(card.dir, card.file),
    enabled: tab === 'history',
    retry: 1,
  })

  const { data: contentResponse, refetch: refetchContent } = useQuery({
    queryKey: CONTENT_ITEM_KEY(card.dir, card.file),
    queryFn: () => fetchContentItem(card.dir, card.file),
    enabled: isReviewedContent,
    retry: 1,
  })
  const contentItem = contentResponse?.ok ? contentResponse.item : undefined
  const reviewModel = contentItem ? contentReviewModel(contentItem) : null
  const reviewMutation = useMutation({
    mutationFn: (action: WbContentReviewAction) => reviewContent(contentItem!.dir, contentItem!.file, action),
    onSuccess: async (result) => {
      if (!result.ok) {
        host.notify({ kind: 'error', message: result.error || '操作失败，可重试' })
        await refetchContent()
        return
      }
      if (result.item?.review_state === 'sink_queued') {
        const launched = await launchQueuedContentItem(result.item, contentExecutionDeps)
        if (!launched.ok) {
          host.notify({ kind: 'error', message: launched.error || '摄入任务启动失败；任务已保留，可重试' })
          invalidateBoard()
          await refetchContent()
          return
        }
        host.notify({ kind: 'success', message: '已交给 Hermes 摄入；完成后自动回写笔记路径' })
        invalidateBoard()
        await refetchContent()
        return
      }
      host.notify({ kind: 'success', message: result.item?.review_state === 'sunk' ? '已沉淀到 Obsidian' : '已归档' })
      invalidateBoard()
      await refetchContent()
    },
    onError: (error) => host.notify({ kind: 'error', message: friendlyApiError(error) }),
  })
  const queuedLaunchMutation = useMutation({
    mutationFn: () => launchQueuedContentItem(contentItem!, contentExecutionDeps),
    onSuccess: async (launched) => {
      host.notify(launched.ok
        ? { kind: 'success', message: 'Hermes 摄入任务已启动；完成后自动回写笔记路径' }
        : { kind: 'error', message: launched.error || '摄入任务启动失败；可再次重试' })
      invalidateBoard()
      await refetchContent()
    },
    onError: (error) => host.notify({ kind: 'error', message: friendlyApiError(error) }),
  })
  // Task 5（2026-08-27）：独立重试抽取——与重试沉淀严格分列，失败原因如实透出
  const retryExtractionMutation = useMutation({
    mutationFn: () => retryExtraction(contentItem!.dir, contentItem!.file),
    onSuccess: async (result) => {
      if (!result.ok) {
        // P0（2026-08-27 目视二轮）：业务错误（如 extraction hook unavailable）
        // 也必须走人话翻译，不得让英文原文直穿 UI。
        host.notify({ kind: 'error', message: friendlyApiError(result.error || '抽取失败，可稍后重试') })
        await refetchContent()
        return
      }
      host.notify({ kind: 'success', message: '抽取完成，原文已更新' })
      await refetchContent()
    },
    onError: (error) => host.notify({ kind: 'error', message: friendlyApiError(error) }),
  })

  const tabBtn = (active: boolean) =>
    cn(
      'cursor-pointer rounded px-2 py-1 text-[0.8125rem] transition-colors',
      active
        ? 'bg-(--ui-accent)/15 text-(--ui-accent)'
        : 'text-(--ui-text-tertiary) hover:bg-(--ui-stroke-secondary)'
    )

  return (
    // P0（2026-08-27 目视二轮）：视口级 fixed 居中弹窗会被宿主右栏原生
    // 表面遮挡（z-index 无法越过），且宽度压迫工作台。改为官方 kanban
    // 同款「面板内右侧滑出抽屉」：锚定在最近 positioned 祖先（Workbench
    // 面板）上，与右栏物理隔离，宽度固定不挤压内容。
    <div className="wb-drawer"
      role="dialog"
      aria-modal="false"
      aria-label="文件预览"
    >
        {/* Header */}
        <div className="mb-3 flex items-center justify-between">
          <span className="text-base font-semibold">{card.title || card.file}</span>
          <button
            type="button"
            aria-label="关闭"
            className="cursor-pointer border-none bg-transparent text-base text-(--ui-text-tertiary) hover:text-(--ui-text-primary)"
            onClick={onClose}
          >
            ✕
          </button>
        </div>

        {/* Tabs */}
        <div className="mb-2 flex items-center gap-1 border-b border-(--ui-stroke-secondary) pb-1">
          <button type="button" className={tabBtn(tab === 'preview')} onClick={() => setTab('preview')}>
            预览
          </button>
          <button type="button" className={tabBtn(tab === 'history')} onClick={() => setTab('history')}>
            运行历史
          </button>
          <div className="ml-auto" />
        </div>

        {/* Tab content */}
        {tab === 'preview' ? (
          <div className="flex-1 overflow-y-auto text-[0.75rem] leading-relaxed">
            {reviewModel && contentItem && (
              <section className="mb-3 rounded-lg border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) p-3">
                <div className="font-medium">内容审核 · {reviewModel.statusText}</div>
                {/* Task 5：收进来 → 审核 → 沉淀 三步回执 */}
                <ol className="mt-2 space-y-1">
                  {contentReceiptSteps(contentItem).map((step) => (
                    <li key={step.label} className="flex items-start gap-2 text-[0.75rem]">
                      {/* 用户拍板（2026-08-27）：徽标全部取消统一样式——
                          纯文本符号前缀 + inline style 上色，零依赖任何编译链路 */}
                      <span
                        style={{
                          flexShrink: 0,
                          color: step.state === 'error' ? 'var(--ui-red)'
                            : step.state === 'done' ? 'var(--ui-green, var(--ui-text-quaternary))'
                            : step.state === 'active' ? 'var(--ui-accent)'
                            : 'var(--ui-text-tertiary)',
                        }}
                      >
                        {step.state === 'error' ? '✖' : step.state === 'done' ? '✔' : step.state === 'active' ? '▶' : step.state === 'skipped' ? '⊘' : '○'}
                      </span>
                      <span className="shrink-0 font-medium text-(--ui-text-primary)">{step.label}</span>
                      <span
                        className="min-w-0 break-all"
                        style={
                          step.state === 'error'
                            ? { color: 'var(--ui-red)', fontWeight: 500 }
                            : undefined
                        }
                      >
                        {step.detail}
                      </span>
                    </li>
                  ))}
                </ol>
                {contentItem.original_url && (
                  <div className="mt-1 break-all text-(--ui-text-tertiary)">来源：{contentItem.original_url}</div>
                )}
                {reviewModel.error && <div className="mt-1 text-(--ui-red)">{reviewModel.error}</div>}
                {reviewModel.notePath && <div className="mt-1 break-all text-(--ui-text-secondary)">笔记：{reviewModel.notePath}</div>}
                {reviewModel.actions.length > 0 && (
                  <div className="mt-3 flex gap-2">
                    {pendingSinkConfirm ? (
                      // P0：自绘确认条——明确两键，替代被吞的 window.confirm
                      <div className="flex w-full items-center gap-2 rounded-md border border-(--ui-accent)/40 bg-(--ui-accent)/10 px-2 py-1.5">
                        <span className="text-[0.75rem] text-(--ui-text-primary)">确认沉淀到 Obsidian？</span>
                        <Button
                          size="xs"
                          disabled={reviewMutation.isPending}
                          onClick={() => { setPendingSinkConfirm(false); reviewMutation.mutate('sink_to_obsidian') }}
                        >
                          确认沉淀
                        </Button>
                        <Button size="xs" variant="outline" onClick={() => setPendingSinkConfirm(false)}>
                          取消
                        </Button>
                      </div>
                    ) : (
                      reviewModel.actions.map((action) => (
                      <Button
                        key={action.id}
                        size="xs"
                        variant={
                          action.id === 'archive_only'
                            ? 'outline'
                            : action.id === 'retry_extraction'
                              ? 'secondary'
                              : 'secondary'
                        }
                        disabled={
                          reviewMutation.isPending ||
                          queuedLaunchMutation.isPending ||
                          retryExtractionMutation.isPending
                        }
                        onClick={() => {
                          if (action.id === 'launch_sink_task') {
                            queuedLaunchMutation.mutate()
                            return
                          }
                          if (action.id === 'retry_extraction') {
                            retryExtractionMutation.mutate()
                            return
                          }
                          if (action.id === 'sink_to_obsidian') {
                            // P0（2026-08-27）：window.confirm 在 bundled 环境被吞
                            // （「沉淀弹窗没渲染」根因），改用自绘两键确认条。
                            setPendingSinkConfirm(true)
                            return
                          }
                          reviewMutation.mutate(action.id)
                        }}
                      >
                        {action.label}
                      </Button>
                      ))
                    )}
                  </div>
                )}
              </section>
            )}
            <div className="whitespace-pre-wrap">
            {isLoading && (
              <div className="flex h-full items-center justify-center text-(--ui-text-tertiary)">加载中…</div>
            )}
            {error && (
              <div className="flex h-full flex-col items-center justify-center gap-2 text-(--ui-red)">
                <span>{String((error as Error).message || '加载失败')}</span>
                <Button size="sm" variant="secondary" onClick={() => void refetch()}>重试</Button>
              </div>
            )}
            {data && <PreviewBody content={data.content || '（空）'} focusTitle={card.entry_title || null} />}
            </div>
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto text-[0.8125rem]">
            {evLoading && (
              <div className="flex h-full items-center justify-center text-(--ui-text-tertiary)">加载中…</div>
            )}
            {evError && (
              <div className="flex h-full flex-col items-center justify-center gap-2 text-(--ui-red)">
                <span>{String((evError as Error).message || '运行历史加载失败')}</span>
                <Button size="sm" variant="secondary" onClick={() => void refetchEvents()}>重试</Button>
              </div>
            )}
            {!evLoading && !evError && (!events || events.entries.length === 0) && (
              <div className="flex h-full items-center justify-center text-(--ui-text-quaternary)">
                暂无运行历史
              </div>
            )}
            {!evLoading && !evError && events && events.entries.length > 0 && (
              <ul className="flex flex-col gap-1">
                {events.entries.map((e) => (
                  <li
                    key={e.id}
                    className="flex items-center gap-2 rounded border border-(--ui-stroke-tertiary) px-2 py-1.5"
                  >
                    <span className="shrink-0 font-mono text-[0.75rem] text-(--ui-text-quaternary)">
                      {String(e.ts).slice(0, 19)}
                    </span>
                    <span className="shrink-0 rounded bg-(--ui-accent)/10 px-1.5 py-0.5 font-medium text-(--ui-accent)">
                      {e.kind}
                    </span>
                    {e.payload && (
                      <span className="min-w-0 flex-1 truncate text-(--ui-text-secondary)">{e.payload}</span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {/* Footer */}
        <div className="mt-3 flex items-center justify-end gap-2">
          <Button size="xs" variant="outline" onClick={onClose}>
            关闭
          </Button>
          <Button
            size="xs"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(card.path)
                host.notify({ kind: 'success', message: '路径已复制' })
              } catch {
                host.notify({ kind: 'error', message: '复制失败' })
              }
            }}
          >
            复制路径
          </Button>
        </div>
    </div>
  )
}
