/** Runtime /batch response contract shared by Home and the legacy Board. */

export interface BatchResponseRow {
  dir: string
  file: string
  entry?: string
  error?: string
}

export interface ValidBatchResponse {
  ok: boolean
  done: BatchResponseRow[]
  failed: BatchResponseRow[]
  summary: { ok: number; fail: number }
  error?: string
}

export type BatchResponseValidation =
  | { valid: true; response: ValidBatchResponse }
  | { valid: false; classification: 'protocol-error' | 'global-rejection'; error: string }

export type BatchAction = 'complete' | 'resolve' | 'trash' | 'to-task'

export interface BatchRequestItem {
  dir: string
  file: string
  entry_title?: string
}

/** Validate the wire shape before any legacy/Home state or cache mutation. */
export function validateBatchResponse(input: unknown): BatchResponseValidation {
  if (!isRecord(input)) return invalid('响应不是 object')
  if (typeof input.ok !== 'boolean') return invalid('响应 ok 必须是 boolean')
  if (!Array.isArray(input.done)) return invalid('响应 done 必须是数组')
  if (!Array.isArray(input.failed)) return invalid('响应 failed 必须是数组')
  if (!isRecord(input.summary)) return invalid('响应 summary 必须是 object')
  const ok = input.summary.ok
  const fail = input.summary.fail
  if (!isCount(ok) || !isCount(fail)) return invalid('响应 summary.ok/fail 必须是 finite 非负整数')
  const done = parseRows(input.done, 'done')
  if (!done.valid) return done
  const failed = parseRows(input.failed, 'failed')
  if (!failed.valid) return failed
  if (input.error !== undefined && typeof input.error !== 'string') return invalid('响应 error 必须是 string')
  return {
    valid: true,
    response: {
      ok: input.ok,
      done: done.rows,
      failed: failed.rows,
      summary: { ok, fail },
      ...(input.error === undefined ? {} : { error: input.error }),
    },
  }
}

export function isGlobalBatchRejection(response: ValidBatchResponse): response is ValidBatchResponse & { error: string } {
  return response.ok === false
    && response.done.length === 0
    && response.failed.length === 0
    && response.summary.ok === 0
    && response.summary.fail === 0
    && typeof response.error === 'string'
    && response.error.length > 0
}

/** Production decision seam for the reachable legacy Board, before any side effect. */
export function settleLegacyBatchResponse(
  action: BatchAction,
  submitted: BatchRequestItem[],
  input: unknown,
): BatchResponseValidation {
  const validation = validateBatchResponse(input)
  if (!validation.valid) return validation
  const response = validation.response
  if (isGlobalBatchRejection(response)) return globalRejection(response.error)
  if (response.summary.ok !== response.done.length || response.summary.fail !== response.failed.length) {
    return invalid('summary 计数与 done/failed 长度不一致')
  }
  const expectedOk = response.failed.length === 0 || response.done.length > 0
  if (response.ok !== expectedOk) return invalid('响应 ok 与 done/failed 真值表不一致')

  const expected = new Set<string>()
  for (const item of submitted) {
    const identity = batchIdentity(action, item.dir, item.file, item.entry_title ?? '')
    if (!identity || expected.has(identity)) return invalid('submitted identity 非空且唯一')
    expected.add(identity)
  }
  const actual = new Set<string>()
  for (const row of [...response.done, ...response.failed]) {
    const identity = batchIdentity(action, row.dir, row.file, row.entry ?? '')
    if (!identity || actual.has(identity)) return invalid('done/failed identity 非空、唯一且不交叠')
    actual.add(identity)
  }
  if (actual.size !== expected.size || [...actual].some(identity => !expected.has(identity))) {
    return invalid('done/failed identity 必须属于并精确覆盖 submitted')
  }
  return validation
}

export interface LegacyBatchResponseEffects {
  notify: (notice: { kind: 'error' | 'warning' | 'success'; message: string }) => void
  invalidate: () => void
  replaceSelection: (items: BatchRequestItem[]) => void
  clearSelection: () => void
  exitMultiMode: () => void
}

/** Production consumer used by WorkbenchBoardPage.runBatch. */
export function consumeLegacyBatchResponse(
  action: BatchAction,
  submitted: BatchRequestItem[],
  input: unknown,
  effects: LegacyBatchResponseEffects,
): BatchResponseValidation {
  const decision = settleLegacyBatchResponse(action, submitted, input)
  if (!decision.valid) {
    effects.notify({ kind: 'error', message: decision.error })
    return decision
  }
  const okN = decision.response.summary.ok
  const failN = decision.response.summary.fail
  const failedItems = failN > 0
    ? submitted.filter(item => decision.response.failed.some(row => (
      batchIdentity(action, item.dir, item.file, item.entry_title ?? '')
      === batchIdentity(action, row.dir, row.file, row.entry ?? '')
    )))
    : []
  const failureDetails = decision.response.failed
    .map(row => `${row.entry?.trim() || row.file}: ${row.error || '操作失败'}`)
    .join('；')
  effects.notify({
    kind: failN > 0 ? 'warning' : 'success',
    message: `批量归档 ${okN} 项${failN ? `，${failN} 项失败：${failureDetails}` : ''}`,
  })
  if (okN > 0) effects.invalidate()
  if (failN > 0) {
    effects.replaceSelection(failedItems)
  } else {
    effects.clearSelection()
    effects.exitMultiMode()
  }
  return decision
}

function batchIdentity(action: BatchAction, dir: string, file: string, entry: string): string | null {
  const canonicalDir = canonicalPath(dir)
  const canonicalFile = canonicalPath(file)
  if (!canonicalDir || !canonicalFile) return null
  const base = JSON.stringify([canonicalDir, canonicalFile])
  return action === 'resolve' || action === 'to-task' ? `${base}:${entry.trim()}` : base
}

function canonicalPath(value: string): string {
  const parts: string[] = []
  for (const part of value.trim().replaceAll('\\', '/').split('/')) {
    if (!part || part === '.') continue
    if (part === '..') {
      if (parts.length === 0) return ''
      parts.pop()
    } else {
      parts.push(part)
    }
  }
  return parts.join('/').toLocaleLowerCase()
}

function parseRows(value: unknown[], label: string): { valid: true; rows: BatchResponseRow[] } | { valid: false; classification: 'protocol-error'; error: string } {
  const rows: BatchResponseRow[] = []
  for (let index = 0; index < value.length; index += 1) {
    const row = value[index]
    if (!isRecord(row) || typeof row.dir !== 'string' || row.dir.length === 0 || typeof row.file !== 'string' || row.file.length === 0) {
      return invalid(`响应 ${label}[${index}] 必须包含非空 string dir/file`)
    }
    if (row.entry !== undefined && typeof row.entry !== 'string') return invalid(`响应 ${label}[${index}].entry 必须是 string`)
    if (row.error !== undefined && typeof row.error !== 'string') return invalid(`响应 ${label}[${index}].error 必须是 string`)
    rows.push({
      dir: row.dir,
      file: row.file,
      ...(row.entry === undefined ? {} : { entry: row.entry }),
      ...(row.error === undefined ? {} : { error: row.error }),
    })
  }
  return { valid: true, rows }
}

function isRecord(value: unknown): value is Record<string, any> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isCount(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && Number.isInteger(value) && value >= 0
}

function invalid(error: string): { valid: false; classification: 'protocol-error'; error: string } {
  return { valid: false, classification: 'protocol-error', error: `批量响应协议错误：${error}` }
}

function globalRejection(error: string): { valid: false; classification: 'global-rejection'; error: string } {
  return { valid: false, classification: 'global-rejection', error }
}