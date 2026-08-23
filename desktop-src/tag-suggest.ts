/**
 * C2（P1-4）：标签建议逻辑（纯函数，零依赖）。
 *
 * 选型结论：前端轻量规则（关键词匹配现有标签库）——不扩 /brief（职责混）、
 * 不调 LLM（慢/贵/禁新通道）；即时、确定性、可测。
 *
 * 规则：
 *  - hay = title + content 小写全文；标签名（去 #project: 前缀 / 去 #）长度 <2 跳过（空泛词）
 *  - 命中且（标签名 ≥3 字符 或 命中标题）→ 高置信（chips）
 *  - 命中但标签名 <3 且不在标题 → 低置信（文本「建议标签：xxx（可确认）」）
 *  - 去重，高置信 ≤5 / 低置信 ≤3
 *  - 无命中 → { tags: [], low: [] }（前端无 chips 不阻塞）
 */

export interface TagSuggestion {
  /** 高置信建议（chips，点选写入） */
  tags: string[]
  /** 低置信建议（文本形态，可确认） */
  low: string[]
}

export function tagName(tag: string): string {
  let n = tag.startsWith('#project:') ? tag.slice('#project:'.length) : tag
  if (n.startsWith('#')) n = n.slice(1)
  return n.trim()
}

export function suggestTags(title: string, content: string, knownTags: string[]): TagSuggestion {
  const hay = `${title}\n${content}`.toLowerCase()
  const titleLower = title.toLowerCase()
  const high: string[] = []
  const low: string[] = []
  const seen = new Set<string>()

  for (const tag of knownTags) {
    const name = tagName(tag)
    if (name.length < 2) continue
    if (seen.has(name)) continue
    seen.add(name)
    if (!hay.includes(name.toLowerCase())) continue
    const inTitle = titleLower.includes(name.toLowerCase())
    if (name.length >= 3 || inTitle) high.push(tag)
    else low.push(tag)
  }

  return { tags: high.slice(0, 5), low: low.slice(0, 3) }
}
