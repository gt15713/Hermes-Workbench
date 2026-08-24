"""workbench-view 插件后端 — Hermes 消息平台 QQ Bot 任务信息流工作台。

挂载：/api/plugins/workbench-view/*
数据源：工作台根目录（配置 root）下的分区目录。

P0 修复（2026-08-09 辩论收敛）：
- _parse_md frontmatter 解析：兼容「标题在前 → frontmatter 在后」的聚合文件（原正则锚定开头导致分区隐身）
- /file 路径穿越：filename 经 root 前缀校验
- /resolve 日志丢失：结构化判重替代子串匹配（同名聚合文件/日志误杀）
- rename 容错：PermissionError 重试 + 回退复制+删除 + 统一错误信封
- 匹配歧义：多候选返回列表（前端/QQ 可反问），不再静默取第一个
- 并发止血：进程内 threading.Lock + os.replace 原子写
"""
from __future__ import annotations

import asyncio
import logging
import os
import re

# P0 修复（2026-08-14）：web_server 用 spec_from_file_location 单文件加载插件
# api 文件，不把 dashboard 目录加入 sys.path——同目录模块（contract/repo/wb_utils）
# 必须由本文件显式插入（对齐 scripts/workbench_db_migrate.py 的做法）。
import sys as _sys
import threading
import time
from datetime import datetime
from pathlib import Path
from pathlib import Path as _Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

_DASHBOARD_DIR = str(_Path(__file__).resolve().parent)
if _DASHBOARD_DIR not in _sys.path:
    _sys.path.insert(0, _DASHBOARD_DIR)

from contract import (
    PARTITIONS,
    SCHEMA_VERSION,
)
from qq_health import assess_qq_health
from repo import _repo as file_repo
from wb_utils import (
    WORKBENCH_ROOT,
    _ensure_completed_at,
    _ensure_schema_version,
    _extract_frontmatter,
    _match_task,
    _maybe_defer,
    _parse_md,
    _patch_frontmatter,
    _replace_frontmatter_status,
    _safe_resolve,
    _slugify,
    _split_entry,
    detect_task_scope,
    existing_video_url,
)
from workbench_config import (
    DEFAULT_DELIVER_TARGET,
    DEFAULT_ROOT,
    DEFAULT_VAULT,
    ensure_partition_dirs,
    expr_to_time,
    get_deliver_target,
    get_partitions,
    get_root,
    get_schedule,
    get_ttl,
    get_vault,
    load_config,
    normalize_config,
    partition_counts,
    save_config,
)

router = APIRouter()
_log = logging.getLogger("workbench-view")


def _get_qq_health() -> dict:
    """Read QQ runtime evidence without opening a second connection or exposing identifiers."""
    hermes_home = Path(
        os.environ.get(
            "HERMES_HOME",
            str(_Path(__file__).resolve().parent.parent.parent.parent),
        )
    )
    return assess_qq_health(
        state_path=hermes_home / "gateway_state.json",
        log_path=hermes_home / "logs" / "gateway.log",
        adapter_path=hermes_home / "hermes-agent" / "gateway" / "platforms" / "qqbot" / "adapter.py",
    )

# 写操作全局锁（进程内串行化读-改-写；跨进程由调用方纪律+原子写兜底）
# 2026-08-09 多选批量：Lock → RLock（批量接口循环调用单条 handler 时同线程可重入，防死锁）
_WRITE_LOCK = threading.RLock()

# 目录显示顺序 + 标签色（前端用）——来自 contract.PARTITIONS（单一事实源）
DIRS = list(PARTITIONS)

# 08-21 研究≠摄入治理（B3）：research 任务会话的工作目录（默认落盘位置，读取不受限）
RESEARCH_CWD = (
    Path(os.environ.get("HERMES_HOME", str(_Path(__file__).resolve().parent.parent.parent.parent)))
    / "cache"
    / "workbench-research"
)


# 工具函数已收敛到 wb_utils.py（阶段 1 分层）——见顶部 import。


# ---------- 存储原语走 FileRepo（阶段 1：后端可替换） ----------

def _atomic_write(path, text, expected_mtime=None):
    """原子写：经 FileRepo（后端可替换）。expected_mtime = 读内容时的 mtime（阶段 2.5 并发防护）。"""
    file_repo.write_text(path, text, expected_mtime=expected_mtime)


def _rename_with_retry(src, dst):
    """move 容错：经 FileRepo。"""
    return file_repo.move(src, dst)


def _log_action(action, detail):
    """工作台日志：经 FileRepo。"""
    file_repo.append_action_log(action, detail)


def _append_log(log_path, section_title, entry):
    """归档索引日志：经 FileRepo（去重）。"""
    file_repo.append_done_log(log_path, section_title, entry)


