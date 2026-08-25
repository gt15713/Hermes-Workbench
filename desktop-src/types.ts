/**
 * Workbench — the 7-partition task/file board. Types mirroring the
 * backend response from /board, /file, /complete, etc.
 */

/** One card in the workbench. Corresponds to a single file (done/trash/task
 *  partition) OR one ## entry (thought/video/psych/dream aggregation files). */
export interface WbCard {
  dir: string
  file: string
  path: string
  title: string
  status: string
  task_id?: null | string
  execution_result?: null | string
  entry_title?: null | string
  entries: string[]
  entry_count: number
  session_id?: null | string
  mtime?: number
  sunk?: null | string
  due?: null | string
  trashed_at?: null | string
  /** Task 5.2 批次 1：frontmatter priority（P0-P3，无则空）/ size（S/M/L，无则空） */
  priority?: null | string
  size?: null | string
  /** A5：frontmatter tags → 规范化标签列表（无则 []） */
  tags?: string[]
}

export interface WbSection {
  dir: string
  key: string
  /** 2026-08-22：分区显示名（自定义分区 = 分区名；缺省回退类型 label） */
  label?: string
  files: WbCard[]
}

export interface WbBoard {
  root: string
  updated_at: string
  today: string
  totals: { pending: number; total: number }
  sections: WbSection[]
}

/** Privacy-safe reference to a task accepted from an authorized message channel. */
export interface WbConversationRef {
  ref_id: string
  platform: 'qq' | 'weixin' | 'messaging' | string
  summary: string
  task_id: string
  status: string
  resume_mode: 'summary' | 'original'
  session_id?: string | null
  updated_at: string
}

export function conversationActionLabel(ref: Pick<WbConversationRef, 'resume_mode' | 'session_id'>): string {
  return ref.resume_mode === 'original' && !!ref.session_id ? '打开原会话' : '摘要续接'
}

/** Column display config — mirrors our 7 partitions. */
export const PARTITION_META: Record<string, { label: string; codicon: string; tone: string }> = {
  thought: { label: '待验证', codicon: 'inbox', tone: 'var(--ui-text-tertiary)' },
  video:   { label: '待回看', codicon: 'eye', tone: '#60a5fa' },
  task:    { label: '任务',   codicon: 'checklist', tone: '#a78bfa' },
  psych:   { label: '心理学', codicon: 'lightbulb', tone: '#34d399' },
  dream:   { label: '梦中邮件', codicon: 'mail', tone: '#fbbf24' },
  done:    { label: '已处理', codicon: 'pass', tone: 'var(--ui-text-tertiary)' },
  trash:   { label: '回收站', codicon: 'trash', tone: '#f87171' },
}

export const partitionMeta = (key: string) =>
  PARTITION_META[key] ?? { label: key, codicon: 'circle-outline', tone: 'var(--ui-text-secondary)' }

export const STATUS_TONE: Record<string, string> = {
  pending: '#fbbf24',
  todo: '#60a5fa',
  in_progress: '#34d399',
  completed: 'var(--ui-text-tertiary)',
  abandoned: '#f87171',
  cleared: 'var(--ui-text-quaternary)',
}

/** Task 5.2 批次 1：优先级徽标（frontmatter priority，P0-P3） */
export const PRIORITY_META: Record<string, { label: string; bg: string; fg: string }> = {
  P0: { label: 'P0', bg: 'rgba(248,113,113,0.16)', fg: '#f87171' },
  P1: { label: 'P1', bg: 'rgba(251,146,60,0.16)', fg: '#fb923c' },
  P2: { label: 'P2', bg: 'rgba(96,165,250,0.16)', fg: '#60a5fa' },
  P3: { label: 'P3', bg: 'rgba(148,163,184,0.16)', fg: '#94a3b8' },
}
export const priorityMeta = (p: string) => PRIORITY_META[p] ?? null

/** Task 5.2 批次 1：尺寸徽标（frontmatter size，S/M/L） */
export const SIZE_META: Record<string, { label: string; fg: string }> = {
  S: { label: 'S', fg: '#34d399' },
  M: { label: 'M', fg: '#a78bfa' },
  L: { label: 'L', fg: '#fbbf24' },
}
export const sizeMeta = (s: string) => SIZE_META[s] ?? null

/** Task 5.2 批次 4：due 是否已超期（本地日期，ISO 字符串比较；无/非法 due → false）。 */
export const isOverdue = (due?: null | string): boolean => {
  if (!due || !/^\d{4}-\d{2}-\d{2}$/.test(due)) return false
  const now = new Date()
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  return due < today
}

/** Task 5.2 批次 1：抽屉「运行历史」事件（GET /recent?dir=&file= → task_events） */
export interface WbEvent {
  id: number
  partition: string
  filename: string
  kind: string
  payload?: string
  ts: string
}

/** A4：/search 单条结果（含最近事件摘要） */
export interface WbSearchResult {
  dir: string
  key: string
  file: string
  title: string
  status: string
  mtime?: string
  priority?: string
  size?: string
  tags: string[]
  entry_count: number
  events: WbEvent[]
}

export interface WbSearchResponse {
  results: WbSearchResult[]
  total: number
  q: string
  tag: string
}

/** 2026-08-22：设置面板（/settings）类型。 */
export interface WbSettingsPartition {
  name: string
  type: string
  fixed: boolean
  count: number
}

export interface WbSettingsSchedulerItem {
  enabled: boolean
  time?: string
}

export interface WbSettings {
  version: number
  root: string
  vault: string
  deliver_target: string
  partitions: WbSettingsPartition[]
  scheduler: Record<string, WbSettingsSchedulerItem>
  ttl: { days: number; mode: 'archive' | 'delete' }
  write_worklog: boolean
}

export interface WbSettingsResponse {
  ok: boolean
  config: WbSettings
  effective?: { root: string; vault: string; deliver_target: string; db: string }
  restart_required?: string[]
  error?: string
}
