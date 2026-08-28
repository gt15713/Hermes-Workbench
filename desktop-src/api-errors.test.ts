import { describe, expect, it } from 'vitest'

import { friendlyApiError } from './api-errors'

/**
 * P0（2026-08-27 目视批次）：底层 API 异常不得以英文原文透给用户。
 * 背景：用户点「重试抽取」看到 Error invoking remote method 'hermes:api':
 * Error: 405 … —— 违反契约「内部 rule ID / 底层细节不作为主文案」。
 */
describe('friendlyApiError', () => {
  it('maps backend-route-not-loaded 405 to human copy with recovery action', () => {
    const out = friendlyApiError(new Error("Error invoking remote method 'hermes:api': Error: 405: [{\"detail\":\"Method Not Allowed\"}]"))
    expect(out).toContain('后端')
    expect(out).toContain('重启')
    expect(out).not.toMatch(/405|Method Not Allowed|hermes:api/)
  })

  it('explains extraction hook unavailable as expected-state copy, not failure', () => {
    const out = friendlyApiError('extraction hook unavailable')
    expect(out).toContain('抓取器')
    expect(out).toContain('仅归档')
    expect(out).not.toMatch(/hook|unavailable/)
  })

  it('maps 404 unknown route the same way', () => {
    const out = friendlyApiError(new Error('404: Not Found'))
    expect(out).toContain('重启')
  })

  it('maps network failure to connectivity copy', () => {
    const out = friendlyApiError(new Error('TypeError: Failed to fetch'))
    expect(out).toContain('连不上')
  })

  it('passes through already-human messages untouched', () => {
    expect(friendlyApiError(new Error('抽取失败，原因写在文件里'))).toBe('抽取失败，原因写在文件里')
  })

  it('falls back to neutral copy for unknown errors without leaking internals', () => {
    const out = friendlyApiError(new Error('E_CONNRESET weird internal stack marker'))
    expect(out).not.toContain('E_CONNRESET')
    expect(out.length).toBeGreaterThan(0)
  })
})
