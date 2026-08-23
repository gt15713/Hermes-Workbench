import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    // P0-B：layout-regression.test.mjs 用 node:test 风格，vitest 无法收集；
    // 排除 .mjs，由 CI 单独 `node --test` 执行。
    include: ['**/*.test.{ts,tsx}'],
  },
})
