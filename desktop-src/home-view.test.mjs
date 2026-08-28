import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

/**
 * Task 3 — 默认首页替换的源码级契约（沿用 brief.test.mjs 同款基建约束）。
 * 契约来源：workbench-v2-ui-state-contract.md L9-25/L49-50 + CoderX §6.3。
 *
 * 2026-08-27 结构纠偏：HomeView/区域组件/空状态已从 board.tsx 抽取至
 * home.tsx（纯重构）。契约锚定行为而非文件布局——首页断言读 home.tsx，
 * 跨文件语义断言读 ui = board + home 合并源码。
 */

const root = new URL('.', import.meta.url)
const src = name => readFileSync(new URL(name, root), 'utf8')
const board = src('board.tsx')
const home = src('home.tsx')
const model = src('home-model.ts')
const ui = board + home

test('default page renders from buildHomeModel, not its own sections filter', () => {
  // 首页组件已抽取到 home.tsx；board.tsx 只负责引入与挂载
  assert.match(home, /function HomeView/)
  assert.match(board, /<HomeView\b/)
  assert.match(board, /from '\.\/home'/)
  assert.match(home, /buildHomeModel\(board\)/)
  // TodayView 的旧口径（自行 filter task 分区）不得复活
  assert.doesNotMatch(ui, /sections\.find\(s => s\.key === 'task'\)\?\.files/)
})

test('tagline and three main regions render under wide screens', () => {
  assert.match(home, /手机收进来的东西，在这里审核、继续、沉淀。/)
  assert.match(home, /lg:grid-cols-3/)
  for (const label of ['今日', '待审核', '需要注意']) {
    assert.ok(home.includes(`'${label}'`), `region label missing: ${label}`)
  }
})

test('recent completed sits below main regions as its own region', () => {
  assert.match(home, /最近完成/)
  assert.match(model, /'recent'/)
})

test('legacy board/table moves behind a secondary entry, implementations intact', () => {
  assert.match(ui, /旧版数据/)
  // 实现与数据未删：旧视图组件仍被引用渲染
  assert.match(board, /<TableBoardView /)
  assert.match(board, /<WbSectionView\b/)
})

test('each region owns a distinct empty state; loading/unreachable stay separate', () => {
  assert.match(home, /HOME_EMPTY_HINTS/)
  for (const hint of ['今天没有安排', '待审核是空的', '没有需要你拍板或修复的事情', '还没有完成记录']) {
    assert.ok(home.includes(hint), `empty hint missing: ${hint}`)
  }
  assert.doesNotMatch(home, /后端不可达<\/div>\s*;\s*return\s+null/) // 全页级单一失败反馈不复用为区域空态
  assert.match(home, /后端暂时不可达/)
  assert.match(home, /链路健康检查中…/)
})

test('unknown status surfaces a fail-closed banner instead of silent drop', () => {
  assert.match(model, /contractErrors\.push/)
  assert.match(home, /状态无法识别/)
})
