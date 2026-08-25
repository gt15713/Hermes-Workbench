export type WbContentReviewAction = 'archive_only' | 'sink_to_obsidian'
export type WbContentAction = WbContentReviewAction | 'launch_sink_task'

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

export function contentReviewModel(item: WbContentItem): WbContentReviewModel {
  if (item.review_state === 'sunk') {
    return {
      statusText: '已沉淀到 Obsidian',
      notePath: item.note_path || null,
      error: null,
      actions: [],
    }
  }
  if (item.review_state === 'archived') {
    return { statusText: '已归档', notePath: null, error: null, actions: [] }
  }
  if (item.review_state === 'sink_queued') {
    return {
      statusText: '等待 Hermes 摄入',
      notePath: null,
      error: null,
      actions: [{ id: 'launch_sink_task', label: '启动 / 重试 Hermes 摄入' }],
    }
  }
  return {
    statusText: item.review_state === 'sink_failed' ? '沉淀失败，可重试' : '待审核',
    notePath: null,
    error: item.last_error || null,
    actions: [
      { id: 'archive_only', label: '仅归档' },
      { id: 'sink_to_obsidian', label: item.review_state === 'sink_failed' ? '重试沉淀' : '沉淀到 Obsidian' },
    ],
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
