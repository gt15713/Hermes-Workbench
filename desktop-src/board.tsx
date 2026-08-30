/**
 * Workbench board page — 7 partitions rendered as columns.
 * Displays cards with status colors, action menus, filtering, collapse.
 *
 * Phase 1 semantic: task/done/trash files = 1 card; aggregation files
 * (thought/video/psych/dream) = N cards (one per ## entry).
 */

import {
  Button,
  cn,
  Codicon,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  host,
  Input,
  Tip,
  useMutation,
  useQuery,
  useValue,
} from '@hermes/plugin-sdk'
import { Component, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

import {
  $collapsedSections,
  $dueFilter,
  $filterText,
  $tagFilter,
  $showArchived,
  $viewMode,
  abandonTask,
  addEntry,
  batchAction,
  BOARD_KEY,
  bindSession,
  completeTask,
  deferTask,
  deleteFile,
  editEntry,
  executeTask,
  fetchBoard,
  fetchBrief,
  fetchConversations,
  fetchFile,
  fetchHealth,
  fetchSearch,
  fetchSettings,
  ingestMessage,
  invalidateBoard,
  resetExecution,
  reopenTask,
  resolveEntry,
  restoreFile,
  saveSettings,
  toTask,
  trashFile,
} from './api'
import { isOverdue, partitionMeta, priorityMeta, sizeMeta, STATUS_TONE, type WbBoard, type WbCard, type WbSearchResult, type WbSection, type WbSettings, type WbSettingsSchedulerItem } from './types'
import { canArchiveTask, launchWorkbenchTask, type WorkbenchExecutionDeps } from './execution'
import { suggestTags, type TagSuggestion } from './tag-suggest'
import type { WbBriefCard } from './api'
import { WbPreviewDrawer } from './drawer'
import { TableBoardView, ViewSwitcher } from './views'
import { HomeView } from './home'
import { ConversationIndexView } from './conversations'
import { consumeLegacyBatchResponse } from './batch-response'

const executionDeps: WorkbenchExecutionDeps = {
  prepare: async input => {
    const result = await executeTask(input.dir, input.file, {
      title: input.title,
      content: input.content,
      due: input.due,
      launch: false,
    })
    invalidateBoard()
    return result
  },
  createSession: input => host.request('session.create', input),
  bind: bindSession,
  submit: (runtimeSessionId, text) => host.request('prompt.submit', {
    session_id: runtimeSessionId,
    text,
  }),
  rollback: async (dir, file, reason) => {
    const result = await resetExecution(dir, file, reason)
    invalidateBoard()
    return result
  },
}

function notifyExecutionFailure(result: Awaited<ReturnType<typeof launchWorkbenchTask>>) {
  const rollbackNote = result.rollbackError
    ? `；自动恢复失败：${result.rollbackError}，请人工检查任务状态`
    : '；任务已恢复为待办'
  host.notify({ kind: 'error', message: `${result.error || '执行启动失败'}${rollbackNote}` })
}

// 08-21：per-card 错误边界——单卡渲染异常不影响整板（定位问题卡并保持看板可用）。
class CardErrorBoundary extends Component<{ children: ReactNode }, { error: unknown }> {
  state = { error: null as unknown }
  static getDerivedStateFromError(error: unknown) {
    return { error }
  }
  render() {
    if (this.state.error) {
      return (
        <div className="mb-1.5 rounded-md border border-(--ui-red) bg-(--ui-bg-elevated) p-2.5 text-[0.75rem] text-(--ui-red)">
          卡片渲染失败（数据异常）
        </div>
      )
    }
    return this.props.children
  }
}

// ── Card component ────────────────────────────────────────────────────

function WbCardView({ card, sectionKey, onPreview, openMenuKey, onMenuOpenChange, multiMode, selected, onToggleSelect, conversationPlatforms, onOpenConversations }: {
  card: WbCard
  sectionKey: string
  onPreview: (c: WbCard) => void
  openMenuKey: string | null
  onMenuOpenChange: (key: string | null) => void
  multiMode: boolean
  selected: Set<string>
  onToggleSelect: (key: string) => void
  conversationPlatforms: string[]
  onOpenConversations: () => void
}) {
  const meta = partitionMeta(sectionKey)
  const tone = STATUS_TONE[card.status] || 'var(--ui-text-tertiary)'
  // A5：当前标签过滤（点击卡片标签 chip 切换）
  const tagFilter = useValue($tagFilter)
  // 单例菜单：menuKey 必须按「分区+文件+条目」唯一（08-21 修复）。聚合文件
  // （待回看/待验证/已处理索引等）一条文件展开 N 张卡，若只按文件命名，点任一卡
  // 会同时打开同文件全部卡的菜单；未悬停卡的触发钮 display:none → rect 全零 →
  // 菜单被定位到 (8,8)（窗口左上角）出现幽灵菜单。JSON 编码防分隔符撞键。
  const menuKey = JSON.stringify([sectionKey, card.file, card.entry_title || ''])
  const menuOpen = openMenuKey === menuKey
  const menuTriggerRef = useRef<HTMLButtonElement>(null)
  const [menuPosition, setMenuPosition] = useState<{ left: number; top: number } | null>(null)

  // The board and the Cronjobs pane are sibling layout surfaces. Position the
  // action menu against the viewport so it can clear either surface instead of
  // being clipped by the board's horizontal scroller.
  useEffect(() => {
    if (!menuOpen || !menuTriggerRef.current) {
      setMenuPosition(null)
      return
    }
    const updatePosition = () => {
      const rect = menuTriggerRef.current?.getBoundingClientRect()
      if (!rect) return
      // 触发钮不可见（display:none，rect 全零）时不定位——避免幽灵菜单出现在窗口左上角
      if (rect.width === 0 || rect.height === 0) {
        setMenuPosition(null)
        return
      }
      const menuWidth = 176
      const gutter = 8
      const placeRight = window.innerWidth - rect.right >= menuWidth + gutter
      const left = placeRight
        ? rect.right + gutter
        : Math.max(gutter, rect.left - menuWidth - gutter)
      const top = Math.max(gutter, Math.min(rect.top, window.innerHeight - 420 - gutter))
      setMenuPosition({ left, top })
    }
    updatePosition()
    window.addEventListener('resize', updatePosition)
    window.addEventListener('scroll', updatePosition, true)
    return () => {
      window.removeEventListener('resize', updatePosition)
      window.removeEventListener('scroll', updatePosition, true)
    }
  }, [menuOpen])
  // 补丁 16：执行前编辑浮窗开关
  const [execOpen, setExecOpen] = useState(false)
  // B2：多选标识（JSON 编码防条目标题含分隔符；dir/file/entry_title 三元组全板唯一）
  const cardKey = JSON.stringify([card.dir, card.file, card.entry_title || ''])
  const isSelected = selected.has(cardKey)
  const canArchive = canArchiveTask(sectionKey, card.status, card.execution_result || undefined)

  const mutOpts = {
    onError: (err: Error) => host.notify({ kind: 'error', message: String(err) }),
    onSuccess: () => invalidateBoard(),
  }

  const doComplete = useMutation({ mutationFn: () => completeTask(card.dir, card.file), ...mutOpts })
  const doDefer = useMutation({ mutationFn: () => deferTask(card.dir, card.file), ...mutOpts })
  const doAbandon = useMutation({ mutationFn: () => abandonTask(card.dir, card.file), ...mutOpts })
  const doReopen = useMutation({ mutationFn: () => reopenTask(card.dir, card.file), ...mutOpts })
  const doTrash = useMutation({ mutationFn: () => trashFile(card.dir, card.file), ...mutOpts })
  const doDelete = useMutation({ mutationFn: () => deleteFile(card.dir, card.file), ...mutOpts })
  const doRestore = useMutation({ mutationFn: () => restoreFile(card.dir, card.file), ...mutOpts })
  // 聚合条目卡（entry_count>0）：快捷动作 = 确认处理（resolve，条目级）
  const doResolve = useMutation({
    mutationFn: () => resolveEntry(card.dir, card.file, card.entry_title ? { entry_title: card.entry_title } : undefined),
    ...mutOpts,
  })
  // A2：聚合条目 → 任务（to-task，条目级）
  const doToTask = useMutation({
    mutationFn: () => toTask(card.dir, card.file, card.entry_title ? { entry_title: card.entry_title } : undefined),
    ...mutOpts,
  })
  // A2：✎ 编辑浮窗开关
  const [editOpen, setEditOpen] = useState(false)

  const execTask = useCallback(async (overrides?: { title?: string; content?: string; due?: string }) => {
    // 防御性兜底：title 缺失时用文件名 stem（后端 _parse_md 已补 title，此处防未来字段再缺）
    const title = overrides?.title || card.title || card.file.replace(/\.md$/, '')
    if (!title) return
    const result = await launchWorkbenchTask({
      dir: card.dir,
      file: card.file,
      title,
      path: card.path,
      ...overrides,
    }, executionDeps)
    if (!result.ok || !result.storedSessionId) {
      notifyExecutionFailure(result)
      return
    }
    host.navigate('/' + encodeURIComponent(result.storedSessionId))
  }, [card])

  // A1：聚合条目执行链路——转临时任务（to-task）→ /execute → 会话。完成回写由任务卡承担。
  const execAggregate = useCallback(async (overrides?: { title?: string; content?: string; due?: string }) => {
    const entryTitle = card.entry_title || ''
    if (!entryTitle) return
    try {
      const converted = await toTask(card.dir, card.file, { entry_title: entryTitle })
      if (!converted.ok) {
        host.notify({ kind: 'error', message: converted.error || '转任务失败' })
        return
      }
      const taskFile = converted.task_file || ''
      const taskTitle = overrides?.title || converted.task || entryTitle
      if (!taskFile) {
        host.notify({ kind: 'error', message: '转任务失败：无任务文件' })
        return
      }
      const result = await launchWorkbenchTask({
        dir: '任务',
        file: taskFile,
        title: taskTitle,
        path: card.path,
        ...overrides,
      }, executionDeps)
      if (!result.ok || !result.storedSessionId) {
        notifyExecutionFailure(result)
        return
      }
      host.navigate('/' + encodeURIComponent(result.storedSessionId))
    } catch (err) {
      host.notify({ kind: 'error', message: String(err) })
    }
  }, [card])

  // 补丁 16：SDK 无 openExternal（renderer 不碰 native）——降级为复制路径 + notify
  const copyPath = async () => {
    try {
      await navigator.clipboard.writeText(card.path)
      host.notify({ kind: 'success', message: '路径已复制' })
    } catch {
      host.notify({ kind: 'error', message: '复制失败' })
    }
  }

  return (
    <>
    <div
      className={cn(
        'group relative mb-1.5 flex flex-col gap-1.5 rounded-md border border-(--ui-stroke-tertiary) border-l-2 bg-(--ui-bg-elevated) p-2.5 text-[0.75rem] transition-colors',
        multiMode ? 'cursor-default' : 'cursor-pointer hover:bg-primary/[0.06]',
        isSelected && 'border-(--ui-accent) bg-[color-mix(in_srgb,var(--ui-accent)_10%,transparent)]'
      )}
      style={{ borderLeftColor: meta.tone }}
      onClick={() => { onMenuOpenChange(null); multiMode ? onToggleSelect(cardKey) : onPreview(card) }}
    >
      {/* B2：多选勾选框（多选模式） */}
      {multiMode && (
        <span
          className="absolute top-1 left-1 z-10 flex size-4 items-center justify-center rounded-full border text-[0.75rem]"
          style={isSelected
            ? { background: 'var(--ui-accent)', borderColor: 'var(--ui-accent)', color: 'var(--ui-bg)' }
            : { borderColor: 'var(--ui-stroke-secondary)', color: 'transparent' }}
        >
          ✓
        </span>
      )}
      {/* Header: title + badges (priority / size / entry count) */}
      <div className="flex items-start justify-between gap-1">
        <span className="line-clamp-2 flex-1 break-words font-medium leading-snug text-[0.9375rem]">
          {card.title || card.file.replace(/\.md$/, '')}
        </span>
        {/* pr-5 reserves space for the absolute kebab trigger (right-1 top-1) so
            priority/size badges never overlap it (2026-08-15 T52B1 UI fix) */}
        <span className="flex shrink-0 items-center gap-1 pr-5">
          {card.priority && priorityMeta(card.priority) && (
            <span
              className="rounded px-1 text-[0.75rem] font-semibold"
              style={{
                backgroundColor: priorityMeta(card.priority)!.bg,
                color: priorityMeta(card.priority)!.fg,
              }}
            >
              {card.priority}
            </span>
          )}
          {card.size && sizeMeta(card.size) && (
            <span
              className="rounded border px-1 text-[0.75rem] font-medium"
              style={{ color: sizeMeta(card.size)!.fg, borderColor: sizeMeta(card.size)!.fg }}
            >
              {card.size}
            </span>
          )}
          {card.entry_count > 0 && (
            <span className="rounded bg-(--ui-accent)/10 px-1 text-[0.75rem] text-(--ui-accent)">
              {card.entry_count}
            </span>
          )}
        </span>
      </div>

      {/* A5：标签 chips（点击切换标签过滤；命中当前过滤高亮） */}
      {card.tags && card.tags.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1">
          {card.tags.map(t => (
            <button
              key={t}
              type="button"
              onClick={(e) => { e.stopPropagation(); $tagFilter.set(tagFilter === t ? '' : t) }}
              className={cn(
                'rounded px-1 text-[0.75rem] leading-4 transition-colors',
                tagFilter === t
                  ? 'bg-(--ui-accent) text-(--ui-bg)'
                  : 'bg-(--ui-bg-elevated) text-(--ui-text-tertiary) hover:text-(--ui-accent)'
              )}
            >
              {t}
            </button>
          ))}
        </div>
      )}

      {/* Status bar */}
      <div className="mt-1 flex items-center gap-1.5 text-[0.75rem] text-(--ui-text-quaternary)">
        <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ backgroundColor: tone }} />
        <span>{card.status}</span>
        {card.due && (
          <span className={isOverdue(card.due) ? 'font-semibold text-(--ui-red)' : undefined}>
            · 截止 {card.due}
            {isOverdue(card.due) && ' ⚠'}
          </span>
        )}
        {card.status === 'in_progress' && card.session_id && <span>· ▶ 执行中</span>}
        {conversationPlatforms.length > 0 && (
          <button
            type="button"
            className="ml-auto rounded bg-(--ui-accent)/10 px-1.5 py-0.5 text-(--ui-accent) hover:bg-(--ui-accent)/20"
            title="查看消息任务"
            onClick={(event) => { event.stopPropagation(); onOpenConversations() }}
          >
            {conversationPlatforms.map(platform => platform === 'qq' ? 'QQ' : platform === 'weixin' ? '微信' : '消息').join(' · ')}
          </button>
        )}
      </div>

      {/* Phase 0-2：常态主按钮（替代 B1 hover 快捷层；多选模式隐藏；低频动作进 ⋮ 菜单） */}
      {!multiMode && (
        <div className="mt-1 flex items-center gap-1">
          {sectionKey === 'task' && card.status === 'todo' ? (
            <>
              <button className="inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)" onClick={(e) => { e.stopPropagation(); doComplete.mutate() }} type="button" aria-label="归档"><Codicon name="check" size="0.7rem" />归档</button>
              <button className="inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)" onClick={(e) => { e.stopPropagation(); setExecOpen(true) }} type="button" aria-label="执行"><Codicon name="play" size="0.7rem" />执行</button>
            </>
          ) : canArchive ? (
            <>
              {/* 执行完成 → 可直接归档（/complete 支持 in_progress，2026-08-17） */}
              <button className="inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)" onClick={(e) => { e.stopPropagation(); doComplete.mutate() }} type="button" aria-label="归档"><Codicon name="check" size="0.7rem" />归档</button>
              {card.status === 'in_progress' && card.session_id && (
                <button className="inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)" onClick={(e) => { e.stopPropagation(); host.navigate('/' + encodeURIComponent(card.session_id!)) }} type="button" aria-label="打开会话"><Codicon name="link-external" size="0.7rem" />打开会话</button>
              )}
            </>
          ) : sectionKey === 'task' && card.status === 'abandoned' ? (
            <button className="inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)" onClick={(e) => { e.stopPropagation(); doReopen.mutate() }} type="button" aria-label="重新打开"><Codicon name="refresh" size="0.7rem" />重新打开</button>
          ) : sectionKey === 'done' && card.entry_count > 0 ? (
            <button className="inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)" onClick={(e) => { e.stopPropagation(); doResolve.mutate() }} type="button" aria-label="确认处理"><Codicon name="check" size="0.7rem" />确认处理</button>
          ) : sectionKey === 'done' ? (
            <>
              {/* 已处理任务带会话 → 可直接打开执行会话回看（2026-08-17） */}
              {card.session_id && (
                <button className="inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)" onClick={(e) => { e.stopPropagation(); host.navigate('/' + encodeURIComponent(card.session_id!)) }} type="button" aria-label="打开会话"><Codicon name="link-external" size="0.7rem" />打开会话</button>
              )}
              <button className="inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)" onClick={(e) => { e.stopPropagation(); doReopen.mutate() }} type="button" aria-label="回到任务列表"><Codicon name="refresh" size="0.7rem" />回到任务列表</button>
            </>
          ) : sectionKey === 'trash' ? (
            <button className="inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)" onClick={(e) => { e.stopPropagation(); doRestore.mutate() }} type="button" aria-label="还原"><Codicon name="refresh" size="0.7rem" />还原</button>
          ) : card.entry_count > 0 ? (
            <>
              <button className="inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)" onClick={(e) => { e.stopPropagation(); doResolve.mutate() }} type="button" aria-label="确认处理"><Codicon name="check" size="0.7rem" />确认处理</button>
              <button className="inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)" onClick={(e) => { e.stopPropagation(); setExecOpen(true) }} type="button" aria-label="执行"><Codicon name="play" size="0.7rem" />执行</button>
              <button className="inline-flex items-center gap-0.5 rounded px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-accent)" onClick={(e) => { e.stopPropagation(); doToTask.mutate() }} type="button" aria-label="转任务"><Codicon name="arrow-right" size="0.7rem" />转任务</button>
            </>
          ) : null}
        </div>
      )}

      {/* Menu trigger */}
      <button
        data-wb-menu
        ref={menuTriggerRef}
        className={cn(
          'absolute right-1 top-1 block rounded p-0.5 text-(--ui-text-tertiary)',
          'hover:bg-(--ui-stroke-secondary)'
        )}
        onClick={(e) => { e.stopPropagation(); onMenuOpenChange(menuOpen ? null : menuKey) }}
        type="button"
        aria-label="Actions"
      >
        <Codicon name="kebab-vertical" size="0.75rem" />
      </button>

      {/* Menu */}
      {menuOpen && menuPosition && (
        <div
          data-wb-menu
          data-wb-menu-overlay
          className="wb-menu-overlay fixed z-[10020] max-w-[calc(100vw-1rem)] min-w-[10rem] rounded-lg border border-(--ui-stroke-secondary)
                     bg-(--ui-bg-elevated) p-1 text-[0.8125rem] shadow-lg backdrop-blur-md"
          style={{ left: menuPosition.left, top: menuPosition.top }}
          onClick={(e) => e.stopPropagation()}
        >
          {sectionKey === 'task' && card.status === 'todo' && (
            <>
              <MenuBtn icon="check" label="✓ 归档" onClick={() => { doComplete.mutate(); onMenuOpenChange(null) }} />
              <MenuBtn icon="play" label="▶ 执行" onClick={() => { setExecOpen(true); onMenuOpenChange(null) }} />
              <MenuBtn icon="history" label="↻ 顺延" onClick={() => { doDefer.mutate(); onMenuOpenChange(null) }} />
              <MenuBtn icon="edit" label="✎ 编辑" onClick={() => { setEditOpen(true); onMenuOpenChange(null) }} />
              <MenuBtn icon="trash" label="✖ 放弃" onClick={() => { doAbandon.mutate(); onMenuOpenChange(null) }} />
            </>
          )}
          {canArchive && card.status !== 'todo' && (
            <>
              <MenuBtn icon="check" label="✓ 归档" onClick={() => { doComplete.mutate(); onMenuOpenChange(null) }} />
              {card.session_id && (
                <MenuBtn icon="link-external" label="▶ 打开会话" onClick={() => { host.navigate('/' + encodeURIComponent(card.session_id!)); onMenuOpenChange(null) }} />
              )}
            </>
          )}
          {sectionKey === 'task' && card.status === 'abandoned' && (
            <MenuBtn icon="refresh" label="↩ 重新打开" onClick={() => { doReopen.mutate(); onMenuOpenChange(null) }} />
          )}
          {sectionKey === 'done' && (
            <>
              {card.session_id && (
                <MenuBtn icon="link-external" label="▶ 打开会话" onClick={() => { host.navigate('/' + encodeURIComponent(card.session_id!)); onMenuOpenChange(null) }} />
              )}
              <MenuBtn icon="refresh" label="↩ 回到任务列表" onClick={() => { doReopen.mutate(); onMenuOpenChange(null) }} />
              {/* 08-21：doTrash 曾定义未用——补「移到回收站」菜单项（软删除，回收站可还原） */}
              <MenuBtn icon="trash" label="🗑 移到回收站" onClick={() => { doTrash.mutate(); onMenuOpenChange(null) }} />
              <MenuBtn icon="trash" label="🗑 永久删除" onClick={() => { if (confirm('确定永久删除？不可恢复。')) { doDelete.mutate(); onMenuOpenChange(null) } }} />
            </>
          )}
          {sectionKey === 'trash' && (
            <>
              <MenuBtn icon="refresh" label="↩ 还原" onClick={() => { doRestore.mutate(); onMenuOpenChange(null) }} />
              <MenuBtn icon="trash" label="🗑 永久删除" onClick={() => { if (confirm('确定永久删除？不可恢复。')) { doDelete.mutate(); onMenuOpenChange(null) } }} />
            </>
          )}
          {sectionKey !== 'task' && sectionKey !== 'done' && sectionKey !== 'trash' && card.entry_count > 0 && (
            <>
              <MenuBtn icon="check" label="✓ 确认处理" onClick={() => { doResolve.mutate(); onMenuOpenChange(null) }} />
              <MenuBtn icon="play" label="▶ 执行" onClick={() => { setExecOpen(true); onMenuOpenChange(null) }} />
              <MenuBtn icon="arrow-right" label="↻ 转任务" onClick={() => { doToTask.mutate(); onMenuOpenChange(null) }} />
              <MenuBtn icon="edit" label="✎ 编辑" onClick={() => { setEditOpen(true); onMenuOpenChange(null) }} />
            </>
          )}
          <MenuBtn icon="eye" label="👁 预览" onClick={() => { onPreview(card); onMenuOpenChange(null) }} />
          <MenuBtn icon="file" label="📂 复制路径" onClick={() => { copyPath(); onMenuOpenChange(null) }} />
        </div>
      )}
    </div>
    {execOpen && (
      <ExecEditDialog
        card={card}
        onClose={() => setExecOpen(false)}
        onConfirm={(o) => { setExecOpen(false); card.entry_title ? execAggregate(o) : execTask(o) }}
      />
    )}
    {editOpen && (
      <EditDialog
        card={card}
        onClose={() => setEditOpen(false)}
        onConfirm={async (o) => {
          setEditOpen(false)
          try {
            const res = await editEntry({ dir: card.dir, file: card.file, entry_title: card.entry_title || undefined, title: o.title, content: o.content, due: o.due })
            if (!res.ok) {
              host.notify({ kind: 'error', message: res.error || '保存失败' })
              return
            }
            invalidateBoard()
            host.notify({ kind: 'success', message: '已保存' })
          } catch (err) {
            host.notify({ kind: 'error', message: String(err) })
          }
        }}
      />
    )}
    </>
  )
}

