# Security Policy

Hermes Workbench 处理 QQ 消息与本地文件，安全边界如下。

## 支持版本

| 版本 | 安全更新 |
|---|---|
| `main` | 支持 |
| 最新 GitHub Release | 支持 |
| 更早的 Alpha / 历史提交 | 不保证 |

安全修复会优先进入 `main`，必要时再发布新的 Alpha。报告问题时请提供 Hermes 版本、
Workbench 版本或提交号，以及操作系统；不要附带真实敏感数据。

## 隐私红线

- **不入库**：token、QQ 群 openid、个人路径、凭据——只存在于用户配置
  （`workbench-config.json`，.gitignore）与运行态文件
- **运行时产物**：`workbench.db` / `scheduler-state.json` / `scheduler.lock`
  含本地数据，禁止上传任何远端
- **日志**：入站 hook 只记平台名与触发信号，**不记录消息内容**
- **测试与文档**：只能使用中性示例路径与虚构 ID，不复制真实配置作为 fixture

## 路径安全

- 所有文件操作经分区白名单 + root 前缀校验（防路径穿越）
- 分区名禁止路径分隔符；自定义分区受白名单约束

## 投递

- QQ 投递走 `hermes send`（官方 REST，宿主凭据），插件不持有凭据
- 投递目标未配置时显式报错（`DELIVERY-UNCONFIGURED`），不静默

## 宿主与上游边界

- Workbench 使用 Hermes 官方插件 SDK、消息适配器和 `hermes send`，不管理宿主凭据
- Hermes 核心程序、QQ 开放平台权限和上游适配器漏洞应同时报告给对应上游
- QQ 平台声明的授权能力不等于 Workbench 已收到事件；健康状态以运行证据为准
- 插件不应要求用户长期修改 Hermes 核心源码或安全设置

## 可靠性边界

- 定时任务随 Hermes 桌面进程存活；进程未运行时任务不执行，重启后按
  `catch_up_hours`（默认 6h）补跑错过的日报/提醒/维护

## 私密报告漏洞

**不要为尚未修复的安全漏洞创建公开 Issue。**

请使用仓库的 [Private vulnerability reporting](https://github.com/gt15713/Hermes-Workbench/security/advisories/new) 提交私密报告。报告建议包含：

- 受影响版本和环境；
- 最小复现步骤与影响；
- 可行的缓解或修复建议（如有）；
- 已脱敏的错误信息。

请勿上传 `workbench.db`、`workbench-config.json`、QQ openid、凭据、真实消息、个人路径、
完整日志或未脱敏截图。若必须提供敏感证据，请先在私密报告中说明，由维护者确认安全的传递方式。

维护者目标是在 7 天内确认报告，并在验证、修复和发布后协调披露。复杂问题可能需要更长时间，
但不会要求报告者先公开细节。

## 普通问题

功能缺陷、安装问题和不涉及安全影响的错误可使用公开 GitHub Issue，并同样需要先脱敏。
