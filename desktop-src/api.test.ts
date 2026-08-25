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

  it('rejects a hung real file request instead of leaving the drawer loading forever', async () => {
    vi.useFakeTimers()
    const neverReturningRest = () => new Promise<never>(() => {})
    const storage = { get: <T>(_key: string, fallback: T) => fallback, set: () => {} }
    const unbind = bindApi(neverReturningRest, storage as never, () => () => {})

    const result = fetchFile('已处理', '任务.md')
    const assertion = expect(result).rejects.toThrow('任务详情加载超时，请重试')
    await vi.advanceTimersByTimeAsync(15_000)
    await assertion
    unbind()
  })

  it('rejects a hung real history request instead of leaving the history tab loading forever', async () => {
    vi.useFakeTimers()
    const neverReturningRest = () => new Promise<never>(() => {})
    const storage = { get: <T>(_key: string, fallback: T) => fallback, set: () => {} }
    const unbind = bindApi(neverReturningRest, storage as never, () => () => {})

    const result = fetchRecentEvents('已处理', '任务.md')
    const assertion = expect(result).rejects.toThrow('运行历史加载超时，请重试')
    await vi.advanceTimersByTimeAsync(15_000)
    await assertion
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
