# QQ Bot 官方能力与 Hermes Workbench 适配建议

> 核验日期：2026-08-24。本文只引用 QQ 机器人开放平台官方文档。官方站点同时保留了旧版手写页和 2026 年更新的自动生成接口页；有冲突时，本文以更新日期更晚、路径为 `/autogen/` 的接口页作为当前基线，并要求上线前在开放平台管理端和沙箱/灰度环境复验。

## 结论摘要

1. Workbench 应复用 Hermes 的唯一 QQ 连接，不创建第二个 QQ 客户端；平台能力和 Hermes 适配能力必须分别验收。
2. 当前官方接口明确支持单聊、群聊 `@机器人`，以及开启“接收所有消息”后的普通群全量事件 `GROUP_MESSAGE_CREATE`；但后者只有平台开关和 Hermes 网关分发都生效时才算可用。
3. 2026 年接口页明确列出主动消息频控和单聊互动召回，不能再沿用旧页“主动推送已停止”的绝对结论；仍应把主动推送视为受权限、关系、拒收开关和额度约束的非可靠通道。
4. 入站必须按事件 `id`/消息 `d.id` 去重；被动回复使用 `msg_id + msg_seq` 做幂等。出站重试不能盲目换 `msg_seq`，否则可能制造重复消息。
5. 新接入优先 Webhook，并完成 Ed25519 验签；若继续复用 Hermes WebSocket，必须实现心跳、ACK 监测、`session_id + seq` 持久化、Resume 和错误码分流。
6. Markdown、富媒体和内嵌键盘均为平台能力，但 Hermes 适配器是否完整透传需要单独验证；Workbench 必须保留纯文本降级。

## 平台能力与 Workbench 责任矩阵

