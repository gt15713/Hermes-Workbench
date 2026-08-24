import { describe, expect, it } from 'vitest'

import { withTimeout } from './request'

describe('withTimeout', () => {
  it('rejects a hung plugin request with an actionable timeout', async () => {
    await expect(withTimeout(new Promise<string>(() => {}), 5, '任务详情加载'))
      .rejects.toThrow('任务详情加载超时，请重试')
  })

  it('preserves a successful result', async () => {
    await expect(withTimeout(Promise.resolve('ok'), 50)).resolves.toBe('ok')
  })
})
