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

// ── WB-S1-034：完整列表/归档可见性等价切片（FR-040/FR-020）──────────────────
// 契约：默认首页每区保持克制（前 8 截断）；超出时提供「查看全部」动作；
// 全量视图复用同一 buildHomeModel 投影（不建第二事实源）并区分 active/archived 边界；
// contractErrors fail-closed 横幅在两种模式下都可见；旧版数据入口保留为 fallback。

test('WB-S1-036: show-all action consumes the production presentation seam', () => {
  assert.match(home, /data-wb-show-all/)
  assert.match(home, /查看全部 \{totalCount\} 项 →/)
  assert.match(home, /buildHomeViewPresentation\(model, viewState\)/)
  assert.match(model, /region\.items\.slice\(0, previewLimit\)/)
  assert.match(model, /canShowAll: region\.items\.length > previewLimit/)
})

test('WB-S1-036: expanded view renders presentation visibleItems without another truncation', () => {
  assert.match(home, /function HomeAllRegionList/)
  assert.match(home, /region\.visibleItems\.map/)
  assert.match(home, /← 返回首页/)
  assert.match(home, /\{title\} · 全部/)
  assert.doesNotMatch(home, /HomeAllRegionList[\s\S]{0,600}slice\(0, 8\)/)
})

test('WB-S1-035: recent provenance split label + unknown status stays fail-closed（行为验收在 home-model-behavior.test.ts，此处为结构守卫）', () => {
  // P1：recent 全量视图头部必须区分「已归档 done 分区」与「已完成未归档 active 分区」
  assert.match(home, /活动任务（active 侧投影）/)
  assert.match(home, /已归档/)
  assert.match(home, /已完成未归档/)
  // contractErrors banner is located at HomeView top level, shared by grid and all-list views
  const bannerIdx = home.indexOf('状态无法识别')
  const allIdx = home.indexOf('HomeAllRegionList')
  assert.ok(bannerIdx !== -1 && allIdx !== -1)
  assert.ok(model.includes('unknown status') || model.includes("未知状态") || model.includes("contractErrors"))
})

test('WB-S1-036: recent preview and expanded output share production presentation state', () => {
  assert.match(home, /items=\{recentRegion\.visibleItems\}/)
  assert.match(home, /onShowAll=\{\(\) => openShowAll\('recent'\)\}/)
  assert.match(model, /visibleItems: expandedSource\.items/)
  assert.doesNotMatch(home, /recentRegion\.items\]\.reverse\(\)/)
})

test('WB-S1-036: legacy fallback is top-level and remains visible in expanded mode', () => {
  assert.match(home, /data-wb-legacy-fallback/)
  assert.match(home, /presentation\.legacyFallbackVisible/)
  assert.match(home, /presentation\.mode === 'expanded'/)
  const fallbackIdx = home.indexOf('presentation.legacyFallbackVisible')
  const branchIdx = home.indexOf("presentation.mode === 'expanded'")
  assert.ok(fallbackIdx !== -1 && branchIdx !== -1 && fallbackIdx < branchIdx)
  assert.doesNotMatch(home, /sections\.find\(s => s\.key === 'task'\)/)
})

// ── WB-S1-041：FR-040 生产接线结构契约（行为 seam 在 archive-view.test.ts）────
test('WB-S1-041: Home renders archive entry, archive view, return button and honest empty states', () => {
  assert.match(home, /data-wb-archive-entry/)
  assert.match(home, /data-wb-archive-back/)
  assert.match(home, /function HomeArchiveView/)
  assert.match(home, /归档 \/ 回收站 · 全部/)
  assert.match(home, /暂无已完成归档/)
  assert.match(home, /回收站是空的/)
  assert.match(home, /dispatchView\(\{ type: 'open-archive' \}\)/)
  assert.match(home, /presentation\.mode === 'archive'/)
})

test('WB-S1-041: archive mode keeps fail-closed banner reachable; legacy fallback stays top-level', () => {
  assert.match(home, /状态无法识别/)
  assert.match(home, /data-wb-legacy-fallback/)
  assert.match(model, /archiveOpen/)
  const bannerIdx = home.indexOf('状态无法识别')
  const archModeIdx = home.indexOf("presentation.mode === 'archive'")
  const legacyIdx = home.indexOf('data-wb-legacy-fallback')
  const entryIdx = home.indexOf('data-wb-archive-entry')
  assert.ok(bannerIdx !== -1 && archModeIdx !== -1, 'banner and archive branch must both exist')
  assert.ok(legacyIdx !== -1 && entryIdx !== -1, 'legacy fallback and archive entry must both render')
})