| 能力 | QQ 平台当前文档 | Hermes / Workbench 必须实现或验证 | 建议状态 |
|---|---|---|---|
| 事件订阅 | `intents` 是位图；QQ 单聊、群事件属于 `GROUP_AND_C2C_EVENT (1<<25)`。特殊事件可能需要申请权限，无权限 intent 会关闭 WebSocket。[Intents](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/event-emit/payload.html#事件订阅-intents) | 只请求最小 intents；启动时记录“已请求/已获批/实际收到”三层状态，禁止仅凭配置显示绿色。 | 必做 |
| 单聊入站 | `C2C_MESSAGE_CREATE` 提供消息 ID、用户 OpenID、正文和附件。[单聊事件](https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/c2c_message_create.html) | Hermes 网关需将事件规范化为 `platform=qqbot` 并保留 `event_id`、`message_id`、`user_openid`；Workbench 仅保存业务所需字段并脱敏日志。 | 首要支持 |
| 群聊 @ | `GROUP_AT_MESSAGE_CREATE` 属于 `GROUP_AND_C2C_EVENT`。[群 @ 事件](https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/group_at_message_create.html) | 验证 Hermes WebSocket/Webhook 分发和消息路由均包含该事件；默认以群 @ 作为低噪声、安全入口。 | 首要支持 |
| 普通群全量 | 开启“接收所有消息”后，群内每条消息会触发 `GROUP_MESSAGE_CREATE`，Intent 仍为 `GROUP_AND_C2C_EVENT (1<<25)`。[群消息（全量模式）](https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/group_message_create.html) | 平台开关、机器人权限、Hermes 事件表、路由器和 Workbench hook 缺一不可。按真实事件遥测判定，不因 intent 已配置就判绿。应提供群 allowlist、成员/命令过滤和总开关。 | 条件支持，默认关闭 |
| 被动回复 | 群聊：5 分钟内、每条最多 5 次；单聊页顶部写 60 分钟、最多 4 次，但同页 `msg_id` 字段又写 5 分钟，官方自身存在冲突。[群聊发送](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_messages.post.html) [单聊发送](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_users_user_openid_messages.post.html) | 采用更保守的 5 分钟提交期限；保存收到时间并在队列入库时计算 deadline。不要依赖允许次数的上限，正常只回复一次。 | 必做 |
| 主动群消息 | 2026-08-12 接口页列出：认证 Bot 60/qpm、未认证 30/qpm；单群 20/qpm、每天最多 1000 条；接口总限 100 QPS。[群聊发送](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_messages.post.html) | 按 Bot、群、日三个维度限流；识别通知开关事件和 `40034100/40034105/40054016`；失败转本地待办，不能无限重试。 | 可选、受限 |
| 主动单聊 / 召回 | 2026-08-12 接口页列出主动单聊频控；用户对话后 30 天内提供四个互动召回周期，每周期一条，使用 `is_wakeup`。[单聊发送](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_users_user_openid_messages.post.html) | 必须维护好友关系、拒收状态、召回周期和额度；只用于用户已明确开启的提醒，不做批量营销。 | 可选、默认关闭 |
| 消息幂等 | `msg_seq` 与 `msg_id` 联合避免重复；相同组合重发失败，错误 `40054005` 表示消息被去重。[群聊发送](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_messages.post.html) [单聊发送](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_users_user_openid_messages.post.html) | 入站对事件外层 `id` 和消息 `d.id` 建唯一键；出站记录业务 operation id、`msg_id`、`msg_seq`、响应消息 ID。超时先查本地投递记录，再决定重试。 | 必做 |
| Markdown / 按钮 | `msg_type=2` 支持 Markdown；`keyboard` 支持预设或自定义按钮，按钮含跳转、回调、指令三类，并有限定权限和客户端版本字段。[群聊发送](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_messages.post.html) [Markdown](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/type/markdown.html) | 适配器必须透传结构化 body，不能把 Markdown/keyboard 串成普通文本；按钮回调订阅 `INTERACTION_CREATE`。权限不足或格式失败时降级成短纯文本命令。 | 渐进启用 |
| 富媒体 | `msg_type=7` 使用上传接口返回的 `file_info`；入站全量群事件可含图片、语音、视频和群文件附件。[群聊发送](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_messages.post.html) [群全量事件](https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/group_message_create.html) | 下载附件必须设大小、MIME、超时和存储 TTL；禁止自动执行文件或把附件 URL/鉴权参数写日志。出站缓存 `file_info` 时按官方 TTL 管理。 | 图片优先，其余按需 |

## 接入与连接治理

### Webhook（推荐的新接入方式）

官方要求 HTTPS 回调，允许端口为 80、443、8080、8443，并要求签名校验。[Webhook](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/event-emit/webhook.html) 事件请求使用 Ed25519，签名基于时间戳与原始 HTTP body；必须在解析/重写 body 前校验。[签名算法](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/interface-framework/sign.html)

Workbench/Hermes 侧应：

- 原样读取 body 并验签，失败立即拒绝；校验 `X-Bot-Appid` 与本地 AppID。
- 增加应用侧时间偏差窗口和已见事件 ID 缓存以防重放；这两项是防御性加固，不应冒充 QQ 官方规定。
- 回调尽快 ACK，将持久化、任务分类和回复放到异步队列。
- 不在 Workbench 插件中保存 AppSecret；凭据只由 Hermes 服务端配置读取。

### WebSocket（复用 Hermes 时的兼容要求）

当前官方 WebSocket 页仍完整描述连接协议：Hello 下发 `heartbeat_interval`；Identify 使用 `QQBot {AccessToken}` 和 intents；Ready 返回 `session_id`；心跳携带最新 `s`；短时间断线后使用 `session_id + seq` 发送 Opcode 6 Resume，平台补发遗漏事件并返回 `RESUMED`。[WebSocket](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/event-emit/websocket.html)

Hermes 适配器必须：

- 仅在业务处理成功后持久化最新 `s`，否则 Resume 可能跳过未完成事件。
- 监测 Heartbeat ACK；缺失时主动断开并重连。
- 对 `4006/4007` 放弃 Resume 并 Identify；`4008/4009` 按文档分流；`4013/4014` 视为 intent 配置或权限故障，不做无限重试；`4914/4915` 停止正式连接并告警。
- 对连接和 Resume 使用指数退避加抖动，同时遵守 `/gateway/bot` 的剩余会话和最大并发限制。
- 即便 Resume 会补发，也必须保留事件去重，因为网络超时与进程崩溃可造成至少一次投递。

## 鉴权与凭据安全

使用 `POST https://api.bot.qq.com/app/getAppAccessToken` 以 AppID/ClientSecret 获取 Access Token，默认有效期不超过 7200 秒；临近过期 60 秒可取得新 token，旧 token 在该窗口仍有效；OpenAPI 头为 `Authorization: QQBot ACCESS_TOKEN`。官方明确要求不要在前端使用访问凭证。[Access Token](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/access-token.html) 旧 Token 鉴权已弃用。[启动接入](https://bot.q.qq.com/wiki/develop/api-v2/)

建议由 Hermes 网关集中缓存和刷新 Token，Workbench 只调用 Hermes 的内部发送能力。日志、健康接口、错误上报和测试夹具不得出现 AppID、ClientSecret、Access Token、用户/群 OpenID、原始消息内容或附件下载 URL。

## 审核、沙箱与运营边界

- 官方介绍指南提供沙箱配置入口；WebSocket 错误 `4914` 表示机器人下架后只允许连接沙箱环境。[接入指南：开发场景选择](https://bot.q.qq.com/wiki/#_7-开发场景选择) [WebSocket](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/event-emit/websocket.html#websocket-错误码)
- 发布前需以开放平台管理端实际可选事件、消息类型、Markdown/按钮权限和“接收所有消息”开关为准；API 文档出现字段不等同于当前机器人已获权限。
- 腾讯会进行发布审核，主体资质必须真实、合法、有效、完整；内容与运营还需遵守平台规范。[运营规范](https://bot.q.qq.com/wiki/business/#_4-主体规范)
- Workbench 任务内容可能包含路径、项目名和私人安排，默认不得回显到非原始会话；群全量消息不得用于成员画像、无关内容留存或静默监控。

## 官方文档冲突与风险处理

1. **主动消息冲突**：旧版消息汇总页写有“2025-04-21 起不再提供主动推送”，但 2026-08-12 更新的单聊/群聊自动生成接口页明确给出主动消息与互动召回能力、频控和错误码。[旧消息页](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/send-receive/send.html) [新单聊接口](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_users_user_openid_messages.post.html) [新群聊接口](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_messages.post.html) 因此产品应采用新接口页为基线，但功能仍置于能力开关后并做真实发送灰度。
2. **普通群消息冲突**：旧 Intents 清单未列 `GROUP_MESSAGE_CREATE`，2026-07-23 的专页则明确它与 `GROUP_AT_MESSAGE_CREATE` 共用 `GROUP_AND_C2C_EVENT`，且要求开启“接收所有消息”。[Intents](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/event-emit/payload.html#事件订阅-intents) [群全量事件](https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/group_message_create.html) 必须以实际事件到达作为验收标准。
3. **单聊被动窗口冲突**：同一新接口页顶部写 60 分钟，请求字段却写 `msg_id` 5 分钟；Workbench 应按 5 分钟保守调度，并记录平台返回错误以便将来更新。
4. **适配器能力未知**：平台支持不代表 Hermes 当前 QQ 适配器已处理事件、附件、Markdown、键盘和主动消息。任何能力只有通过“平台开关 → 网关收到事件/响应 → Workbench 入库/投递”端到端证据后才显示绿色。

## 建议实施顺序

1. 固化单聊与群 @ 的端到端回归；补齐事件外层 ID、消息 ID 和 `msg_seq` 幂等记录。
2. 审计 Hermes 对 `GROUP_MESSAGE_CREATE` 的 WebSocket/Webhook dispatch 与路由分支；通过真实普通群消息验证后再开放群 allowlist。
3. 将主动发送改为显式能力开关，增加 Bot/关系/日配额限流、拒收状态和失败降级。
4. Markdown 与按钮先做纯文本降级；只有 Hermes 能透传结构化消息并收到互动回调时再启用。
5. 若 Hermes 支持 Webhook，迁移到 Webhook + Ed25519；若暂时仅支持 WebSocket，完成 Resume、ACK、错误码和去重测试。
6. 建立定期官方文档漂移检查，重点监控 `/autogen/` 页面更新时间和旧汇总页冲突。
