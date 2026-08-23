# Hermes Workbench

> **前置依赖**：本插件是 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 桌面端插件，**非独立服务**。
> 使用需：① Hermes Agent 桌面端（宿主）② 已连接 QQ Bot。两者缺一不可。
>
> Hermes 消息平台的 QQ Bot 任务信息流工作台插件：QQ 群消息自动收录 → 看板流转 →
> Hermes 处理 → 回执 → 归档，全程可回电脑续接。

## 定位

**Hermes Workbench 是一个独立插件，不是垂直工具**：通用全品类任务信息流平台。
任务怎么处理（调研/总结/摄入）是 Hermes Skill 的事，Workbench 只负责
**登记 / 展示 / 提醒 / 归档**。

## 依赖（三件套，缺一不可）

1. **QQ 群**（消息通道）
2. **Hermes Workbench 插件**（本仓库，信息流核心）
3. **Hermes 宿主**（Hermes Agent，内容处理执行者 + `hermes send` 投递）

> 插件**零 Hermes cron 依赖**：定时任务（日报/提醒/维护/归档）全部内建。

> **可靠性边界**：定时任务运行在 Hermes 桌面进程内，Hermes 未运行时不会执行；
> 重启后自动补跑最近 6 小时内错过的任务（可配置 `catch_up_hours`，0=禁用）。

## 特性

- **QQ 消息自动收录**：链接/任务/想法按语义落入对应分区（幂等去重）
- **看板流转**：待验证 / 待回看 / 任务 / 已处理 / 回收站 + 自定义分区
- **定时任务内建**：每日日报（LLM 生成 + 写工作日志 + QQ 投递）、超期提醒、
  每日维护（归档巡检 + DB 收敛 + 回收站 TTL）、执行生命周期协调（每 10 分钟）
- **任务级可见性**：执行失败/空结果/投递失败均有显式状态与错误计数，不静默
- **投递自愈**：QQ 投递失败自动重试（5 分钟 × 3）
- **设置面板**：路径 / 分区 / 定时 / 保留 / 投递目标全部可配置

## 安装

1. 将本仓库复制到 Hermes 插件目录：`<HERMES_HOME>/plugins/workbench-view`
2. 重启 Hermes 桌面端
3. 打开工作台 → ⚙ 设置：配置工作台文件夹位置、QQ 投递目标（`qqbot:<群 openid>`）
4. 配置完成后 QQ 群消息即自动落卡

> 首次使用建议先跑一次「日报 / 提醒」定时任务验证链路。

## 配置

配置文件：`workbench-config.json`（插件目录，首次保存设置时生成）。
完整字段与环境变量覆盖见 [config.example.yaml](config.example.yaml)。

## 开发

- 后端：`dashboard/`（FastAPI 插件 API + scheduler + 双写存储）
- 前端：`desktop-src/`（React，构建产物 `desktop/plugin.js` **进仓库**）
- 脚本：`scripts/`（维护/日报/提醒等调度脚本，随插件分发）
- 构建：`node build-desktop.mjs`（见 [CONTRIBUTING.md](CONTRIBUTING.md)）
- 测试：`pytest dashboard/` + `cd desktop-src && npm test`

## 安全

隐私红线与报告渠道见 [SECURITY.md](SECURITY.md)。本项目为个人维护项目，
按现状提供，无担保——见 [DISCLAIMER.md](DISCLAIMER.md)。

## License

[MIT](LICENSE)
