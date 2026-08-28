import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

/**
 * Task 4 — Explainable Today briefing & unified counts (frontend contract).
 *
 * 项目测试基建事实：desktop-src 只有 static contract tests（无 jsdom/
 * Testing Library —— 插件在 Hermes 宿主内渲染）。node:fs 读取源码的契约
 * 测试必须放 .mjs（layout-regression.test.mjs 同款），因为 tsconfig 无
 * @types/node；vitest include 只收 name.test.ts/tsx 形式（不含 .mjs），
 * .mjs 由 CI 用 `node --test` 独立执行（vitest.config.mjs 注释已声明该约定）。
 *
 * 2026-08-27 结构纠偏（纯重构）：首页组件自 board.tsx 抽取到 home.tsx。
 * 契约锚定行为而非文件布局——UI 文案断言统一读 `ui = board + home`
 * （合并后的生产源码），board/home 各自的内部归属由组件边界保证。
 *
 * 契约（对应 WORKBENCH 计划 Task 4 "Interfaces"）：
 *  - Today 卡：人类可读中文 reason 作为主文案，e 依据收进「查看依据」；
 *  - 内部 rule id 不作为用户主文案渲染（只存在于 api 类型）；
 *  - Today / Board / Table 三处计数共用同一 board payload 数据源；
 *  - 聚合分区按 entry_count 计数，空壳（entry_count===0）不渲染单卡
 *    （phantom 待回看 = 0）。
 */

const root = new URL('.', import.meta.url)
const board = readFileSync(new URL('board.tsx', root), 'utf8')
const home = readFileSync(new URL('home.tsx', root), 'utf8')
const views = readFileSync(new URL('views.tsx', root), 'utf8')
const api = readFileSync(new URL('api.ts', root), 'utf8')
const ui = board + home

test('brief cards render the human-readable Chinese reason as main copy', () => {
  assert.match(home, /card\.title/)
  assert.match(home, /\{card\.reason\}/)
})

test('internal rule id stays out of the user-facing main copy', () => {
  // rule 只在 api 接口类型存在，不作为 UI 主文案被渲染
  assert.match(api, /rule: string/)
  // 生产源码主文案区不得直接渲染 card.rule / c.rule
  assert.doesNotMatch(ui, /<div[^>]*>\s*\{card\.rule\}/)
  assert.doesNotMatch(ui, /<div[^>]*>\s*\{c\.rule\}/)
})

test('literal evidence lives under an expandable 查看依据 list', () => {
  assert.match(home, /查看依据/)
  assert.match(home, /card\.evidence\.map/)
})

test('cards are labelled 规则建议 (deterministic, not agent opinion)', () => {
  assert.match(ui, /规则建议/)
})

test('Board and Table count from the same board.sections payload', () => {
  // section.files.reduce 计数在留守 board 的看板组件内；Table 实现在 views
  assert.match(board, /section\.files\.reduce/)
  assert.match(views, /board\.sections/)
  assert.match(views, /section\.files/)
})

test('aggregate sections count by entry_count; empty shell renders no phantom card', () => {
  assert.match(board, /entry_count/)
  assert.match(board, /entry_count === 0/)
})

test('default home derives all counts through the single buildHomeModel projection', () => {
  // Task 2/3 取代旧口径：视图不得各自 sections.find(...)=>files；
  // 统一由 home-model.buildHomeModel 投影（本文件上一版断言的意图「同一数据源」
  // 由唯一投影函数更强地满足）。
  assert.match(home, /buildHomeModel\(board\)/)
  assert.doesNotMatch(ui, /sections\.find\(s => s\.key === 'task'\)/)
})
