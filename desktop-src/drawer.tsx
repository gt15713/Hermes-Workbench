/**
 * Workbench drawer — file content preview + run history tabs.
 * Task 5.2 批次 1: adds "运行历史" tab reading task_events via /recent?dir=&file=.
 */
import { Button, cn, host, useQuery } from '@hermes/plugin-sdk'
import { useState } from 'react'
import { fetchFile, fetchRecentEvents, FILE_KEY, RECENT_EVENTS_KEY } from './api'
import type { WbCard } from './types'


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

  const { data, isLoading, error } = useQuery({
    queryKey: FILE_KEY(card.dir, card.file),
    queryFn: () => fetchFile(card.dir, card.file),
    enabled: true,
  })

  const { data: events, isLoading: evLoading } = useQuery({
    queryKey: RECENT_EVENTS_KEY(card.dir, card.file),
    queryFn: () => fetchRecentEvents(card.dir, card.file),
    enabled: tab === 'history',
  })

  const tabBtn = (active: boolean) =>
    cn(
      'cursor-pointer rounded px-2 py-1 text-[0.8125rem] transition-colors',
      active
        ? 'bg-(--ui-accent)/15 text-(--ui-accent)'
        : 'text-(--ui-text-tertiary) hover:bg-(--ui-stroke-secondary)'
    )

  return (
    <div
      className={cn(
        'fixed inset-0 z-[10001] flex items-center justify-center bg-black/40'
      )}
      onClick={onClose}
    >
      <div
        className="flex h-[80vh] w-[560px] max-w-[92vw] flex-col rounded-xl border border-(--ui-stroke-secondary)
                   bg-(--ui-bg-elevated) p-5 text-(--ui-text-primary) shadow-[0_20px_60px_rgba(0,0,0,0.5)]"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
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
          <div className="flex-1 overflow-y-auto whitespace-pre-wrap text-[0.75rem] leading-relaxed">
            {isLoading && (
              <div className="flex h-full items-center justify-center text-(--ui-text-tertiary)">加载中…</div>
            )}
            {error && (
              <div className="flex h-full items-center justify-center text-(--ui-text-danger)">加载失败</div>
            )}
            {data && <PreviewBody content={data.content || '（空）'} focusTitle={card.entry_title || null} />}
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto text-[0.8125rem]">
            {evLoading && (
              <div className="flex h-full items-center justify-center text-(--ui-text-tertiary)">加载中…</div>
            )}
            {!evLoading && (!events || events.entries.length === 0) && (
              <div className="flex h-full items-center justify-center text-(--ui-text-quaternary)">
                暂无运行历史
              </div>
            )}
            {!evLoading && events && events.entries.length > 0 && (
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
    </div>
  )
}