def _remove_done_index_entry(stem: str) -> None:
    """reopen 回任务列表时，从 已处理 每日索引移除对应条目。

    索引只反映当前已完成项；条目本身的完成/重开历史保留在任务文件里。
    """
    done_dir = WORKBENCH_ROOT / "已处理"
    if not done_dir.is_dir():
        return
    for idx in sorted(done_dir.glob("*.md")):
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", idx.stem):
            continue
        try:
            text = idx.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if f"[[{stem}|" not in text and f"[[{stem}]]" not in text:
            continue
        lines = text.splitlines()
        # 记录每行所属小节（## 标题）
        section_of: dict[int, str] = {}
        current = ""
        for i, line in enumerate(lines):
            m = re.match(r"^##\s+(.+)（(\d+)\s*条）\s*$", line)
            if m:
                current = m.group(1)
            section_of[i] = current
        remove_idx = [
            i for i, line in enumerate(lines)
            if re.match(r"^-\s*\[\[" + re.escape(stem) + r"[|\]]", line)
        ]
        if not remove_idx:
            continue
        by_section: dict[str, int] = {}
        for i in remove_idx:
            sec = section_of.get(i, "")
            by_section[sec] = by_section.get(sec, 0) + 1
        out: list[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            m = re.match(r"^(##\s+.+?)（(\d+)\s*条）\s*$", line)
            if m:
                sec_name = m.group(1)
                n = int(m.group(2)) - by_section.get(sec_name, 0)
                if n > 0:
                    out.append(f"## {sec_name}（{n} 条）")
                i += 1
                continue
            if i in remove_idx:
                i += 1
                continue
            out.append(line)
            i += 1
        _atomic_write(idx, "\n".join(out).strip("\n") + "\n")
        _log_action("移除已处理索引条目", f"「{stem}」reopen 回任务列表")



# ---------- API ----------

@router.get("/board")
def board() -> dict:
    """聚合六个目录 → 每条目一卡。

    R4 阶段 2/3 改造：
    - 移除读路径 _maybe_defer 副作用（顺延改显式 POST /defer，GET 零写）
    - 计数改条目级（聚合文件 N 条 = N，而非按文件计 1）
    - 回收站分区不参与 pending 计数（排除 status:todo 污染）
    - 去除 files[:6]/entries[:8] 截断，返回真实 entry_count

    R4 阶段 A3：async def → def——无 await 的端点用同步 def，FastAPI 自动
    放线程池执行，同步磁盘 IO 不再阻塞事件循环（08-09 曾踩 272s 阻塞）。

    P0-3（B2）：读时懒同步——board 加载前 sync_from_files()（仅 DB 读模式）；
    外部编辑（Obsidian 手改）最长漂移窗口从 24h 降到本次请求。失败不影响读取（日志告警）。
    """
    if getattr(file_repo, "read_from_db", True) and not os.environ.get("WORKBENCH_READ_FROM_DB", "").strip() == "0":
        try:
            file_repo.sync_from_files()
        except Exception:  # noqa: BLE001
            logging.getLogger("workbench").warning("sync_from_files failed", exc_info=True)
    sections = []
    totals = {"pending": 0, "total": 0}

    for p in get_partitions():
        dirname, key = p["name"], p["type"]
        files = []
        # 阶段 2：文件列表走 repo（读切 DB 事实源，按 mtime 倒序由 SqliteRepo 排序）
        for f in file_repo.list_files(dirname):
            info = _parse_md(f)
            status = info["status"]
            n_entries = len(info["entries"])
            # 分区类型判定（2026-08-15 P0 修复：多行分裂 bug）：
            #   aggregation（待验证/待回看/心理学随想/梦中的邮件）→ 按条目展开
            #   single_card（任务/回收站/已处理的单任务文件）→ 整文件一卡
            is_aggregation = key in {"thought", "video", "psych", "dream"}
            if key == "done":
                # 已处理/ 混合分区：日期格式名（YYYY-MM-DD.md）= 聚合目录索引，按条目展开
                # 其余 = 已归档的任务/条目文件，整文件一卡
                is_aggregation = bool(re.match(r"^\d{4}-\d{2}-\d{2}\.md$", info["file"]))
                # 08-21：已处理日期索引不渲染成卡（消除「任务文件+索引条目」双卡观感）；
                # 索引文件保留在磁盘/DB，供日报与审计读取，仅不进看板分区。
                if is_aggregation:
                    continue
            if not is_aggregation:
                # 单卡文件：不按条目展开，item_count=1
                item_count = 1
                info["entry_count"] = 0
                info["entries"] = []
            else:
                # 聚合文件：按条目计数
                # 空壳文件（全条目已处理，只剩 frontmatter）按 0 计，不虚增 pending/total
                item_count = n_entries
                info["entry_count"] = n_entries
            if status in ("pending", "todo") and key != "trash":
                totals["pending"] += item_count
            totals["total"] += item_count
            files.append(info)
        sections.append({"dir": dirname, "key": key, "label": dirname, "files": files})

    return {
        "root": str(WORKBENCH_ROOT),
        "updated_at": datetime.now().strftime("%H:%M:%S"),
        "today": datetime.now().strftime("%Y-%m-%d"),
        "totals": totals,
        "sections": sections,
    }


@router.get("/settings")
def get_settings() -> dict:
    """设置面板：当前配置 + 生效值 + 分区文件数 + 重启生效标记。"""
    cfg = load_config()
    counts = partition_counts(Path(get_root()))
    scheduler_ui: dict = {}
    for key, item in get_schedule().items():
        row = {"enabled": bool(item.get("enabled", True))}
        if key != "lifecycle":
            row["time"] = expr_to_time(item.get("expr", ""))
        scheduler_ui[key] = row
    partitions_ui = []
    for p in get_partitions():
        partitions_ui.append({**p, "count": counts.get(p["name"], 0)})
    db_path = ""
    try:
        db_path = str(getattr(file_repo, "db", None).db_path) if getattr(file_repo, "db", None) else ""
    except Exception:  # noqa: BLE001
        db_path = ""
    return {
        "ok": True,
        "config": {
            "version": 1,
            "root": str(cfg.get("root") or DEFAULT_ROOT),
            "vault": str(cfg.get("vault") or DEFAULT_VAULT),
            "deliver_target": str(cfg.get("deliver_target") or DEFAULT_DELIVER_TARGET),
            "partitions": partitions_ui,
            "scheduler": scheduler_ui,
            "ttl": get_ttl(),
            "write_worklog": bool(cfg.get("write_worklog", True)),
        },
        "effective": {
            "root": get_root(),
            "vault": get_vault(),
            "deliver_target": get_deliver_target(),
            "db": db_path,
        },
        "restart_required": ["root", "vault"],
    }


@router.post("/settings")
def update_settings(body: dict) -> dict:
    """保存设置：校验 → 分区增删（非空保护）→ 建目录 → 原子写配置。"""
    try:
        normalized = normalize_config(body or {})
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    old = load_config()
    old_names = {p["name"] for p in old.get("partitions", [])}
    new_names = {p["name"] for p in normalized["partitions"]}
    removed = old_names - new_names
    counts = partition_counts(Path(get_root()))
    for name in removed:
        n = counts.get(name, 0)
        if n > 0:
            return {"ok": False, "error": f"分区「{name}」非空（{n} 个文件），不能删除"}
    for name in removed:
        d = Path(get_root()) / name
        try:
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
        except OSError:
            pass  # 空目录清理失败不阻塞保存

    # P0-B 修正：分区目录建在「生效 root」（env 优先）而非配置字符串——
    # 否则测试/新装时 config root 与实际 root 不一致会建错位置。
    created = ensure_partition_dirs(Path(get_root()), normalized["partitions"])
    try:
        save_config(normalized)
    except OSError as exc:
        return {"ok": False, "error": f"保存失败：{exc}"}
    return {
        "ok": True,
        "saved": True,
        "created_partitions": created,
        "removed_partitions": sorted(removed),
        "restart_required": ["root", "vault"],
    }


@router.get("/search")
def search(q: str = "", tag: str = "", limit: int = 50) -> dict:
    """A4 全局搜索 + A5 标签过滤（读路径与 /board 同源）。

    - q：标题/文件名/正文/tags 子串匹配（大小写不敏感，中文按子串）
    - tag：仅返回 frontmatter tags 包含该标签的文件
    - 每条结果关联最近 3 条 task_events（运行历史摘要，复用 /recent 链路）
    - 排序：mtime 倒序（与 /board 一致）；limit 默认 50
    """
    query = (q or "").strip().lower()
    tag_q = (tag or "").strip()
    results: list[dict] = []
    for p in get_partitions():
        dirname, key = p["name"], p["type"]
        for f in file_repo.list_files(dirname):
            try:
                info = _parse_md(f)
                text = file_repo.read_text(f) or ""
            except OSError:
                continue
            tags = info.get("tags") or []
            if tag_q and tag_q not in tags:
                continue
            if query:
                haystack = " ".join(
                    [info["title"], info["file"], text, *tags]
                ).lower()
                if query not in haystack:
                    continue
            try:
                evts = file_repo.db.list_file_events(dirname, info["file"], limit=3)
            except Exception:  # noqa: BLE001
                evts = []
            results.append(
                {
                    "dir": dirname,
                    "key": key,
                    "file": info["file"],
                    "title": info["title"],
                    "status": info["status"],
                    "mtime": info["mtime"],
                    "priority": info["priority"],
                    "size": info["size"],
                    "tags": tags,
                    "entry_count": info.get("entry_count", 0),
                    "events": evts,
                }
            )
    results.sort(key=lambda r: str(r["mtime"]), reverse=True)
    return {"results": results[:limit], "total": len(results), "q": q, "tag": tag}


def _ws_upgrade_authorized(ws) -> bool:
    """对齐官方 kanban：委托 dashboard 的 canonical WS 鉴权门（token/ticket/internal 全模式）。

    延迟 import：测试环境（无 hermes_cli.web_server）时接受，保持可测性。
    """
    try:
        from hermes_cli import web_server as _ws
    except Exception:  # noqa: BLE001
        return True
    return bool(_ws._ws_auth_ok(ws))


@router.websocket("/events")
async def ws_events(ws: WebSocket):
    """事件通道 WebSocket（阶段 4；对齐官方 kanban task_events WS 模式）。

    - 鉴权：_ws_upgrade_authorized（query token/ticket/internal，浏览器无法设 WS header）；
    - 断点：query `since` 初始游标（前端重连传已见最大 id，消除历史重放）；
    - 推送：每秒查 task_events 增量 → send_json({"events": [...], "cursor": N})；
    - 无新事件时发 {"heartbeat": true} 保活（5s 间隔）。
    """
    if not _ws_upgrade_authorized(ws):
        await ws.close(code=1008)
        return
    await ws.accept()
    try:
        try:
            cursor = int(ws.query_params.get("since", "0") or 0)
        except (TypeError, ValueError):
            cursor = 0
        last_beat = time.monotonic()
        while True:
            try:
                evts = file_repo.db.list_events(since_id=cursor, limit=200)
            except Exception as e:  # noqa: BLE001
                logging.getLogger("workbench").warning("events read failed: %s", e)
                evts = []
            if evts:
                cursor = max(cursor, max(int(e["id"]) for e in evts))
                await ws.send_json({"events": evts, "cursor": cursor})
            elif time.monotonic() - last_beat >= 5:
                await ws.send_json({"heartbeat": True})
                last_beat = time.monotonic()
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        return
    except asyncio.CancelledError:
        return
    except Exception as exc:  # noqa: BLE001 defensive：不崩 worker
        logging.getLogger("workbench").warning("ws events error: %s", exc)
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass


# P0-1（B4）：Briefing 惰性缓存（BRIEF_CACHE_MINUTES 已拍板=30；env 可覆盖）
_BRIEF_CACHE: dict = {"ts": 0.0, "payload": None}


@router.post("/brief")
def brief() -> dict:
    """P0-1（B4）：Agent Briefing——惰性生成今日建议卡（≤5 张，5 类）。

    - 缓存：后端内存 BRIEF_CACHE_MINUTES（默认 30）命中直接返回；前端会话缓存叠加
    - 生成通道：subprocess `hermes -z <prompt>`（headless prompt；进程隔离不干扰主 Agent；
      复用 Hermes 配置/fallback/成本记账；零新依赖）
    - 失败/超时/解析失败 → degraded=true（前端规则型降级 + 「Agent 简报暂不可用」）
    - 不落盘、不写 Workbench（只读 board 数据 + 内存建议）
    """
    import json
    import subprocess
    import time as _time

    now = _time.time()
    cache_min = int(os.environ.get("WORKBENCH_BRIEF_CACHE_MINUTES", "30") or 30)
    if _BRIEF_CACHE["payload"] and now - _BRIEF_CACHE["ts"] < cache_min * 60:
        return _BRIEF_CACHE["payload"]

    # 输入构造：board 精简视图（任务区 in_progress/超期/todo + 各分区计数）
    try:
        board_data = board()  # 复用 /board 读路径（含懒同步）
        tasks = []
        for section in board_data.get("sections", []):
            for card in section.get("files", []):
                if section["key"] == "task" and card.get("status") in ("todo", "in_progress"):
                    tasks.append(f"- [{card.get('status')}] {card.get('title')} (due={card.get('due') or '无'})")
        summary_lines = []
        for section in board_data.get("sections", []):
            n = len(section.get("files", []))
            if n:
                summary_lines.append(f"{section['key']}: {n} 条")
        summary = "；".join(summary_lines)
        tasks_text = "\n".join(tasks[:40]) or "（无活跃任务）"
        prompt = (
            "你是 Hermes Workbench 的每日简报助手。基于以下工作台数据生成今日建议，"
            "最多 5 条。类别仅限：new_task（建议新任务）/duplicate（可能重复）/blocked（被阻塞）/overdue（超期需重估）/decision（需要用户决策）。"
            "只输出一个 JSON 数组，每条：{\"type\":\"...\",\"title\":\"...\",\"reason\":\"...\",\"action\":\"...\"}。"
            "不要输出 JSON 之外任何文字。\n\n"
            f"工作台概况：{summary}\n活跃任务：\n{tasks_text}\n"
        )
        # 会话列表隔离：oneshot 标记 source=tool（CLI 约定：tool 来源不出现在用户会话列表）
        _brief_env = {**os.environ, "HERMES_SESSION_SOURCE": "tool"}
        r = subprocess.run(
            ["hermes", "-z", prompt],
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            errors="replace",
            env=_brief_env,
        )
        out = (r.stdout or "").strip()
        m = re.search(r"\[.*\]", out, re.S)
        if not m:
            raise ValueError("no json array in output")
        cards = json.loads(m.group(0))
        if not isinstance(cards, list):
            raise ValueError("not a list")
        cards = [c for c in cards if isinstance(c, dict) and c.get("type") in (
            "new_task", "duplicate", "blocked", "overdue", "decision"
        )][:5]
        payload = {
            "ok": True,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "cards": cards,
            "degraded": False,
        }
    except Exception as e:  # noqa: BLE001
        logging.getLogger("workbench").warning("brief generation failed: %s", e)
        payload = {
            "ok": True,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "cards": [],
            "degraded": True,
        }
    _BRIEF_CACHE["ts"] = now
    _BRIEF_CACHE["payload"] = payload
    return payload


@router.get("/health")
def health() -> dict:
    """链路健康：Workbench 子系统 + 只读 QQ 传输/摄取/兼容性证据。"""
    import json as _json

    try:
        db_ok = file_repo.db.health()
    except Exception:  # noqa: BLE001
        db_ok = False
    plugin_root = _Path(_DASHBOARD_DIR).parent
    scheduler_alive = False
    try:
        lock = _json.loads((plugin_root / "scheduler.lock").read_text(encoding="utf-8"))
        hb = datetime.fromisoformat(lock.get("heartbeat_at", ""))
        scheduler_alive = (datetime.now() - hb).total_seconds() < 180
    except Exception:  # noqa: BLE001 - 租约缺失/损坏 → 视为未存活
        scheduler_alive = False
    state: dict = {}
    try:
        state = _json.loads((plugin_root / "scheduler-state.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        state = {}
    from scheduler import _active_errors

    error_count, last_error = _active_errors(state)
    delivery_pending = bool(state.get("pending_delivery"))
    vault_configured = bool(get_vault())
    qq = _get_qq_health()
    checks = [
        {
            "id": "database",
            "label": "工作台数据库",
            "status": "green" if db_ok else "red",
            "detail": "可读写" if db_ok else "不可用",
        },
        {
            "id": "scheduler",
            "label": "定时调度器",
            "status": "green" if scheduler_alive else "red",
            "detail": "心跳正常" if scheduler_alive else "心跳超时或未启动",
        },
        {
            "id": "delivery",
            "label": "消息投递",
            "status": "red" if error_count > 0 else ("yellow" if delivery_pending else "green"),
            "detail": (
                f"未解决错误 {error_count} 项"
                if error_count > 0
                else ("等待重试" if delivery_pending else "无待处理故障")
            ),
        },
        {
            "id": "vault",
            "label": "Obsidian 写入",
            "status": "green" if vault_configured else "yellow",
            "detail": "已配置" if vault_configured else "未配置（不影响工作台）",
        },
        {
            "id": "qq_transport",
            "label": "QQ 连接",
            **qq["transport"],
        },
        {
            "id": "qq_c2c",
            "label": "QQ 私聊摄取",
            **qq["c2c"],
        },
        {
            "id": "qq_group",
            "label": "QQ 群 @ 摄取",
            **qq["group"],
        },
        {
            "id": "qq_full_group",
            "label": "QQ 普通群消息",
            **qq["full_group"],
        },
    ]
    statuses = {check["status"] for check in checks}
    status = "red" if "red" in statuses else ("yellow" if "yellow" in statuses else "green")
    label = {"green": "链路正常", "yellow": "链路待观察", "red": "链路故障"}[status]
    return {
        "ok": True,
        "db": db_ok,
        "scheduler_alive": scheduler_alive,
        "error_count": error_count,
        "last_error": last_error,
        "delivery_pending": delivery_pending,
        "vault_configured": vault_configured,
        "qq": qq,
        "status": status,
        "label": label,
        "checks": checks,
        "last_updated": state.get("updated_at"),
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


@router.get("/recent")
def recent(limit: int = 10, dir: str = "", file: str = "") -> dict:
    """最近动作（Task 5.2 批次 1 扩展）。

    - 无 dir/file：R4 阶段 A4 原行为——读 日志/YYYY-MM-DD.md 最近 N 条动作记录
      （返回 [{"ts": "HH:MM", "action": "…", "detail": "…"}, ...] 时间倒序）
    - 提供 dir+file：读 task_events 按 partition+filename 过滤（created_at 倒序）
      （抽屉「运行历史」标签页数据源，复用本端点不新增）
    """
    if dir and file:
        try:
            evts = file_repo.db.list_file_events(dir, file, limit=limit)
        except Exception:  # noqa: BLE001
            evts = []
        return {"entries": evts, "source": "task_events"}


    LOG_DIR = WORKBENCH_ROOT / "日志"
    entries = []
    if LOG_DIR.is_dir():
        files = sorted(LOG_DIR.glob("*.md"), reverse=True)[:3]  # 最近 3 天
        for f in files:
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            # 格式：## HH:MM action\n\n- detail
            cur = None
            for line in text.splitlines():
                m = re.match(r"^## (\d{2}:\d{2})\s+(.+)$", line)
                if m:
                    if cur:
                        entries.append(cur)
                    cur = {"ts": m.group(1), "action": m.group(2), "detail": "", "date": f.stem}
                    continue
                if cur and cur["detail"] == "" and line.startswith("- "):
                    cur["detail"] = line[2:].strip()
            if cur:
                entries.append(cur)
    entries = entries[-limit:][::-1]  # 最近 limit 条，时间正序
    return {"entries": entries}


@router.post("/batch")
async def batch(body: dict) -> dict:
    """批量动作（2026-08-09 多选功能）：一次处理多个条目/文件。

    body={
        "action": "resolve" | "to-task" | "trash" | "complete",
        "items": [{"dir": ..., "file": ..., "entry_title"?: ...}, ...],
    }
    - resolve/to-task：支持条目级（entry_title）与文件级（无 entry_title），复用单条逻辑
    - trash/complete：文件级（entry_title 忽略）
    汇总结果一次返回，动作日志统一写一条批量记录。
    """
    action = body.get("action", "")
    items = body.get("items") or []
    if action not in {"resolve", "to-task", "trash", "complete"}:
        return {"ok": False, "error": "bad action"}
    if not items or not isinstance(items, list):
        return {"ok": False, "error": "items required"}

    done, failed = [], []
    for it in items:
        # 逐项调用单条 handler（同线程 RLock 可重入，不会死锁）
        try:
            if action == "resolve":
                r = await resolve(it)
            elif action == "to-task":
                r = await to_task(it)
            elif action == "trash":
                r = await trash(it)
            else:
                r = await complete(it)
            if r.get("ok"):
                done.append({"dir": it.get("dir"), "file": r.get("file") or it.get("file"), "entry": it.get("entry_title") or "", "detail": r})
            else:
                failed.append({"dir": it.get("dir"), "file": it.get("file"), "entry": it.get("entry_title") or "", "error": r.get("error") or "failed"})
        except Exception as e:
            failed.append({"dir": it.get("dir"), "file": it.get("file"), "entry": it.get("entry_title") or "", "error": str(e)})

    # 统一一条批量日志（不逐条刷）
    if done:
        action_cn = {"resolve": "批量确认处理", "to-task": "批量转任务", "trash": "批量移入回收站", "complete": "批量完成"}.get(action, action)
        _log_action(action_cn, f"{len(done)} 项成功" + (f"，{len(failed)} 项失败" if failed else "") + "：" + "、".join(
            f"{d['file']}" + (f"#{d['entry']}" if d["entry"] else "") for d in done[:20]
        ) + (" 等" if len(done) > 20 else ""))

    return {"ok": not failed or bool(done), "done": done, "failed": failed, "summary": {"ok": len(done), "fail": len(failed)}}


@router.get("/file")
async def read_file(dirname: str, filename: str) -> dict:
    """读取单个文件全文（前端点开查看）。"""
    p = _safe_resolve(dirname, filename)
    if p is None:
        return {"error": "bad dir or path"}
    if not p.is_file():
        return {"error": "not found"}
    return {"dir": dirname, "file": filename, "content": p.read_text(encoding="utf-8", errors="replace")}


@router.post("/abandon")
async def abandon(body: dict) -> dict:
    """放弃任务 → 移入回收站（2026-08-16 拍板：放弃 = 可逆暂别）。

    body={"dir": "任务", "file": "xxx.md"} 或 {"title": "任务标题"}
    status: todo → abandoned；文件移入回收站（保留 abandoned 标记 + origin + trashed_at，可还原）。
    还原时 abandoned → todo 复活（见 /restore）。区别于「永久删除」：永久删除仅存在于
    已处理/回收站内、二次确认后彻底抹除；放弃是可逆暂别。
    """
    from datetime import date as _date

    with _WRITE_LOCK:
        target = None
        if body.get("file") and body.get("dir"):
            cand = _safe_resolve(body["dir"], body["file"])
            if cand and cand.is_file():
                target = cand
        elif body.get("title"):
            cands = _match_task(body["title"])
            if len(cands) == 1:
                target = cands[0]
            elif len(cands) > 1:
                return {"ok": False, "error": "ambiguous", "candidates": [c.stem for c in cands]}
        if target is None:
            return {"ok": False, "error": "task not found"}

        text = target.read_text(encoding="utf-8", errors="replace")
        new_text = _replace_frontmatter_status(text, "todo", "abandoned")
        if new_text == text:
            return {"ok": False, "error": "only todo tasks can be abandoned"}
        today = _date.today().strftime("%Y-%m-%d")
        new_text = _patch_frontmatter(new_text, {"abandoned_at": today}) if "abandoned_at:" not in new_text else new_text
        new_text += f"\n## 放弃记录\n\n- {today} 已放弃（移入回收站，可还原）\n"
        if "origin:" not in new_text:
            new_text = _patch_frontmatter(new_text, {"origin": f"任务/{target.name}", "trashed_at": today})
        _atomic_write(target, new_text)
        # 移入回收站（与 /trash 同流程：唯一化防重名）
        trash_dir = WORKBENCH_ROOT / "回收站"
        trash_dir.mkdir(exist_ok=True)
        dest = trash_dir / target.name
        if dest.exists():
            dest = trash_dir / (target.stem + "-dup" + target.suffix)
        _rename_with_retry(target, dest)
        file_repo.event("回收站", dest.name, "abandon", f"放弃移入回收站（原 任务/{target.name}）")
        _log_action("放弃任务（移入回收站）", f"任务「{target.stem}」{today} 放弃")
        return {"ok": True, "file": dest.name, "abandoned": True, "abandoned_at": today, "moved_to": "回收站"}


@router.post("/reopen")
async def reopen(body: dict) -> dict:
    """重新打开已放弃任务 / 已处理任务回到任务列表（R4 阶段 5 + Task 5.2 批次 2）。

    body={"dir": "任务", "file": "xxx.md"} → abandoned → todo（保留 abandoned_at 改 reopened_at）
    body={"dir": "已处理", "file": "xxx.md"} → cleared|completed → todo + 移回 任务/（保留 completed_at 历史，加 reopened_at）
    """
    from datetime import date as _date

    with _WRITE_LOCK:
        target = None
        if body.get("file") and body.get("dir"):
            cand = _safe_resolve(body["dir"], body["file"])
            if cand and cand.is_file():
                target = cand
        elif body.get("title"):
            cands = _match_task(body["title"])
            if len(cands) == 1:
                target = cands[0]
            elif len(cands) > 1:
                return {"ok": False, "error": "ambiguous", "candidates": [c.stem for c in cands]}
        if target is None:
            return {"ok": False, "error": "task not found"}

        mt = target.stat().st_mtime
        text = target.read_text(encoding="utf-8", errors="replace")
        today = _date.today().strftime("%Y-%m-%d")
        dirname = str(body.get("dir") or "")

        # 分支：已处理 → 任务区（跨分区移动 + DB 镜像同步）
        if dirname == "已处理":
            new_text = _replace_frontmatter_status(text, "cleared", "todo")
            if new_text == text:
                new_text = _replace_frontmatter_status(new_text, "completed", "todo")
            if new_text == text:
                return {"ok": False, "error": "only done tasks can be moved back"}
            # completed_at 保留为历史；补 reopened_at
            if "reopened_at:" not in new_text:
                new_text = _patch_frontmatter(new_text, {"reopened_at": today})
            new_text += f"\n## 重新打开记录\n\n- {today} 已回到任务列表\n"
            _atomic_write(target, new_text, expected_mtime=mt)
            # 移回任务区（_rename_with_retry = file_repo.move：tasks 行迁移 + moved 事件）
            task_dir = WORKBENCH_ROOT / "任务"
            task_dir.mkdir(exist_ok=True)
            dest = task_dir / target.name
            if dest.exists():
                dest = task_dir / (target.stem + "-" + _slugify(target.stem)[:12] + target.suffix)
            _rename_with_retry(target, dest)
            file_repo.event("任务", dest.name, "reopen", f"回到任务列表（原 已处理/{target.name}）")
            _log_action("回到任务列表", f"「{target.stem}」从 已处理 移回 任务")
            _remove_done_index_entry(target.stem)
            return {"ok": True, "file": dest.name, "reopened": True, "moved_from": "已处理"}

        # 分支：任务区 abandoned → todo（原逻辑）
        new_text = _replace_frontmatter_status(text, "abandoned", "todo")
        if new_text == text:
            return {"ok": False, "error": "only abandoned tasks can be reopened"}
        # 把 abandoned_at 改名为 reopened_at（保留历史），无则补 reopened_at
        if "abandoned_at:" in new_text:
            new_text = re.sub(r"^abandoned_at:.*$", f"reopened_at: {today}", new_text, count=1, flags=re.M)
        else:
            new_text = _patch_frontmatter(new_text, {"reopened_at": today})
        new_text += f"\n## 重新打开记录\n\n- {today} 已恢复为待办\n"
        _atomic_write(target, new_text, expected_mtime=mt)

    _log_action("重新打开任务", f"任务「{target.stem}」{_date.today().strftime('%Y-%m-%d')} 恢复待办")
    return {"ok": True, "file": target.name, "reopened": True}


@router.post("/complete")
async def complete(body: dict) -> dict:
    """完成任务：patch status → completed + 追加完成记录 + 归档到已处理/。

    支持两种定位：
    - 精确：body={"dir": "任务", "file": "xxx.md"}
    - 标题匹配：body={"title": "整理Skill"}（多候选返回 candidates 供反问）
    """
    from datetime import date as _date

    with _WRITE_LOCK:
        # 定位任务文件
        target = None
        if body.get("file") and body.get("dir"):
            cand = _safe_resolve(body["dir"], body["file"])
            if cand and cand.is_file():
                target = cand
        elif body.get("title"):
            cands = _match_task(body["title"])
            if len(cands) == 1:
                target = cands[0]
            elif len(cands) > 1:
                return {
                    "ok": False,
                    "error": "ambiguous",
                    "candidates": [c.stem for c in cands],
                    "message": "匹配到多个任务，请确认标题",
                }
        if target is None:
            return {"ok": False, "error": "task not found"}

        # patch status（仅 frontmatter 内替换，避免正文误伤）
        mt = target.stat().st_mtime  # 阶段 2.5：expected_mtime 并发防护
        text = target.read_text(encoding="utf-8", errors="replace")
        frontmatter = _extract_frontmatter(text)[0] or {}
        current_status = str(frontmatter.get("status") or "").strip()
        execution_result = str(frontmatter.get("execution_result") or "").strip().lower()
        if current_status == "in_progress" and execution_result != "success":
            return {"ok": False, "error": "execution result required"}
        new_text = _replace_frontmatter_status(text, "todo", "completed")
        if new_text == text:
            # 2026-08-17：执行完成（in_progress）的任务也允许归档
            new_text = _replace_frontmatter_status(text, "in_progress", "completed")
        if new_text == text:
            # 兼容旧会话监测器或外部 Agent 已直接写成 completed 的任务。
            # 仍在任务区时必须由此唯一正式入口补齐记录并移动归档。
            frontmatter = _extract_frontmatter(text)[0] or {}
            if frontmatter.get("status") != "completed":
                return {"ok": False, "error": "already completed or no todo status"}
            new_text = text
        today = _date.today().strftime("%Y-%m-%d")
        new_text = _ensure_completed_at(new_text, today)
        new_text = _ensure_schema_version(new_text)
        if "## 完成记录" not in new_text:
            new_text += f"\n## 完成记录\n\n- {today} 已标记完成\n"
        _atomic_write(target, new_text, expected_mtime=mt)

        # 归档：移动到 已处理/（R4 阶段 1 修复：同名冲突时强制唯一化文件名，
        # 杜绝「用户以为归档成功实际任务留在原地」的静默说谎）
        done_dir = WORKBENCH_ROOT / "已处理"
        done_dir.mkdir(exist_ok=True)
        dest = done_dir / target.name
        if dest.exists():
            dest = done_dir / (target.stem + "-" + _slugify(target.stem)[:12] + target.suffix)
        _rename_with_retry(target, dest)

        # 追加已处理日志（结构化去重）
        log = done_dir / f"{today}.md"
        _append_log(log, "任务（1 条）", f"[[{dest.stem}|{target.stem}]] — 标记完成")

    _log_action("完成 → 已处理", f"任务「{target.stem}」{_date.today().strftime('%Y-%m-%d')} 标记完成")
    return {"ok": True, "file": target.name, "archived": True, "archived_as": dest.name, "completed_at": today}


@router.post("/resolve")
async def resolve(body: dict) -> dict:
    """确认/归档：把 pending/queued 条目标记为已处理并移入 已处理/。

    body={"dir": "待验证"|"待回看"|"梦中的邮件", "file": "xxx.md"}
    body 可选 entry_title：指定聚合文件内某条 ## 条目 → 只归档该条目（拆条目不拆文件）
    """
    from datetime import date as _date

    with _WRITE_LOCK:
        if body.get("dir") not in {"待验证", "待回看", "梦中的邮件", "心理学随想"}:
            return {"ok": False, "error": "bad dir"}
        p = _safe_resolve(body["dir"], body.get("file", ""))
        if p is None or not p.is_file():
            return {"ok": False, "error": "not found"}

        mt = p.stat().st_mtime  # 阶段 2.5：expected_mtime 并发防护
        text = p.read_text(encoding="utf-8", errors="replace")
        entry_title = (body.get("entry_title") or "").strip()

        if entry_title:
            # 拆条目不拆文件：只归档目标条目
            try:
                remaining, section_text = _split_entry(text, entry_title)
            except ValueError as e:
                return {"ok": False, "error": str(e)}
            today = _date.today().strftime("%Y-%m-%d")
            # R4 C1：沉淀二元标记（sunk=已沉淀到笔记体系 / 默认仅归档）
            sunk = body.get("sunk") or ""
            sunk_line = f"sunk: {sunk}\n" if sunk else ""
            sunk_note = f"- {today} 已沉淀（{sunk}）\n" if sunk else ""
            new_file_name = p.stem + "-" + _slugify(entry_title) + ".md"
            new_content = (
                f"---\ntype: queued\nstatus: cleared\n"
                f"category: {body.get('category', '')}\n"
                f"completed_at: {today}\n"
                f"origin: {body['dir']}/{p.name}\n"
                f"{sunk_line}"
                "---\n\n"
                f"# {entry_title}\n\n"
                f"{section_text}\n\n"
                f"## 处理记录\n\n- {today} 已确认处理（条目级）\n{sunk_note}"
            )
            done_dir = WORKBENCH_ROOT / "已处理"
            done_dir.mkdir(exist_ok=True)
            dest = done_dir / new_file_name
            _atomic_write(dest, new_content)
            _atomic_write(p, remaining, expected_mtime=mt)  # 原文件并发防护（dest 新建不校验）
            log = done_dir / f"{today}.md"
            _append_log(log, "已确认（1 条）", f"[[{dest.stem}|{entry_title}]] — 条目级，来自 {body['dir']}" + ("，已沉淀" if sunk else ""))
            _log_action("确认条目 → 已处理", f"「{entry_title}」从 {body['dir']}/{p.name} 拆出归档" + (f"（沉淀：{sunk}）" if sunk else ""))
            file_repo.event(body["dir"], p.name, "resolved", f"确认条目「{entry_title}」→ 已处理")
            return {"ok": True, "file": dest.name, "archived": True, "entry": entry_title, "sunk": sunk or None}

        # 文件级（向后兼容）
        new_text = _replace_frontmatter_status(text, "pending", "cleared")
        if new_text == text:
            new_text = _replace_frontmatter_status(new_text, "todo", "cleared")
        today = _date.today().strftime("%Y-%m-%d")
        new_text = _ensure_completed_at(new_text, today)
        new_text = _ensure_schema_version(new_text)
        # R4 C1：沉淀二元标记
        sunk = body.get("sunk") or ""
        if sunk:
            new_text = _patch_frontmatter(new_text, {"sunk": sunk})
        new_text += f"\n## 处理记录\n\n- {today} 已确认处理\n" + (f"- {today} 已沉淀（{sunk}）\n" if sunk else "")
        _atomic_write(p, new_text, expected_mtime=mt)

        done_dir = WORKBENCH_ROOT / "已处理"
        done_dir.mkdir(exist_ok=True)
        dest = done_dir / p.name
        if not dest.exists():
            _rename_with_retry(p, dest)

        # 追加已处理日志：结构化判重（不依赖 stem 子串，避免与日志同名误杀）
        log = done_dir / f"{today}.md"
        _append_log(log, "已确认（1 条）", f"[[{dest.stem}|{dest.stem}]] — 来自 {body['dir']}" + ("，已沉淀" if sunk else ""))

    _log_action("确认处理 → 已处理", f"「{p.stem}」来自 {body['dir']} 已确认" + (f"（沉淀：{sunk}）" if sunk else ""))
    file_repo.event(body["dir"], p.name, "resolved", f"确认处理「{p.stem}」→ 已处理")
    return {"ok": True, "file": p.name, "archived": True, "sunk": sunk or None}


@router.post("/to-task")
async def to_task(body: dict) -> dict:
    """转任务：把 待验证/待回看 条目文件转为正式任务（复制到 任务/ 并标记原文件已转）。"""
    from datetime import date as _date

    with _WRITE_LOCK:
        # 08-21：+心理学随想（【温暖和踏实…】卡执行转任务报 bad dir 根因）
        if body.get("dir") not in {"待验证", "待回看", "梦中的邮件", "心理学随想"}:
            return {"ok": False, "error": "bad dir"}
        p = _safe_resolve(body["dir"], body.get("file", ""))
        if p is None or not p.is_file():
            return {"ok": False, "error": "not found"}

        text = p.read_text(encoding="utf-8", errors="replace")
        entry_title = (body.get("entry_title") or "").strip()
        title = (body.get("title") or entry_title or p.stem).strip()
        # R4 阶段 1 修复：任务文件名经 _slugify 清洗（防 Windows 非法字符异常）
        task_path = WORKBENCH_ROOT / "任务" / f"{_slugify(title)}.md"
        if task_path.exists():
            return {"ok": False, "error": "task already exists: " + title}

        today = _date.today().strftime("%Y-%m-%d")
        if entry_title:
            # 条目级：拆出目标小节作为任务内容
            try:
                remaining, section_text = _split_entry(text, entry_title)
            except ValueError as e:
                return {"ok": False, "error": str(e)}
            scope = detect_task_scope(section_text)
            task_text = (
                "---\n"
                f"type: task\nstatus: todo\nschema_version: {SCHEMA_VERSION}\ncreated: {today}\nsource: workbench\n"
                f"origin: {body['dir']}/{p.name}#{entry_title}\n"
                f"scope: {scope}\n"
                "---\n\n"
                f"# {title}\n\n"
                f"{section_text}\n\n"
                "## 备注\n\n- 由工作台条目转任务（拆条目不拆文件）\n"
            )
            _atomic_write(task_path, task_text)
            # 原文件删除该小节
            _atomic_write(p, remaining)
            _log_action("转任务（条目级）", f"「{entry_title}」从 {body['dir']}/{p.name} → 任务「{title}」")
            file_repo.event(body["dir"], p.name, "to_task", f"转任务「{entry_title}」→ {title}")
            # A1：返回新任务文件名（前端执行链路定位用）
            return {"ok": True, "task": title, "file": p.name, "entry": entry_title, "task_file": task_path.name, "task_dir": "任务"}

        # 文件级（向后兼容）— 复制正文（去 frontmatter，而非只写来源引用）
        import re as _re
        body_text = _re.sub(r"^---.*?---\s*\n?", "", text, count=1, flags=_re.S).strip()
        scope = detect_task_scope(body_text)
        task_text = (
            "---\n"
            f"type: task\nstatus: todo\nschema_version: {SCHEMA_VERSION}\ncreated: {today}\nsource: workbench\n"
            f"origin: {body['dir']}/{p.name}\n"
            f"scope: {scope}\n"
            "---\n\n"
            f"# {title}\n\n"
            f"{body_text}\n\n"
            "## 备注\n\n"
            "- 由工作台转任务\n"
        )
        _atomic_write(task_path, task_text)

        # 原文件标记已转
        new_text = _replace_frontmatter_status(text, "pending", "converted")
        if new_text == text:
            new_text = _replace_frontmatter_status(new_text, "todo", "converted")
        new_text += f"\n## 处理记录\n\n- {today} 已转为任务：{title}\n"
        _atomic_write(p, new_text)

    _log_action("转任务", f"「{p.stem}」→ 任务「{title}」")
    file_repo.event(body["dir"], p.name, "to_task", f"转任务「{p.stem}」→ {title}")
    return {"ok": True, "task": title, "file": p.name}


@router.post("/trash")
async def trash(body: dict) -> dict:
    """删除：移入 回收站/（不物理删除）。R4 阶段 4：写入时在回收站文件 frontmatter 记录 origin（供还原）。"""
    from datetime import date as _date

    with _WRITE_LOCK:
        dirname = body.get("dir")
        if not dirname or dirname not in {d for d, _ in DIRS}:
            return {"ok": False, "error": "bad dir"}
        p = _safe_resolve(dirname, body.get("file", ""))
        if p is None or not p.is_file():
            return {"ok": False, "error": "not found"}
        trash_dir = WORKBENCH_ROOT / "回收站"
        trash_dir.mkdir(exist_ok=True)
        dest = trash_dir / p.name
        if dest.exists():
            dest = trash_dir / (p.stem + "-dup" + p.suffix)
        # 移入前补 origin 字段（仅当没有时）——供还原定位原分区
        text = p.read_text(encoding="utf-8", errors="replace")
        if "origin:" not in text:
            today = _date.today().strftime("%Y-%m-%d")
            text = _patch_frontmatter(text, {"origin": f"{dirname}/{p.name}", "trashed_at": today})
            _atomic_write(p, text)
        _rename_with_retry(p, dest)
    _log_action("移入回收站", f"「{p.stem}」从 {dirname}")
    return {"ok": True, "trashed": dest.name}


@router.post("/restore")
async def restore(body: dict) -> dict:
    """回收站还原（R4 阶段 4 已拍板：还原 + 30 天 TTL 双出口）。

    body={"file": "xxx.md"}（回收站内文件名）
    按 frontmatter origin 字段回移原分区；origin 缺失 → 按文件名在 待验证/待回看/任务 匹配；
    仍无 → 回「待验证」兜底。
    """
    from datetime import date as _date

    with _WRITE_LOCK:
        filename = (body.get("file") or "").strip()
        if not filename:
            return {"ok": False, "error": "file required"}
        p = _safe_resolve("回收站", filename)
        if p is None or not p.is_file():
            return {"ok": False, "error": "not found in trash"}

        text = p.read_text(encoding="utf-8", errors="replace")
        # 解析 origin
        origin = ""
        m_origin = re.search(r"^origin:\s*(.+?)\s*$", text, re.M)
        if m_origin:
            origin = m_origin.group(1).strip()
        today = _date.today().strftime("%Y-%m-%d")

        # 还原语义（已拍板）：放弃状态还原 → 复活为待办（避免灰色死胡同）
        if re.search(r"^status:\s*abandoned\s*$", text, re.M):
            text = _replace_frontmatter_status(text, "abandoned", "todo")
            if "reopened_at:" not in text:
                text = _patch_frontmatter(text, {"reopened_at": today})
            _atomic_write(p, text)

        # 确定回移目标
        target_dir = None
        if origin:
            parts = origin.split("/", 1)
            if parts and parts[0] in {"待验证", "待回看", "任务", "心理学随想", "梦中的邮件"}:
                target_dir = WORKBENCH_ROOT / parts[0]
        if target_dir is None:
            # 文件名匹配：在 待验证/待回看/任务 找同名
            for cand_name in ("待验证", "待回看", "任务"):
                cand_dir = WORKBENCH_ROOT / cand_name
                if (cand_dir / filename).exists():
                    target_dir = cand_dir
                    break
        if target_dir is None:
            target_dir = WORKBENCH_ROOT / "待验证"
        target_dir.mkdir(exist_ok=True)

        # 目标同名冲突 → 唯一化
        dest = target_dir / filename
        if dest.exists():
            dest = target_dir / (p.stem + "-restored-" + p.suffix)

        _rename_with_retry(p, dest)
    _log_action("回收站还原", f"「{p.stem}」→ {dest.parent.name}" + (f"（origin: {origin}）" if origin else "（无 origin，兜底）"))
    return {"ok": True, "file": dest.name, "restored_to": dest.parent.name}


@router.post("/add")
async def add_entry(body: dict) -> dict:
    """手动添加条目（工作台 pane 直接写入，不经过 QQ）。
    body={"dir": "待验证"|"待回看"|"任务"|"梦中的邮件", "title": "标题", "content": "内容(可选)",
          "category": "分类(可选)", "due": "YYYY-MM-DD(任务可选)"}
    任务 → 独立文件（一任务一文件）；其余 → 按天聚合文件（追加 ## 小节）。
    """
    from datetime import datetime as _dt

    dirname = body.get("dir")
    if dirname not in {"待验证", "待回看", "任务", "梦中的邮件", "心理学随想"}:
        return {"ok": False, "error": "bad dir"}
    title = (body.get("title") or "").strip()
    if not title:
        return {"ok": False, "error": "title required"}
    content = (body.get("content") or "").strip()
    # 08-21 跨分区全局去重：同视频短链已存在于任一分区 → duplicate（防 OThqZGc 类重复卡）
    dup_url = existing_video_url(WORKBENCH_ROOT, title + "\n" + content)
    if dup_url:
        return {"ok": True, "duplicate": True, "dir": dirname, "reason": f"链接已收录：{dup_url}"}
    category = (body.get("category") or "").strip()
    due = (body.get("due") or "").strip()
    # Task 5.2 批次 5 补丁 10：priority 透传（P0-P3，大小写归一；非法忽略）
    priority = (body.get("priority") or "").strip().upper()
    if priority not in {"P0", "P1", "P2", "P3", ""}:
        priority = ""
    now = _dt.now()
    today = now.strftime("%Y-%m-%d")
    ts = now.strftime("%H:%M")

    d = WORKBENCH_ROOT / dirname
    d.mkdir(exist_ok=True)

    with _WRITE_LOCK:
        if dirname == "任务":
            # 独立文件（R4 阶段 1 修复：文件名经 _slugify 清洗，防 Windows 非法字符异常）
            fname = f"{_slugify(title)}.md"
            p = d / fname
            if p.exists():
                return {"ok": False, "error": "task already exists: " + title}
            due_line = f"due: {due}\n" if due else ""
            priority_line = f"priority: {priority}\n" if priority else ""
            text = (
                "---\n"
                f"type: task\nstatus: todo\nschema_version: {SCHEMA_VERSION}\ncreated: {today} {ts}\nsource: manual\n{priority_line}{due_line}"
                "---\n\n"
                f"# {title}\n\n"
                f"**手动添加：** {now:%Y-%m-%d %H:%M}\n"
            )
            if content:
                text += f"\n## 备注\n\n{content}\n"
            _atomic_write(p, text)
            _log_action("手动添加任务", f"「{title}」" + (f"（due {due}）" if due else ""))
            return {"ok": True, "file": p.name, "dir": dirname}

        # 聚合文件（按天）
        category_map = {"待验证": "thought_pending", "待回看": "video_pending", "梦中的邮件": "dream_mail", "心理学随想": "psych_pending"}
        cat = category or category_map.get(dirname, "")
        p = d / f"{today}.md"
        if p.exists():
            text = p.read_text(encoding="utf-8", errors="replace")
        else:
            text = (
                f"# {dirname}收录 {today}\n\n"
                "---\n"
                f"type: queued\nschema_version: {SCHEMA_VERSION}\ncategory: {cat}\nstatus: pending\n"
                f"received_at: {today} {ts}\nsource: manual\n"
                "---\n"
            )
        section = f"\n## {title}\n"
        if content:
            section += f"\n**备注：**\n- {content}\n"
        section += "\n---\n"
        text = text.rstrip() + "\n" + section
        _atomic_write(p, text)
        _log_action(f"手动添加 → {dirname}", f"「{title}」")
        return {"ok": True, "file": p.name, "dir": dirname}


@router.post("/ingest-message")
async def ingest_message(body: dict) -> dict:
    """QQ/外部消息收录（阶段 2.5 幂等 outbox）。

    body={"message_id": "必填唯一ID", "dir": "待验证"|"待回看"|"任务"|"梦中的邮件"|"心理学随想",
          "title": "...", "content": "..."(可选), "category": (可选), "due": (可选)}

    幂等语义：
    - message_id 已消费（ingest_messages.status=done）→ 返回 duplicate=True，不重复写入；
    - 崩溃残留（status=processing）→ 视为未消费，允许重放（重试写入）；
    - 写入失败 → 保留 processing，下次同 message_id 重试。
    """
    from datetime import datetime as _dt

    message_id = (body.get("message_id") or "").strip()
    if not message_id:
        return {"ok": False, "error": "message_id required"}
    dirname = body.get("dir") or "待验证"
    if dirname not in {"待验证", "待回看", "任务", "梦中的邮件", "心理学随想"}:
        return {"ok": False, "error": "bad dir"}
    # 幂等：已消费 → 直接跳过（不重复写）
    if file_repo.db.ingest_exists(message_id):
        return {"ok": True, "duplicate": True, "dir": dirname}

    title = (body.get("title") or "").strip()
    if not title:
        return {"ok": False, "error": "title required"}
    content = (body.get("content") or "").strip()
    # 08-21 跨分区全局去重：同视频短链已存在于任一分区 → duplicate（防 OThqZGc 类重复卡）
    dup_url = existing_video_url(WORKBENCH_ROOT, title + "\n" + content)
    if dup_url:
        return {"ok": True, "duplicate": True, "dir": dirname, "reason": f"链接已收录：{dup_url}"}
    category = (body.get("category") or "").strip()
    due = (body.get("due") or "").strip()
    # Task 5.2 批次 5 补丁 10：priority 透传（P0-P3，大小写归一；非法忽略）
    priority = (body.get("priority") or "").strip().upper()
    if priority not in {"P0", "P1", "P2", "P3", ""}:
        priority = ""
    now = _dt.now()
    today = now.strftime("%Y-%m-%d")
    ts = now.strftime("%H:%M")

    d = WORKBENCH_ROOT / dirname
    d.mkdir(exist_ok=True)

    with _WRITE_LOCK:
        if dirname == "任务":
            fname = f"{_slugify(title)}.md"
            p = d / fname
            if p.exists():
                return {"ok": False, "error": "task already exists: " + title}
            due_line = f"due: {due}\n" if due else ""
            scope = detect_task_scope(title + "\n" + content)
            text = (
                "---\n"
                f"type: task\nstatus: todo\nschema_version: {SCHEMA_VERSION}\ncreated: {today} {ts}\nsource: qq\n{due_line}"
                f"scope: {scope}\n"
                "---\n\n"
                f"# {title}\n\n"
                f"**QQ 收录：** {now:%Y-%m-%d %H:%M}\n"
            )
            if content:
                text += f"\n## 备注\n\n{content}\n"
        else:
            category_map = {"待验证": "thought_pending", "待回看": "video_pending", "梦中的邮件": "dream_mail", "心理学随想": "psych_pending"}
            cat = category or category_map.get(dirname, "")
            p = d / f"{today}.md"
            if p.exists():
                text = p.read_text(encoding="utf-8", errors="replace")
            else:
                text = (
                    f"# {dirname}收录 {today}\n\n"
                    "---\n"
                    f"type: queued\nschema_version: {SCHEMA_VERSION}\ncategory: {cat}\nstatus: pending\n"
                    f"received_at: {today} {ts}\nsource: qq\n"
                    "---\n"
                )
            section = f"\n## {title}\n"
            if content:
                section += f"\n**备注：**\n- {content}\n"
            section += "\n---\n"
            text = text.rstrip() + "\n" + section

        # claim processing（崩溃重放语义）→ 双写 → done
        file_repo.db.ingest_upsert(message_id, dirname, p.name, "processing")
        try:
            _atomic_write(p, text)
        except Exception:
            # 写入失败：保留 processing，下次重放
            raise
        file_repo.db.ingest_upsert(message_id, dirname, p.name, "done")
        # API-B（B1）：记录带信息的 created 业务事件（UPDATE 镜像空行或 INSERT；两种场景恰好一条，幂等）
        file_repo.db.record_ingest_created(dirname, p.name, f"收录：{title}")
        _log_action(f"QQ 收录 → {dirname}", f"「{title}」")
        return {"ok": True, "duplicate": False, "file": p.name, "dir": dirname}


@router.post("/defer")
async def defer_task(body: dict) -> dict:
    """显式顺延任务（R4 阶段 2 已拍板：手动顺延 + 3 次卡住态）。

    body={"dir": "任务", "file": "xxx.md"} 或 {"title": "任务标题"}
    同一任务顺延 3 次后停止，返回 stuck=True（前端显示「卡住」）。
    """

    with _WRITE_LOCK:
        target = None
        if body.get("file") and body.get("dir"):
            cand = _safe_resolve(body["dir"], body["file"])
            if cand and cand.is_file():
                target = cand
        elif body.get("title"):
            cands = _match_task(body["title"])
            if len(cands) == 1:
                target = cands[0]
            elif len(cands) > 1:
                return {"ok": False, "error": "ambiguous", "candidates": [c.stem for c in cands]}
        if target is None:
            return {"ok": False, "error": "task not found"}

        text = target.read_text(encoding="utf-8", errors="replace")
        if "status: todo" not in text:
            return {"ok": False, "error": "only todo tasks can be deferred"}
        m = re.search(r"^due:\s*(\d{4}-\d{2}-\d{2})\s*$", text, re.M)
        if not m:
            return {"ok": False, "error": "no due date"}

        r = _maybe_defer(target)
        if r is None:
            return {"ok": False, "error": "no defer needed (due not overdue)"}
        if r.get("stuck"):
            _log_action("顺延被拒（卡住）", f"任务「{target.stem}」已顺延 {r['count']} 次，达到上限")
            return {"ok": True, "stuck": True, "count": r["count"], "file": target.name}
        _log_action("手动顺延", f"任务「{target.stem}」{r['from']} → {r['to']}（第 {r['count']} 次）")
        return {"ok": True, "deferred": True, "from": r["from"], "to": r["to"], "count": r["count"], "file": target.name}


@router.post("/execute")
async def execute_task(body: dict) -> dict:
    """让 GT 执行任务：可选先编辑（title/content/due 覆盖）→ 标记 in_progress → 触发执行器 cron。

    body={"dir": "任务", "file": "xxx.md", "title"?: "新标题", "content"?: "补充要求", "due"?: "YYYY-MM-DD"}
    """
    from datetime import datetime as _dt

    with _WRITE_LOCK:
        # 定位任务文件（R4 阶段 1 修复：改用 _safe_resolve + dir 白名单，封堵路径穿越）
        target = None
        if body.get("file") and body.get("dir"):
            cand = _safe_resolve(body["dir"], body["file"])
            if cand and cand.is_file():
                target = cand
        elif body.get("title"):
            cands = _match_task(body["title"])
            if len(cands) == 1:
                target = cands[0]
            elif len(cands) > 1:
                return {"ok": False, "error": "ambiguous", "candidates": [c.name for c in cands]}
        if target is None:
            return {"ok": False, "error": "task not found"}

        mt = target.stat().st_mtime  # 阶段 2.5：expected_mtime 并发防护（读后首次写校验，同事务续写不重复）
        text = target.read_text(encoding="utf-8", errors="replace")
        if "status: completed" in text:
            return {"ok": False, "error": "already completed"}
        # 会话创建失败后允许重试：只有已有 session_id 的 in_progress 才视为正在运行
        if "status: in_progress" in text and body.get("launch") is not False:
            return {"ok": False, "error": "already running"}
        if "status: in_progress" in text and re.search(r"^session_id:\s*\S+", text, re.M):
            return {"ok": False, "error": "already running"}

        # 可选的执行前编辑
        edited = False
        new_title = (body.get("title") or "").strip()
        content = (body.get("content") or "").strip()
        due = (body.get("due") or "").strip()
        # 08-21：执行来源审计（click|api|auto），排查自动执行路径用
        source = (body.get("source") or "click").strip() or "click"

        if new_title and new_title != target.stem:
            # 更新 # 标题行 + 重命名文件
            text = re.sub(r"^# .+$", f"# {new_title}", text, count=1, flags=re.M)
            safe_title = _slugify(new_title)
            new_path = target.with_name(safe_title + ".md")
            if new_path.exists() and new_path != target:
                return {"ok": False, "error": "target title file exists"}
            _atomic_write(target, text, expected_mtime=mt)  # 先写内容，再改名
            try:
                _rename_with_retry(target, new_path)
                target = new_path
            except OSError:
                pass  # 改名失败保留原名，内容已更新
            edited = True

        if due and not re.search(r"^due:", text, re.M):
            # frontmatter 补 due
            text = _patch_frontmatter(text, {"due": due})
            _atomic_write(target, text)
            edited = True
        elif due:
            text = re.sub(r"^due:.*$", f"due: {due}", text, count=1, flags=re.M)
            _atomic_write(target, text)
            edited = True

        if content:
            text = target.read_text(encoding="utf-8", errors="replace")
            # 08-21 防累积：已有「执行前补充」段时在段内追加，不新建重复标题
            # （历史文件曾被旧版编辑框预填正文，产生重复消息污染，本次已数据清理）
            m_prep = re.search(r"^##\s*执行前补充\s*$", text, re.M)
            if m_prep:
                seg_end = len(text)
                m_next = re.search(r"^##\s", text[m_prep.end():], re.M)
                if m_next:
                    seg_end = m_prep.end() + m_next.start()
                text = text[:seg_end].rstrip() + f"\n\n{content}\n" + text[seg_end:]
            else:
                text += f"\n## 执行前补充\n\n{content}\n"
            _atomic_write(target, text)
            edited = True

        if edited:
            _log_action("▶ 执行前编辑", f"「{target.stem}」已更新")

        text = target.read_text(encoding="utf-8", errors="replace")
        started_at = _dt.now()
        # 08-21 研究≠摄入治理（B1）：任务范围复核改写（任务正文 + 执行前补充）
        scope = detect_task_scope(text + "\n" + content)
        new_text = text.replace("status: todo", "status: in_progress", 1)
        new_text = _patch_frontmatter(new_text, {
            "execution_result": "pending",
            "execution_started_at": started_at.isoformat(timespec="seconds"),
            "scope": scope,
        })
        new_text = re.sub(r"^execution_finished_at:[^\r\n]*\r?\n?", "", new_text, count=1, flags=re.M)
        if source == "click":
            exec_line = f"- {started_at:%Y-%m-%d %H:%M} 用户点击「▶ 执行」，GT 开始处理\n"
        else:
            exec_line = f"- {started_at:%Y-%m-%d %H:%M} 执行启动（source={source}），GT 开始处理\n"
        new_text += f"\n## 执行记录\n\n{exec_line}"
        if scope == "research":
            RESEARCH_CWD.mkdir(parents=True, exist_ok=True)
        _atomic_write(target, new_text)
        _log_action("▶ 执行任务", f"「{target.stem}」已派给 GT（source={source}）")
        file_repo.event(body.get("dir", ""), target.name, "execute", f"▶ 执行任务「{target.stem}」已派给 GT（source={source}）")

    # 手动工作台任务由前端创建 Hermes 会话；这里仅完成任务准备和状态切换。
    return {
        "ok": True,
        "status": "in_progress",
        "file": target.name,
        "path": str(target),
        "scope": scope,
        "cwd": str(RESEARCH_CWD) if scope == "research" else str(WORKBENCH_ROOT.parent),
    }


@router.post("/bind-session")
async def bind_session(body: dict) -> dict:
    """把工作台任务绑定到可见 Hermes 执行会话。"""
    session_id = str(body.get("session_id") or "").strip()
    if not session_id:
        return {"ok": False, "error": "session_id required"}
    with _WRITE_LOCK:
        target = _safe_resolve(str(body.get("dir") or ""), str(body.get("file") or ""))
        if not target or not target.is_file():
            return {"ok": False, "error": "task not found"}
        text = target.read_text(encoding="utf-8", errors="replace")
        # session_id 必须写入 YAML frontmatter，不能插到文件首行破坏 Obsidian 解析。
        patched = _patch_frontmatter(text, {"session_id": session_id})
        if patched == text and not re.search(r"(^|\n)---[ \t]*\r?\n", text):
            return {"ok": False, "error": "task has no frontmatter"}
        text = patched
        _atomic_write(target, text)
        _log_action("🔗 绑定执行会话", f"「{target.stem}」→ {session_id}")
        file_repo.event(body.get("dir", ""), target.name, "bind_session", f"🔗 绑定执行会话 → {session_id}")
    return {"ok": True, "session_id": session_id, "file": target.name}


@router.post("/reset-execution")
async def reset_execution(body: dict) -> dict:
    """会话创建/提交/绑定失败时，把孤儿执行从 in_progress 恢复为 todo。"""
    with _WRITE_LOCK:
        target = _safe_resolve(str(body.get("dir") or ""), str(body.get("file") or ""))
        if not target or not target.is_file():
            return {"ok": False, "error": "task not found"}
        text = target.read_text(encoding="utf-8", errors="replace")
        new_text = _replace_frontmatter_status(text, "in_progress", "todo")
        if new_text == text:
            return {"ok": False, "error": "task is not in progress"}
        # 复位时同时清掉孤儿会话与本次执行控制字段；失败原因保留在正文。
        new_text = re.sub(
            r"^(?:session_id|execution_result|execution_started_at|execution_finished_at):[^\r\n]*\r?\n?",
            "",
            new_text,
            flags=re.M,
        )
        reason = str(body.get("reason") or "会话启动失败").strip()
        new_text += f"\n## 执行失败记录\n\n- {datetime.now():%Y-%m-%d %H:%M} {reason}\n"
        _atomic_write(target, new_text)
        _log_action("执行失败 → 恢复待办", f"「{target.stem}」：{reason}")
    file_repo.event(body.get("dir", ""), target.name, "reset_execution", f"执行失败恢复待办：{reason}")
    return {"ok": True, "status": "todo", "file": target.name}


@router.post("/edit")
async def edit_entry(body: dict) -> dict:
    """编辑聚合条目 / 任务文件：title/content/due（不改状态）。A2（2026-08-15）。

    body={"dir": ..., "file": ..., "entry_title"?: ..., "title"?: ..., "content"?: ..., "due"?: ..., "amend"?: ...}
    - 条目级（entry_title 给定）：聚合文件内重命名 ## 小节 + 小节内追加备注 + frontmatter due
    - 文件级（无 entry_title）：改 # 标题（不改文件名）+ 追加备注 + frontmatter due
    - 文件级 + amend=true（方案 Z，2026-08-20）：content 整体替换正文（保留 frontmatter），
      frontmatter 追加 edited_by_user/edited_at 显式修正标记（审计可溯源）
    """
    with _WRITE_LOCK:
        dirname = body.get("dir")
        p = _safe_resolve(dirname, body.get("file", ""))
        if p is None or not p.is_file():
            return {"ok": False, "error": "not found"}
        entry_title = (body.get("entry_title") or "").strip()
        new_title = (body.get("title") or "").strip()
        content = (body.get("content") or "").strip()
        due = (body.get("due") or "").strip()
        # API-A（B1）：tags 整体替换（list | 逗号分隔 str → 归一化去空去重）；priority P0-P3 校验非法忽略。
        # 仅文件级生效；条目级（entry_title）忽略不报错（聚合条目无独立 frontmatter）。
        raw_tags = body.get("tags")
        tag_list: list[str] = []
        if raw_tags is not None:
            if isinstance(raw_tags, str):
                raw_tags = [t for t in raw_tags.split(",") if t.strip()]
            elif not isinstance(raw_tags, list):
                raw_tags = []
            seen: set[str] = set()
            for t in raw_tags:
                s = str(t).strip()
                if s and s not in seen:
                    seen.add(s)
                    tag_list.append(s)
        priority_raw = (body.get("priority") or "").strip()
        priority = priority_raw.upper() if priority_raw.upper() in {"P0", "P1", "P2", "P3"} else ""
        mt = p.stat().st_mtime
        text = p.read_text(encoding="utf-8", errors="replace")
        changed = False

        if entry_title:
            # 条目级：定位 ## 小节标题行
            pat = re.compile(r"^##\s*" + re.escape(entry_title) + r"\s*$", re.M)
            m = pat.search(text)
            if m is None:
                return {"ok": False, "error": "entry not found"}
            if new_title and new_title != entry_title:
                text = text[:m.start()] + f"## {new_title}" + text[m.end():]
                changed = True
            if content:
                ins_at = m.start() + len(f"## {new_title}" if changed else m.group(0))
                text = text[:ins_at] + f"\n**备注：**\n- {content}" + text[ins_at:]
                changed = True
            if due:
                if re.search(r"^due:", text, re.M):
                    text = re.sub(r"^due:.*$", f"due: {due}", text, count=1, flags=re.M)
                else:
                    text = _patch_frontmatter(text, {"due": due})
                changed = True
        else:
            if body.get("amend"):
                # 方案 Z：整体替换正文（保留 frontmatter）+ 用户修正标记
                fm, fm_start, fm_end, _nl = _extract_frontmatter(text)
                if fm is None:
                    return {"ok": False, "error": "amend requires frontmatter"}
                if not content:
                    return {"ok": False, "error": "amend requires content"}
                from datetime import datetime as _now_dt

                now = _now_dt.now().strftime("%Y-%m-%d %H:%M")
                head_end = text.find("\n---", fm_end) + len("\n---")
                if head_end <= 0:
                    return {"ok": False, "error": "frontmatter block malformed"}
                head = text[:head_end]
                head = _patch_frontmatter(
                    head, {"edited_by_user": "true", "edited_at": now}
                )
                text = head + "\n\n" + content.strip() + "\n"
                changed = True
            # 文件级
            if new_title:
                text = re.sub(r"^# .+$", f"# {new_title}", text, count=1, flags=re.M)
                changed = True
            if content:
                text = text.rstrip() + f"\n\n## 备注\n\n{content}\n"
                changed = True
            if due:
                if re.search(r"^due:", text, re.M):
                    text = re.sub(r"^due:.*$", f"due: {due}", text, count=1, flags=re.M)
                else:
                    text = _patch_frontmatter(text, {"due": due})
                changed = True
            # API-A（B1）：文件级 tags 整体替换 / priority 写入（条目级忽略）
            if tag_list:
                text = _patch_frontmatter(text, {"tags": "[" + ", ".join(tag_list) + "]"})
                changed = True
            if priority:
                text = _patch_frontmatter(text, {"priority": priority})
                changed = True

        if not changed:
            return {"ok": False, "error": "nothing to change"}
        _atomic_write(p, text, expected_mtime=mt)
    _log_action("✎ 编辑", f"「{p.stem}」" + (f"#{entry_title}" if entry_title else "") + ("；字段:tags/priority" if (tag_list or priority) and not entry_title else "") + " 已更新" if changed else "")
    fields_note = ""
    if not entry_title and (tag_list or priority):
        parts = []
        if tag_list:
            parts.append("tags")
        if priority:
            parts.append("priority")
        fields_note = "；字段:" + ",".join(parts)
    file_repo.event(dirname or "", p.name, "edited", f"编辑{'条目' if entry_title else '任务'}：{new_title or entry_title or p.stem}{fields_note}")
    return {"ok": True, "file": p.name, "entry": entry_title or None, "edited": True}


@router.post("/delete")
async def delete_file(body: dict) -> dict:
    """永久删除文件（仅回收站/已处理分区可用；二次确认后）。

    磁盘删除文件 + DB 行清除 + task_events 记录。
    """
    dirname = str(body.get("dir") or "")
    filename = str(body.get("file") or "")

    # 仅回收站（trash）和已处理（done）分区可用
    expected_keys = {"trash", "done"}
    candidate_key = None
    for dname, key in DIRS:
        if dname == dirname:
            candidate_key = key
            break
    if candidate_key not in expected_keys:
        return {"ok": False, "error": "仅回收站/已处理文件可永久删除"}

    with _WRITE_LOCK:
        target = _safe_resolve(dirname, filename)
        if not target or not target.is_file():
            return {"ok": False, "error": "file not found"}

        # 磁盘删除 + DB 清除（DualRepo.delete 双写）
        file_repo.delete(target)
        # task_events 记录
        file_repo.event(dirname, filename, "deleted", "永久删除")

        _log_action("永久删除", f"「{filename}」从{dirname}彻底删除（磁盘 + DB + events）")

    return {"ok": True, "dir": dirname, "file": filename, "deleted": True}
