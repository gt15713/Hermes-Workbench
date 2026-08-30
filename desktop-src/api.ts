/**
 * Workbench data layer — consumes the existing backend endpoints
 * (/board, /file, /complete, /resolve, /to-task, /trash, /delete,
 * /defer, /abandon, /reopen, /bind-session, /reset-execution, /add)
 * through ctx.rest (namespace-scoped to /api/plugins/workbench-view).
 */

import { atom, type PluginRestOptions, type PluginStorage, queryClient } from '@hermes/plugin-sdk'
import type { WbBoard, WbConversationRef, WbEvent, WbSearchResponse, WbSettings, WbSettingsResponse } from './types'
import type { WbContentItem } from './content-review'

type Rest = <T>(path: string, opts?: PluginRestOptions) => Promise<T>
type Socket = (path: string, onMessage: (data: unknown) => void) => () => void

let rest: null | Rest = null

// ── atoms ────────────────────────────────────────────────────────────

/** Per-section collapse overrides (true=collapsed). */
export const $collapsedSections = atom<Record<string, boolean>>({})

/** Filter text (searches titles + entries). */
export const $filterText = atom<string>('')

/** A5：按标签过滤（点击卡片标签 chip 切换；空 = 不过滤）。 */
export const $tagFilter = atom<string>('')

/** Whether to show done/trash sections. */
export const $showArchived = atom<boolean>(false)

/** P0-3：到期/超期快捷筛选（all | today | overdue）。 */
export type WbDueFilter = 'all' | 'today' | 'overdue'
export const $dueFilter = atom<WbDueFilter>('all')

/** Task 5.2 批次 3：视图模式（board 看板 / table 表格）。Phase 0-1：List 已删。持久化。 */
export type WbViewMode = 'board' | 'table'
export const $viewMode = atom<WbViewMode>('board')

// v2：2026-08-22 等宽看板——清空历史折叠默认（psych/dream/trash 曾默认折叠成窄轨），
// 升版存储键以重置旧会话遗留的折叠覆盖。
const COLLAPSED_KEY = 'wbCollapsedSections.v2'
const SHOW_ARCHIVED_KEY = 'wbShowArchived'
const VIEW_MODE_KEY = 'wbViewMode'
const TAG_FILTER_KEY = 'wbTagFilter'
const DUE_FILTER_KEY = 'wbDueFilter'

// ── bind ─────────────────────────────────────────────────────────────

export function bindApi(r: Rest, storage: PluginStorage, socket: Socket): () => void {
  rest = r
  const unsubs: Array<() => void> = []

  const persist = <T>(
    atom: { get(): T; set(v: T): void; listen(cb: (v: T) => void): () => void },
    key: string,
    fallback: T
  ) => {
    atom.set(storage.get(key, fallback))
    unsubs.push(atom.listen(value => storage.set(key, value)))
  }

  persist($collapsedSections, COLLAPSED_KEY, {})
  persist($showArchived, SHOW_ARCHIVED_KEY, false)
  persist($viewMode, VIEW_MODE_KEY, 'board')
  persist($tagFilter, TAG_FILTER_KEY, '')
  persist($dueFilter, DUE_FILTER_KEY, 'all')
  // Phase 0-1：存量 $viewMode='list' 回落 'board'（List 视图已删除；storage 旧值兼容）
  if (($viewMode.get() as string) === 'list') $viewMode.set('board')

  // Task 5.2 批次 2：实时活动双通道——WS 即时刷新 + 30s 轮询兜底。
  // ctx.socket('/events') → 后端 /api/plugins/workbench-view/events（task_events 增量）。
  // 收到帧即失效 board + 运行历史缓存；socket 断开/未连接时轮询继续兜底。
  const closeSocket = socket('/events?since=0', data => onEventsFrame(data))
  unsubs.push(closeSocket)

  return () => {
    unsubs.forEach(u => u())
    rest = null
  }
}

/** One live task_events frame → invalidate the board + recent-events caches.
 *  The 30s poll stays as the fallback; the socket just makes the board instant. */
function onEventsFrame(data: unknown): void {
  const events = (data as { events?: unknown[] })?.events

  if (!events?.length) {
    return
  }

  void queryClient.invalidateQueries({ queryKey: BOARD_KEY })
  void queryClient.invalidateQueries({ queryKey: ['workbench', 'events'] })
}

function call<T>(path: string, opts?: PluginRestOptions): Promise<T> {
  return rest
    ? rest<T>(path, opts)
    : Promise.reject(new Error('workbench api not ready'))
}

// ── query keys ───────────────────────────────────────────────────────

export const BOARD_KEY = ['workbench', 'board'] as const
export const FILE_KEY = (dir: string, file: string) => ['workbench', 'file', dir, file] as const
export const RECENT_EVENTS_KEY = (dir: string, file: string) => ['workbench', 'events', dir, file] as const
export const CONTENT_ITEM_KEY = (dir: string, file: string) => ['workbench', 'content-item', dir, file] as const

