import { afterEach, describe, expect, it, vi } from 'vitest'

import { withTimeout } from './request'

vi.mock('@hermes/plugin-sdk', () => ({
  atom: () => ({ get: () => ({}), set: () => {}, listen: () => () => {} }),
  queryClient: { invalidateQueries: () => Promise.resolve() },
}))

import { bindApi, captureContent, fetchFile, fetchRecentEvents, reviewContent } from './api'

afterEach(() => {
  vi.useRealTimers()
})

describe('withTimeout', () => {
  it('rejects a hung plugin request with an actionable timeout', async () => {
    await expect(withTimeout(new Promise<string>(() => {}), 5, '任务详情加载'))
      .rejects.toThrow('任务详情加载超时，请重试')
  })

  it('preserves a successful result', async () => {
    await expect(withTimeout(Promise.resolve('ok'), 50)).resolves.toBe('ok')
  })

  it('passes the file timeout to the host-native request contract', async () => {
    const calls: Array<{ path: string; timeoutMs?: number }> = []
    const boundedRest = async <T>(path: string, options?: { timeoutMs?: number }) => {
      calls.push({ path, timeoutMs: options?.timeoutMs })
      return { content: 'ok' } as T
    }
    const storage = { get: <T>(_key: string, fallback: T) => fallback, set: () => {} }
    const unbind = bindApi(boundedRest as never, storage as never, () => () => {})

    await fetchFile('已处理', '任务.md')
    expect(calls).toEqual([{ path: '/file?dirname=%E5%B7%B2%E5%A4%84%E7%90%86&filename=%E4%BB%BB%E5%8A%A1.md', timeoutMs: 15_000 }])
    unbind()
  })

  it('passes the history timeout to the host-native request contract', async () => {
    const calls: Array<{ path: string; timeoutMs?: number }> = []
    const boundedRest = async <T>(path: string, options?: { timeoutMs?: number }) => {
      calls.push({ path, timeoutMs: options?.timeoutMs })
      return { entries: [] } as T
    }
    const storage = { get: <T>(_key: string, fallback: T) => fallback, set: () => {} }
    const unbind = bindApi(boundedRest as never, storage as never, () => () => {})

    await fetchRecentEvents('已处理', '任务.md')
    expect(calls).toEqual([{ path: '/recent?limit=50&dir=%E5%B7%B2%E5%A4%84%E7%90%86&file=%E4%BB%BB%E5%8A%A1.md', timeoutMs: 15_000 }])
    unbind()
  })
})

describe('reviewed content API boundary', () => {
  it('captures content without implying archive or knowledge ingestion', async () => {
    const calls: Array<{ path: string; body: unknown }> = []
    const rest = async <T>(path: string, options?: { body?: unknown }) => {
      calls.push({ path, body: options?.body })
      return { ok: true, item: { capture_id: 'CAP-001' } } as T
    }
    const storage = { get: <T>(_key: string, fallback: T) => fallback, set: () => {} }
    const unbind = bindApi(rest as never, storage as never, () => () => {})

    await captureContent({ source_id: 'qq-1', source_url: 'https://example.com/?utm_source=qq', original_text: '原文', title: '示例' })

    expect(calls).toEqual([{ path: '/content/capture', body: {
      source_id: 'qq-1', source_url: 'https://example.com/?utm_source=qq', original_text: '原文', title: '示例',
    } }])
    unbind()
  })

  it('sends an explicit review action instead of treating capture as consent', async () => {
    const calls: Array<{ path: string; body: unknown }> = []
    const rest = async <T>(path: string, options?: { body?: unknown }) => {
      calls.push({ path, body: options?.body })
      return { ok: true, item: { capture_id: 'CAP-001' } } as T
    }
    const storage = { get: <T>(_key: string, fallback: T) => fallback, set: () => {} }
    const unbind = bindApi(rest as never, storage as never, () => () => {})

    await reviewContent('待验证', 'content-CAP-001.md', 'sink_to_obsidian')

    expect(calls).toEqual([{ path: '/content/review', body: {
      dir: '待验证', file: 'content-CAP-001.md', action: 'sink_to_obsidian',
    } }])
    unbind()
  })
})
