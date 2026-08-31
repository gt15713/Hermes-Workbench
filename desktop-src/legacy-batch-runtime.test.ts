import { describe, expect, it, vi } from 'vitest'

import { consumeLegacyBatchResponse, isGlobalBatchRejection, settleLegacyBatchResponse, validateBatchResponse } from './batch-response'

describe('legacy Board /batch runtime contract', () => {
  it('rejects missing done/failed/summary without producing a usable response', () => {
    expect(validateBatchResponse({ ok: false, error: 'bad action' }).valid).toBe(false)
    expect(validateBatchResponse({ ok: false, done: [], failed: [], summary: { ok: 0, fail: 0 } }).valid).toBe(true)
  })

  it('rejects malformed item rows and malformed counts', () => {
    expect(validateBatchResponse({ ok: true, done: [{}], failed: [], summary: { ok: 1, fail: 0 } }).valid).toBe(false)
    expect(validateBatchResponse({ ok: true, done: [], failed: [], summary: { ok: '0', fail: 0 } }).valid).toBe(false)
  })

  it('recognizes field-complete global rejection and preserves its actionable error', () => {
    const result = validateBatchResponse({ ok: false, done: [], failed: [], summary: { ok: 0, fail: 0 }, error: 'bad action' })
    expect(result.valid).toBe(true)
    if (result.valid) {
      expect(isGlobalBatchRejection(result.response)).toBe(true)
      expect(result.response.error).toBe('bad action')
    }
  })

  const submitted = [
    { dir: '任务', file: 'a.md', entry_title: ' First ' },
    { dir: '任务', file: 'a.md', entry_title: 'Second' },
  ]

  const effects = () => ({
    notify: vi.fn(),
    invalidate: vi.fn(),
    offerUndo: vi.fn(),
    replaceSelection: vi.fn(),
    clearSelection: vi.fn(),
    exitMultiMode: vi.fn(),
  })

  it.each([
    ['count mismatch', { ok: true, done: [{ dir: '任务', file: 'a.md', entry: 'First' }, { dir: '任务', file: 'a.md', entry: 'Second' }], failed: [], summary: { ok: 1, fail: 0 } }],
    ['ok mismatch', { ok: false, done: [{ dir: '任务', file: 'a.md', entry: 'First' }, { dir: '任务', file: 'a.md', entry: 'Second' }], failed: [], summary: { ok: 2, fail: 0 } }],
    ['duplicate/overlap', { ok: true, done: [{ dir: '任务', file: 'a.md', entry: 'First' }], failed: [{ dir: '任务', file: 'a.md', entry: 'First', error: 'x' }], summary: { ok: 1, fail: 1 } }],
    ['foreign/missing', { ok: true, done: [{ dir: '任务', file: 'a.md', entry: 'First' }], failed: [{ dir: '任务', file: 'foreign.md', entry: 'Second', error: 'x' }], summary: { ok: 1, fail: 1 } }],
    ['schema invalid', { ok: false, error: 'bad action' }],
  ])('blocks %s in the production consumer before legacy side effects', (_label, response) => {
    const sideEffects = effects()
    const decision = consumeLegacyBatchResponse('resolve', submitted, response, sideEffects)
    expect(decision.valid).toBe(false)
    expect(sideEffects.invalidate).not.toHaveBeenCalled()
    expect(sideEffects.replaceSelection).not.toHaveBeenCalled()
    expect(sideEffects.clearSelection).not.toHaveBeenCalled()
    expect(sideEffects.exitMultiMode).not.toHaveBeenCalled()
    expect(sideEffects.notify).toHaveBeenCalledOnce()
    expect(sideEffects.notify.mock.calls[0][0]).toMatchObject({ kind: 'error' })
    expect(sideEffects.notify.mock.calls[0][0].message).toContain('批量响应协议错误')
  })

  it('preserves a field-complete global business rejection without protocol prefix or side effects', () => {
    const sideEffects = effects()
    const decision = consumeLegacyBatchResponse('resolve', submitted, {
      ok: false, done: [], failed: [], summary: { ok: 0, fail: 0 }, error: 'bad action',
    }, sideEffects)
    expect(decision).toMatchObject({ valid: false, classification: 'global-rejection', error: 'bad action' })
    expect(sideEffects.notify).toHaveBeenCalledWith({ kind: 'error', message: 'bad action' })
    expect(sideEffects.invalidate).not.toHaveBeenCalled()
    expect(sideEffects.replaceSelection).not.toHaveBeenCalled()
    expect(sideEffects.clearSelection).not.toHaveBeenCalled()
    expect(sideEffects.exitMultiMode).not.toHaveBeenCalled()
  })

  it('consumes valid full and partial settlements with the existing side effects', () => {
    const fullEffects = effects()
    const full = consumeLegacyBatchResponse('resolve', submitted, {
      ok: true,
      done: [{ dir: '任务', file: 'a.md', entry: 'First' }, { dir: '任务', file: 'a.md', entry: 'Second' }],
      failed: [], summary: { ok: 2, fail: 0 },
    }, fullEffects)
    expect(full.valid).toBe(true)
    expect(fullEffects.notify).toHaveBeenCalledWith({ kind: 'success', message: '批量归档 2 项' })
    expect(fullEffects.invalidate).toHaveBeenCalledOnce()
    expect(fullEffects.replaceSelection).not.toHaveBeenCalled()
    expect(fullEffects.clearSelection).toHaveBeenCalledOnce()
    expect(fullEffects.exitMultiMode).toHaveBeenCalledOnce()

    const partialEffects = effects()
    const partial = consumeLegacyBatchResponse('resolve', submitted, {
      ok: true,
      done: [{ dir: '任务', file: 'a.md', entry: 'First' }],
      failed: [{ dir: '任务', file: 'a.md', entry: 'Second', error: 'blocked' }],
      summary: { ok: 1, fail: 1 },
    }, partialEffects)
    expect(partial.valid).toBe(true)
    expect(partialEffects.notify).toHaveBeenCalledWith({ kind: 'warning', message: expect.stringContaining('Second: blocked') })
    expect(partialEffects.invalidate).toHaveBeenCalledOnce()
    expect(partialEffects.replaceSelection).toHaveBeenCalledOnce()
    expect(partialEffects.replaceSelection).toHaveBeenCalledWith([submitted[1]])
    expect(partialEffects.clearSelection).not.toHaveBeenCalled()
    expect(partialEffects.exitMultiMode).not.toHaveBeenCalled()
  })

  it('retains all canonical submitted failures and keeps all-failed batches in retry mode', () => {
    const sideEffects = effects()
    const decision = consumeLegacyBatchResponse('resolve', submitted, {
      ok: false,
      done: [],
      failed: [
        { dir: '任务\\.', file: 'A.MD', entry: ' First ', error: 'blocked one' },
        { dir: '.\\任务', file: 'a.md', entry: ' Second ', error: 'blocked two' },
      ],
      summary: { ok: 0, fail: 2 },
    }, sideEffects)
    expect(decision.valid).toBe(true)
    expect(sideEffects.notify).toHaveBeenCalledWith({ kind: 'warning', message: expect.stringContaining('Second: blocked two') })
    expect(sideEffects.invalidate).not.toHaveBeenCalled()
    expect(sideEffects.replaceSelection).toHaveBeenCalledOnce()
    expect(sideEffects.replaceSelection).toHaveBeenCalledWith(submitted)
    expect(sideEffects.clearSelection).not.toHaveBeenCalled()
    expect(sideEffects.exitMultiMode).not.toHaveBeenCalled()
  })

  it('accepts only the backend ok truth for all-failed and rejects contradictory values', () => {
    const allFailed = {
      ok: false,
      done: [],
      failed: [
        { dir: '任务', file: 'a.md', entry: 'First', error: 'blocked' },
        { dir: '任务', file: 'a.md', entry: 'Second', error: 'blocked' },
      ],
      summary: { ok: 0, fail: 2 },
    }
    expect(settleLegacyBatchResponse('resolve', submitted, allFailed).valid).toBe(true)
    expect(settleLegacyBatchResponse('resolve', submitted, { ...allFailed, ok: true })).toMatchObject({
      valid: false,
      classification: 'protocol-error',
    })
  })

  it('ignores response entry identity for complete', () => {
    expect(settleLegacyBatchResponse('complete', [{ dir: '任务', file: 'a.md', entry_title: 'ignored' }], {
      ok: true, done: [{ dir: '任务', file: 'a.md', entry: '' }], failed: [], summary: { ok: 1, fail: 0 },
    }).valid).toBe(true)
  })

  it('offers only the authoritative successful trash receipt to the production consumer', () => {
    const sideEffects = effects()
    const trashSubmitted = [
      { dir: '任务', file: 'ok.md' },
      { dir: '任务', file: 'failed.md' },
    ]
    const decision = consumeLegacyBatchResponse('trash', trashSubmitted, {
      ok: true,
      done: [{ dir: '任务', file: 'ok.md' }],
      failed: [{ dir: '任务', file: 'failed.md', error: 'blocked' }],
      summary: { ok: 1, fail: 1 },
      operation_id: '0123456789abcdef0123456789abcdef',
      undo_receipt: {
        schema: 'workbench.batch-trash-undo',
        version: 2,
        operation_id: '0123456789abcdef0123456789abcdef',
        action: 'trash',
        expires_at: '2026-08-30T12:15:00+00:00',
        items: [{ dir: '任务', file: 'ok.md' }],
      },
    }, sideEffects)

    expect(decision.valid).toBe(true)
    expect(sideEffects.offerUndo).toHaveBeenCalledOnce()
    expect(sideEffects.offerUndo).toHaveBeenCalledWith(expect.objectContaining({
      action: 'trash',
      items: [{ dir: '任务', file: 'ok.md' }],
    }))
  })

  it('rejects a trash receipt that mixes a failed identity before UI side effects', () => {
    const sideEffects = effects()
    const trashSubmitted = [
      { dir: '任务', file: 'ok.md' },
      { dir: '任务', file: 'failed.md' },
    ]
    const decision = consumeLegacyBatchResponse('trash', trashSubmitted, {
      ok: true,
      done: [{ dir: '任务', file: 'ok.md' }],
      failed: [{ dir: '任务', file: 'failed.md', error: 'blocked' }],
      summary: { ok: 1, fail: 1 },
      operation_id: '0123456789abcdef0123456789abcdef',
      undo_receipt: {
        operation_id: '0123456789abcdef0123456789abcdef',
        action: 'trash',
        expires_at: '2026-08-30T12:15:00+00:00',
        items: [{ dir: '任务', file: 'ok.md' }, { dir: '任务', file: 'failed.md' }],
      },
    }, sideEffects)

    expect(decision).toMatchObject({ valid: false, classification: 'protocol-error' })
    expect(sideEffects.offerUndo).not.toHaveBeenCalled()
    expect(sideEffects.invalidate).not.toHaveBeenCalled()
    expect(sideEffects.replaceSelection).not.toHaveBeenCalled()
  })
})