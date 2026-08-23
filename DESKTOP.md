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

构建器默认从 `HERMES_HOME/hermes-agent/node_modules/esbuild` 获取；如源码仓库迁移，先设置 `HERMES_AGENT_SOURCE` 指向 Hermes Agent 仓库根目录。

运行包只允许三个 Hermes 官方运行时导入：`@hermes/plugin-sdk`、`react`、`react/jsx-runtime`。构建脚本会在输出后强制检查。

回退期内，原桌面源码保留在 Hermes Agent 仓库中，但不应同时作为内置插件加载；Hermes 的加载规则会让同 ID 内置版覆盖磁盘版。
