# 数据一致性与双写仲裁（docs/data-consistency.md）

> 版本：2026-08-22（P0 文档化，依据 dashboard/repo.py DualRepo 实现 + 幂等 outbox）
> 适用范围：Hermes Workbench（workbench-view 插件）数据层

## 1. 事实源

- 默认读路径走 SQLite（`workbench.db`）：`WORKBENCH_READ_FROM_DB=1`，**DB 为唯一事实源**，文件为可选只读镜像；
- 回滚通道：`WORKBENCH_READ_FROM_DB=0` → 读回文件（灰度回滚用）。

## 2. 写路径（灰度期双写）

- 文件优先写；文件写失败 → **不碰 DB**（上抛，调用方处理）；
- DB 镜像写失败 → warning 不阻断业务，一致性由每日校验兜底；
- 移动/删除同理：文件操作成功 → DB 镜像失败仅告警。

## 3. 读路径容错

- DB 读失败 → 回退文件读（warning 不阻断）。

## 4. 并发控制

- 进程内：`_WRITE_LOCK`（RLock 串行化读-改-写）；
- 跨进程：`FileLock`（Windows msvcrt 非阻塞 + 轮询，超时 → TimeoutError；非 Windows 降级无锁）；
- mtime 前置校验：`expected_mtime` 冲突 → 上抛 `WorkbenchConflictError`，调用方回滚/重试，**不吞异常**。

## 5. 幂等

- **收录**：`ingest_messages` outbox——`message_id` 主键唯一；`status=processing` = 崩溃残留可重放，`done` = 已消费；
- **完成**：`complete` 归档后重复调用 → `task not found`，不产生第二份归档；任务区已 `completed` → 由唯一正式入口补齐完成记录并归档；
- **跨分区 URL 去重**：`existing_video_url` 扫全分区，同短链 → `duplicate`（防 OThqZGc 类重复卡）。

## 6. 一致性兜底与备份

- 每日校验：`workbench_db_verify.py`（文件 vs DB 差异巡检）；
- 备份：`scripts/hermes_backup.py` 月度快照（含 `workbench.db` + Obsidian 全库）；
- 恢复语义：恢复后需重新索引 OpenViking vectordb（索引可重建，进程锁定时被排除）。

## 7. 投递失败告警（P0）

- QQ 文本发送失败 → `gateway_state.json` 平台段 `error_code=delivery_failed` + 结构化日志（`DELIVERY-ALERT`）；
- 下一次发送成功或重连（connect）自动清除，避免陈旧错误误导。
