import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, posix, win32 } from 'node:path'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@hermes/plugin-sdk', () => ({
  atom: (initial: unknown) => {
    let value = initial
    return { get: () => value, set: (next: unknown) => { value = next }, listen: () => () => {} }
  },
  queryClient: { invalidateQueries: async () => {} },
}))


import {
  consumeBatchResponse,
  consumeBatchUndoResponse,
  consumeLegacyBatchResponse,
  type BatchUndoReceipt,
} from './batch-response'

const receipt: BatchUndoReceipt = {
  schema: 'workbench.batch-trash-undo',
  version: 2,
  operation_id: '0123456789abcdef0123456789abcdef',
  action: 'trash',
  expires_at: '2026-08-30T12:15:00+00:00',
  items: [{ dir: '任务', file: 'ok.md' }],
}

const probePath = fileURLToPath(new URL('../dashboard/batch_undo_contract_probe.py', import.meta.url))
const pluginRoot = dirname(dirname(fileURLToPath(import.meta.url)))

export const projectPythonCandidates = (
  root: string,
  platform = process.platform,
  override = process.env.WORKBENCH_TEST_PYTHON,
): string[] => {
  if (override) return [override]
  return platform === 'win32'
    ? [win32.join(root, '.venv', 'Scripts', 'python.exe')]
    : [posix.join(root, '.venv', 'bin', 'python')]
}

type PythonResolverOptions = {
  root?: string
  platform?: NodeJS.Platform
  override?: string
  exists?: (candidate: string) => boolean
  probe?: (candidate: string) => void
}

export const resolveProjectTestPython = ({
  root = pluginRoot,
  platform = process.platform,
  override = process.env.WORKBENCH_TEST_PYTHON,
  exists = existsSync,
  probe = candidate => { execFileSync(candidate, ['-c', 'import psutil'], { stdio: 'pipe' }) },
}: PythonResolverOptions = {}): string => {
  const candidates = projectPythonCandidates(root, platform, override)
  const failures: string[] = []
  for (const candidate of candidates) {
    if (!exists(candidate)) {
      failures.push(`${candidate} (missing)`)
      continue
    }
    try {
      probe(candidate)
      return candidate
    } catch (error) {
      failures.push(`${candidate} (${error instanceof Error ? error.message : String(error)})`)
    }
  }
  throw new Error(
    `SOURCE_MISSING: explicit or repository test Python with psutil is required; provision it from pyproject.toml. Checked: ${failures.join(', ')}`,
  )
}

const testPython = resolveProjectTestPython()
const probe = (scenario: string) => JSON.parse(execFileSync(testPython, [probePath, scenario], { encoding: 'utf8' }))
const undoEffects = () => ({ notify: vi.fn(), invalidate: vi.fn(), clearReceipt: vi.fn(), retainReceipt: vi.fn() })

