# -*- coding: utf-8 -*-
"""Workbench 个性化配置（设置面板后端事实源，2026-08-22）。

- 存储：插件目录 workbench-config.json（插件自持，独立于 Hermes config.yaml）
- 覆盖优先级：环境变量（测试/CI/临时覆盖）> 配置文件 > 内置默认
- 生效策略：
    · 立即生效：scheduler 任务时间/开关、回收站保留（下次维护）、投递目标、日报写日志
    · 重启生效：root/vault 路径（模块 import 期解析）；分区新增即时建目录、白名单随重启
- 分区模型：固定 4 分区（待回看/任务/已处理/回收站，不可删）+ 默认遗留
  （待验证/心理学随想/梦中的邮件，可删但默认存在）+ 用户自定义（空分区可删）
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional

from contract import PARTITIONS

_PLUGIN_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = Path(
    os.environ.get("WORKBENCH_CONFIG", str(_PLUGIN_DIR / "workbench-config.json"))
)

DEFAULT_ROOT = str(Path.home() / "Workbench")
DEFAULT_VAULT = ""
DEFAULT_DELIVER_TARGET = ""

# A2 一期（GT 边界）：默认仍 dual；db_only/file_only 仅配置就绪，
# 二期执行回执 API 化后再翻转新装默认。
DEFAULT_STORAGE_MODE = "dual"

# 固定分区（不可删除/改名；P0 辩论拍板：默认 5 固定含待验证）
FIXED_PARTITIONS = frozenset({"待验证", "待回看", "任务", "已处理", "回收站"})

# 分区类型 → 语义（前端 meta / 聚合 vs 单卡）
PARTITION_TYPES = ("thought", "video", "task", "psych", "dream", "done", "trash")

# 默认调度（与迁移前的 Hermes cron 语义一致）
DEFAULT_SCHEDULE = {
    "lifecycle": {"enabled": True, "expr": "*/10 * * * *"},
    "maintenance": {"enabled": True, "expr": "30 12 * * *"},
    "daily_report": {"enabled": True, "expr": "0 20 * * *"},
    "nudge": {"enabled": True, "expr": "15 12 * * *"},
}

_NAME_RE = re.compile(r"[\\/:*?\"<>|\x00-\x1f]")


def _default_partitions() -> list[dict]:
    """内置默认分区（P0 拍板 5 固定）；心理学随想/梦中的邮件不再默认，
    已存在用户配置兼容保留（作为可删用户分区）。"""
    return [
        {"name": name, "type": ptype, "fixed": name in FIXED_PARTITIONS}
        for name, ptype in PARTITIONS
        if name in FIXED_PARTITIONS
    ]


def default_config() -> dict:
    return {
        "version": 1,
        "root": DEFAULT_ROOT,
        "vault": DEFAULT_VAULT,
        "deliver_target": DEFAULT_DELIVER_TARGET,
        "partitions": _default_partitions(),
        "scheduler": {k: dict(v) for k, v in DEFAULT_SCHEDULE.items()},
        "ttl": {"days": 30, "mode": "archive"},
        "write_worklog": False,
        "catch_up_hours": 6,  # A4：启动补跑窗口（小时，0=禁用）
        "storage_mode": DEFAULT_STORAGE_MODE,  # A2：dual | db_only | file_only
    }


# ---------------------------------------------------------------------------
# 读写
# ---------------------------------------------------------------------------


def load_config() -> dict:
    """读取配置（合并默认；缺失/损坏 → 默认）。"""
    defaults = default_config()
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return defaults
    if not isinstance(raw, dict):
        return defaults
    return _merge(defaults, raw)


def _merge(base: dict, over: dict) -> dict:
    """浅合并 + 嵌套 dict 深合并（分区/调度整表替换）。"""
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict) and k in ("scheduler", "ttl"):
            out[k] = {**base[k], **v}
        elif v is not None:
            out[k] = v
    return out


def save_config(cfg: dict) -> dict:
    """校验 + 原子保存；返回规范化配置。校验失败抛 ValueError。"""
    normalized = normalize_config(cfg)
    tmp = CONFIG_FILE.with_name(CONFIG_FILE.name + ".tmp")
    tmp.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, CONFIG_FILE)
    return normalized


def normalize_config(cfg: dict) -> dict:
    """规范化 + 校验（分区结构/调度/ttl/路径）。"""
    d = default_config()
    root = str(cfg.get("root") or d["root"]).strip() or DEFAULT_ROOT
    vault = str(cfg.get("vault") or d["vault"]).strip()
    if not root:
        raise ValueError("root 不能为空")
    # P0 放宽：vault 空 = 未接入 Obsidian（日报不写工作日志，告警不崩溃）

    partitions = cfg.get("partitions")
    if not isinstance(partitions, list) or not partitions:
        raise ValueError("至少需要一个分区")
    seen: set[str] = set()
    fixed_seen: set[str] = set()
    out_parts: list[dict] = []
    for p in partitions:
        if not isinstance(p, dict):
            raise ValueError("分区格式错误")
        name = str(p.get("name") or "").strip()
        ptype = str(p.get("type") or "").strip()
        # 固定分区名强制 fixed（升级兼容：旧 7 分区配置里待验证等标记可能为 false）
        fixed = name in FIXED_PARTITIONS or bool(p.get("fixed"))
        if not name:
            raise ValueError("分区名不能为空")
        if len(name) > 20:
            raise ValueError(f"分区名过长：{name}")
        if _NAME_RE.search(name) or name.startswith("."):
            raise ValueError(f"分区名含非法字符：{name}")
        if name in seen:
            raise ValueError(f"分区名重复：{name}")
        if ptype not in PARTITION_TYPES:
            raise ValueError(f"分区类型非法：{ptype}")
        seen.add(name)
        if fixed:
            fixed_seen.add(name)
        out_parts.append({"name": name, "type": ptype, "fixed": fixed})
    missing_fixed = FIXED_PARTITIONS - fixed_seen
    if missing_fixed:
        raise ValueError(f"固定分区不可删除：{'/'.join(sorted(missing_fixed))}")

    scheduler: dict = {}
    for key, default in DEFAULT_SCHEDULE.items():
        item = cfg.get("scheduler", {}).get(key, {})
        enabled = bool(item.get("enabled", default["enabled"]))
        if "time" in item and key != "lifecycle":
            expr = time_to_expr(item["time"])
        else:
            expr = str(item.get("expr") or default["expr"]).strip()
        if not re.match(r"^\S+\s+\S+\s+\S+\s+\S+\s+\S+$", expr):
            raise ValueError(f"调度表达式非法（{key}）：{expr}")
        scheduler[key] = {"enabled": enabled, "expr": expr}

    ttl = cfg.get("ttl") or {}
    try:
        days = int(ttl.get("days", 30))
    except (TypeError, ValueError):
        raise ValueError("回收站保留天数必须为数字") from None
    if not 1 <= days <= 365:
        raise ValueError("回收站保留天数须在 1-365 之间")
    mode = str(ttl.get("mode") or "archive").strip().lower()
    if mode not in ("archive", "delete"):
        raise ValueError("回收站模式须为 archive 或 delete")

    deliver = str(cfg.get("deliver_target") or d["deliver_target"]).strip()
    # P0 放宽：deliver_target 空 = 未配置投递（error 级显式状态，不 crash 不静默）

    storage_mode = str(cfg.get("storage_mode") or d["storage_mode"]).strip().lower()
    if storage_mode not in ("dual", "db_only", "file_only"):
        raise ValueError("storage_mode 须为 dual / db_only / file_only")

    try:
        catch_up_hours = int(cfg.get("catch_up_hours", d["catch_up_hours"]))
    except (TypeError, ValueError):
        catch_up_hours = d["catch_up_hours"]
    catch_up_hours = max(0, min(168, catch_up_hours))

    return {
        "version": 1,
        "root": root,
        "vault": vault,
        "deliver_target": deliver,
        "partitions": out_parts,
        "scheduler": scheduler,
        "ttl": {"days": days, "mode": mode},
        "write_worklog": bool(cfg.get("write_worklog", False)),
        "catch_up_hours": catch_up_hours,
        "storage_mode": storage_mode,
    }


# ---------------------------------------------------------------------------
# 动态 getter（环境变量 > 配置 > 默认）
# ---------------------------------------------------------------------------


def get_root() -> str:
    env = os.environ.get("WORKBENCH_ROOT", "").strip()
    if env:
        return env
    return str(load_config().get("root") or DEFAULT_ROOT)


def get_vault() -> str:
    env = os.environ.get("OBSIDIAN_VAULT", "").strip()
    if env:
        return env
    return str(load_config().get("vault") or DEFAULT_VAULT)


def get_deliver_target() -> str:
    env = os.environ.get("WORKBENCH_DELIVER_TARGET", "").strip()
    if env:
        return env
    return str(load_config().get("deliver_target") or DEFAULT_DELIVER_TARGET)


def get_db_path() -> str:
    """workbench.db 路径：env WORKBENCH_DB 优先，默认插件目录（P0-A 参数化）。"""
    env = os.environ.get("WORKBENCH_DB", "").strip()
    if env:
        return env
    return str(CONFIG_FILE.parent / "workbench.db")


def get_partitions() -> list[dict]:
    """有效分区表（内置 + 自定义，保持配置顺序）。"""
    return [dict(p) for p in load_config().get("partitions", _default_partitions())]


def get_partition_names() -> frozenset[str]:
    return frozenset(p["name"] for p in get_partitions())


def get_schedule() -> dict:
    return {k: dict(v) for k, v in load_config().get("scheduler", DEFAULT_SCHEDULE).items()}


def get_ttl() -> dict:
    ttl = load_config().get("ttl") or {}
    return {
        "days": int(ttl.get("days", 30)),
        "mode": ttl.get("mode", "archive") if ttl.get("mode") in ("archive", "delete") else "archive",
    }


def get_write_worklog() -> bool:
    return bool(load_config().get("write_worklog", True))


def get_catch_up_hours() -> int:
    """启动补跑窗口（小时）；env WORKBENCH_CATCH_UP_HOURS 优先，0=禁用。默认 6。"""
    env = os.environ.get("WORKBENCH_CATCH_UP_HOURS", "").strip()
    if env:
        try:
            return max(0, min(168, int(env)))
        except ValueError:
            return 6
    try:
        return max(0, min(168, int(load_config().get("catch_up_hours", 6))))
    except (TypeError, ValueError):
        return 6


def _root_has_content(root: Path) -> bool:
    """root 分区目录下是否已有 .md 文件（新装安全网用）。"""
    root = Path(root)
    for p in get_partitions():
        d = root / p["name"]
        if d.is_dir() and any(d.glob("*.md")):
            return True
    return False


def get_storage_mode() -> str:
    """存储模式（A2）：env WORKBENCH_STORAGE_MODE > 配置 > 默认 dual。

    新装安全网：无配置文件且 root 已有 .md 内容 → 强制回退 dual
    （防误删/半成品：db_only 只影响收录/展示，执行回执二期前仍走文件）。
    """
    env = os.environ.get("WORKBENCH_STORAGE_MODE", "").strip().lower()
    if env in ("dual", "db_only", "file_only"):
        mode = env
    else:
        mode = str(load_config().get("storage_mode") or DEFAULT_STORAGE_MODE).strip().lower()
        if mode not in ("dual", "db_only", "file_only"):
            mode = DEFAULT_STORAGE_MODE
    if mode != "dual" and not CONFIG_FILE.exists():
        if _root_has_content(Path(get_root())):
            return "dual"
    return mode


# ---------------------------------------------------------------------------
# 分区辅助（目录创建 / 计数 / 时间换算）
# ---------------------------------------------------------------------------


def ensure_partition_dirs(root: Path | str, partitions: Optional[list[dict]] = None) -> list[str]:
    """确保每个分区目录存在；返回新建目录名列表。"""
    root = Path(root)
    created: list[str] = []
    for p in partitions or get_partitions():
        d = root / p["name"]
        if not d.is_dir():
            d.mkdir(parents=True, exist_ok=True)
            created.append(p["name"])
    return created


def partition_counts(root: Path | str) -> dict[str, int]:
    """各分区文件数（删除保护：非空分区不可删）。"""
    root = Path(root)
    out: dict[str, int] = {}
    for p in get_partitions():
        d = root / p["name"]
        if not d.is_dir():
            out[p["name"]] = 0
            continue
        out[p["name"]] = len(list(d.glob("*.md")))
    return out


def expr_to_time(expr: str) -> str:
    """'0 20 * * *' → '20:00'；无法解析 → 原样返回。"""
    parts = [p for p in str(expr or "").split() if p.strip()]
    if len(parts) == 5 and parts[0].isdigit() and parts[1].isdigit():
        return f"{int(parts[1]):02d}:{int(parts[0]):02d}"
    return expr


def time_to_expr(hhmm: str) -> str:
    """'20:00' → '0 20 * * *'；非法 → 抛 ValueError。"""
    m = re.match(r"^(\d{1,2}):(\d{2})$", str(hhmm or "").strip())
    if not m:
        raise ValueError(f"时间格式须为 HH:MM：{hhmm}")
    hour, minute = int(m.group(1)), int(m.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"时间超出范围：{hhmm}")
    return f"{minute} {hour} * * *"
