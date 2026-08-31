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
  operation_id?: string
  undo_receipt?: BatchUndoReceipt
}

export interface BatchUndoReceipt {
  schema: 'workbench.batch-trash-undo'
  version: 2
  operation_id: string
  action: 'trash'
  expires_at: string
  items: Array<{ dir: string; file: string }>
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
  const undo = parseUndoReceipt(input.operation_id, input.undo_receipt)
  if (!undo.valid) return undo
  return {
    valid: true,
    response: {
      ok: input.ok,
      done: done.rows,
      failed: failed.rows,
      summary: { ok, fail },
      ...(input.error === undefined ? {} : { error: input.error }),
      ...(undo.receipt === undefined ? {} : { operation_id: undo.receipt.operation_id, undo_receipt: undo.receipt }),
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
  const receipt = response.undo_receipt
  if (action === 'trash' && response.done.length > 0) {
    if (!receipt) return invalid('trash 成功响应必须包含 authoritative undo receipt')
    const doneIdentities = response.done.map(row => batchIdentity('trash', row.dir, row.file, ''))
    const receiptIdentities = receipt.items.map(item => batchIdentity('trash', item.dir, item.file, ''))
    if (receiptIdentities.length !== doneIdentities.length || receiptIdentities.some((identity, index) => identity !== doneIdentities[index])) {
      return invalid('undo receipt identities 必须精确等于 trash done identities')
    }
  } else if (receipt) {
    return invalid('undo receipt 只允许用于有成功项的 trash 响应')
  }
  return validation
}

export interface BatchResponseEffects {
  notify: (notice: { kind: 'error' | 'warning' | 'success'; message: string }) => void
  invalidate: () => void
  offerUndo: (receipt: BatchUndoReceipt) => void
  replaceSelection: (items: BatchRequestItem[]) => void
  clearSelection: () => void
  exitMultiMode: () => void
}

/** Production consumer used by WorkbenchBoardPage.runBatch. */
export function consumeBatchResponse(
  action: BatchAction,
  submitted: BatchRequestItem[],
  input: unknown,
  effects: BatchResponseEffects,
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
    message: `${action === 'trash' ? '批量移入回收站' : '批量归档'} ${okN} 项${failN ? `，${failN} 项失败：${failureDetails}` : ''}`,
  })
  if (okN > 0) effects.invalidate()
  if (action === 'trash' && decision.response.undo_receipt) effects.offerUndo(decision.response.undo_receipt)
  if (failN > 0) {
    effects.replaceSelection(failedItems)
  } else {
    effects.clearSelection()
    effects.exitMultiMode()
  }
  return decision
}

/** Compatibility export while legacy Board and default Home converge on one seam. */
export const consumeLegacyBatchResponse = consumeBatchResponse
export type LegacyBatchResponseEffects = BatchResponseEffects

export interface BatchUndoResponseEffects {
  notify: (notice: { kind: 'error' | 'warning' | 'success'; message: string }) => void
  invalidate: () => void
  clearReceipt: () => void
  retainReceipt?: () => void
}

export type BatchUndoResponseValidation =
  | {
    valid: true
    response: {
      ok: boolean
      restored: Array<{ dir: string; file: string }>
      failed: Array<{ dir: string; file: string; error: string }>
      summary: { restored: number; failed: number }
      receipt: { schema: 'workbench.batch-trash-undo'; version: 2; operation_id: string; action: 'trash'; consumed: boolean }
      error?: string
    }
  }
  | { valid: false; classification: 'protocol-error'; error: string }

