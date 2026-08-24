# Workbench Desktop 交付说明

Workbench 采用 Hermes 官方统一插件布局：Python 后端与桌面前端同属 `plugins/workbench-view`。

- `desktop-src/`：桌面前端可维护源码，不得直接被 Hermes 加载。
- `desktop/plugin.js`：由构建脚本生成的 ESM 运行文件，Hermes 从统一插件入口加载。
- `desktop/build-info.json`：构建时间、构建器版本、输出哈希和外部依赖白名单。
- `build-desktop.mjs`：可重复构建与静态校验入口。

构建命令：

```powershell
node build-desktop.mjs
```

开发依赖由 `desktop-src/package-lock.json` 锁定。首次构建先安装依赖：

```powershell
cd desktop-src
npm ci
cd ..
node build-desktop.mjs
```

构建器优先使用 `HERMES_AGENT_SOURCE` 或 Hermes 源码树中已有的 `esbuild`，独立克隆环境则使用 `desktop-src/node_modules/esbuild`。因此 CI 和普通贡献者不依赖本机 Hermes 源码也能完成可重复构建。

运行包只允许三个 Hermes 官方运行时导入：`@hermes/plugin-sdk`、`react`、`react/jsx-runtime`。构建脚本会在输出后强制检查。

回退期内，原桌面源码保留在 Hermes Agent 仓库中，但不应同时作为内置插件加载；Hermes 的加载规则会让同 ID 内置版覆盖磁盘版。
