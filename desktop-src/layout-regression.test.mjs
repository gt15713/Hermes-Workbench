import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const root = new URL('.', import.meta.url)
const board = readFileSync(new URL('board.tsx', root), 'utf8')
const api = readFileSync(new URL('api.ts', root), 'utf8')
const css = readFileSync(new URL('workbench.css', root), 'utf8')
// P0-B：宿主样式仅本机/HERMES_HOME 可用时校验；开源 CI 缺省则跳过该项
const hermesStylesPath = process.env.HERMES_HOME
  ? `${process.env.HERMES_HOME}/hermes-agent/apps/desktop/src/styles.css`
  : null
let hermesStyles = null
if (hermesStylesPath) {
  try {
    hermesStyles = readFileSync(hermesStylesPath, 'utf8')
  } catch {
    hermesStyles = null
  }
}

test('collapsed rails remain available for manual collapse', () => {
  assert.match(board, /wb-section--collapsed/)
  assert.match(board, /writing-mode:vertical-rl|\[writing-mode:vertical-rl\]/)
  assert.match(css, /\.wb-section--collapsed/)
  assert.match(css, /\.wb-section--collapsed[\s\S]*background/)
  assert.match(css, /\.wb-section--collapsed[\s\S]*border/)
})

test('expanded board columns share one fixed width (16rem, in workbench.css)', () => {
  // 宿主 Tailwind 无 w-[16rem]/min-w-[14rem]/max-w-[18rem] 规则（已核验 dist CSS），
  // 等宽必须写在插件自有 CSS 中，否则类为死类、列宽回到内容自适应。
  assert.match(css, /\.wb-section\s*\{[\s\S]*?width:\s*16rem/)
  assert.match(css, /\.wb-section\s*\{[\s\S]*?min-width:\s*16rem/)
  assert.match(css, /\.wb-section\s*\{[\s\S]*?max-width:\s*16rem/)
  assert.doesNotMatch(board, /wb-section flex[\s\S]*?w-\[16rem\]/)
})

test('all board sections default expanded (equal widths, no auto-collapse)', () => {
  assert.match(board, /collapsedOverride \?\? false/)
  assert.match(api, /COLLAPSED_KEY = 'wbCollapsedSections\.v2'/)
  assert.match(api, /persist\(\$collapsedSections, COLLAPSED_KEY, \{\}\)/)
})

test('dialogs use plugin-owned width class (host lacks w-[min(52rem,94vw)])', () => {
  assert.match(css, /\.wb-dialog\s*\{[\s\S]*?width:\s*min\(52rem, 94vw\)/)
  assert.match(board, /DialogContent className="wb-dialog"/)
  assert.doesNotMatch(board, /w-\[min\(52rem,94vw\)\]/)
})

test('card action menu trigger is always visible (host lacks group-hover:block)', () => {
  assert.match(board, /data-wb-menu[\s\S]*?absolute right-1 top-1 block rounded/)
  assert.doesNotMatch(board, /group-hover:block/)
  assert.doesNotMatch(board, /hidden rounded p-0\.5/)
})

test('card action menu is an overlay that can clear the Cronjobs pane', () => {
  assert.match(board, /data-wb-menu-overlay/)
  assert.match(board, /position:\s*'fixed'|position:\s*`fixed`|fixed/)
  assert.match(css, /\.wb-menu-overlay/)
})

test('health popover follows Workbench theming and closes on outside pointerdown', () => {
  assert.match(board, /data-wb-health/)
  assert.match(board, /closest\('\[data-wb-health\]'\)/)
  assert.match(board, /setShowHealthDetails\(false\)/)
  assert.match(css, /\.wb-health-popover\s*\{[\s\S]*?background-color:\s*var\(--ui-bg-elevated\)/)
  assert.match(css, /\.wb-health-popover\s*\{[\s\S]*?border:/)
  assert.doesNotMatch(board, /bg-\(--ui-bg-primary\).*链路健康详情/)
})

test('detail and history reads use the host-native bounded request contract', () => {
  assert.match(api, /fetchFile[\s\S]*?timeoutMs:\s*15_000/)
  assert.match(api, /fetchRecentEvents[\s\S]*?timeoutMs:\s*15_000/)
  assert.doesNotMatch(api, /withTimeout/)
})

test('today suggestions explain their deterministic basis without implying an agent decision', () => {
  assert.match(board, /✨ 规则建议/)
  assert.match(board, /依据任务状态、截止日期和最近结果生成/)
  assert.doesNotMatch(board, /✨ Agent 建议/)
})

test('Hermes session composer contract remains stable', { skip: !hermesStyles }, () => {
  assert.match(hermesStyles, /--composer-width:\s*100%/)
  assert.match(hermesStyles, /--chat-min-width:\s*28rem/)
})
