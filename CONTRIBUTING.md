# Contributing

感谢关注 Hermes Workbench。请先阅读 [README](README.md) 与 [SECURITY](SECURITY.md)。

## 开发环境

- Python 3.11+（`pytest`、`ruff`、`pyyaml`、`fastapi`）
- Node 20+（`desktop-src` 下 `npm ci`）

## 本地验证（提交前必须全过）

```powershell
python -m pytest dashboard -q          # 后端回归（隔离配置，不碰真实数据）
cd desktop-src
npm ci
npx vitest run                          # 前端单测
npx tsc --noEmit                        # 类型检查
cd ..
node build-desktop.mjs                  # 重建 bundle
git diff --exit-code desktop/plugin.js  # 构建产物与提交一致（plugin.js 进仓库）
```

> **构建链铁律**：打包 / asar / 发布产物构建仅由维护者执行；贡献者只提交源码，
> 重建校验由 CI 兜底。

## 提交规范

- 一条提交一个逻辑变更；信息用中文或英文，说明「改了什么 + 为什么」
- 涉及 frontmatter/DB schema 的改动必须同步 `docs/data-consistency.md` 与测试
- 不新增「个人化默认值」：路径/群 ID/凭据一律走配置与 env，不进代码

## 状态机与数据契约（红线）

- 7 态存储轴不新增第 8 持久态；`waiting` 等派生状态只推导、不落库
- 双写（文件 + SQLite 镜像）为当前事实源语义；切换 DB 事实源须先显式立项
- 任务状态查询先看工作台文件/DB，不凭记忆下结论

## 隐私红线（提交前自检）

- 全仓库 grep 零命中：`token`、群 openid、个人路径、`.bak` 产物
- `workbench-config.json` / `workbench.db` / `scheduler-*` 均在 .gitignore，禁止强推

## Issue / PR

- Issue 模板字段：复现步骤 / 期望 / 实际 / 环境（OS + Hermes 版本）
- PR 需附带测试证据（pytest / vitest 输出）与行为说明
