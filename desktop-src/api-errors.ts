/**
 * P0（2026-08-27 目视批次）：底层 API 异常 → 人话文案。
 *
 * 背景：桌面插件 API 走 hermes:api IPC 桥；后端插件路由是 Gateway 进程
 * 启动时挂载的（Python 无热载）。前端新增端点在用户重启桌面端之前必然
 * 405/404 —— 这类「版本代差」必须翻成可行动的中文，而不是把
 * "Error invoking remote method 'hermes:api': 405 Method Not Allowed"
 * 原样甩给用户。
 */

const RULES: Array<{ test: RegExp, text: string }> = [
  {
    // 抽取钩子未注入：本会话后端没有配置抓取器（预期行为，非故障）
    test: /extraction hook unavailable/i,
    text: '这条内容目前无法自动抓取正文——本会话还没有配置抓取器。可以先「仅归档」保留原文，或重启桌面端后由 Agent 链路补抓。',
  },
  {
    // 后端还没有这个路由 = 插件前后端版本代差，需要整端重启让 Python 侧重挂
    test: /\b(40[45])\b|Method Not Allowed|Not Found/i,
    text: '后端还没有这条功能入口（本次会话的后端早于最新构建）。重启一次 Hermes 桌面端就会生效；数据不受影响。',
  },
  {
    test: /Failed to fetch|NetworkError|ERR_NETWORK|ECONNREFUSED|fetch failed/i,
    text: '连不上工作台后端——请确认 Hermes 正在运行，稍后重试。',
  },
  {
    test: /\b(40[13])\b|Unauthorized|Forbidden|permission/i,
    text: '后端拒绝了这次操作（权限或登录态问题）。稍后重试，若持续出现请反馈。',
  },
  {
    test: /\b50[0-4]\b|Internal Server Error|timeout|timed out/i,
    text: '后端处理时出错了。请稍后重试；反复出现请带上这条提示反馈。',
  },
]

/** 把任意抛出的错误翻译成中文人话；已是人话的消息原样放行。 */
export function friendlyApiError(error: unknown): string {
  const raw = error instanceof Error ? error.message : String(error ?? '')
  if (!raw) return '操作失败了，请稍后重试'
  // 已经是人话（不含内部痕迹）就直接放行，避免二次包装
  const looksInternal =
    /Error invoking remote method|TypeError|Error:\s*\d{3}|^\d{3}:\s|^[A-Z_]{6,}$|\bE_[A-Z]+\b|^[a-z_]+(\s[a-z_]+)*$/.test(raw)
  if (!looksInternal) return raw
  for (const rule of RULES) {
    if (rule.test.test(raw)) return rule.text
  }
  return '操作没有成功。请稍后重试；若再次出现，请截图这条提示反馈。'
}
