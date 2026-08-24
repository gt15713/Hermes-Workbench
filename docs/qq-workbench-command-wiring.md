# QQ Workbench 命令接线契约

> 当前状态：**封档搁置，不启用**。恢复条件：Hermes 官方提供发送者授权后的插件 Hook。禁止通过修改 Hermes 核心、前置 Hook 或第二套 QQ 连接绕过。

Workbench 提供内部函数 `plugin_api.qq_command(body)`。它刻意不注册为 HTTP 路由，
避免调用方伪造“已经授权”。请求包含 `text` 和 QQ 官方 `message_id`，响应包含适合 QQ
纯文本回复的 `reply`。

支持 `/wb 帮助`、`/wb 今日`、`/wb 状态`、`/wb 任务 <内容>`、
`/wb 完成 <任务标题>`、`/wb 归档 <任务标题>`、
`/wb 延期 <任务标题> <YYYY-MM-DD>`。

写命令必须提供 `message_id`，Workbench 使用它做幂等；标题歧义只返回候选，不猜测目标。

## 安全边界

Hermes 当前的 `pre_gateway_dispatch` 在发送者授权之前执行，因此 Workbench 的该 Hook
不能调用该函数执行操作。Hermes 接线点必须：

1. 先完成平台、群和发送者授权；
2. 仅处理明确位于 `/wb` 或 `工作台` 命名空间的命令；
3. 传递原始 QQ `message_id`，并用接口返回的 `reply` 回复原消息；
4. 不因超时更换消息 ID 后再次执行；
5. 不记录 AppSecret、AccessToken、OpenID 或原始群消息。

在 Hermes 提供授权后插件 Hook 之前，不修改 Hermes 核心源码、不创建额外 WebSocket，
也不通过前置 Hook 绕过授权。读命令同样走授权后路径，避免泄露任务与健康信息。

## 普通群消息验收

只有平台开关生效、Hermes 实际路由 `GROUP_MESSAGE_CREATE`、Workbench 收到近期明确的
事件类型证据三者同时成立，普通群消息健康灯才显示绿色。Intent 或源码字符串本身不能
证明运行链路可用。
