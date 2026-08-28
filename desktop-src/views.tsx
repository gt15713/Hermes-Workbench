/**
 * Workbench views — Table & List (Task 5.2 批次 3).
 *
 * Board view stays in board.tsx untouched; these two consume the SAME
 * /board payload (sections) with no new backend endpoints.
 *
 * Filter/collapse semantics mirror the Board: $filterText filters titles,
 * $showArchived reveals done/trash, $collapsedSections hides a partition.
 * Row/card click opens the preview drawer (same onPreview wiring).
 */

import { cn, Codicon, useValue } from '@hermes/plugin-sdk'
import { Fragment, useMemo } from 'react'

import { $collapsedSections, $filterText, $showArchived } from './api'
import { isOverdue, partitionMeta, priorityMeta, sizeMeta, STATUS_TONE, type WbBoard, type WbCard, type WbSection } from './types'

// ── shared helpers ────────────────────────────────────────────────────

const fmtTime = (mtime?: number | null | string): string => {
  if (!mtime) return '—'
  // 后端 /board 的 mtime 为预格式化字符串（"MM-DD HH:MM"），直接展示
  if (typeof mtime === 'string') return mtime
  const d = new Date(mtime * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function PriorityBadge({ value }: { value?: null | string }) {
  const meta = value ? priorityMeta(value) : null
  if (!meta) return null
  return (
    <span className="rounded px-1 text-[0.75rem] font-semibold" style={{ background: meta.bg, color: meta.fg }}>
      {meta.label}
    </span>
  )
}

function SizeBadge({ value }: { value?: null | string }) {
  const meta = value ? sizeMeta(value) : null
  if (!meta) return null
  return (
    <span className="rounded border px-1 text-[0.75rem] font-semibold" style={{ borderColor: meta.fg, color: meta.fg }}>
      {meta.label}
    </span>
  )
}

function StatusCell({ status }: { status: string }) {
  const tone = STATUS_TONE[status] || 'var(--ui-text-tertiary)'
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="size-1.5 shrink-0 rounded-full" style={{ background: tone }} />
      <span className="text-(--ui-text-secondary)">{status}</span>
    </span>
  )
}

/**
 * Filter + collapse semantics shared with the Board:
 *  - done/trash hidden unless $showArchived
 *  - collapsed partitions excluded
 *  - $filterText matches title or file
 */
function useVisibleSections(board: WbBoard): WbSection[] {
  // 订阅 atom（与 Board 的 useValue 语义一致）：筛选/折叠/显示归档变化实时生效
  const filterText = useValue($filterText).toLowerCase()
  const collapsed = useValue($collapsedSections)
  const showArchived = useValue($showArchived)

  return useMemo(() => {
    const out: WbSection[] = []
    for (const section of board.sections) {
      if (!showArchived && (section.key === 'done' || section.key === 'trash')) continue
      if (collapsed[section.key]) continue
      const files = filterText
        ? section.files.filter(c =>
            c.title.toLowerCase().includes(filterText) ||
            c.file.toLowerCase().includes(filterText)
          )
        : section.files
      if (files.length > 0) out.push({ ...section, files })
    }
    return out
  }, [board.sections, filterText, collapsed, showArchived])
}

// ── Table view ────────────────────────────────────────────────────────

export function TableBoardView({ board, onPreview }: { board: WbBoard; onPreview: (c: WbCard) => void }) {
  const sections = useVisibleSections(board)

  const rows = useMemo(() => {
    const out: Array<{ section: WbSection; card: WbCard }> = []
    for (const section of sections) {
      for (const card of section.files) out.push({ section, card })
    }
    return out
  }, [sections])

  // C1（P1-2）：按 #project: 前缀标签分组——无标签 → 「未分组」。先筛选（rows 已过滤）后分组。
  const projectOf = (card: WbCard): string => {
    const t = (card.tags || []).find(tag => tag.startsWith('#project:'))
    return t ? t.slice('#project:'.length).trim() : ''
  }

  const collapsedProj = useValue($collapsedSections)

  const groups = useMemo(() => {
    const map = new Map<string, Array<{ section: WbSection; card: WbCard }>>()
    for (const row of rows) {
      const name = projectOf(row.card) || '未分组'
      const arr = map.get(name)
      if (arr) arr.push(row)
      else map.set(name, [row])
    }
    return Array.from(map.entries()).sort((a, b) => {
      if (a[0] === '未分组') return 1
      if (b[0] === '未分组') return -1
      return a[0].localeCompare(b[0])
    })
  }, [rows])

  const toggleGroup = (name: string) => {
    const key = 'project:' + name
    const cur = $collapsedSections.get()
    $collapsedSections.set({ ...cur, [key]: !(cur[key] ?? false) })
  }

  if (rows.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center text-[0.8125rem] text-(--ui-text-quaternary)">
        暂无条目
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-auto px-3 pb-3">
      <table className="w-full border-collapse text-[0.8125rem]">
        <thead>
          <tr className="sticky top-0 bg-(--ui-bg) text-left text-(--ui-text-tertiary)">
            <th className="px-2 py-1.5 font-medium">分区</th>
            <th className="px-2 py-1.5 font-medium">标题</th>
            <th className="px-2 py-1.5 font-medium">状态</th>
            <th className="px-2 py-1.5 font-medium">优先级</th>
            <th className="px-2 py-1.5 font-medium">尺寸</th>
            <th className="px-2 py-1.5 font-medium">标签</th>
            <th className="px-2 py-1.5 font-medium">Due</th>
            <th className="px-2 py-1.5 font-medium">更新时间</th>
          </tr>
        </thead>
        <tbody>
          {groups.map(([name, groupRows]) => {
            const key = 'project:' + name
            const collapsed = collapsedProj[key] ?? false
            return (
              <Fragment key={name}>
                <tr
                  className="cursor-pointer border-t border-(--ui-stroke-secondary) bg-(--ui-bg-quinary)/50 hover:bg-(--ui-bg-quinary)"
                  onClick={() => toggleGroup(name)}
                >
                  <td colSpan={7} className="px-2 py-1.5">
                    <span className="inline-flex items-center gap-1.5 font-semibold text-(--ui-text-secondary)">
                      <Codicon name={collapsed ? 'chevron-right' : 'chevron-down'} size="0.7rem" />
                      {name === '未分组' ? <span className="text-(--ui-text-quaternary)">未分组</span> : (
                        <span className="rounded bg-(--ui-accent)/10 px-1.5 py-0.5 text-(--ui-accent)">#project:{name}</span>
                      )}
                      <span className="text-[0.75rem] font-normal text-(--ui-text-quaternary)">{groupRows.length}</span>
                    </span>
                  </td>
                </tr>
                {!collapsed && groupRows.map(({ section, card }) => {
            const meta = partitionMeta(section.key)
            return (
              <tr
                key={section.key + ':' + card.file + (card.entry_title || '')}
                className="cursor-pointer border-t border-(--ui-stroke-tertiary) transition-colors hover:bg-(--ui-bg-quinary)"
                onClick={() => onPreview(card)}
              >
                <td className="px-2 py-1.5 whitespace-nowrap text-(--ui-text-secondary)">
                  <Codicon name={meta.codicon} size="0.7rem" style={{ color: meta.tone }} />
                  <span className="ml-1.5">{meta.label}</span>
                </td>
                <td className="max-w-[22rem] truncate px-2 py-1.5 font-medium text-(--ui-text-primary)">
                  {card.title || card.file.replace(/\.md$/, '')}
                </td>
                <td className="px-2 py-1.5 whitespace-nowrap">
                  <StatusCell status={card.status} />
                </td>
                <td className="px-2 py-1.5 whitespace-nowrap">
                  <PriorityBadge value={card.priority} />
                </td>
                <td className="px-2 py-1.5 whitespace-nowrap">
                  <SizeBadge value={card.size} />
                </td>
                <td className="px-2 py-1.5">
                  {card.tags && card.tags.length > 0 ? (
                    <span className="flex flex-wrap gap-1">
                      {card.tags.map(t => (
                        <span key={t} className="rounded bg-(--ui-accent)/10 px-1 text-[0.75rem] text-(--ui-accent)">
                          {t}
                        </span>
                      ))}
                    </span>
                  ) : (
                    <span className="text-(--ui-text-quaternary)">—</span>
                  )}
                </td>
                <td className={cn('px-2 py-1.5 whitespace-nowrap', isOverdue(card.due) ? 'font-semibold text-(--ui-red)' : 'text-(--ui-text-secondary)')}>
                  {card.due || '—'}
                  {isOverdue(card.due) && ' ⚠'}
                </td>
                <td className="px-2 py-1.5 whitespace-nowrap font-mono text-[0.75rem] text-(--ui-text-quaternary)">
                  {fmtTime(card.mtime)}
                </td>
              </tr>
            )
                })}
                </Fragment>
              )
            })}
        </tbody>
      </table>
    </div>
  )
}

// ── View switcher ─────────────────────────────────────────────────────

export const VIEW_MODES: Array<{ key: 'board' | 'table'; label: string }> = [
  { key: 'board', label: 'Board' },
  { key: 'table', label: 'Table' },
]

export function ViewSwitcher({ mode, onChange }: { mode: string; onChange: (m: 'board' | 'table') => void }) {
  return (
    <div className="flex items-center rounded-md border border-(--ui-stroke-secondary) p-0.5">
      {VIEW_MODES.map(v => (
        <button
          key={v.key}
          className={cn(
            'rounded px-2 py-0.5 text-[0.8125rem] transition-colors',
            mode === v.key
              ? 'bg-(--ui-accent) text-white'
              : 'text-(--ui-text-tertiary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-text-primary)'
          )}
          onClick={() => onChange(v.key)}
          type="button"
        >
          {v.label}
        </button>
      ))}
    </div>
  )
}