describe('WB-S1-064 explicit CI and repository Python contract', () => {
  it('uses exact Windows and Ubuntu overrides without PATH or venv fallback', () => {
    expect(projectPythonCandidates('C:\\repo', 'win32', 'D:\\hosted\\python.exe')).toEqual(['D:\\hosted\\python.exe'])
    expect(projectPythonCandidates('/repo', 'linux', '/opt/hosted/python')).toEqual(['/opt/hosted/python'])
  })

  it('uses only the platform repository venv when no override is supplied', () => {
    expect(projectPythonCandidates('C:\\repo', 'win32', '')).toEqual(['C:\\repo\\.venv\\Scripts\\python.exe'])
    expect(projectPythonCandidates('/repo', 'linux', '')).toEqual(['/repo/.venv/bin/python'])
  })

  it('fails explicitly for a missing override and never probes another interpreter', () => {
    const probe = vi.fn()
    expect(() => resolveProjectTestPython({
      root: '/repo', platform: 'linux', override: '/missing/python', exists: () => false, probe,
    })).toThrow('SOURCE_MISSING')
    expect(probe).not.toHaveBeenCalled()
  })

  it('fails explicitly when the selected interpreter cannot import psutil', () => {
    const probe = vi.fn(() => { throw new Error('No module named psutil') })
    expect(() => resolveProjectTestPython({
      root: '/repo', platform: 'linux', override: '/ci/python', exists: () => true, probe,
    })).toThrow('No module named psutil')
    expect(probe).toHaveBeenCalledOnce()
  })

  it('accepts a validated repository venv interpreter', () => {
    const probe = vi.fn()
    expect(resolveProjectTestPython({
      root: '/repo', platform: 'linux', override: '', exists: () => true, probe,
    })).toBe('/repo/.venv/bin/python')
    expect(probe).toHaveBeenCalledWith('/repo/.venv/bin/python')
  })

  it('keeps workflow interpreter export and dependency installation authoritative', () => {
    const workflow = readFileSync(fileURLToPath(new URL('../.github/workflows/ci.yml', import.meta.url)), 'utf8')
    const pyproject = readFileSync(fileURLToPath(new URL('../pyproject.toml', import.meta.url)), 'utf8')
    expect(workflow).toContain('WORKBENCH_TEST_PYTHON={sys.executable}')
    expect(workflow).toContain('python -m pip install . --group dev')
    expect(workflow).not.toMatch(/pip install pytest|pip install psutil/)
    expect(pyproject).toContain('"psutil"')
    expect(pyproject).toContain('"pytest"')
    expect(pyproject).toContain('"ruff==0.16.5"')
  })
})

describe('WB-S1-061 real Python endpoint → Home/legacy Undo consumers', () => {
  it.each(['intent-settle', 'outcome-settle'])('rejects no terminal subset for %s double-write failure', scenario => {
    const wire = probe(scenario)
    for (const consumer of ['Home', 'legacy Board']) {
      const sideEffects = undoEffects()
      const result = consumeBatchUndoResponse(wire.receipt, wire.response, sideEffects)
      expect(result.valid, consumer).toBe(true)
      expect(sideEffects.clearReceipt, consumer).toHaveBeenCalledOnce()
      expect(sideEffects.retainReceipt, consumer).not.toHaveBeenCalled()
      expect(sideEffects.invalidate, consumer).toHaveBeenCalledOnce()
      expect(sideEffects.notify.mock.calls[0][0].message, consumer).not.toContain('协议错误')
    }
  })

  it('preserves durable exact identities when terminal ledger and sidecar both fail', () => {
    const wire = probe('terminal-sidecar')
    expect(wire.exception).toContain('recovery sidecar write failure')
    expect(wire.claimed_ledger.state).toBe('claimed')
    expect(wire.claimed_ledger.items.map((item: { dir: string; file: string }) => [item.dir, item.file])).toEqual([
      ['任务', 'one.md'], ['任务', 'two.md'],
    ])
    expect(wire.claim_exists_after_exception).toBe(false)
    expect(wire.settled_ledger.state).toBe('consumed')
    expect(wire.settled_ledger.items.map((item: { dir: string; file: string }) => [item.dir, item.file])).toEqual([
      ['任务', 'one.md'], ['任务', 'two.md'],
    ])
  })

  it('shows real busy/expired/collision errors and retains receipts in both consumers', () => {
    const wire = probe('rejections')
    for (const error of ['operation busy', 'operation expired', 'original path collision']) {
      for (const consumer of ['Home', 'legacy Board']) {
        const sideEffects = undoEffects()
        const result = consumeBatchUndoResponse(wire.receipts[error], wire.responses[error], sideEffects)
        expect(result.valid, `${consumer}: ${error}`).toBe(true)
        expect(sideEffects.notify, `${consumer}: ${error}`).toHaveBeenCalledWith({ kind: 'error', message: error })
        expect(sideEffects.retainReceipt, `${consumer}: ${error}`).toHaveBeenCalledOnce()
        expect(sideEffects.clearReceipt, `${consumer}: ${error}`).not.toHaveBeenCalled()
        expect(sideEffects.invalidate, `${consumer}: ${error}`).not.toHaveBeenCalled()
      }
    }
  })
})

