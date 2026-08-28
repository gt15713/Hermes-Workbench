import { describe, expect, it } from 'vitest'

import { conversationPrimaryAction, homeCardPrimaryAction } from './card-action'

/**
 * Task 4 — 一张卡一个主操作（统一映射，单源真相）。
 *
 * 状态词表与 home-model.ts 同源实证：
 * - INBOX   = pending / queued / todo / ''（后端缺省=新进件）→ 开始处理
 * - ACTIVE  = in_progress / active / processing              → 查看进度
 * - ATTENTION = waiting_user / failed / failure 组合态       → 确认处理
 * - COMPLETED 族 = completed / ingested / accepted / ignored / done → 查看证据
 * 映射表外状态返回 null（fail-closed：绝不猜按钮），不产生第二个主操作。
 */

type Case = [string, string, string] // status, expectedKind, expectedLabel

const HOME_CASES: Case[] = [
  ['pending', 'start', '开始处理'],
  ['queued', 'start', '开始处理'],
  ['todo', 'start', '开始处理'],
  ['', 'start', '开始处理'],
  ['in_progress', 'progress', '查看进度'],
  ['active', 'progress', '查看进度'],
  ['processing', 'progress', '查看进度'],
  ['waiting_user', 'confirm', '确认处理'],
  ['failed', 'confirm', '确认处理'],
  ['completed', 'evidence', '查看证据'],
  ['ingested', 'evidence', '查看证据'],
  ['accepted', 'evidence', '查看证据'],
  ['ignored', 'evidence', '查看证据'],
  ['done', 'evidence', '查看证据'],
]

describe('homeCardPrimaryAction', () => {
  it.each(HOME_CASES)('status=%s → %s (%s)', (status, kind, label) => {
    const action = homeCardPrimaryAction({ status })
    expect(action).not.toBeNull()
    expect(action!.kind).toBe(kind)
    expect(action!.label).toBe(label)
    expect(action!.enabled).toBe(true)
  })

  it('failed execution outranks its raw status (failure combo state)', () => {
    const action = homeCardPrimaryAction({ status: 'in_progress', execution_result: 'Failure' })
    expect(action!.kind).toBe('confirm')
  })

  it('returns an actionable reason in Chinese for every mapped status', () => {
    for (const [status] of HOME_CASES) {
      const action = homeCardPrimaryAction({ status })
      expect(action!.reason).toBeTruthy()
      // eslint-disable-next-line no-control-regex
      expect(action!.reason!).toMatch(/[\u4e00-\u9fa5]/)
    }
  })

  it('refuses to guess a primary action for unmapped statuses (fail-closed)', () => {
    expect(homeCardPrimaryAction({ status: 'wild_unknown_state' })).toBeNull()
  })

  it('only ever produces one of the six agreed action kinds with agreed labels', () => {
    const allowedKinds = new Set(['start', 'progress', 'confirm', 'evidence', 'open_original', 'resume_summary'])
    const allowedLabels = new Set(['开始处理', '查看进度', '确认处理', '查看证据', '打开原会话', '摘要续接'])
    for (const [status] of HOME_CASES) {
      const action = homeCardPrimaryAction({ status })!
      expect(allowedKinds.has(action.kind)).toBe(true)
      expect(allowedLabels.has(action.label)).toBe(true)
    }
  })
})

describe('conversationPrimaryAction', () => {
  it('original resume with a stable official session_id opens the original session', () => {
    const action = conversationPrimaryAction({ resume_mode: 'original', session_id: '20260827_122006_568068' })
    expect(action.kind).toBe('open_original')
    expect(action.label).toBe('打开原会话')
    expect(action.enabled).toBe(true)
  })

  it('fails closed to summary resume when session_id is missing or blank', () => {
    for (const session_id of [null, undefined, '', '   ']) {
      const action = conversationPrimaryAction({ resume_mode: 'original', session_id: session_id as string | null | undefined })
      expect(action.kind).toBe('resume_summary')
      expect(action.label).toBe('摘要续接')
    }
  })

  it('summary mode stays summary even when a session_id happens to exist', () => {
    const action = conversationPrimaryAction({ resume_mode: 'summary', session_id: 'stored-1' })
    expect(action.kind).toBe('resume_summary')
    expect(action.label).toBe('摘要续接')
  })
})
