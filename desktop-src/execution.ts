export interface WorkbenchExecutionInput {
  dir: string
  file: string
  title: string
  path: string
  content?: string
  due?: string
}

interface PreparedTask {
  ok: boolean
  status?: string
  file?: string
  path?: string
  error?: string
  // 08-21 研究≠摄入治理（B1/B3）：任务范围 + 会话工作目录（后端 /execute 返回）
  scope?: 'research' | 'ingest' | 'execute'
  cwd?: string
}

interface SessionHandle {
  session_id?: string
  stored_session_id?: string
}

interface OperationResult {
  ok: boolean
  status?: string
  session_id?: string
  error?: string
}

export interface WorkbenchExecutionDeps {
  prepare(input: WorkbenchExecutionInput): Promise<PreparedTask>
  createSession(input: { source: string; title: string; cwd?: string }): Promise<SessionHandle>
  bind(dir: string, file: string, storedSessionId: string): Promise<OperationResult>
  submit(runtimeSessionId: string, text: string): Promise<unknown>
  rollback(dir: string, file: string, reason: string): Promise<OperationResult>
}

export type WorkbenchExecutionPhase =
  | 'prepare'
  | 'session.create'
  | 'bind-session'
  | 'prompt.submit'
  | 'running'

export interface WorkbenchExecutionResult {
  ok: boolean
  phase: WorkbenchExecutionPhase
  file: string
  path: string
  storedSessionId?: string
  error?: string
  rollbackError?: string
}

export function canArchiveTask(sectionKey: string, status: string, executionResult?: string): boolean {
  if (sectionKey !== 'task') return false
  if (status === 'todo' || status === 'completed') return true
  return status === 'in_progress' && executionResult === 'success'
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

function taskPrompt(input: WorkbenchExecutionInput, currentPath: string, scope?: string): string {
  const detail = input.content ? `\n任务详情：${input.content}` : ''
  // 08-21 研究≠摄入（B2）：research 范围显式声明禁令，压过技能流程里的摄入步骤
  const scopeLine =
    scope === 'research'
      ? '\n\n任务范围：research —— 默认不写 Obsidian，先给结论（可吃进形态：结论+素材结构化）；完成后询问是否需要吃进，明确同意才写入'
      : ''
  return `执行任务：「${input.title}」
任务文件：${currentPath}${detail}${scopeLine}

纪律（任务完成≠会话结束）：
1. 完成并验证后 → 任务文件 frontmatter 写 execution_result: success
2. 无法完成 → execution_result: failure + 正文追加「## 执行失败记录」说明原因
3. 未完成/被中断 → 保持 execution_result: pending，禁止虚假成功`
}

async function rollback(
  deps: WorkbenchExecutionDeps,
  input: WorkbenchExecutionInput,
  file: string,
  phase: Exclude<WorkbenchExecutionPhase, 'prepare' | 'running'>,
  path: string,
  error: unknown,
): Promise<WorkbenchExecutionResult> {
  const reason = `${phase} 失败：${errorMessage(error)}`
  let rollbackError: string | undefined
  try {
    const result = await deps.rollback(input.dir, file, reason)
    if (!result.ok) {
      rollbackError = result.error || '恢复待办失败'
    }
  } catch (rollbackFailure) {
    rollbackError = errorMessage(rollbackFailure)
  }
  return {
    ok: false,
    phase,
    file,
    path,
    error: reason,
    ...(rollbackError ? { rollbackError } : {}),
  }
}

export async function launchWorkbenchTask(
  input: WorkbenchExecutionInput,
  deps: WorkbenchExecutionDeps,
): Promise<WorkbenchExecutionResult> {
  let prepared: PreparedTask
  try {
    prepared = await deps.prepare(input)
  } catch (error) {
    return {
      ok: false,
      phase: 'prepare',
      file: input.file,
      path: input.path,
      error: errorMessage(error),
    }
  }

  if (!prepared.ok) {
    return {
      ok: false,
      phase: 'prepare',
      file: prepared.file || input.file,
      path: prepared.path || input.path,
      error: prepared.error || '任务准备失败',
    }
  }

  const file = prepared.file || input.file
  const path = prepared.path || input.path
  // 08-21 研究≠摄入（B3）：research 会话工作目录隔离（默认落盘不进 Obsidian）
  const scope = prepared.scope || 'research'
  // P0-B：cwd 一律取后端返回值；无返回值不回退个人路径（交宿主默认），隐私中立
  const cwd = prepared.cwd
  let session: SessionHandle
  try {
    session = await deps.createSession({
      source: 'workbench',
      title: `工作台｜${input.title}`,
      cwd,
    })
  } catch (error) {
    return rollback(deps, input, file, 'session.create', path, error)
  }

  const runtimeId = session.session_id
  const storedId = session.stored_session_id || runtimeId
  if (!runtimeId || !storedId) {
    return rollback(deps, input, file, 'session.create', path, '会话返回缺少标识')
  }

  try {
    const bound = await deps.bind(input.dir, file, storedId)
    if (!bound.ok) {
      return rollback(deps, input, file, 'bind-session', path, bound.error || '绑定被拒绝')
    }
  } catch (error) {
    return rollback(deps, input, file, 'bind-session', path, error)
  }

  try {
    await deps.submit(runtimeId, taskPrompt(input, path, scope))
  } catch (error) {
    return rollback(deps, input, file, 'prompt.submit', path, error)
  }

  return {
    ok: true,
    phase: 'running',
    file,
    path,
    storedSessionId: storedId,
  }
}
