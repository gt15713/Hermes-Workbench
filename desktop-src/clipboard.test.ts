import { describe, expect, it, vi } from 'vitest'

import { writeWorkbenchClipboard } from './clipboard'

describe('writeWorkbenchClipboard', () => {
  it('prefers the Hermes Desktop native clipboard bridge', async () => {
    const nativeWrite = vi.fn().mockResolvedValue(undefined)
    const webWrite = vi.fn().mockResolvedValue(undefined)

    await writeWorkbenchClipboard('续接内容', { nativeWrite, webWrite })

    expect(nativeWrite).toHaveBeenCalledWith('续接内容')
    expect(webWrite).not.toHaveBeenCalled()
  })

  it('falls back to the web clipboard outside Hermes Desktop', async () => {
    const webWrite = vi.fn().mockResolvedValue(undefined)

    await writeWorkbenchClipboard('续接内容', { webWrite })

    expect(webWrite).toHaveBeenCalledWith('续接内容')
  })

  it('reports an unavailable clipboard instead of silently succeeding', async () => {
    await expect(writeWorkbenchClipboard('续接内容', {})).rejects.toThrow('Clipboard API is unavailable')
  })
})
