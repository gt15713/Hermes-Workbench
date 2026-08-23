# Security

Hermes Workbench 处理 QQ 消息与本地文件，安全边界如下。

## 隐私红线

- **不入库**：token、QQ 群 openid、个人路径、凭据——只存在于用户配置
  （`workbench-config.json`，.gitignore）与运行态文件
- **运行时产物**：`workbench.db` / `scheduler-state.json` / `scheduler.lock`
  含本地数据，禁止上传任何远端
- **日志**：入站 hook 只记平台名与触发信号，**不记录消息内容**

## 路径安全

- 所有文件操作经分区白名单 + root 前缀校验（防路径穿越）
- 分区名禁止路径分隔符；自定义分区受白名单约束

## 投递

- QQ 投递走 `hermes send`（官方 REST，宿主凭据），插件不持有凭据
- 投递目标未配置时显式报错（`DELIVERY-UNCONFIGURED`），不静默

## 可靠性边界

- 定时任务随 Hermes 桌面进程存活；进程未运行时任务不执行，重启后按
  `catch_up_hours`（默认 6h）补跑错过的日报/提醒/维护

## 报告

发现安全问题请通过 GitHub Issue（标记 `security`）报告，或联系维护者。
修复前请勿公开披露细节。
