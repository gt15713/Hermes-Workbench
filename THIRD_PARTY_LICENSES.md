# 第三方许可声明

## @hermes/plugin-sdk

- **来源**：Hermes Agent 桌面端内置（运行时宿主提供；`desktop/plugin.js` 构建时 external，不随本仓库分发）
- **许可类型**：MIT（Hermes Agent 仓库 LICENSE，Copyright (c) 2025 Nous Research）
- **核实日期**：2026-08-23
- **兼容性**：MIT ↔ MIT 兼容 ✅
- **说明**：SDK 源码位于 Hermes Agent `apps/desktop/src/sdk/`，随 Hermes 发行；本仓库仅声明宿主依赖，不复制其代码

## 前端运行时依赖

- `react` / `react/jsx-runtime`：由 Hermes 桌面端宿主提供（构建 external），MIT
- 本仓库 `desktop-src/package.json` 开发依赖（typescript/vitest/esbuild 等）：MIT/ISC，仅构建期使用，不进入发行产物

## 后端依赖

- `fastapi` / `yaml`（PyYAML）：MIT，由 Hermes 宿主环境提供或用户安装

> 完整依赖树核验（`npm ls --all --json` / `pip freeze`）建议在每次 release 前更新本文件。
