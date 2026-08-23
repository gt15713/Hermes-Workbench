import { expect, it } from 'vitest'

import { suggestTags, tagName } from './tag-suggest'

function eq(actual: unknown, expected: unknown, msg: string) {
  expect(actual, msg).toEqual(expected)
}

it('生成稳定、分置信度且有上限的标签建议', () => {
const known = ['#project:架构全景', '#教程', '#视频', '#心理学', '#a', '#阻塞', '#心理侧写']

// 1. 标题命中 → 高置信
eq(suggestTags('架构全景 批次任务', '', known).tags, ['#project:架构全景'], '标题命中 project 标签高置信')
// 2. 正文命中 ≥3 字符 → 高置信；<3 字符且不在标题 → 低置信
eq(suggestTags('任务', '看一个心理学视频教程', known).tags, ['#心理学'], '正文命中≥3字符高置信')
eq(suggestTags('任务', '看一个心理学视频教程', known).low, ['#教程', '#视频'], '正文命中短标签低置信（按 knownTags 序）')
// 3. 低置信：短标签且不在标题（#a 跳过；#阻塞 命中正文但 2 字符 → low）
eq(suggestTags('某任务', '阻塞了', known).low, ['#阻塞'], '短标签低置信文本形态')
eq(suggestTags('某任务', '阻塞了', known).tags, [], '低置信不进 chips')
// 4. 无命中 → 空
eq(suggestTags('无关标题', '无关内容', known), { tags: [], low: [] }, '无命中空建议')
// 5. 去重 + 上限
const many = ['#p1', '#p2', '#p3', '#p4', '#p5', '#p6', '#p7', '#p8']
eq(suggestTags('p1 p2 p3 p4 p5 p6 p7 p8 标题', '', many).tags.length, 5, '高置信上限 5')
// 6. tagName 去前缀
eq(tagName('#project:架构全景'), '架构全景', 'tagName 去 project 前缀')
eq(tagName('#教程'), '教程', 'tagName 去 #')
// 7. 标题命中短标签（≥2 但 <3 且在标题）→ 高置信
eq(suggestTags('阻塞了', '', known).tags, ['#阻塞'], '标题命中短标签高置信')
})