// ── reads ────────────────────────────────────────────────────────────

export const fetchBoard = () => call<WbBoard>('/board')

export const fetchConversations = () =>
  call<{ ok: boolean; items: WbConversationRef[] }>('/conversations')

export const fetchFile = (dir: string, file: string) =>
  call<{ content: string }>(
    `/file?dirname=${encodeURIComponent(dir)}&filename=${encodeURIComponent(file)}`,
    { timeoutMs: 15_000 }
  )

export const fetchContentItem = (dir: string, file: string) =>
  call<WbContentItemResponse>(
    `/content/item?dir=${encodeURIComponent(dir)}&file=${encodeURIComponent(file)}`
  )

/** Task 5.2 批次 1：运行历史（复用 /recent，dir+file 时后端查 task_events 倒序） */
export const fetchRecentEvents = (dir: string, file: string) =>
  call<{ entries: WbEvent[]; source?: string }>(
    `/recent?limit=50&dir=${encodeURIComponent(dir)}&file=${encodeURIComponent(file)}`,
    { timeoutMs: 15_000 }
  )

/** A4：全局搜索（标题/内容/标签；tag 可选过滤）。 */
export const fetchSearch = (q: string, tag = '') =>
  call<WbSearchResponse>(
    `/search?limit=20&q=${encodeURIComponent(q)}${tag ? `&tag=${encodeURIComponent(tag)}` : ''}`
  )

// P0-1（B4）：Agent Briefing——惰性生成今日建议卡（后端 30 分钟缓存）
export interface WbBriefCard {
  type: 'new_task' | 'duplicate' | 'blocked' | 'overdue' | 'decision'
  title: string
  reason: string
  action: string
  rule: string
  evidence: string[]
}
export interface WbBriefResponse {
  ok: boolean
  generated_at?: string
  cards: WbBriefCard[]
  degraded: boolean
}
export const fetchBrief = () =>
  call<WbBriefResponse>('/brief', { method: 'POST', body: {} })

/** 2026-08-22：设置面板——读取配置（路径/分区/定时/保留/投递）。 */
export const fetchSettings = () => call<WbSettingsResponse>('/settings')

/** P0-3：链路健康（/health 扩展：scheduler 租约/错误计数/投递待重试/vault 配置）。 */
export interface WbHealth {
  ok: boolean
  db: boolean
  scheduler_alive: boolean
  error_count: number
  last_error?: { job: string; at: string; reason: string } | null
  delivery_pending: boolean
  vault_configured: boolean
  status: 'green' | 'yellow' | 'red' | 'disabled'
  label: string
  checks: Array<{
    id: string
    label: string
    status: 'green' | 'yellow' | 'red' | 'disabled'
    detail: string
  }>
  last_updated?: string | null
  ts: string
}
export const fetchHealth = () => call<WbHealth>('/health')

/** 2026-08-22：设置面板——保存配置。 */
export const saveSettings = (body: WbSettings) =>
  call<{ ok: boolean; saved?: boolean; created_partitions?: string[]; removed_partitions?: string[]; restart_required?: string[]; error?: string }>('/settings', {
    method: 'POST',
    body,
  })

// P0-1（B4）：建议卡「采纳」→ 收录到待验证（幂等 outbox；message_id 由调用方保证唯一）
export const ingestMessage = (
  message_id: string,
  dir: string,
  title: string,
  opts?: { content?: string; priority?: string }
) =>
  call<{ ok: boolean; duplicate?: boolean; file?: string; dir?: string; error?: string }>('/ingest-message', {
    method: 'POST',
    body: { message_id, dir, title, ...opts },
  })

export interface WbContentCaptureInput {
  source_id: string
  source_url: string
  original_text: string
  title: string
}

export interface WbContentItemResponse {
  ok: boolean
  duplicate?: boolean
  item?: WbContentItem
  error?: string
}

/** Capture is only an inbox write. It never implies archive or knowledge ingestion. */
export const captureContent = (body: WbContentCaptureInput) =>
  call<WbContentItemResponse>('/content/capture', { method: 'POST', body })

/** A separate reviewed action is required before archive or Obsidian ingestion. */
export const reviewContent = (dir: string, file: string, action: 'archive_only' | 'sink_to_obsidian') =>
  call<WbContentItemResponse>('/content/review', {
    method: 'POST',
    body: { dir, file, action },
  })

/**
 * Task 5（2026-08-27）：独立重试抽取——与「重试沉淀」严格分列。
 * 钩子未注入时后端如实返回 retryable 错误，绝不显示假成功。
 */