export function validateBatchUndoResponse(
  expected: BatchUndoReceipt,
  input: unknown,
): BatchUndoResponseValidation {
  if (!isRecord(input) || typeof input.ok !== 'boolean') return invalidUndo('响应 ok 必须是 boolean')
  if (!Array.isArray(input.restored) || !Array.isArray(input.failed) || !isRecord(input.summary)) {
    return invalidUndo('restored/failed/summary 形状无效')
  }
  if (!isCount(input.summary.restored) || !isCount(input.summary.failed)) return invalidUndo('summary 计数无效')
  if (!isRecord(input.receipt)
    || input.receipt.schema !== 'workbench.batch-trash-undo'
    || input.receipt.version !== 2
    || input.receipt.operation_id !== expected.operation_id
    || input.receipt.action !== 'trash'
    || typeof input.receipt.consumed !== 'boolean') {
    return invalidUndo('receipt operation/action/consumed 不匹配')
  }
  if (input.error !== undefined && typeof input.error !== 'string') return invalidUndo('error 必须是 string')
  const restored: Array<{ dir: string; file: string }> = []
  const failed: Array<{ dir: string; file: string; error: string }> = []
  const actual = new Set<string>()
  for (let index = 0; index < input.restored.length; index += 1) {
    const row = input.restored[index]
    if (!isRecord(row) || Object.keys(row).sort().join(',') !== 'dir,file' || typeof row.dir !== 'string' || typeof row.file !== 'string') {
      return invalidUndo(`restored[${index}] identity 无效`)
    }
    const identity = batchIdentity('trash', row.dir, row.file, '')
    if (!identity || actual.has(identity)) return invalidUndo('restored/failed identity 必须唯一')
    actual.add(identity)
    restored.push({ dir: row.dir, file: row.file })
  }
  for (let index = 0; index < input.failed.length; index += 1) {
    const row = input.failed[index]
    if (!isRecord(row) || Object.keys(row).sort().join(',') !== 'dir,error,file'
      || typeof row.dir !== 'string' || typeof row.file !== 'string' || typeof row.error !== 'string') {
      return invalidUndo(`failed[${index}] identity/error 无效`)
    }
    const identity = batchIdentity('trash', row.dir, row.file, '')
    if (!identity || actual.has(identity)) return invalidUndo('restored/failed identity 必须唯一')
    actual.add(identity)
    failed.push({ dir: row.dir, file: row.file, error: row.error })
  }
  if (input.summary.restored !== restored.length || input.summary.failed !== failed.length) {
    return invalidUndo('summary 与 restored/failed 长度不一致')
  }
  if (!input.receipt.consumed) {
    if (input.ok || actual.size !== 0 || input.summary.restored !== 0 || input.summary.failed !== 0 || typeof input.error !== 'string' || !input.error) {
      return invalidUndo('未消费拒绝必须零移动并带可行动 error')
    }
  } else {
    const expectedIdentities = expected.items.map(item => batchIdentity('trash', item.dir, item.file, ''))
    if (actual.size !== expectedIdentities.length || expectedIdentities.some(identity => !identity || !actual.has(identity))) {
      return invalidUndo('terminal consumed 必须精确结算 receipt 全部 identities')
    }
    if (input.ok !== (restored.length > 0)) return invalidUndo('ok 与 restored 数量不一致')
  }
  return {
    valid: true,
    response: {
      ok: input.ok,
      restored,
      failed,
      summary: { restored: input.summary.restored, failed: input.summary.failed },
      receipt: { schema: 'workbench.batch-trash-undo', version: 2, operation_id: expected.operation_id, action: 'trash', consumed: input.receipt.consumed },
      ...(input.error === undefined ? {} : { error: input.error }),
    },
  }
}

export function consumeBatchUndoResponse(
  expected: BatchUndoReceipt,
  input: unknown,
  effects: BatchUndoResponseEffects,
): BatchUndoResponseValidation {
  const decision = validateBatchUndoResponse(expected, input)
  if (!decision.valid) {
    effects.notify({ kind: 'error', message: decision.error })
    effects.retainReceipt?.()
    return decision
  }
  const response = decision.response
  if (!response.receipt.consumed) {
    effects.notify({ kind: 'error', message: response.error || '撤销移入回收站被拒绝，receipt 已保留' })
    effects.retainReceipt?.()
    return decision
  }
  if (response.restored.length > 0) effects.invalidate()
  effects.notify({
    kind: response.failed.length > 0 ? 'warning' : 'success',
    message: `撤销移入回收站：恢复 ${response.restored.length} 项${response.failed.length ? `，${response.failed.length} 项失败；本 receipt 已终结，不可再次撤销：${response.failed.map(item => `${item.file}: ${item.error}`).join('；')}` : ''}`,
  })
  effects.clearReceipt()
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

function parseUndoReceipt(operationId: unknown, value: unknown): { valid: true; receipt?: BatchUndoReceipt } | { valid: false; classification: 'protocol-error'; error: string } {
  if (operationId === undefined && value === undefined) return { valid: true }
  if (typeof operationId !== 'string' || !/^[0-9a-f]{32}$/.test(operationId)) return invalid('operation_id 必须是 32 位小写 hex')
  if (!isRecord(value) || value.schema !== 'workbench.batch-trash-undo' || value.version !== 2) return invalid('undo_receipt schema/version 不支持')
  if (value.operation_id !== operationId || value.action !== 'trash') return invalid('undo_receipt operation/action 不匹配')
  if (typeof value.expires_at !== 'string' || !Number.isFinite(Date.parse(value.expires_at))) return invalid('undo_receipt expires_at 无效')
  if (!Array.isArray(value.items) || value.items.length === 0) return invalid('undo_receipt items 必须非空')
  const items: Array<{ dir: string; file: string }> = []
  for (let index = 0; index < value.items.length; index += 1) {
    const item = value.items[index]
    if (!isRecord(item) || Object.keys(item).sort().join(',') !== 'dir,file' || typeof item.dir !== 'string' || typeof item.file !== 'string') {
      return invalid(`undo_receipt items[${index}] 必须只有 string dir/file`)
    }
    items.push({ dir: item.dir, file: item.file })
  }
  return { valid: true, receipt: { schema: 'workbench.batch-trash-undo', version: 2, operation_id: operationId, action: 'trash', expires_at: value.expires_at, items } }
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

function invalidUndo(error: string): { valid: false; classification: 'protocol-error'; error: string } {
  return { valid: false, classification: 'protocol-error', error: `撤销移入回收站响应协议错误：${error}` }
}