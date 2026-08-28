/**
 * Task 4 — 一张卡一个主操作（Primary Action，单源统一映射）。
 *
 * 设计约束（CoderX §4）：
 * - 首页卡片只渲染一个主按钮；重试/复制路径/归档/诊断等留在抽屉（drawer）。
 * - 映射表外状态 → null（fail-closed，不猜按钮、不虚设待审核）。
 * - 消息任务：只有 resume_mode=original 且存在稳定官方 session_id 才能打开原会话；
 *   否则一律摘要续接。绝不根据标题/时间猜测 session。
 * - 中文 reason 为主文案（为什么/依据），内部 rule id 不上 UI。
 * - 平台来源用文字/图标表达，不用状态色承载语义。
 *
 * 状态词表与 home-model.ts 同源（HOME_STATUS_VOCAB），禁止第二词表。
 */
import { HOME_STATUS_VOCAB, isFailedExecution } from './home-model'

export type PrimaryActionKind =
  | 'start'
  | 'progress'
  | 'confirm'
  | 'evidence'
  | 'open_original'
  | 'resume_summary'

export interface PrimaryAction {
  kind: PrimaryActionKind
  label: '开始处理' | '查看进度' | '确认处理' | '查看证据' | '打开原会话' | '摘要续接'
  enabled: boolean
  reason?: string
}

/** 首页主操作的输入：任意 WbCard 形状的子集（含 execution_result 组合态）。 */
export type PrimaryActionCard = {
  status?: string
  execution_result?: null | string
}

const STATUS_PRIMARY: Record<
  'inbox' | 'active' | 'attention' | 'completed',
  { kind: PrimaryActionKind; label: PrimaryAction['label']; reason: string }
> = {
  inbox: { kind: 'start', label: '开始处理', reason: '新进件还没有开过工——从这一步启动它' },
  active: { kind: 'progress', label: '查看进度', reason: '正在执行中，看最新进展' },
  attention: { kind: 'confirm', label: '确认处理', reason: '需要你拍板或修复后才能继续' },
  completed: { kind: 'evidence', label: '查看证据', reason: '已完结，可核对产物与沉淀记录' },
}

/**
 * 统一主操作映射（含失败组合态覆盖）。
 * 返回 null = 表外状态，UI 必须走 fail-closed 提示而不是猜一个按钮。
 */
export function homeCardPrimaryAction(card: PrimaryActionCard): PrimaryAction | null {
  const status = (card.status || '').trim().toLowerCase()

  // 失败组合态优先于原始状态（execution_result=failure 实证自 auto_archive/plugin_api L1103）
  if (isFailedExecution({ execution_result: card.execution_result })) {
    return { ...STATUS_PRIMARY.attention, enabled: true }
  }
  if (HOME_STATUS_VOCAB.inbox.has(status) || status === '') {
    return { ...STATUS_PRIMARY.inbox, enabled: true }
  }
  if (HOME_STATUS_VOCAB.active.has(status)) {
    return { ...STATUS_PRIMARY.active, enabled: true }
  }
  if (HOME_STATUS_VOCAB.attention.has(status)) {
    return { ...STATUS_PRIMARY.attention, enabled: true }
  }
  // completed 族中 done 已由完成态归类；abandoned/cleared 属终态但不承诺「证据」，
  // 保持 fail-closed（映射表外），由调用方以次要菜单兜底。
  if (
    status === 'completed' ||
    status === 'ingested' ||
    status === 'accepted' ||
    status === 'ignored' ||
    status === 'done'
  ) {
    return { ...STATUS_PRIMARY.completed, enabled: true }
  }
  return null
}

/** 消息任务行的主操作输入（WbConversationRef 子集）。 */
export type ConversationActionRef = {
  resume_mode: 'summary' | 'original'
  session_id?: string | null
}

/**
 * 会话任务主操作：
 * resume_mode=original 且 session_id 非空白 → 打开原会话；
 * 其余全部摘要续接（fail-closed；session 身份不可信时不给直达入口）。
 */
export function conversationPrimaryAction(ref: ConversationActionRef): PrimaryAction {
  const sessionId = (ref.session_id || '').trim()
  if (ref.resume_mode === 'original' && sessionId) {
    return { kind: 'open_original', label: '打开原会话', enabled: true, reason: `官方会话 ${sessionId.slice(0, 12)}… 可直达` }
  }
  return { kind: 'resume_summary', label: '摘要续接', enabled: true, reason: '无稳定原会话引用，用摘要继续最稳' }
}
