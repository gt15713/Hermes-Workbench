import { describe, expect, it } from 'vitest'

import { canArchiveTask, launchWorkbenchTask, type WorkbenchExecutionDeps } from './execution'

interface Harness {
  status: 'todo' | 'in_progress'
  boundSession: null | string
  promptSubmitted: boolean
  submittedText: string
  createCwd: string | undefined
}

function makeHarness(overrides: Partial<WorkbenchExecutionDeps> & { scope?: 'research' | 'ingest' | 'execute' } = {}) {
  const state: Harness = {
    status: 'todo',
    boundSession: null,
    promptSubmitted: false,
    submittedText: '',
    createCwd: '',
  }
  const scope = overrides.scope ?? 'research'

  const deps: WorkbenchExecutionDeps = {
    prepare: async () => {
      state.status = 'in_progress'
      return {
        ok: true,
        status: 'in_progress',
        file: 'renamed.md',
        path: '~/Workbench/任务/renamed.md',
        scope,
        cwd: scope === 'research' ? '~/Workbench/cache/workbench-research' : '~/Workbench',
      }
    },
    createSession: async input => {
      state.createCwd = input.cwd
      return { session_id: 'runtime-1', stored_session_id: 'stored-1' }
    },
    bind: async (_dir, _file, storedId) => {
      state.boundSession = storedId
      return { ok: true, session_id: storedId }
    },
    submit: async (_runtimeId, text) => {
      state.promptSubmitted = true
      state.submittedText = text
    },
    rollback: async () => {
      state.status = 'todo'
      state.boundSession = null
      return { ok: true, status: 'todo' }
    },
    ...overrides,
  }

  return { state, deps }
}

const task = {
  dir: '任务',
  file: 'original.md',
  title: '测试任务',
  path: '~/Workbench/任务/original.md',
}

describe('launchWorkbenchTask', () => {
  it('keeps a manual archive action available for completed tasks still in the task partition', () => {
    expect(canArchiveTask('task', 'completed', 'pending')).toBe(true)
    expect(canArchiveTask('task', 'done', 'success')).toBe(true)
    expect(canArchiveTask('task', 'in_progress', 'success')).toBe(true)
    expect(canArchiveTask('task', 'in_progress', 'pending')).toBe(false)
    expect(canArchiveTask('task', 'in_progress', 'failure')).toBe(false)
    expect(canArchiveTask('done', 'completed')).toBe(false)
  })

  it('restores the task when session creation fails', async () => {
    const { state, deps } = makeHarness({
      createSession: async () => {
        throw new Error('gateway offline')
      },
    })

    const result = await launchWorkbenchTask(task, deps)

    expect(result).toMatchObject({ ok: false, phase: 'session.create', file: 'renamed.md' })
    expect(state).toMatchObject({ status: 'todo', boundSession: null, promptSubmitted: false })
  })

  it('does not submit a prompt when session binding is rejected', async () => {
    const { state, deps } = makeHarness({
      bind: async () => ({ ok: false, error: 'task not found' }),
    })

    const result = await launchWorkbenchTask(task, deps)

    expect(result).toMatchObject({ ok: false, phase: 'bind-session' })
    expect(state).toMatchObject({ status: 'todo', boundSession: null, promptSubmitted: false })
  })

  it('restores the task when the first prompt is not accepted', async () => {
    const { state, deps } = makeHarness({
      submit: async () => {
        throw new Error('submit rejected')
      },
    })

    const result = await launchWorkbenchTask(task, deps)

    expect(result).toMatchObject({ ok: false, phase: 'prompt.submit' })
    expect(state).toMatchObject({ status: 'todo', boundSession: null, promptSubmitted: false })
  })

  it('keeps the task running only after prepare, create, bind, and submit all succeed', async () => {
    const { state, deps } = makeHarness()

    const result = await launchWorkbenchTask(task, deps)

    expect(result).toEqual({
      ok: true,
      phase: 'running',
      file: 'renamed.md',
      path: '~/Workbench/任务/renamed.md',
      storedSessionId: 'stored-1',
    })
    expect(state).toMatchObject({ status: 'in_progress', boundSession: 'stored-1', promptSubmitted: true })
    expect(state.submittedText).toContain('execution_result: success')
    expect(state.submittedText).toContain('execution_result: failure')
  })

  it('adds the research no-write + ask-ingest directive and isolates cwd', async () => {
    const { state, deps } = makeHarness({ scope: 'research' })
    const result = await launchWorkbenchTask(task, deps)
    expect(result.ok).toBe(true)
    expect(state.submittedText).toContain('默认不写 Obsidian')
    expect(state.submittedText).toContain('询问是否需要吃进')
    expect(state.createCwd).toBe('~/Workbench/cache/workbench-research')
  })

  it('omits the no-write directive and keeps workbench cwd for ingest scope', async () => {
    const { state, deps } = makeHarness({ scope: 'ingest' })
    const result = await launchWorkbenchTask(task, deps)
    expect(result.ok).toBe(true)
    expect(state.submittedText).not.toContain('默认不写 Obsidian')
    expect(state.createCwd).toBe('~/Workbench')
  })
})
