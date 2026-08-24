# Contributing

感谢关注 Hermes Workbench。请先阅读 [README](README.md) 与 [SECURITY](SECURITY.md)。

## 开发环境

- Python 3.11+（项目依赖见 `pyproject.toml`）
- Node 20+（前端依赖由 `desktop-src/package-lock.json` 锁定）
- Git；如需实机验证，使用当前支持的 Hermes Desktop

## 本地验证（提交前必须全过）

```powershell
python -m pytest dashboard -q          # 后端回归（隔离配置，不碰真实数据）
ruff check dashboard scripts

cd desktop-src
npm ci
npm test                                # 前端单测
npm run typecheck                       # 类型检查
cd ..

node --test desktop-src/layout-regression.test.mjs
node build-desktop.mjs                   # 重建 bundle
git diff --exit-code desktop/plugin.js  # 构建产物与提交一致（plugin.js 进仓库）
python scripts/workbench_privacy_gate.py
```

CI 会在 Ubuntu 与 Windows 上重复执行上述核心门禁。提交前不能只依赖本机通过。

> **构建链铁律**：Hermes 打包 / asar 由 Hermes 上游负责；本仓库只维护磁盘插件源码与
> `desktop/plugin.js`。不要通过修改 Hermes 核心源码实现 Workbench 功能。

## 提交规范

- 一条提交一个逻辑变更；信息用中文或英文，说明「改了什么 + 为什么」
- 涉及 frontmatter/DB schema 的改动必须同步 `docs/data-consistency.md` 与测试
- 不新增「个人化默认值」：路径/群 ID/凭据一律走配置与 env，不进代码
- 修复必须覆盖根因并增加回归测试；不要仅修改一条真实任务或运行态数据
- 前端行为变更需说明 Board、Table、今日页、详情或健康弹窗中的影响范围

## 状态机与数据契约（红线）

- 7 态存储轴不新增第 8 持久态；`waiting` 等派生状态只推导、不落库
- 双写（文件 + SQLite 镜像）为当前事实源语义；切换 DB 事实源须先显式立项
- 任务状态查询先看工作台文件/DB，不凭记忆下结论

## 隐私红线（提交前自检）

- 必须运行 `python scripts/workbench_privacy_gate.py`，结果为 `privacy gate: clean`
- `workbench-config.json` / `workbench.db` / `scheduler-*` 均在 .gitignore，禁止强推
- 禁止提交真实 QQ openid、访问凭据、个人路径、消息正文、数据库、日志、截图或备份
- 测试必须使用中性示例路径与虚构 ID；不可复制真实运行配置作为 fixture

## Issue / PR

- 普通 Bug 可提交公开 Issue；安全漏洞必须按 [SECURITY.md](SECURITY.md) 私密报告
- Issue 至少包含：复现步骤、期望、实际、OS、Hermes 版本和 Workbench 提交/版本
- 提交日志或截图前必须脱敏；不要上传真实配置或数据库
- PR 需附测试证据、行为说明、数据兼容性和隐私影响
- 涉及 QQ 的 PR 必须区分私聊、群 @、普通群消息和主动投递，不得用配置存在代替事件级证据
- 涉及任务状态的 PR 必须说明成功、失败、无终态、手动归档和自动归档的行为