describe('WB-S1-059 production Undo transport', () => {
  it('runs Home and legacy receipt-to-Undo flows through the production transport', async () => {
    const calls: Array<{ path: string; body: unknown }> = []
    const undoResult = {
      ok: true,
      restored: [{ dir: '任务', file: 'ok.md' }],
      failed: [],
      summary: { restored: 1, failed: 0 },
      receipt: { schema: receipt.schema, version: 2 as const, operation_id: receipt.operation_id, action: 'trash' as const, consumed: true },
    }
    const batchResult = {
      ok: true,
      done: [{ dir: '任务', file: 'ok.md' }],
      failed: [{ dir: '任务', file: 'failed.md', error: 'blocked' }],
      summary: { ok: 1, fail: 1 },
      operation_id: receipt.operation_id,
      undo_receipt: receipt,
    }
    const rest = async <T>(path: string, options?: { body?: unknown }) => {
      calls.push({ path, body: options?.body })
      return (path === '/batch' ? batchResult : undoResult) as T
    }
    const { batchAction, bindApi, undoBatchTrash } = await import('./api')
    const cleanup = bindApi(rest, { get: (_key: string, fallback: unknown) => fallback, set: () => {} }, () => () => {})
    const submitted = [{ dir: '任务', file: 'ok.md' }, { dir: '任务', file: 'failed.md' }]

    const homeEffects = { notify: vi.fn(), invalidate: vi.fn(), offerUndo: vi.fn(), replaceSelection: vi.fn(), clearSelection: vi.fn(), exitMultiMode: vi.fn() }
    const homeBatch = await batchAction('trash', submitted)
    expect(consumeBatchResponse('trash', submitted, homeBatch, homeEffects).valid).toBe(true)
    const homeReceipt = homeEffects.offerUndo.mock.calls[0][0] as BatchUndoReceipt
    expect(consumeBatchUndoResponse(homeReceipt, await undoBatchTrash(homeReceipt), { notify: vi.fn(), invalidate: vi.fn(), clearReceipt: vi.fn() }).valid).toBe(true)

    const legacyEffects = { notify: vi.fn(), invalidate: vi.fn(), offerUndo: vi.fn(), replaceSelection: vi.fn(), clearSelection: vi.fn(), exitMultiMode: vi.fn() }
    const legacyBatch = await batchAction('trash', submitted)
    expect(consumeLegacyBatchResponse('trash', submitted, legacyBatch, legacyEffects).valid).toBe(true)
    const legacyReceipt = legacyEffects.offerUndo.mock.calls[0][0] as BatchUndoReceipt
    expect(consumeBatchUndoResponse(legacyReceipt, await undoBatchTrash(legacyReceipt), { notify: vi.fn(), invalidate: vi.fn(), clearReceipt: vi.fn() }).valid).toBe(true)

    expect(calls).toEqual([
      { path: '/batch', body: { action: 'trash', items: submitted } },
      { path: '/batch/undo', body: receipt },
      { path: '/batch', body: { action: 'trash', items: submitted } },
      { path: '/batch/undo', body: receipt },
    ])
    cleanup()
  })
})

