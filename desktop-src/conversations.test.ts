import { describe, expect, it } from 'vitest'

import { conversationActionLabel } from './types'

describe('conversationActionLabel', () => {
  it('does not promise an original session when only summary resume is available', () => {
    expect(conversationActionLabel({ resume_mode: 'summary', session_id: null })).toBe('摘要续接')
  })

  it('offers the original session only when Hermes supplied a stable session id', () => {
    expect(conversationActionLabel({ resume_mode: 'original', session_id: 'session-1' })).toBe('打开原会话')
  })
})
