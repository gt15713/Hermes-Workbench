# P0-E 发布闸门检查单（2026-08-23 定稿）

> 放行判定 = 干净环境端到端通过 + 隐私门禁零命中 + 当前回归基线 371 全绿，不是文件清单勾满。

## ① 干净环境端到端（唯一硬判据）

```text
git clone <repo> workbench-view
   → 复制到 <HERMES_HOME>/plugins/workbench-view
   → 重启 Hermes 桌面端
   → 打开工作台 → ⚙ 设置：配置 工作台文件夹（root）+ QQ 投递目标（deliver_target）
   → 保存（空值可保存，未配置项显式提示）
   → QQ 群发一条带链接消息 → 看板自动落卡（待回看/任务）
   → 触发一次定时任务 dry-run（日报 --data / 维护 --dry-run）→ 输出正确
   → 全程零手工干预（不修改源码、不手动建目录）
```

通过标准：装好即用闭环（收录 → 落卡 → 状态可见 → 定时可跑），无静默失败。

## ② 隐私 grep 闸门

```powershell
python scripts/workbench_privacy_gate.py
```

期望：0 命中。`desktop/plugin.js` 必须包含在扫描内（它进仓库）。

## ③ 回归基线（332 项全绿）

| 套件 | 数量 | 命令 |
|---|--:|---|
| pytest（dashboard） | 351 | `python -m pytest dashboard -q` |
| vitest（desktop-src） | 10 | `cd desktop-src && npx vitest run` |
| layout-regression | 10 | `node --test desktop-src/layout-regression.test.mjs` |

## ④ 发布动作（维护者执行）

1. `git init` + 首提交（.gitignore 已就位：运行时产物/配置/DB 全部排除）
2. 创建 GitHub 仓库 `Hermes-Workbench`（MIT LICENSE 已就位）
3. push 后 CI 自动跑（ruff + pytest + vitest + node --test + tsc + bundle 重建校验）
4. 发布 v0.1.0 tag + Release 说明（打包/asar 仅 CoderX 手工，55 红线不豁免）

## ⑤ 记录

- 通过后更新 outputs README 与 00 清单：P0-E ✅ 已发布
