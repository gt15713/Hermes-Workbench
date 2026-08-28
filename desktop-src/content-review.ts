export type WbContentReviewAction = 'archive_only' | 'sink_to_obsidian'
export type WbContentAction = WbContentReviewAction | 'launch_sink_task' | 'retry_extraction'

export interface WbContentItem {
  capture_id: string
  source_ref: string
  dir: string
  file: string
  title: string
  original_url: string | null
  canonical_url: string | null
  original_text: string | null
  extraction_state: 'pending' | 'extracted' | 'failed'
  review_state: 'pending' | 'archived' | 'sink_queued' | 'sunk' | 'sink_failed'
  note_path: string | null
  last_error: string | null
  captured_at: string
  reviewed_at: string | null
  sink_task_id?: string
  sink_task_dir?: string
  sink_task_file?: string
  sink_task_path?: string
}

export interface WbContentReviewModel {
  statusText: string
  notePath: string | null
  error: string | null
  actions: Array<{ id: WbContentAction; label: string }>
}

/** Task 5（2026-08-27）：收进来 → 审核 → 沉淀 三步回执的每一步。 */
export interface WbContentStep {
  label: '收进来' | '审核' | '沉淀'
  state: 'done' | 'active' | 'todo' | 'error' | 'skipped'
  detail: string
}

/**
 * 三步回执链：展示层唯一口径。
 * - 失败必须有真实原因（last_error），不给成功色；
 * - 仅归档是「跳过沉淀」的独立结局，不是成功也不是失败。
 */
export function contentReceiptSteps(item: WbContentItem): WbContentStep[] {
  const source = item.original_url || '消息正文收录'
  const steps: WbContentStep[] = [
    { label: '收进来', state: 'done', detail: `${source}` },
  ]

  // 审核（含抽取质量）；一旦用户已在审核态做出决定（非 pending），审核即完成
  if (item.extraction_state === 'failed') {
    steps.push({ label: '审核', state: 'error', detail: `抽取失败：${item.last_error || '原因未知'}（可重试抽取）` })
  } else if (item.review_state === 'pending') {
    steps.push({
      label: '审核',
      state: 'active',
      detail: item.extraction_state === 'pending' ? '抽取未完成——原文尚未就绪，可重试抽取' : '原文与来源已就绪',
    })
  } else {
    steps.push({ label: '审核', state: 'done', detail: '已审核并作出决定' })
  }

  // 沉淀
  switch (item.review_state) {
    case 'sunk':
      steps.push({ label: '沉淀', state: 'done', detail: `笔记：${item.note_path || ''}` })
      break
    case 'archived':
      steps.push({ label: '沉淀', state: 'skipped', detail: '仅归档——你选择不进知识库' })
      break
    case 'sink_queued':
      steps.push({ label: '沉淀', state: 'active', detail: `已创建摄入任务 ${item.sink_task_id || ''}，等 Hermes 回执` })
      break
    case 'sink_failed':
      steps.push({ label: '沉淀', state: 'error', detail: `沉淀失败：${item.last_error || '原因未知'}（可重试）` })
      break
    default:
      steps.push({ label: '沉淀', state: 'todo', detail: '等你审核后决定：仅归档 或 沉淀到 Obsidian' })
  }
  return steps
}

export function contentReviewModel(item: WbContentItem): WbContentReviewModel {
  const extractionFailed = item.extraction_state === 'failed'

  if (item.review_state === 'sunk') {
    return {
      statusText: extractionFailed ? '已沉淀（抽取历史有失败记录）' : '已沉淀到 Obsidian',
      notePath: item.note_path || null,
      error: null,
      actions: [],
    }
  }
  if (item.review_state === 'archived') {
    return { statusText: '已归档', notePath: null, error: null, actions: [] }
  }

  const actions: Array<{ id: WbContentAction; label: string }> = []
  // 独立「重试抽取」入口——绝不允许用「重试沉淀」冒充（CoderX §5）
  if (extractionFailed) {
    actions.push({ id: 'retry_extraction', label: '重试抽取' })
  }
  if (item.review_state === 'sink_queued') {
    return {
      statusText: '等待 Hermes 摄入',
      notePath: null,
      error: null,
      actions: [...actions, { id: 'launch_sink_task', label: '启动 / 重试 Hermes 摄入' }],
    }
  }

  let statusText = item.review_state === 'sink_failed' ? '沉淀失败，可重试' : '待审核'
  if (extractionFailed && !statusText.includes('抽取失败')) {
    statusText = `抽取失败 · ${statusText}`
  }
  actions.push(
    { id: 'archive_only', label: '仅归档' },
    { id: 'sink_to_obsidian', label: item.review_state === 'sink_failed' ? '重试沉淀' : '沉淀到 Obsidian' },
  )
  return {
    statusText,
    notePath: null,
    error: item.last_error || null,
    actions,
  }
}

export function launchQueuedContentItem(item: WbContentItem, deps: WorkbenchExecutionDeps) {
  if (
    item.review_state !== 'sink_queued' ||
    !item.sink_task_dir || !item.sink_task_file || !item.sink_task_path
  ) {
    return Promise.resolve({
      ok: false as const,
      phase: 'prepare' as const,
      file: item.sink_task_file || '',
      path: item.sink_task_path || '',
      error: '摄入任务回执不完整',
    })
  }
  return launchWorkbenchTask({
    dir: item.sink_task_dir,
    file: item.sink_task_file,
    title: `摄入：${item.title}`,
    path: item.sink_task_path,
  }, deps)
}
import { launchWorkbenchTask, type WorkbenchExecutionDeps } from './execution'
