import { Codicon, host } from '@hermes/plugin-sdk'
import { useEffect, useRef, useState } from 'react'

import { writeWorkbenchClipboard } from './clipboard'
import { conversationPrimaryAction } from './card-action'
import type { WbConversationRef } from './types'

const platformLabel = (platform: string) => ({ qq: 'QQ', weixin: '微信', messaging: '消息平台' })[platform] ?? platform

function ConversationActionButton({ item }: { item: WbConversationRef }) {
  // Task 4（2026-08-27）：主操作统一映射——original+稳定 session_id 才直达，否则摘要续接
  const primary = conversationPrimaryAction(item)
  const canOpen = primary.kind === 'open_original'
  const [copyStatus, setCopyStatus] = useState<'idle' | 'copied' | 'error'>('idle')
  const resetTimer = useRef<number | null>(null)

  useEffect(() => () => {
    if (resetTimer.current !== null) window.clearTimeout(resetTimer.current)
  }, [])

  const handleClick = async () => {
    if (canOpen) {
      host.navigate('/' + encodeURIComponent(item.session_id!))
      return
    }
    try {
      await writeWorkbenchClipboard(`继续处理任务 ${item.task_id}：${item.summary}`)
      setCopyStatus('copied')
    } catch {
      setCopyStatus('error')
    }
    if (resetTimer.current !== null) window.clearTimeout(resetTimer.current)
    resetTimer.current = window.setTimeout(() => setCopyStatus('idle'), 1800)
  }

  const label = canOpen
    ? primary.label
    : copyStatus === 'copied'
      ? '已复制'
      : copyStatus === 'error'
        ? '复制失败'
        : primary.label

  return <button type="button" className="rounded border border-(--ui-stroke-secondary) px-2 py-1 text-[0.75rem] text-(--ui-text-secondary) hover:bg-(--ui-stroke-secondary)" onClick={() => { void handleClick() }} title={canOpen ? '跳转到 Hermes 原会话' : copyStatus === 'error' ? '剪贴板不可用，请稍后重试' : '复制续接摘要，可粘贴到任意新会话'}>{label}</button>
}

export function ConversationIndexView({ items, loading, error }: { items: WbConversationRef[]; loading: boolean; error: unknown }) {
  if (loading) return <div className="p-6 text-sm text-(--ui-text-tertiary)">正在加载消息任务…</div>
  if (error) return <div className="p-6 text-sm text-red-400">消息任务加载失败，请稍后重试。</div>
  if (!items.length) return <div className="flex flex-1 flex-col items-center justify-center gap-2 p-8 text-center"><Codicon name="comment-discussion" size="1.5rem" /><div className="text-sm font-medium">暂无消息任务</div><div className="max-w-lg text-[0.8125rem] text-(--ui-text-tertiary)">从已授权的 QQ 或微信发送 /wb 任务后，会在这里生成脱敏索引。</div></div>

  return <div className="flex flex-1 flex-col gap-2 overflow-y-auto p-3">
    <div className="mb-1 text-[0.75rem] text-(--ui-text-tertiary)">仅记录授权后创建的任务；原始用户与消息标识不会写入 Workbench。</div>
    {items.map(item => {
      return <article key={item.ref_id} className="rounded-lg border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) p-3"><div className="flex items-start gap-3">
        <span className="rounded bg-(--ui-stroke-secondary) px-2 py-0.5 text-[0.75rem] text-(--ui-text-secondary)">{platformLabel(item.platform)}</span>
        <div className="min-w-0 flex-1"><div className="truncate text-sm font-medium">{item.summary || '未命名消息任务'}</div><div className="mt-1 flex flex-wrap gap-x-3 text-[0.75rem] text-(--ui-text-tertiary)"><span>任务 {item.task_id}</span><span>{item.status}</span><span>{item.updated_at.replace('T', ' ')}</span></div></div>
        <ConversationActionButton item={item} />
      </div></article>
    })}
  </div>
}