function MenuBtn({ icon, label, onClick }: { icon: string; label: string; onClick: () => void }) {
  return (
    <button
      className="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-(--ui-text-primary)
                 hover:bg-(--ui-stroke-secondary)"
      onClick={onClick}
      type="button"
    >
      {label}
    </button>
  )
}

// ── Section (column) ──────────────────────────────────────────────────

function WbSectionView({ section, onPreview, openMenuKey, onMenuOpenChange, multiMode, selected, onToggleSelect, conversationPlatformsByTask, onOpenConversations }: {
  section: WbSection
  onPreview: (c: WbCard) => void
  openMenuKey: string | null
  onMenuOpenChange: (key: string | null) => void
  multiMode: boolean
  selected: Set<string>
  onToggleSelect: (key: string) => void
  conversationPlatformsByTask: Map<string, string[]>
  onOpenConversations: () => void
}) {
  const meta = partitionMeta(section.key)
  const label = section.label ?? meta.label
  const collapsedOverride = useValue($collapsedSections)[section.key]
  // 08-21：默认全展开（列内滚动已解决延申）；保留 hooks 结构防 310；
  // 单卡异常由 CardErrorBoundary 隔离。
  const [showAllArchived, setShowAllArchived] = useState(true)

  // Apply filter
  const filterText = useValue($filterText).toLowerCase()
  const tagFilter = useValue($tagFilter)
  const showArchived = useValue($showArchived)
  // P0-3：到期/超期快捷筛选
  const dueFilter = useValue($dueFilter)
  const todayLocal = useMemo(() => {
    const n = new Date()
    return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, '0')}-${String(n.getDate()).padStart(2, '0')}`
  }, [])

  // 补丁 15：聚合文件按条目展开（阶段 1 语义回归修复）——待验证/待回看/心理学随想/
  // 梦中的邮件（entry_count > 0）按 ## 条目逐条展开成卡；任务/已处理/回收站整文件一卡。
  const expanded = useMemo(() => {
    const out: WbCard[] = []
    for (const card of section.files) {
      if (card.entry_count > 0 && card.entries.length > 0) {
        for (const entry of card.entries) {
          out.push({ ...card, title: entry, entry_title: entry })
        }
      } else if (card.entry_count === 0 && section.key !== 'task' && section.key !== 'done' && section.key !== 'trash') {
        // A1 ①：聚合空壳（全条目已 resolve，只剩 frontmatter）不渲染——不显示「待回看收录 2026-08-15」单卡
        continue
      } else {
        out.push(card)
      }
    }
    return out
  }, [section.files, section.key])

  const filtered = useMemo(() => {
    if (!filterText && (section.key === 'done' || section.key === 'trash') && !showArchived) {
      return []
    }
    return expanded.filter(c =>
      (tagFilter ? (c.tags?.includes(tagFilter) ?? false) : true) &&
      (dueFilter === 'all'
        ? true
        : c.due
          ? dueFilter === 'today' ? c.due === todayLocal : c.due < todayLocal
          : false) &&
      (!filterText ||
        c.title.toLowerCase().includes(filterText) ||
        c.file.toLowerCase().includes(filterText))
    )
  }, [expanded, filterText, tagFilter, dueFilter, todayLocal, showArchived, section.key])

  // 二级折叠逻辑保留但默认关闭（showAllArchived=true 恒显示全部；按钮不出现）
  const ARCHIVED_PREVIEW_LIMIT = 10
  const archivedPreview = section.key === 'done' || section.key === 'trash'
  const visible = archivedPreview && !showAllArchived ? filtered.slice(0, ARCHIVED_PREVIEW_LIMIT) : filtered


  // 2026-08-22（已拍板等宽）：所有分区默认展开为等宽列（w-[16rem]），
  // 不再按分区/空内容自动折叠成窄轨；手动折叠仍可用（collapsedOverride 优先）。
  const collapsed = collapsedOverride ?? filtered.length === 0

  const toggleCollapse = () => {
    const current = $collapsedSections.get()
    $collapsedSections.set({ ...current, [section.key]: !collapsed })
  }

  // 计数语义：聚合分区按条目计数（后端 entry_count，空壳文件=0 不计）；单卡分区按文件计数
  const isAggregate =
    section.key === 'thought' || section.key === 'video' || section.key === 'psych' || section.key === 'dream'
  const cardCount = section.files.reduce(
    (n, f) => n + (isAggregate ? (f.entry_count || 0) : f.entry_count > 0 ? f.entry_count : 1),
    0,
  )

  if (!showArchived && (section.key === 'done' || section.key === 'trash') && filtered.length === 0) {
    return null
  }

  if (collapsed) {
    return (
      <button
        type="button"
        className="wb-section--collapsed flex h-full w-8 shrink-0 flex-col items-center gap-1.5 rounded-lg p-2 transition-colors hover:bg-(--ui-stroke-secondary)"
        onClick={toggleCollapse}
        aria-label={`展开${label}`}
        title={`展开${label}`}
      >
        <span className="grid h-5 shrink-0 place-items-center">
          <span className="size-1.5 rounded-full" style={{ backgroundColor: meta.tone }} />
        </span>
        <span className="text-[0.6875rem] font-medium uppercase tracking-wide text-(--ui-text-tertiary) [writing-mode:vertical-rl]">
          {meta.label}
        </span>
        {cardCount > 0 && (
          <span className="text-[0.6875rem] tabular-nums text-(--ui-text-quaternary)">{cardCount}</span>
        )}
      </button>
    )
  }

  return (
    <div className="wb-section flex min-h-0 max-h-full shrink-0 flex-col rounded-lg p-2 transition-colors bg-[color-mix(in_srgb,var(--ui-bg-quinary)_50%,transparent)]">
      {/* Column header */}
      <button
        className={cn(
          'flex h-6 items-center gap-1.5 rounded px-1 text-left',
          'text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary)'
        )}
        onClick={toggleCollapse}
        type="button"
      >
        <Codicon name={collapsed ? 'chevron-right' : 'chevron-down'} size="0.7rem" />
        <span className="size-1.5 rounded-full" style={{ backgroundColor: meta.tone }} />
        <span className="text-[0.8125rem] font-semibold">{label}</span>
        <span className="ml-auto text-[0.75rem] tabular-nums text-(--ui-text-quaternary)">{cardCount}</span>
      </button>

      {/* Cards */}
      {!collapsed && (
        <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto">
          {filtered.length === 0 && (
            <span className="px-2 py-3 text-center text-[0.75rem] text-(--ui-text-quaternary)">暂无条目</span>
          )}
          {visible.map(card => (
            <CardErrorBoundary key={card.file + (card.entry_title || '')}>
              <WbCardView
                card={card}
                sectionKey={section.key}
                onPreview={onPreview}
                openMenuKey={openMenuKey}
                onMenuOpenChange={onMenuOpenChange}
                multiMode={multiMode}
                selected={selected}
                onToggleSelect={onToggleSelect}
                conversationPlatforms={card.task_id ? (conversationPlatformsByTask.get(card.task_id) ?? []) : []}
                onOpenConversations={onOpenConversations}
              />
            </CardErrorBoundary>
          ))}
          {archivedPreview && filtered.length > ARCHIVED_PREVIEW_LIMIT && !showAllArchived && (
            <button
              type="button"
              className="rounded border border-(--ui-stroke-secondary) px-2 py-1 text-[0.6875rem] text-(--ui-text-secondary) hover:border-(--ui-accent) hover:text-(--ui-accent)"
              onClick={() => setShowAllArchived(true)}
            >
              显示全部（{filtered.length} 条）
            </button>
          )}
        </div>
      )}
    </div>
  )
}



// ── ExecEditDialog (补丁 16)：执行前编辑浮窗（复用 NewTaskDialog 风格：
//    w-[52rem]、遮罩不响应点击、主题 token；字段：标题/内容(执行前补充)/Due） ───

/** 执行前编辑预填：提取任务文件的用户内容（去 frontmatter + 系统历史段落）。
 *  保留 备注 / 执行前补充 / 手动添加 等用户指令，避免编辑框空白导致重复添加冲突。
 *  08-21 增强：①统一行尾（QQ/manual 文件 CRLF、脚本文件 LF 混存）；②剥文件头与正文内嵌的
 *  类 frontmatter 块（收录时写入的 ---type: queued--- 块）；③去「原始消息」段落——标题与
 *  文件同名、或标题/正文含链接标记（b23.tv / - URL: / - 来源：），含重复嵌套在「执行前补充」
 *  里的同一消息；用户手写纯文本指令（如「只研究，不摄入 Obsidian」）保留。 */
function extractTaskBody(md: string): string {
  const text = md.replace(/\r\n/g, '\n')
  const title = (text.match(/^#\s+(.+)$/m)?.[1] ?? '').trim()
  const esc = title ? title.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') : ''
  // ① 文件头 frontmatter（首个 --- 块；m 标志 + 行首锚定，兼容 CRLF 统一后的 LF）
  let cleaned = text.replace(/^---[\s\S]*?^---\s*\n?/m, '')
  // ② 正文内嵌的类 frontmatter 块：--- 包住且每行都是「key: value」YAML 形状。
  //    （不能用任意 --- 配对——正文里的横向分隔线会配错对，实测 08-21）
  cleaned = cleaned.replace(/^---\n((?:[ \t]*[\w-]+:[^\n]*\n)+?)^---\s*$/gm, '')
  // ③ 系统历史段落（完成/处理/重新打开/执行/失败/原始消息）。
  //    JS 无 \Z 锚点（\Z 按字面 Z 处理）——用 (?![\s\S]) 表示「输入结束」，
  //    否则最后一个系统段（如末尾的 完成记录/执行记录）永远删不掉。
  const SYS = /^##\s*(完成记录|处理记录|重新打开记录|执行记录|执行失败记录|原始消息)[\s\S]*?(?=^##\s|(?![\s\S]))/gm
  cleaned = cleaned.replace(SYS, '').trim()
  // ④ H1 标题行
  cleaned = cleaned.replace(/^#\s+.+\n?/, '').trim()
  // ⑤ 去「原始消息」段落：标题与文件同名，或标题/正文含链接标记（b23.tv / - URL: / - 来源:）。
  //    这类段落是转任务时写进文件的 QQ/B站消息原文，卡片上已可见，编辑框不必再显示；
  //    嵌套在「执行前补充」里的重复消息同样被删，但用户手写纯文本指令保留。
  const MSG = /^##\s+[^\n]+\s*$[\s\S]*?(?=^##\s|(?![\s\S]))/gm
  cleaned = cleaned.replace(MSG, whole => {
    const heading = whole.slice(0, whole.indexOf('\n')).trim()
    if (esc && heading === `## ${title}`) return ''
    if (/b23\.tv|(?:youtube\.com|youtu\.be)/i.test(heading)) return ''
    if (/(?:^|\n)[ \t]*(?:[-•*][ \t]*)?(?:URL|链接|来源)[ \t]*[:：]/.test(whole)) return ''
    return whole
  }).trim()
  // ⑥ 清理残留的横向分隔线（---）与空标题段（如「执行前补充」只剩重复消息被删后的空段）
  cleaned = cleaned.replace(/^---\s*$/gm, '').trim()
  cleaned = cleaned.replace(/^##\s+[^\n]*\n*(?=##\s|(?![\s\S]))/gm, '').trim()
  return cleaned
}

