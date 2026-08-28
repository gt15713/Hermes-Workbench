import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

/**
 * P0（2026-08-27 目视批次）— drawer 源码级契约（沿用 brief.test.mjs 同款基建约束）。
 * 1) drawer 内禁止 window.confirm（bundled 环境 native 对话框被吞，
 *    「沉淀弹窗没渲染」根因），必须走自绘确认；
 * 2) 抽屉浮层层级必须高于右侧停靠面板（wb-menu-overlay=10020 同款约束）；
 * 3) 三步回执步骤必须带显式中状态徽标（仅色点不可辨）。
 */

const src = readFileSync(new URL('drawer.tsx', import.meta.url), 'utf8')

test('drawer never invokes window.confirm (native dialogs are swallowed in bundled env)', () => {
  // 只匹配真实调用（window.confirm( ），注释里的字样不算违规
  assert.ok(!/window\.confirm\s*\(/.test(src), 'window.confirm(...) call must not appear in drawer.tsx')
})

test('drawer renders self-drawn sink confirmation with explicit two buttons', () => {
  assert.ok(src.includes('确认沉淀'), 'missing 确认沉淀 button')
  assert.ok(src.includes('取消'), 'missing 取消 button')
})

test('drawer uses full-bleed .wb-drawer (user decision 2026-08-27: both tabs fill the content area)', () => {
  assert.ok(src.includes('wb-drawer'), 'drawer must use .wb-drawer class')
  const css = readFileSync(new URL('./workbench.css', import.meta.url), 'utf8')
  assert.match(css, /\.wb-drawer\s*\{[^}]*position:\s*absolute/, 'css must anchor drawer absolute')
  assert.match(css, /\.wb-drawer\s*\{[^}]*width:\s*100%/, 'drawer must be full width (user wants both tabs to fill)')
  assert.match(css, /\.wb-drawer\s*\{[^}]*left:\s*0/, 'drawer must span from left edge too')
})

test('receipt steps expose explicit chinese state badges (已完成/进行中/已失败)', () => {
  // 用户拍板（2026-08-27）：胶囊徽标全部取消 → 纯文本符号前缀 + inline style
  for (const sym of ['✔', '▶', '✖', '⊘', '○']) {
    assert.ok(src.includes(sym), `missing state symbol ${sym}`)
  }
  assert.ok(!src.includes('wb-badge'), 'badge classes must be gone')
  // 错误详情 inline 上色（不依赖 tailwind）
  assert.match(src, /step\.state === 'error'\s*\?\s*\{ color: 'var\(--ui-red\)'/, 'error detail must color via inline style')
})
