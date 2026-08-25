import { describe, expect, it } from 'vitest'

import { contentReviewModel, launchQueuedContentItem } from './content-review'

const base = {
  capture_id: 'CAP-001',
  source_ref: 'SOURCE-001',
  dir: '待验证',
  file: 'content-CAP-001.md',
  title: '示例内容',
  original_url: 'https://example.com/watch?v=1&utm_source=qq#intro',
  canonical_url: 'https://example.com/watch?v=1',
  original_text: '示例原文',
  extraction_state: 'pending' as const,
  review_state: 'pending' as const,
  note_path: null,
  last_error: null,
  captured_at: '2026-08-25T17:00:00+08:00',
  reviewed_at: null,
}

describe('reviewed content actions', () => {
  it('keeps capture separate from both archive and knowledge ingestion', () => {
    const model = contentReviewModel(base)
    expect(model.actions.map((action) => action.id)).toEqual(['archive_only', 'sink_to_obsidian'])
    expect(model.notePath).toBeNull()
    expect(model.statusText).toBe('待审核')
  })

  it('never presents a note path after a failed sink', () => {
    const model = contentReviewModel({
      ...base,
      extraction_state: 'failed',
      review_state: 'sink_failed',
      note_path: null,
      last_error: '知识库写入失败',
    })
    expect(model.notePath).toBeNull()
    expect(model.statusText).toBe('沉淀失败，可重试')
    expect(model.actions.map((action) => action.id)).toContain('sink_to_obsidian')
  })

  it('shows the durable note path only after a successful reviewed sink', () => {
    const model = contentReviewModel({
      ...base,
      extraction_state: 'extracted',
      review_state: 'sunk',
      note_path: '知识库/示例.md',
    })
    expect(model.notePath).toBe('知识库/示例.md')
    expect(model.statusText).toBe('已沉淀到 Obsidian')
    expect(model.actions).toEqual([])
  })

  it('shows an Agent queue without claiming an Obsidian note exists', () => {
    const model = contentReviewModel({
      ...base,
      review_state: 'sink_queued',
      sink_task_id: 'WB-A1B2C3D4',
      sink_task_dir: '任务',
      sink_task_file: 'content-ingest-a1b2c3d4.md',
      sink_task_path: 'D:/Obsidian/个人工作台/任务/content-ingest-a1b2c3d4.md',
    })

    expect(model.statusText).toBe('等待 Hermes 摄入')
    expect(model.notePath).toBeNull()
    expect(model.actions).toEqual([{ id: 'launch_sink_task', label: '启动 / 重试 Hermes 摄入' }])
  })

  it('launches the exact queued ingestion task through the normal Workbench execution chain', async () => {
    const submitted: string[] = []
    const item = {
      ...base,
      review_state: 'sink_queued' as const,
      sink_task_id: 'WB-A1B2C3D4',
      sink_task_dir: '任务',
      sink_task_file: 'content-ingest-a1b2c3d4.md',
      sink_task_path: 'D:/Obsidian/个人工作台/任务/content-ingest-a1b2c3d4.md',
    }
    const result = await launchQueuedContentItem(item, {
      prepare: async input => ({ ok: true, file: input.file, path: input.path, scope: 'ingest' }),
      createSession: async () => ({ session_id: 'runtime-1', stored_session_id: 'stored-1' }),
      bind: async () => ({ ok: true }),
      submit: async (_sessionId, text) => { submitted.push(text) },
      rollback: async () => ({ ok: true }),
    })

    expect(result.ok).toBe(true)
    expect(result.file).toBe('content-ingest-a1b2c3d4.md')
    expect(submitted).toHaveLength(1)
    expect(submitted[0]).toContain('任务文件：D:/Obsidian/个人工作台/任务/content-ingest-a1b2c3d4.md')
  })
})