/** 聚合条目卡：只提取当前条目对应的 ## 小节（不含同文件其他条目），
 *  并清理小节内的内嵌 frontmatter 与尾部 --- 分隔线（08-21）。
 *  之前执行前编辑取整个聚合文件 → 点哪张卡都显示全部条目。 */
function extractEntrySection(md: string, entryTitle: string): string {
  const text = md.replace(/\r\n/g, '\n')
  const esc = entryTitle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const m = text.match(new RegExp(`^##\\s*${esc}\\s*$[\\s\\S]*?(?=^##\\s|(?![\\s\\S]))`, 'm'))
  if (!m) return ''
  let sec = m[0]
  sec = sec.replace(/^---\n((?:[ \t]*[\w-]+:[^\n]*\n)+?)^---\s*$/gm, '')
  sec = sec.replace(/^---\s*$/gm, '')
  // 08-21：预览只显示用户内容——剥掉收录元数据行（原始消息/URL/链接/来源）。
  // 元数据保留在文件里可追溯，仅不在预览展示；带 [:：] 防误伤正文行。
  sec = sec.replace(/^[ \t]*(?:[-•*][ \t]*)?(?:原始消息|URL|链接|来源)[ \t]*[:：].*$/gm, '')
  // 只剩标题（无实际内容）→ 返回空，预览显示「无额外内容」
  sec = sec.trim()
  return /^##\s+[^\n]+$/.test(sec) ? '' : sec
}