describe('WB-S1-057 default Home authoritative Undo consumer', () => {
  const effects = () => ({
    notify: vi.fn(),
    invalidate: vi.fn(),
    offerUndo: vi.fn(),
    replaceSelection: vi.fn(),
    clearSelection: vi.fn(),
    exitMultiMode: vi.fn(),
  })

  it('fails closed when successful Home trash lacks its receipt', () => {
    const sideEffects = effects()
    const result = consumeBatchResponse('trash', [{ dir: '任务', file: 'ok.md' }], {
      ok: true,
      done: [{ dir: '任务', file: 'ok.md' }],
      failed: [],
      summary: { ok: 1, fail: 0 },
    }, sideEffects)
    expect(result.valid).toBe(false)
    expect(sideEffects.offerUndo).not.toHaveBeenCalled()
    expect(sideEffects.invalidate).not.toHaveBeenCalled()
  })

  it('offers only exact backend successes for full and partial Home trash', () => {
    const sideEffects = effects()
    const result = consumeBatchResponse('trash', [
      { dir: '任务', file: 'ok.md' },
      { dir: '任务', file: 'failed.md' },
    ], {
      ok: true,
      done: [{ dir: '任务', file: 'ok.md' }],
      failed: [{ dir: '任务', file: 'failed.md', error: 'blocked' }],
      summary: { ok: 1, fail: 1 },
      operation_id: receipt.operation_id,
      undo_receipt: receipt,
    }, sideEffects)
    expect(result.valid).toBe(true)
    expect(sideEffects.offerUndo).toHaveBeenCalledWith(receipt)
    expect(sideEffects.replaceSelection).toHaveBeenCalledWith([{ dir: '任务', file: 'failed.md' }])
  })

  it.each([
    ['missing', undefined],
    ['missing schema', { ...receipt, schema: undefined }],
    ['unknown schema', { ...receipt, schema: 'workbench.other' }],
    ['unknown version', { ...receipt, version: 999 }],
    ['mixed failed', { ...receipt, items: [...receipt.items, { dir: '任务', file: 'failed.md' }] }],
    ['duplicate', { ...receipt, items: [...receipt.items, ...receipt.items] }],
    ['bad action', { ...receipt, action: 'delete' }],
  ])('rejects %s receipt before Home success effects', (_label, badReceipt) => {
    const sideEffects = effects()
    const response: Record<string, unknown> = {
      ok: true,
      done: [{ dir: '任务', file: 'ok.md' }],
      failed: [{ dir: '任务', file: 'failed.md', error: 'blocked' }],
      summary: { ok: 1, fail: 1 },
    }
    if (badReceipt !== undefined) {
      response.operation_id = receipt.operation_id
      response.undo_receipt = badReceipt
    }
    const result = consumeBatchResponse('trash', [
      { dir: '任务', file: 'ok.md' },
      { dir: '任务', file: 'failed.md' },
    ], response, sideEffects)
    expect(result.valid).toBe(false)
    expect(sideEffects.offerUndo).not.toHaveBeenCalled()
    expect(sideEffects.invalidate).not.toHaveBeenCalled()
  })

  it('retains local receipt for busy/expired/tampered/schema rejection', () => {
    for (const error of ['operation busy', 'operation expired', 'operation record mismatch', 'operation schema unsupported']) {
      const sideEffects = { notify: vi.fn(), invalidate: vi.fn(), clearReceipt: vi.fn() }
      const result = consumeBatchUndoResponse(receipt, {
        ok: false,
        restored: [],
        failed: [],
        summary: { restored: 0, failed: 0 },
        receipt: { schema: 'workbench.batch-trash-undo', version: 2, operation_id: receipt.operation_id, action: 'trash', consumed: false },
        error,
      }, sideEffects)
      expect(result.valid).toBe(true)
      expect(sideEffects.clearReceipt).not.toHaveBeenCalled()
      expect(sideEffects.notify).toHaveBeenCalledWith({ kind: 'error', message: expect.stringContaining(error) })
    }
  })

  it('clears only an authoritative terminal consumed response and exposes partial failures', () => {
    const sideEffects = { notify: vi.fn(), invalidate: vi.fn(), clearReceipt: vi.fn() }
    const twoItemReceipt = { ...receipt, items: [...receipt.items, { dir: '任务', file: 'two.md' }] }
    const result = consumeBatchUndoResponse(twoItemReceipt, {
      ok: true,
      restored: [{ dir: '任务', file: 'ok.md' }],
      failed: [{ dir: '任务', file: 'two.md', error: 'restore failed' }],
      summary: { restored: 1, failed: 1 },
      receipt: { schema: 'workbench.batch-trash-undo', version: 2, operation_id: twoItemReceipt.operation_id, action: 'trash', consumed: true },
    }, sideEffects)
    expect(result.valid).toBe(true)
    expect(sideEffects.clearReceipt).toHaveBeenCalledOnce()
    expect(sideEffects.invalidate).toHaveBeenCalledOnce()
    expect(sideEffects.notify).toHaveBeenCalledWith({ kind: 'warning', message: expect.stringContaining('不可再次撤销') })
    expect(sideEffects.notify.mock.calls[0][0].message).toContain('two.md: restore failed')
  })

})