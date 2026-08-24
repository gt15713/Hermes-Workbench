# Hermes Workbench

Hermes Agent 的本地任务信息流插件：把 QQ 消息或手工录入转成可追踪任务，提供看板、执行历史、提醒、回执、归档和链路健康状态。

> 当前版本：[`v0.1.0-alpha`](https://github.com/gt15713/Hermes-Workbench/releases/latest)
>
> 已验证宿主：Hermes Desktop `v0.20.5`
>
> 本项目不是独立应用，也不会修改 Hermes 核心程序或核心配置。

## 它负责什么

Workbench 负责 **登记、展示、提醒、状态协调与归档**；任务实际如何调研、总结或处理，仍由 Hermes 和对应 Skill 完成。

完整消息闭环需要 Hermes Desktop、本插件和已连接的 QQ Bot。仅使用本地任务管理时可以不配置 QQ。

定时任务由插件内建，不依赖 Hermes cron。Hermes 未运行时定时任务不会执行；重启后会补跑最近 6 小时内错过的任务，窗口可通过 `catch_up_hours` 调整。

## 主要功能

- QQ 私聊或群聊消息自动收录，链接、任务和想法按规则进入对应分区；
- 看板与 Table 两种视图，支持搜索、标签和到期筛选；
- 待验证、待回看、任务、已处理、回收站及自定义分区；
- 运行历史、最近执行结果、失败原因和投递状态可见；
- 成功任务自动归档，并提供手动归档入口；
- 日报、超期提醒、维护清理及每 10 分钟一次的生命周期协调；
- QQ 投递失败自动重试（5 分钟一次，最多 3 次）；
- 数据库、调度器、投递、Obsidian 和 QQ 链路的分层健康检查。

## 5 分钟快速开始

### 1. 安装插件

从 [Releases](https://github.com/gt15713/Hermes-Workbench/releases/latest) 下载源码包，或克隆仓库：

```powershell
git clone https://github.com/gt15713/Hermes-Workbench.git workbench-view
```

将整个目录放到：

```text
<HERMES_HOME>/plugins/workbench-view
```

仓库已包含 `desktop/plugin.js`，普通用户无需安装 Node.js，也无需自行构建前端。

### 2. 重启并配置

1. 完全退出并重新打开 Hermes Desktop；
2. 从侧边栏打开 **Workbench**；
3. 点击右上角 **设置**；
4. 配置工作台文件夹；
5. 如需 QQ 回执，配置投递目标：`qqbot:<群 openid>`；
6. 保存设置。

### 3. 验证安装

- Workbench 能显示看板，且不会一直停在“加载中”；
- 顶部 Pending / Total 数量可正常返回；
- 点击链路健康按钮可看到数据库、调度、投递和 QQ 分层状态；
- 手工新建一个测试任务，或通过已验证的 QQ 通道发送测试消息；
- 任务出现后，打开卡片确认详情与运行历史可以加载。

> 不建议通过修改 Hermes 核心文件来安装或修复 Workbench。Hermes 更新可能覆盖核心文件，而磁盘插件目录和 Workbench 数据应保持独立。

## QQ 能力矩阵

| 能力 | 当前状态 | 说明 |
|---|---|---|
| QQ 私聊收录 | 已验证 | 可接收并生成任务 |
| QQ 群聊 @机器人 | 已验证 | 群内明确 @机器人时可收录 |
| QQ 普通群消息 | 待上游验证 | 没有稳定的事件级证据时，健康灯保持黄色 |
| QQ 主动群推送 | 可用 | 需要配置正确的 `qqbot:<群 openid>` |

“机器人可获取群内全部消息”是 QQ 开放平台侧的授权能力，不等于 Hermes 当前适配器已经把每种事件交给 Workbench。Workbench 只根据实际收到的事件显示健康状态，不会仅凭配置或源码声明显示绿色。

### Workbench 命令接口

后端提供仅供宿主授权后调用的内部 QQ 命令契约：`/wb 帮助`、`/wb 今日`、`/wb 状态`、
`/wb 任务`、`/wb 完成`、`/wb 归档` 和 `/wb 延期`。写命令必须携带 QQ 官方消息 ID
以保证幂等；任务标题存在歧义时不会自动选择。

该函数不暴露为 HTTP 路由，也不会在 `pre_gateway_dispatch` 中执行，因为 Hermes 的这个
Hook 位于发送者授权之前。接线要求见 [QQ Workbench 命令接线契约](docs/qq-workbench-command-wiring.md)。

## 任务生命周期

```text
QQ/手工收录
    ↓
待验证 / 待回看 / 任务
    ↓
执行中 ── 成功 ──→ 自动或手动归档 ──→ 已处理
    │
    ├── 失败 ─────→ 保留任务并给出恢复建议
    └── 无终态 ───→ 继续观察，不误判为完成
```

- 自动归档只依据持久化的执行状态与终态结果，不根据聊天记忆猜测；
- 符合条件的任务可从卡片操作菜单手动归档；
- 失败、空结果或投递失败不会被静默归档；
- 任务详情与运行历史读取均有宿主原生超时保护，失败时可安全重试。

## “规则建议”的依据

今日页的建议不是模型自由发挥，而是由确定性规则生成，依据包括任务状态、截止日期、最近执行结果，以及阻塞、失败或投递状态。每条建议会展示规则标签和依据，只提供操作提示，不会自动修改任务。

## 链路健康灯

| 状态 | 含义 | 建议操作 |
|---|---|---|
| 绿色 | 已配置，并且存在近期运行证据 | 无需处理 |
| 黄色 | 已配置但缺少近期证据，或受上游能力限制 | 查看详情，按提示发送测试消息 |
| 红色 | 已检测到数据库、调度、连接或投递故障 | 打开详情，根据具体故障项排查 |
| 灰色 | 功能未配置或已关闭 | 按需配置或启用 |

黄色表示“待观察”，不等于已经故障；绿色则必须有实际运行证据。

## 配置与本地数据

配置文件为插件目录中的 `workbench-config.json`，首次保存设置时生成。完整字段与环境变量覆盖见 [config.example.yaml](config.example.yaml)。

| 文件 | 用途 | 是否应提交 GitHub |
|---|---|---|
| `workbench-config.json` | 用户路径、分区、投递目标和调度设置 | 否 |
| `workbench.db` | 任务、状态和运行历史 | 否 |
| `scheduler-state.json` / `scheduler.lock` | 调度运行状态 | 否 |
| 工作台目录 | 任务文件和双写数据 | 否 |
| Obsidian 工作日志 | 可选的日报写入目标 | 否 |

插件不保存 Hermes 或 QQ 凭据；QQ 投递通过 Hermes 官方 `hermes send` 链路完成。

### 更新与备份

更新插件前建议备份 `workbench-config.json`、`workbench.db` 和自己配置的工作台目录。更新源码时不要用空目录覆盖上述运行数据。更新后重启 Hermes，再检查 Pending / Total、健康详情和一张历史任务卡片。

## 常见问题

### Workbench 一直显示加载中

1. 确认目录名为 `workbench-view`，并位于 `<HERMES_HOME>/plugins/`；
2. 完全退出后重新打开 Hermes；
3. 查看 Workbench 健康详情和 Hermes 插件日志；
4. 不要同时加载相同 ID 的另一份 Workbench 插件。

### 健康检查显示黄色或红色

黄色时先看具体层级；普通群消息为黄色可能只是缺少上游事件证据。红色时，详情会指出数据库、调度、投递或连接故障。修复后以新的时间戳和事件证据为准。

### 私聊正常，但群消息没有落卡

- 先在群内明确 @机器人测试；
- 确认 QQ 开放平台权限与 Hermes QQ 连接正常；
- 普通群消息是否可达取决于 Hermes 上游适配器，不能由 Workbench 单方面补齐；
- 分别查看“QQ 群 @ 摄取”和“QQ 普通群消息”，不要只看总连接状态。

### 已完成任务没有归档

- 打开卡片查看最近执行结果与运行历史；
- 成功终态会进入可归档状态，失败或无终态会继续保留；
- 对符合条件的任务使用卡片操作菜单中的手动归档；
- 如果详情持续加载失败，先处理链路健康中的数据库或插件请求错误。

### 日报或提醒没有发送

- 确认 Hermes 在计划执行时间处于运行状态；
- 检查 `deliver_target`；
- 查看调度器心跳与消息投递层状态；
- 重启补跑只覆盖 `catch_up_hours` 指定的窗口。

### Hermes 更新后 Workbench 没有生效

- 确认磁盘插件仍位于 `<HERMES_HOME>/plugins/workbench-view`；
- 完全退出并重新打开 Hermes；
- 检查是否出现另一份同 ID 插件覆盖磁盘版；
- 不要通过长期修改 Hermes 核心源码来维持 Workbench 功能。

## 开发与验证

- 后端：`dashboard/`（FastAPI 插件 API、scheduler、双写存储）；
- 前端：`desktop-src/`（React 源码）；
- 运行 bundle：`desktop/plugin.js`（生成后随仓库发布）；
- 脚本：`scripts/`（日报、提醒和维护任务）。

```powershell
python -m pytest dashboard -q

cd desktop-src
npm ci
npm test
npm run typecheck
cd ..

node --test desktop-src/layout-regression.test.mjs
node build-desktop.mjs
git diff --exit-code desktop/plugin.js
python scripts/workbench_privacy_gate.py
```

贡献规范见 [CONTRIBUTING.md](CONTRIBUTING.md)，桌面交付结构见 [DESKTOP.md](DESKTOP.md)。

## 已知限制

- 当前为 Alpha 版本；升级前应备份本地配置与数据库；
- 普通 QQ 群消息仍取决于 Hermes 上游适配器的事件支持；
- 定时任务随 Hermes 桌面进程存活，并非系统级后台服务；
- Workbench 管理任务状态，但不替代 Hermes Skill 的具体执行能力。

## 安全与许可

隐私边界与报告方式见 [SECURITY.md](SECURITY.md)。项目按现状提供，无担保，详见 [DISCLAIMER.md](DISCLAIMER.md)。

许可证：[MIT](LICENSE)