export const retryExtraction = (dir: string, file: string) =>
  call<WbContentItemResponse>('/content/retry-extraction', {
    method: 'POST',
    body: { dir, file },
  })

// ── writes ───────────────────────────────────────────────────────────

export const completeTask = (dir: string, file: string) =>
  call<{ ok: boolean; file?: string; error?: string }>('/complete', {
    method: 'POST',
    body: { dir, file },
  })

/** Resolve an entry (move to done). Supports optional sunk note. */
export const resolveEntry = (dir: string, file: string, opts?: { entry_title?: string; sunk?: string }) =>
  call<{ ok: boolean; file?: string; error?: string }>('/resolve', {
    method: 'POST',
    body: { dir, file, ...opts },
  })

/** Convert an entry to a proper task. */
export const toTask = (dir: string, file: string, opts?: { entry_title?: string }) =>
  call<{ ok: boolean; task?: string; file?: string; entry?: string; task_file?: string; task_dir?: string; error?: string }>('/to-task', {
    method: 'POST',
    body: { dir, file, ...opts },
  })

/** Defer a task by one day. */
export const deferTask = (dir: string, file: string) =>
  call<{ ok: boolean; file?: string; error?: string }>('/defer', {
    method: 'POST',
    body: { dir, file },
  })

/** Execute a task: status → in_progress + execute 事件埋点（批次 2：执行按钮先走 /execute 再建会话）。 */
export const executeTask = (dir: string, file: string, opts?: { title?: string; content?: string; due?: string; launch?: boolean; source?: string }) =>
  call<{ ok: boolean; status?: string; file?: string; path?: string; error?: string }>('/execute', {
    method: 'POST',
    body: { dir, file, source: 'click', ...opts },
  })

/** Abandon a task (mark as not doing). */
export const abandonTask = (dir: string, file: string) =>
  call<{ ok: boolean; abandoned?: boolean; error?: string }>('/abandon', {
    method: 'POST',
    body: { dir, file },
  })

/** Reopen an abandoned task. */
export const reopenTask = (dir: string, file: string) =>
  call<{ ok: boolean; reopened?: boolean; error?: string }>('/reopen', {
    method: 'POST',
    body: { dir, file },
  })

/** Move to trash. */
export const trashFile = (dir: string, file: string) =>
  call<{ ok: boolean; file?: string; error?: string }>('/trash', {
    method: 'POST',
    body: { dir, file },
  })

/** Permanently delete (done/trash only). */
export const deleteFile = (dir: string, file: string) =>
  call<{ ok: boolean; deleted?: boolean; error?: string }>('/delete', {
    method: 'POST',
    body: { dir, file },
  })

/** Restore from trash. */
export const restoreFile = (dir: string, file: string) =>
  call<{ ok: boolean; restored_to?: string; error?: string }>('/restore', {
    method: 'POST',
    body: { file },
  })

/** Bind a session to a task. */
export const bindSession = (dir: string, file: string, sessionId: string) =>
  call<{ ok: boolean; session_id?: string; error?: string }>('/bind-session', {
    method: 'POST',
    body: { dir, file, session_id: sessionId },
  })

/** Restore a task to todo when create/bind/submit fails during launch. */
export const resetExecution = (dir: string, file: string, reason: string) =>
  call<{ ok: boolean; status?: string; file?: string; error?: string }>('/reset-execution', {
    method: 'POST',
    body: { dir, file, reason },
  })

/** Add a new entry. */
export const addEntry = (body: { dir: string; title: string; content?: string; due?: string; priority?: string }) =>
  call<{ ok: boolean; file?: string; dir?: string; error?: string }>('/add', {
    method: 'POST',
    body,
  })

/** Invalidate the board cache (call after any write). */
export const invalidateBoard = () => void queryClient.invalidateQueries({ queryKey: BOARD_KEY })

/** A2：编辑聚合条目 / 任务文件（title/content/due/tags，不改状态）。amend=true 时整体替换正文（方案 Z）。 */
export const editEntry = (body: { dir: string; file: string; entry_title?: string; title?: string; content?: string; due?: string; tags?: string[]; amend?: boolean }) =>
  call<{ ok: boolean; file?: string; entry?: string | null; error?: string }>('/edit', {
    method: 'POST',
    body,
  })

/** B2：批量动作（/batch 端点，2026-08-09 已实现）。action: resolve|to-task|trash|complete。 */
export const batchAction = (
  action: 'resolve' | 'to-task' | 'trash' | 'complete',
  items: Array<{ dir: string; file: string; entry_title?: string }>
) =>
  call<{
    ok: boolean
    done: Array<{ dir?: string; file?: string; entry?: string }>
    failed: Array<{ dir?: string; file?: string; entry?: string; error?: string }>
    summary: { ok: number; fail: number }
    error?: string
  }>('/batch', {
    method: 'POST',
    body: { action, items },
  })
