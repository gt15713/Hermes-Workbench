# Workbench 上线前差异审查

审查范围：`origin/main@70348c8..669fe53`  
结论：**APPROVE**（未发现未关闭的 Blocker / Important）

## 执行摘要

| 严重度 | 未关闭 | 已关闭 |
| --- | ---: | ---: |
| Critical | 0 | 0 |
| High / Blocker | 0 | 2 |
| Important | 0 | 3 |
| Minor | 1 | 3 |

唯一未关闭项是上游 Starlette `TestClient` 的弃用警告，不影响当前功能与发布。

## 关键结论

- 生命周期：进行中任务的成功、失败、无终态结果分别进入“应归档”“需恢复”“继续观察”，不会再把成功或失败误写成无终态。
- 详情与历史：改用 Hermes 插件 REST 原生 `timeoutMs`，不再使用会遗留底层请求的 `Promise.race` 包装。已核验 Hermes 0.20.5 的 `PluginRestOptions`、`pluginRest` 转发和 Electron HTTP `req.setTimeout(...); req.destroy(...)` 实现。
- QQ 健康：普通群消息没有事件级运行证据时固定保持黄色，不再因源码能力声明误报绿色。
- 隐私：扫描覆盖 Windows 两种路径分隔符；tracked 文件不可读时失败关闭；扫描器自身不会自匹配。
- 构建：项目显式声明 `esbuild`，统一源码行尾和工作目录；独立克隆 `npm ci` 后的 bundle 与仓库产物 SHA-256 完全一致。
- UI：健康弹窗使用不透明的 Workbench 主题表面，点击外部可关闭；今日建议明确标为“规则建议”并说明依据。

## 影响面

- 后端：今日规则建议、QQ 分层健康状态、隐私发布门禁。
- 前端：任务详情和运行历史读取、今日页文案、健康弹窗。
- 发布：依赖锁、跨机器确定性构建、上线检查文档。
- 不修改 Hermes 核心配置或程序文件；运行时只使用 Hermes 官方插件 SDK 契约。

## 验证证据

- Python：353 passed。
- Vitest：10 passed。
- 布局契约：10 passed。
- TypeScript：通过。
- Ruff：通过。
- 隐私门禁：clean。
- 维护任务：`--dry-run` 正常；日报 `--data` 输出结构正确。
- 独立克隆：`npm ci`、测试、类型检查、构建和 bundle 字节一致性均通过；npm audit 为 0 vulnerabilities。
- 实机 Hermes：Workbench 可加载；0 Pending / 22 Total 与后端一致；健康弹窗样式、分层状态和外部点击关闭已验证；Table 模式无虚假“待回看”任务。

## 方法与限制

审查结合完整 Git diff、调用链和影响面分析、测试、干净克隆、静态安全扫描及实机 UI 验证。QQ 普通群消息是否可由当前 Hermes 上游适配器接收，仍由事件级证据决定，因此界面保持黄色，而不是把上游未提供的能力伪装为已验证可用。
