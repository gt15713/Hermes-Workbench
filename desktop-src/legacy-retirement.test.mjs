import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const root = new URL('.', import.meta.url)
const board = readFileSync(new URL('board.tsx', root), 'utf8')
const api = readFileSync(new URL('api.ts', root), 'utf8')

test('legacy access is demoted outside the primary Home/messages navigation', () => {
  const primary = board.match(/<div[^>]*data-wb-primary-nav[^>]*>([\s\S]*?)<\/div>/)?.[1]
  assert.ok(primary, 'primary navigation must have a stable contract marker')
  assert.match(primary, /首页/)
  assert.match(primary, /消息任务/)
  assert.doesNotMatch(primary, /旧版数据|完整数据（兼容）/)
})

test('an explicit compatibility entry preserves access without claiming retirement', () => {
  assert.match(board, /data-wb-legacy-entry/)
  assert.match(board, /完整数据（兼容）/)
  assert.match(board, /兼容入口：保留完整列表、项目分组、批量操作与异常状态修复/)
  assert.match(board, /data-wb-legacy-entry[\s\S]*?setShowLegacy\(true\)/)
})

test('legacy render branch and shared board data remain intact', () => {
  assert.match(board, /showLegacy/)
  assert.match(board, /<TableBoardView /)
  assert.match(board, /<WbSectionView\b/)
  assert.match(api, /fetchBoard = \(\) => call<WbBoard>\('\/board'\)/)
})