function ExecEditDialog({ card, onClose, onConfirm }: {
  card: WbCard
  onClose: () => void
  onConfirm: (o: { title?: string; content?: string; due?: string }) => void
}) {
  const [title, setTitle] = useState(card.title || card.file.replace(/\.md$/, ''))
  const [content, setContent] = useState('')
  const [due, setDue] = useState(card.due || '')
  const [rawBody, setRawBody] = useState('')
  const [rawOriginal, setRawOriginal] = useState('')
  const [editingRaw, setEditingRaw] = useState(false)
  const [busy, setBusy] = useState(false)

  // 2026-08-20 简化：补充框默认空（编辑优先、不被任务正文干扰）；
  // 任务正文/原始内容提取后只读展示在分隔线下方，供查看不预填。
  // 方案 Z：默认只读；"修正原文"按钮开启可编辑，保存时 amend 写回（带 edited_by_user 标记）。
  useEffect(() => {
    let cancelled = false
    void fetchFile(card.dir, card.file)
      .then(res => {
        if (cancelled) return
        // 条目卡只显示当前条目小节；任务卡显示整个任务文件清理后的正文（08-21）
        const body = card.entry_title
          ? extractEntrySection(res?.content || '', card.entry_title)
          : extractTaskBody(res?.content || '')
        if (body) {
          setRawBody(body)
          setRawOriginal(body)
        }
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [card.dir, card.file, card.entry_title])

  const submit = async () => {
    const t = title.trim()
    if (!t) {
      host.notify({ kind: 'error', message: '标题不能为空' })
      return
    }
    setBusy(true)
    try {
      // 方案 Z：修正过原文 → 先 amend 写回（保留 frontmatter + edited_by_user 标记），再执行。
      // 条目卡禁止文件级 amend（会整体覆盖聚合文件）——修正条目请走「✎ 编辑」。
      if (!card.entry_title && editingRaw && rawBody.trim() !== rawOriginal.trim()) {
        const amendRes = await editEntry({ dir: card.dir, file: card.file, amend: true, content: rawBody.trim() })
        if (!amendRes.ok) {
          host.notify({ kind: 'error', message: `修正原文失败：${amendRes.error || '未知错误'}` })
          return
        }
      }
      await onConfirm({ title: t, content: content.trim() || undefined, due: due.trim() || undefined })
    } finally {
      setBusy(false)
    }
  }

  const field = 'w-full rounded border border-(--ui-stroke-secondary) bg-(--ui-bg) px-2 py-1 text-[0.75rem] text-(--ui-text-primary) outline-none focus:border-(--ui-accent)'

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent
        className="wb-dialog"
        style={{ width: 'min(52rem, 94vw)', maxWidth: '94vw' }}
      >
        <DialogHeader>
          <DialogTitle>▶ 执行前编辑</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-2">
          <label className="flex flex-col gap-1 text-[0.8125rem] text-(--ui-text-secondary)">
            标题
            <input className={field} value={title} onChange={(e) => setTitle(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1 text-[0.8125rem] text-(--ui-text-secondary)">
            内容（执行前补充）
            <textarea className={field + ' min-h-[5rem] resize-y'} value={content} onChange={(e) => setContent(e.target.value)} placeholder={'可选：补充执行要求（如「只研究，不摄入 Obsidian」）'} />
          </label>
          <div className="my-1 border-t border-(--ui-stroke-secondary)" aria-hidden="true" />
          <label className="flex flex-col gap-1 text-[0.8125rem] text-(--ui-text-secondary)">
            <span className="flex items-center justify-between">
              原始内容{editingRaw ? '（修正模式）' : '（只读）'}
              {card.entry_title ? (
                <span className="text-[0.6875rem] text-(--ui-text-quaternary)">
                  条目内容（修正请用 ✎ 编辑）
                </span>
              ) : (
                <button
                  type="button"
                  className="rounded border border-(--ui-stroke-secondary) px-2 py-0.5 text-[0.6875rem] text-(--ui-text-secondary) hover:border-(--ui-accent) hover:text-(--ui-accent)"
                  onClick={() => setEditingRaw(v => !v)}
                >
                  {editingRaw ? '完成修正' : '修正原文'}
                </button>
              )}
            </span>
            {editingRaw ? (
              <textarea
                className={field + ' min-h-[8rem] resize-y'}
                value={rawBody}
                onChange={(e) => setRawBody(e.target.value)}
              />
            ) : (
              <div className={field + ' max-h-[12rem] overflow-y-auto whitespace-pre-wrap break-words'}>
                {rawBody || '（无额外内容）'}
              </div>
            )}
          </label>
          <label className="flex flex-col gap-1 text-[0.8125rem] text-(--ui-text-secondary)">
            Due
            <input className={field} type="date" value={due} onChange={(e) => setDue(e.target.value)} />
          </label>
        </div>
        <DialogFooter>
          <Button size="sm" variant="outline" onClick={onClose}>取消</Button>
          <Button size="sm" onClick={submit} disabled={busy}>{busy ? '执行中…' : '确认执行'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ── A2：✎ 编辑浮窗（聚合条目 / 任务文件：title/content/due，不改状态） ────

function EditDialog({ card, onClose, onConfirm }: {
  card: WbCard
  onClose: () => void
  onConfirm: (o: { title?: string; content?: string; due?: string }) => void | Promise<void>
}) {
  const [title, setTitle] = useState(card.title || card.file.replace(/\.md$/, ''))
  const [content, setContent] = useState('')
  const [due, setDue] = useState(card.due || '')
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    const t = title.trim()
    if (!t) {
      host.notify({ kind: 'error', message: '标题不能为空' })
      return
    }
    setBusy(true)
    try {
      await onConfirm({ title: t, content: content.trim() || undefined, due: due.trim() || undefined })
    } finally {
      setBusy(false)
    }
  }

  const field = 'w-full rounded border border-(--ui-stroke-secondary) bg-(--ui-bg) px-2 py-1 text-[0.75rem] text-(--ui-text-primary) outline-none focus:border-(--ui-accent)'

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent
        className="wb-dialog"
        style={{ width: 'min(52rem, 94vw)', maxWidth: '94vw' }}
      >
        <DialogHeader>
          <DialogTitle>✎ 编辑</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-2">
          <label className="flex flex-col gap-1 text-[0.8125rem] text-(--ui-text-secondary)">
            标题
            <input className={field} value={title} onChange={(e) => setTitle(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1 text-[0.8125rem] text-(--ui-text-secondary)">
            内容（备注/补充）
            <textarea className={field + ' min-h-[6rem] resize-y'} value={content} onChange={(e) => setContent(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1 text-[0.8125rem] text-(--ui-text-secondary)">
            Due
            <input className={field} type="date" value={due} onChange={(e) => setDue(e.target.value)} />
          </label>
        </div>
        <DialogFooter>
          <Button size="sm" variant="outline" onClick={onClose}>取消</Button>
          <Button size="sm" onClick={submit} disabled={busy}>{busy ? '保存中…' : '保存'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ── DialogSelect (补丁 14)：主题 token 自定义下拉（原生 select option 背景不可控、
//    SDK Select 插件环境不可靠，弃用两者）。点击外部/选中后关闭。 ───────────

function DialogSelect({ value, onChange, options, placeholder }: {
  value: string
  onChange: (v: string) => void
  options: Array<{ value: string; label: string }>
  placeholder?: string
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  // 补丁 20：value 一变即收起（最可靠——覆盖任何事件时序干扰）
  useEffect(() => {
    setOpen(false)
  }, [value])

  const current = options.find(o => o.value === value)

  return (
    <div className="relative" ref={ref}>
      <button
        className="flex w-full items-center justify-between rounded border border-(--ui-stroke-secondary) bg-(--ui-bg) px-2 py-1 text-[0.75rem] text-(--ui-text-primary) outline-none hover:border-(--ui-accent)"
        onClick={() => setOpen(!open)}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className="truncate">{current ? current.label : (placeholder || '')}</span>
        <Codicon name={open ? 'chevron-up' : 'chevron-down'} size="0.7rem" />
      </button>
      {open && (
        <div
          className="absolute top-full left-0 z-50 mt-1 max-h-48 w-full overflow-y-auto rounded border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated) p-1 shadow-lg"
          role="listbox"
        >
          {options.map(o => (
            <button
              key={o.value}
              className={cn(
                'flex w-full items-center rounded px-2 py-1 text-left text-[0.75rem]',
                o.value === value
                  ? 'bg-(--ui-accent)/10 text-(--ui-accent)'
                  : 'text-(--ui-text-primary) hover:bg-(--ui-stroke-secondary)'
              )}
              onPointerDown={(e) => {
                e.preventDefault()
                setOpen(false)
                onChange(o.value)
              }}
              onClick={() => { setOpen(false); onChange(o.value) }}
              type="button"
              role="option"
              aria-selected={o.value === value}
            >
              {o.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ── New task dialog (Task 5.2 批次 5 补丁 10) ─────────────────────────

const NEW_TASK_DIRS = [
  { value: '任务', label: '任务' },
  { value: '待验证', label: '待验证' },
  { value: '待回看', label: '待回看' },
  { value: '心理学随想', label: '心理学随想' },
  { value: '梦中的邮件', label: '梦中的邮件' },
]

const PRIORITY_OPTIONS = [
  { value: '', label: '无' },
  { value: 'P0', label: 'P0' },
  { value: 'P1', label: 'P1' },
  { value: 'P2', label: 'P2' },
  { value: 'P3', label: 'P3' },
]

function NewTaskDialog({ board, onClose }: { board: WbBoard; onClose: () => void }) {
  const [dir, setDir] = useState('任务')
  const [title, setTitle] = useState('')
  // Phase 0-8：priority 手动选择已从新建浮窗移除（默认由 Agent 建议/系统推断；徽标无值不显示）
  const [due, setDue] = useState('')
  const [content, setContent] = useState('')
  const [busy, setBusy] = useState(false)
  // C2（P1-4）：标签建议 chips（前端轻量规则；禁自动写入——点选才进 picked）
  const [suggestion, setSuggestion] = useState<null | TagSuggestion>(null)
  const [picked, setPicked] = useState<Set<string>>(new Set())

  const knownTags = useMemo(() => {
    const set = new Set<string>()
    for (const s of board.sections) for (const c of s.files) for (const t of c.tags || []) set.add(t)
    return Array.from(set)
  }, [board])

  // 300ms 防抖：内容输入后建议
  useEffect(() => {
    if (!title.trim() && !content.trim()) {
      setSuggestion(null)
      return
    }
    const timer = window.setTimeout(() => {
      setSuggestion(suggestTags(title, content, knownTags))
    }, 300)
    return () => window.clearTimeout(timer)
  }, [title, content, knownTags])

  const submit = async () => {
    const t = title.trim()
    if (!t) {
      host.notify({ kind: 'error', message: '标题不能为空' })
      return
    }
    setBusy(true)
    try {
      const res = await addEntry({ dir, title: t, due: due || undefined, content: content.trim() || undefined })
      if (!res.ok) {
        host.notify({ kind: 'error', message: res.error || '创建失败' })
        return
      }
      // C2：点选标签写入（创建后 /edit，API-A；禁自动写入）
      if (picked.size > 0 && res.file) {
        const tags = Array.from(picked)
        const ed = await editEntry({ dir, file: res.file, tags })
        if (!ed.ok) host.notify({ kind: 'warning', message: '标签写入失败：' + (ed.error || '') })
      }
      invalidateBoard()
      onClose()
    } catch (err) {
      host.notify({ kind: 'error', message: String(err) })
    } finally {
      setBusy(false)
    }
  }

  const field = 'w-full rounded border border-(--ui-stroke-secondary) bg-(--ui-bg) px-2 py-1 text-[0.75rem] text-(--ui-text-primary) outline-none focus:border-(--ui-accent)'

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent
        className="wb-dialog"
        style={{ width: 'min(52rem, 94vw)', maxWidth: '94vw' }}
      >
        <DialogHeader>
          <DialogTitle>＋ 新建任务</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3">

        <label className="flex flex-col gap-1 text-[0.8125rem] text-(--ui-text-secondary)">
          标题（必填）
          <input className={field} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="任务标题" autoFocus />
        </label>

        <label className="flex flex-col gap-1 text-[0.8125rem] text-(--ui-text-secondary)">
          分区
          <DialogSelect value={dir} onChange={setDir} options={NEW_TASK_DIRS} placeholder="选择分区" />
        </label>

        <label className="flex flex-col gap-1 text-[0.8125rem] text-(--ui-text-secondary)">
          Due（截止日期）
          <input className={field} type="date" value={due} onChange={(e) => setDue(e.target.value)} />
        </label>

        <label className="flex flex-col gap-1 text-[0.8125rem] text-(--ui-text-secondary)">
          内容（可选）
          <textarea className={field + ' min-h-24 resize-y'} value={content} onChange={(e) => setContent(e.target.value)} placeholder="备注/要求…" />
        </label>

        {/* C2（P1-4）：标签建议 chips（点选才写；低置信文本形态；无建议不阻塞） */}
        {(suggestion && (suggestion.tags.length > 0 || suggestion.low.length > 0)) && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[0.8125rem] text-(--ui-text-tertiary)">✨ 建议标签：</span>
            {suggestion.tags.map(tag => {
              const active = picked.has(tag)
              return (
                <button
                  key={tag}
                  className={cn(
                    'rounded px-1.5 py-0.5 text-[0.8125rem] transition-colors',
                    active
                      ? 'bg-(--ui-accent) text-(--ui-bg)'
                      : 'bg-(--ui-bg-quinary) text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary)'
                  )}
                  onClick={() => {
                    setPicked(prev => {
                      const n = new Set(prev)
                      if (n.has(tag)) n.delete(tag)
                      else n.add(tag)
                      return n
                    })
                  }}
                  type="button"
                >
                  {tag}
                </button>
              )
            })}
            {suggestion.low.length > 0 && (
              <span className="text-[0.8125rem] text-(--ui-text-quaternary)">
                建议标签：{suggestion.low.join(' ')}（可确认）
              </span>
            )}
          </div>
        )}

        </div>
        <DialogFooter>
          <Button size="sm" variant="outline" onClick={onClose}>取消</Button>
          <Button size="sm" onClick={() => void submit()} disabled={busy}>{busy ? '创建中…' : '创建'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ── Today view（P0-1，B4）────────────────────────────────────────────
// 2026-08-27 结构纠偏：HomeView/BriefCardView/TodayCardRow/HomeRegionCardList/
// HOME_EMPTY_HINTS/BRIEF_TYPE_META 已整体抽取至 ./home.tsx（逐字搬移，行为零变更）。

// ── Board page ────────────────────────────────────────────────────────

export function WorkbenchBoardPage() {
  const { data: board, isLoading, error } = useQuery({
    queryKey: BOARD_KEY,
    queryFn: () => fetchBoard(),
    refetchInterval: 30_000,
  })
  const [previewCard, setPreviewCard] = useState<null | WbCard>(null)
  // 菜单单例：openMenuKey 全板唯一，打开新卡自动收回旧菜单（补丁 8）
  const [openMenuKey, setOpenMenuKey] = useState<string | null>(null)
  // 点菜单/触发按钮以外任意区域 → 自动收起（2026-08-17）
  useEffect(() => {
    if (!openMenuKey) return
    const onDown = (e: PointerEvent) => {
      if (e.target instanceof Element && e.target.closest('[data-wb-menu]')) return
      setOpenMenuKey(null)
    }
    document.addEventListener('pointerdown', onDown)
    return () => document.removeEventListener('pointerdown', onDown)
  }, [openMenuKey])
  // 补丁 10：新建任务浮窗
  const [showNewTask, setShowNewTask] = useState(false)
  // 2026-08-22：设置浮窗（路径/分区/定时/保留/投递）
  const [showSettings, setShowSettings] = useState(false)
  const [showHealthDetails, setShowHealthDetails] = useState(false)
  // 健康详情与卡片菜单保持同一交互契约：点击组件外部或按 Escape 即收起。
  useEffect(() => {
    if (!showHealthDetails) return
    const onPointerDown = (event: PointerEvent) => {
      if (event.target instanceof Element && event.target.closest('[data-wb-health]')) return
      setShowHealthDetails(false)
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setShowHealthDetails(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [showHealthDetails])
  // P0-3：链路健康 + 投递配置 + 到期筛选（hooks 无条件在顶部）
  const health = useQuery({ queryKey: ['workbench', 'health'], queryFn: fetchHealth, refetchInterval: 30_000 })
  const conversations = useQuery({ queryKey: ['workbench', 'conversations'], queryFn: fetchConversations, refetchInterval: 30_000 })
  const conversationPlatformsByTask = useMemo(() => {
    const grouped = new Map<string, Set<string>>()
    for (const item of conversations.data?.items ?? []) {
      const platforms = grouped.get(item.task_id) ?? new Set<string>()
      platforms.add(item.platform)
      grouped.set(item.task_id, platforms)
    }
    return new Map(Array.from(grouped, ([taskId, platforms]) => [taskId, Array.from(platforms).sort()]))
  }, [conversations.data?.items])
  const settings = useQuery({ queryKey: ['workbench', 'settings'], queryFn: fetchSettings })
  const dueFilter = useValue($dueFilter)
  const [bannerDismissedDate, setBannerDismissedDate] = useState(
    () => (typeof localStorage === 'undefined' ? '' : (localStorage.getItem('wbDeliveryBannerDismissedDate') || ''))
  )
  // P0-1（B4）v2（Task 3）：默认首页 = HomeView；旧七列看板/表格收进「旧版数据」
  const [showLegacy, setShowLegacy] = useState(false)
  const [showConversations, setShowConversations] = useState(false)
  // 视图模式（持久化在 storage；setViewMode 直接写 atom，Input 区下方按钮即见即切）
  const viewMode = useValue($viewMode)
  const setViewMode = (m: 'board' | 'table') => $viewMode.set(m)

  // B2：多选模式 + 批量操作（/batch 端点）
  const [multiMode, setMultiMode] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [batchBusy, setBatchBusy] = useState(false)
  // A4：全局搜索（防抖 250ms → /search；结果下拉点击 → 预览）
  const [searchQ, setSearchQ] = useState('')
  const [debouncedQ, setDebouncedQ] = useState('')
  const [searchOpen, setSearchOpen] = useState(false)
  const searchRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(searchQ.trim()), 250)
    return () => clearTimeout(t)
  }, [searchQ])
  useEffect(() => {
    if (!searchOpen) return
    const onDown = (e: MouseEvent) => {
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) setSearchOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [searchOpen])
  const { data: searchData } = useQuery({
    queryKey: ['workbench', 'search', debouncedQ],
    queryFn: () => fetchSearch(debouncedQ),
    enabled: debouncedQ.length > 0,
  })
  const tagFilter = useValue($tagFilter)
  // 08-21 修复 #300/#310：filterText/showArchived 必须在组件顶部无条件调用
  // （曾写在 JSX 内、位于 isLoading/error/!board 提前 return 之后，导致
  // 加载态 18 hooks vs 完整态 20 hooks 的数量跳变 → Minified React #300/#310）。
  const filterText = useValue($filterText)
  const showArchived = useValue($showArchived)
  const toCard = (r: WbSearchResult, root: string): WbCard => ({
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
  })

  const toggleSelect = (key: string) =>
    setSelected(prev => {
      const n = new Set(prev)
      if (n.has(key)) n.delete(key)
      else n.add(key)
      return n
    })

  const runBatch = async (action: 'complete' | 'resolve' | 'trash') => {
    if (selected.size === 0) return
    setBatchBusy(true)
    try {
      const items = Array.from(selected).map(k => {
        const [dir, file, entry_title] = JSON.parse(k) as [string, string, string]
        return { dir, file, ...(entry_title ? { entry_title } : {}) }
      })
      const res = await batchAction(action, items)
      consumeLegacyBatchResponse(action, items, res, {
        notify: notice => host.notify(notice),
        invalidate: invalidateBoard,
        replaceSelection: failedItems => setSelected(new Set(failedItems.map(item => JSON.stringify([
          item.dir,
          item.file,
          item.entry_title ?? '',
        ])))),
        clearSelection: () => setSelected(new Set()),
        exitMultiMode: () => setMultiMode(false),
      })
    } catch (err) {
      host.notify({ kind: 'error', message: String(err) })
    } finally {
      setBatchBusy(false)
    }
  }

  if (isLoading) {
    return <div className="flex h-full items-center justify-center text-sm text-(--ui-text-tertiary)">加载中…</div>
  }
  if (error) {
    return <div className="flex h-full items-center justify-center text-sm text-(--ui-red)">后端不可达</div>
  }
  if (!board) return null

  const deliverMissing = settings.data?.ok === true && !settings.data.config.deliver_target
  const showDeliveryBanner = !!deliverMissing && bannerDismissedDate !== board.today
  const healthData = health.data
  // Task 6（2026-08-27）：三色语义单源化——绿/黄/红；灰只留在明细行。
  // data 未到或未知档 fail-closed：灯点用中性占位，不发黄不发红。
  const healthDot = health.isLoading
    ? 'bg-(--ui-stroke-secondary)'
    : healthData && (healthData.status === 'green' || healthData.status === 'yellow' || healthData.status === 'red')
      ? { green: 'bg-[#34d399]', yellow: 'bg-[#fbbf24]', red: 'bg-[#f87171]' }[healthData.status]
      : 'bg-(--ui-stroke-secondary)'
  // 明细行允许灰色（未开始/忽略的检查项）
  const checkTone = (status: 'green' | 'yellow' | 'red' | 'disabled') => ({
    green: 'bg-[#34d399]',
    yellow: 'bg-[#fbbf24]',
    red: 'bg-[#f87171]',
    disabled: 'bg-[#94a3b8]',
  }[status])
  const healthLabel = health.isLoading
    ? '健康检查…'
    : health.error
      ? '暂时不可用'
      : ({ green: '一切正常', yellow: '有点状况', red: '暂时不可用', disabled: '健康检查…' } as Record<string, string>)[healthData?.status ?? 'disabled']

  return (
    <div className="wb-root flex h-full flex-col">
      {/* P0-3：未配置投递横幅 */}
      {showDeliveryBanner && (
        <div className="flex items-center gap-2 border-b border-[#fbbf24]/30 bg-[#fbbf24]/10 px-3 py-1.5 text-[0.75rem] text-[#fbbf24]">
          <Codicon name="warning" size="0.8rem" />
          <span>投递目标未配置，日报/提醒不会发送到 QQ。</span>
          <button
            type="button"
            className="rounded border border-[#fbbf24]/40 px-1.5 py-0.5 hover:bg-[#fbbf24]/20"
            onClick={() => setShowSettings(true)}
          >
            去设置
          </button>
          <button
            type="button"
            className="text-[0.6875rem] text-[#fbbf24]/70 hover:text-[#fbbf24]"
            onClick={() => {
              setBannerDismissedDate(board.today)
              localStorage.setItem('wbDeliveryBannerDismissedDate', board.today)
            }}
          >
            今日忽略
          </button>
        </div>
      )}
      {/* Toolbar */}
      <div className="flex items-center gap-2 border-b border-(--ui-stroke-secondary) px-3 py-2">
        <Codicon name="checklist" size="1rem" />
        <span className="text-sm font-semibold">工作台</span>
        {/* WB-S1-030：主导航只保留当前产品面；完整旧数据降为显式兼容入口。 */}
        <div data-wb-primary-nav className="flex items-center rounded-md border border-(--ui-stroke-secondary) p-0.5">
          <button
            type="button"
            className={cn(
              'rounded px-2 py-0.5 text-[0.8125rem] transition-colors',
              !showLegacy && !showConversations ? 'bg-(--ui-accent) text-white' : 'text-(--ui-text-tertiary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-text-primary)'
            )}
            onClick={() => { setShowLegacy(false); setShowConversations(false) }}
          >
            首页
          </button>
          <button
            type="button"
            className={cn(
              'rounded px-2 py-0.5 text-[0.8125rem] transition-colors',
              showConversations ? 'bg-(--ui-accent) text-white' : 'text-(--ui-text-tertiary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-text-primary)'
            )}
            onClick={() => { setShowLegacy(false); setShowConversations(true) }}
          >
            消息任务
          </button>
        </div>
        <button
          data-wb-legacy-entry
          type="button"
          title="兼容入口：保留完整列表、项目分组、批量操作与异常状态修复"
          aria-pressed={showLegacy && !showConversations}
          className={cn(
            'inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[0.75rem] transition-colors',
            showLegacy && !showConversations
              ? 'bg-(--ui-stroke-secondary) text-(--ui-text-primary)'
              : 'text-(--ui-text-quaternary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-text-secondary)'
          )}
          onClick={() => { setShowLegacy(true); setShowConversations(false) }}
        >
          <Codicon name="archive" size="0.65rem" />
          完整数据（兼容）
        </button>
        <span className="text-[0.75rem] text-(--ui-text-quaternary)">
          {board.totals.pending} Pending / {board.totals.total} Total
        </span>
        <div className="ml-auto flex items-center gap-2">
          {!multiMode && (
            <Button size="sm" variant="outline" onClick={() => { setSelected(new Set()); setMultiMode(true) }}>
              <Codicon name="checklist" size="0.7rem" />
              <span className="ml-1">批量</span>
            </Button>
          )}
          <Button size="sm" onClick={() => setShowNewTask(true)}>
            <Codicon name="add" size="0.7rem" />
            <span className="ml-1">新建任务</span>
          </Button>
          {/* A4：全局搜索（/search；结果点击 → 预览抽屉） */}
          <div className="relative" ref={searchRef}>
            <Input
              className="h-7 w-52 text-[0.8125rem]"
              placeholder="搜索…"
              value={searchQ}
              onChange={(e) => { setSearchQ(e.target.value); setSearchOpen(true) }}
              onFocus={() => setSearchOpen(true)}
              onKeyDown={(e) => { if (e.key === 'Escape') { setSearchQ(''); setSearchOpen(false) } }}
            />
            {searchOpen && debouncedQ && searchData && (
              <div className="absolute right-0 top-full z-50 mt-1 max-h-80 w-72 overflow-y-auto rounded-lg border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated) p-1 text-[0.8125rem] shadow-lg">
                {searchData.results.length === 0 ? (
                  <div className="px-2 py-2 text-(--ui-text-tertiary)">无匹配结果</div>
                ) : (
                  searchData.results.map(r => (
                    <button
                      key={`${r.dir}:${r.file}`}
                      type="button"
                      className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left hover:bg-(--ui-stroke-secondary)"
                      onPointerDown={() => { setPreviewCard(toCard(r, board.root)); setSearchOpen(false) }}
                    >
                      <span className="shrink-0 text-[0.75rem] text-(--ui-text-tertiary)">
                        {partitionMeta(r.key).label}
                      </span>
                      <span className="min-w-0 flex-1 truncate font-medium text-(--ui-text-primary)">{r.title}</span>
                      {r.tags.slice(0, 2).map(t => (
                        <span key={t} className="shrink-0 rounded bg-(--ui-accent)/10 px-1 text-[0.75rem] text-(--ui-accent)">
                          {t}
                        </span>
                      ))}
                    </button>
                  ))
                )}
              </div>
            )}
          </div>
          {/* A5：激活的标签过滤（点击 chip 清除） */}
          {tagFilter && (
            <button
              type="button"
              className="flex items-center gap-1 rounded-full bg-(--ui-accent)/15 px-2 py-0.5 text-[0.8125rem] text-(--ui-accent)"
              onClick={() => $tagFilter.set('')}
            >
              #{tagFilter}
              <Codicon name="close" size="0.6rem" />
            </button>
          )}
          <Input
            className="h-7 w-44 text-[0.8125rem]"
            placeholder="筛选…"
            value={filterText}
            onChange={(e) => $filterText.set(e.target.value)}
          />
          <Button
            size="sm"
            variant="outline"
            onClick={() => $showArchived.set(!$showArchived.get())}
          >
            {showArchived ? '隐藏已归档' : '显示已归档'}
          </Button>
          {/* P0-3：到期/超期快捷筛选 */}
          <div className="flex items-center rounded-md border border-(--ui-stroke-secondary) p-0.5">
            {([
              ['all', '全部'],
              ['today', '今天到期'],
              ['overdue', '已超期'],
            ] as const).map(([key, label]) => (
              <button
                key={key}
                type="button"
                className={cn(
                  'rounded px-2 py-0.5 text-[0.75rem] transition-colors',
                  dueFilter === key
                    ? 'bg-(--ui-accent) text-white'
                    : 'text-(--ui-text-tertiary) hover:bg-(--ui-stroke-secondary) hover:text-(--ui-text-primary)'
                )}
                onClick={() => $dueFilter.set(key)}
              >
                {label}
              </button>
            ))}
          </div>
          {/* P0-3：链路健康条 */}
          <div className="relative" data-wb-health>
            <button
              type="button"
              className="flex items-center gap-1 rounded px-1.5 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary)"
              onClick={() => setShowHealthDetails(v => !v)}
              aria-expanded={showHealthDetails}
              title="查看链路健康详情"
            >
              <span className={`size-2 rounded-full ${healthDot}`} />
              <span>{healthLabel}</span>
              <Codicon name={showHealthDetails ? 'chevron-up' : 'chevron-down'} size="0.65rem" />
            </button>
            {showHealthDetails && healthData && (
              <div className="wb-health-popover absolute right-0 top-full z-30 mt-1 w-72 rounded-md p-2 text-(--ui-text-primary)">
                <div className="mb-1.5 flex items-center justify-between text-[0.75rem] font-semibold text-(--ui-text-primary)">
                  <span>链路健康详情</span>
                  <span className="font-normal text-(--ui-text-quaternary)">{healthData.ts}</span>
                </div>
                <div className="space-y-1">
                  {healthData.checks.map(check => (
                    <div key={check.id} className="flex items-start gap-2 rounded px-1.5 py-1 hover:bg-(--ui-bg-quaternary)">
                      <span className={`mt-1 size-2 shrink-0 rounded-full ${checkTone(check.status)}`} />
                      <div className="min-w-0 flex-1">
                        <div className="text-[0.75rem] text-(--ui-text-primary)">{check.label}</div>
                        <div className="text-[0.6875rem] text-(--ui-text-tertiary)">{check.detail}</div>
                      </div>
                    </div>
                  ))}
                </div>
                {healthData.last_updated && (
                  <div className="mt-1.5 border-t border-(--ui-stroke-secondary) pt-1.5 text-[0.6875rem] text-(--ui-text-quaternary)">
                    最近状态更新：{healthData.last_updated.replace('T', ' ')}
                  </div>
                )}
              </div>
            )}
          </div>
          {/* 2026-08-22：个性化设置 */}
          <Button size="sm" variant="outline" onClick={() => setShowSettings(true)} title="工作台设置">
            <Codicon name="gear" size="0.7rem" />
            <span className="ml-1">设置</span>
          </Button>
          {/* Task 5.2 批次 3：三视图切换器（持久化） */}
          <ViewSwitcher mode={viewMode} onChange={setViewMode} />
        </div>
      </div>

      {/* B2：多选批量操作条（多选模式激活时） */}
      {multiMode && (
        <div className="flex items-center gap-2 border-b border-(--ui-stroke-secondary) bg-(--ui-accent)/5 px-3 py-1.5">
          <span className="text-[0.8125rem] text-(--ui-text-secondary)">已选 {selected.size} 项</span>
          <Button size="sm" variant="outline" disabled={batchBusy || selected.size === 0} onClick={() => runBatch('complete')}>批量归档</Button>
          <Button size="sm" variant="outline" disabled={batchBusy || selected.size === 0} onClick={() => runBatch('resolve')}>批量归档</Button>
          <Button size="sm" variant="outline" disabled={batchBusy || selected.size === 0} onClick={() => runBatch('trash')}>批量删除</Button>
          <Button size="sm" variant="outline" onClick={() => { setSelected(new Set()); setMultiMode(false) }}>取消</Button>
        </div>
      )}

      {/* P0-1（B4）v2（Task 3）：HomeView = 默认首页；旧看板/表格 = 旧版数据态；消息任务独立 */}
      {showConversations ? (
        <ConversationIndexView
          items={conversations.data?.items ?? []}
          loading={conversations.isLoading}
          error={conversations.error}
        />
      ) : !showLegacy ? (
        <HomeView board={board} onPreview={setPreviewCard} onOpenLegacy={() => setShowLegacy(true)} />
      ) : (
        <>
          {/* Task 5.2 批次 3：Board / Table 两视图（同一 /board 数据；Phase 0-1：List 已删） */}
          {viewMode === 'table' && <TableBoardView board={board} onPreview={setPreviewCard} />}
          {viewMode === 'board' && (
            <div className="flex flex-1 gap-3 overflow-x-auto p-3">
              {board.sections.map(section => (
                <WbSectionView
                  key={section.key}
                  section={section}
                  onPreview={setPreviewCard}
                  openMenuKey={openMenuKey}
                  onMenuOpenChange={setOpenMenuKey}
                  multiMode={multiMode}
                  selected={selected}
                  onToggleSelect={toggleSelect}
                  conversationPlatformsByTask={conversationPlatformsByTask}
                  onOpenConversations={() => { setShowLegacy(false); setShowConversations(true) }}
                />
              ))}
            </div>
          )}
        </>
      )}

      {/* Preview drawer (含运行历史 tab) */}
      {previewCard && (
        <WbPreviewDrawer card={previewCard} onClose={() => setPreviewCard(null)} />
      )}

      {/* 补丁 10：新建任务浮窗 */}
      {showNewTask && <NewTaskDialog board={board} onClose={() => setShowNewTask(false)} />}
      {/* 2026-08-22：设置浮窗 */}
      {showSettings && <SettingsDialog onClose={() => setShowSettings(false)} />}
    </div>
  )
}

// ── SettingsDialog (2026-08-22)：个性化设置（路径/分区/定时/保留/投递） ────

const PARTITION_TYPE_OPTIONS = [
  { value: 'thought', label: '待验证类（聚合条目）' },
  { value: 'video', label: '待回看类（聚合条目）' },
  { value: 'task', label: '任务类（单卡）' },
  { value: 'done', label: '归档类（单卡）' },
]

const SCHEDULE_ROWS = [
  { key: 'daily_report', label: '每日日报', note: '数据 → 生成 → 工作日志 → QQ' },
  { key: 'nudge', label: '超期提醒', note: '无内容不发送' },
  { key: 'maintenance', label: '每日维护', note: '归档巡检 + DB 收敛 + 回收站 TTL' },
  { key: 'lifecycle', label: '生命周期协调', note: '每 10 分钟' },
]

function SettingsDialog({ onClose }: { onClose: () => void }) {
  const field = 'w-full rounded border border-(--ui-stroke-secondary) bg-(--ui-bg) px-2 py-1 text-[0.75rem] text-(--ui-text-primary) outline-none focus:border-(--ui-accent)'
  const { data, isLoading, error } = useQuery({
    queryKey: ['workbench', 'settings'],
    queryFn: () => fetchSettings(),
  })
  const [form, setForm] = useState<null | WbSettings>(null)
  const [busy, setBusy] = useState(false)
  const [newName, setNewName] = useState('')
  const [newType, setNewType] = useState('thought')
  const [restartHint, setRestartHint] = useState<string[]>([])
  const [errMsg, setErrMsg] = useState('')

  useEffect(() => {
    if (data?.ok && data.config) {
      setForm(JSON.parse(JSON.stringify(data.config)) as WbSettings)
    }
  }, [data])

  if (!form) {
    return (
      <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
        <DialogContent className="wb-dialog" style={{ width: 'min(52rem, 94vw)', maxWidth: '94vw' }}>
          <DialogHeader>
            <DialogTitle>⚙ 工作台设置</DialogTitle>
          </DialogHeader>
          <div className="flex items-center justify-center py-10 text-sm text-(--ui-text-tertiary)">
            {isLoading ? '加载中…' : (error ? '设置加载失败' : '')}
          </div>
        </DialogContent>
      </Dialog>
    )
  }

  const set = (k: keyof WbSettings, v: unknown) => setForm(f => (f ? { ...f, [k]: v } : f))
  const setScheduler = (k: string, v: Partial<WbSettingsSchedulerItem>) =>
    setForm(f => (f ? { ...f, scheduler: { ...f.scheduler, [k]: { ...f.scheduler[k], ...v } } } : f))

  const addPartition = () => {
    const name = newName.trim()
    if (!name) return
    if (form.partitions.some(p => p.name === name)) {
      setErrMsg('分区名已存在')
      return
    }
    setForm(f => (f ? { ...f, partitions: [...f.partitions, { name, type: newType, fixed: false, count: 0 }] } : f))
    setNewName('')
    setErrMsg('')
  }

  const removePartition = (name: string) => {
    setForm(f => (f ? { ...f, partitions: f.partitions.filter(p => p.name !== name) } : f))
  }

  const save = async () => {
    if (!form) return
    setBusy(true)
    setErrMsg('')
    try {
      const res = await saveSettings(form)
      if (!res.ok) {
        setErrMsg(res.error || '保存失败')
        return
      }
      invalidateBoard()
      host.notify({ kind: 'success', message: '设置已保存' })
      if (res.restart_required?.length) {
        setRestartHint(res.restart_required)
      } else {
        onClose()
      }
    } catch (err) {
      setErrMsg(String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="wb-dialog" style={{ width: 'min(52rem, 94vw)', maxWidth: '94vw' }}>
        <DialogHeader>
          <DialogTitle>⚙ 工作台设置</DialogTitle>
        </DialogHeader>
        <div className="flex max-h-[70vh] flex-col gap-4 overflow-y-auto pr-1 text-[0.8125rem]">
          {/* 路径 */}
          <section>
            <div className="mb-1 flex items-center gap-2">
              <h3 className="text-[0.8125rem] font-semibold text-(--ui-text-primary)">路径</h3>
              <span className="rounded bg-(--ui-accent)/10 px-1.5 text-[0.6875rem] text-(--ui-accent)">重启后生效</span>
            </div>
            <label className="flex flex-col gap-1 text-(--ui-text-secondary)">
              工作台文件夹
              <input className={field} value={form.root} onChange={(e) => set('root', e.target.value)} placeholder="~/Workbench" />
            </label>
            <label className="mt-2 flex flex-col gap-1 text-(--ui-text-secondary)">
              Obsidian 知识库（日报工作日志位置）
              <input className={field} value={form.vault} onChange={(e) => set('vault', e.target.value)} placeholder="Obsidian 库路径（可留空）" />
            </label>
          </section>

          {/* 分区 */}
          <section>
            <div className="mb-1 flex items-center gap-2">
              <h3 className="text-[0.8125rem] font-semibold text-(--ui-text-primary)">分区</h3>
              <span className="rounded bg-(--ui-accent)/10 px-1.5 text-[0.6875rem] text-(--ui-accent)">新增即时生效</span>
              <span className="text-[0.6875rem] text-(--ui-text-quaternary)">删除仅限空分区</span>
            </div>
            <div className="flex flex-col gap-1">
              {form.partitions.map(p => (
                <div key={p.name} className="flex items-center gap-2 rounded border border-(--ui-stroke-secondary) px-2 py-1">
                  <Codicon name={partitionMeta(p.type).codicon} size="0.8rem" />
                  <span className="min-w-0 flex-1 truncate font-medium text-(--ui-text-primary)">{p.name}</span>
                  <span className="text-[0.6875rem] text-(--ui-text-quaternary)">{partitionMeta(p.type).label}</span>
                  {p.fixed ? (
                    <span className="text-[0.6875rem] text-(--ui-text-quaternary)">固定</span>
                  ) : (
                    <button
                      type="button"
                      disabled={p.count > 0}
                      title={p.count > 0 ? `非空（${p.count} 个文件）不能删除` : '删除分区'}
                      className="text-(--ui-text-tertiary) hover:text-(--ui-red) disabled:cursor-not-allowed disabled:opacity-40"
                      onClick={() => removePartition(p.name)}
                    >
                      <Codicon name="trash" size="0.8rem" />
                    </button>
                  )}
                </div>
              ))}
            </div>
            <div className="mt-2 flex items-center gap-2">
              <input className={field + ' flex-1'} value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="新分区名（≤20 字）" />
              <DialogSelect value={newType} onChange={setNewType} options={PARTITION_TYPE_OPTIONS} />
              <Button size="sm" variant="outline" onClick={addPartition}>＋ 添加</Button>
            </div>
          </section>

          {/* 定时任务 */}
          <section>
            <div className="mb-1 flex items-center gap-2">
              <h3 className="text-[0.8125rem] font-semibold text-(--ui-text-primary)">定时任务</h3>
              <span className="rounded bg-(--ui-accent)/10 px-1.5 text-[0.6875rem] text-(--ui-accent)">立即生效</span>
            </div>
            <div className="flex flex-col gap-1.5">
              {SCHEDULE_ROWS.map(row => (
                <div key={row.key} className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    className="size-3.5"
                    checked={form.scheduler[row.key]?.enabled ?? true}
                    onChange={(e) => setScheduler(row.key, { enabled: e.target.checked })}
                  />
                  <span className="w-24 shrink-0 text-(--ui-text-primary)">{row.label}</span>
                  {row.key !== 'lifecycle' ? (
                    <input
                      className={field + ' w-24'}
                      type="time"
                      value={form.scheduler[row.key]?.time ?? '20:00'}
                      onChange={(e) => setScheduler(row.key, { time: e.target.value })}
                    />
                  ) : (
                    <span className="w-24 text-[0.6875rem] text-(--ui-text-quaternary)">每 10 分钟</span>
                  )}
                  <span className="min-w-0 truncate text-[0.6875rem] text-(--ui-text-quaternary)">{row.note}</span>
                </div>
              ))}
            </div>
            <label className="mt-2 flex items-center gap-2 text-(--ui-text-secondary)">
              <input type="checkbox" className="size-3.5" checked={form.write_worklog} onChange={(e) => set('write_worklog', e.target.checked)} />
              日报写入 Obsidian 工作日志
            </label>
          </section>

          {/* 投递 */}
          <section>
            <div className="mb-1 flex items-center gap-2">
              <h3 className="text-[0.8125rem] font-semibold text-(--ui-text-primary)">QQ 投递</h3>
              <span className="rounded bg-(--ui-accent)/10 px-1.5 text-[0.6875rem] text-(--ui-accent)">立即生效</span>
            </div>
            <label className="flex flex-col gap-1 text-(--ui-text-secondary)">
              投递目标（qqbot:群 openid）
              <input className={field} value={form.deliver_target} onChange={(e) => set('deliver_target', e.target.value)} placeholder="qqbot:..." />
            </label>
          </section>

          {/* 保留 */}
          <section>
            <div className="mb-1 flex items-center gap-2">
              <h3 className="text-[0.8125rem] font-semibold text-(--ui-text-primary)">回收站保留</h3>
              <span className="rounded bg-(--ui-accent)/10 px-1.5 text-[0.6875rem] text-(--ui-accent)">下次维护生效</span>
            </div>
            <div className="flex items-center gap-2">
              <input
                className={field + ' w-24'}
                type="number"
                min={1}
                max={365}
                value={form.ttl.days}
                onChange={(e) => set('ttl', { ...form.ttl, days: Number(e.target.value) })}
              />
              <span className="text-(--ui-text-secondary)">天</span>
              <DialogSelect
                value={form.ttl.mode}
                onChange={(m) => set('ttl', { ...form.ttl, mode: m as 'archive' | 'delete' })}
                options={[
                  { value: 'archive', label: '归档保留（移入已处理）' },
                  { value: 'delete', label: '物理删除' },
                ]}
              />
            </div>
          </section>

          {errMsg && (
            <div className="rounded border border-(--ui-red) bg-(--ui-bg-elevated) px-2 py-1.5 text-[0.75rem] text-(--ui-red)">
              {errMsg}
            </div>
          )}
          {restartHint.length > 0 && (
            <div className="rounded border border-(--ui-accent)/30 bg-(--ui-accent)/5 px-2 py-1.5 text-[0.75rem] text-(--ui-text-secondary)">
              已保存。以下设置重启 Hermes 后生效：{restartHint.join('、')}（路径 / 分区白名单）
            </div>
          )}
        </div>
        <DialogFooter>
          <Button size="sm" variant="outline" onClick={onClose}>取消</Button>
          <Button size="sm" onClick={save} disabled={busy}>{busy ? '保存中…' : '保存'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
