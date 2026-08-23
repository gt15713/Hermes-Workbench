# -*- coding: utf-8 -*-
"""Workbench 执行结果协调器——显式成功语义 + 回写。

数据流：
- Workbench 任务区 in_progress + session_id 文件 → frontmatter 扫描
- 仅接受任务 frontmatter 的 execution_result: success|failure
- 完成 → 回写 status=completed + completed_at + 「## 完成记录」+ event(completed)
  （不移已处理——归档巡检 workbench_archive.py 会把 completed 任务移走，闭环）
- 失败 → 回写 status=todo + 「## 执行失败记录」+ event(reset_execution)
- 证据不足 → 保持 in_progress（安全侧，绝不误完成）+ 输出提示

安全模型：会话结束不等于任务成功。in_progress→completed 唯一自动路径是
execution_result: success；pending、缺失和未知值全部保持 in_progress。
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

_STATUS_RE = re.compile(r"^status:\s*(.+?)\s*$", re.M)
_SESSION_RE = re.compile(r"^session_id:\s*(\S+)\s*$", re.M)


def _fm(text: str) -> dict:
    m = re.search(r"(^|\n)---[ \t]*\r?\n(.*?)\r?\n---", text, re.S)
    if not m:
        return {}
    out = {}
    for line in m.group(2).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def scan_in_progress(root: Path) -> list[dict]:
    """扫描 任务/ 区：frontmatter status=in_progress 且有 session_id 的文件。"""
    out: list[dict] = []
    task_dir = root / "任务"
    if not task_dir.is_dir():
        return out
    for p in sorted(task_dir.glob("*.md")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fm = _fm(text)
        if fm.get("status") != "in_progress":
            continue
        sid = fm.get("session_id", "")
        if not sid:
            continue
        out.append({"path": p, "text": text, "session_id": sid})
    return out


def decide(task_text: str) -> str:
    """显式结果判定 → completed | failed | unknown。"""
    result = _fm(task_text).get("execution_result", "").strip().lower()
    if result == "success":
        return "completed"
    if result == "failure":
        return "failed"
    return "unknown"


def _patch_fm_field(text: str, field: str, value: str) -> str:
    """frontmatter 行级写（有则替换，无则插入）。"""
    m = re.search(r"(^|\n)---[ \t]*\r?\n(.*?)\r?\n---", text, re.S)
    if not m:
        return text
    fm_text = m.group(2)
    if re.search(rf"^{re.escape(field)}:[ \t]*.*?$", fm_text, re.M):
        fm_text = re.sub(rf"^{re.escape(field)}:[ \t]*.*?$", f"{field}: {value}", fm_text, count=1, flags=re.M)
    else:
        newline = "\r\n" if "\r\n" in fm_text else "\n"
        fm_text = fm_text.rstrip() + newline + f"{field}: {value}"
    return text[: m.start(2)] + fm_text + text[m.end(2):]


def apply_result(item: dict, decision: str, root: Path, dual=None, now=None) -> str:
    """回写：completed / failed / skipped（unknown 不改）。返回动作名。

    经 dual（DualRepo 双写）写文件与 DB 镜像；无 dual → 纯文件（脚本降级）。
    幂等：已 completed（"## 完成记录" 已存在）→ skipped；重复调用不追加重复记录节。
    """
    if decision == "unknown":
        return "skipped"
    path: Path = item["path"]
    text = item["text"]
    now = now or dt.datetime.now()
    ts = now.strftime("%Y-%m-%d %H:%M")

    if decision == "completed":
        if "## 完成记录" in text:
            return "skipped"  # 幂等
        text = _patch_fm_field(text, "status", "completed")
        text = _patch_fm_field(text, "completed_at", now.strftime("%Y-%m-%d"))
        text = _patch_fm_field(text, "execution_finished_at", now.isoformat(timespec="seconds"))
        text = text.rstrip() + f"\n\n## 完成记录\n\n- {ts} 收到显式成功结果，自动标记完成\n"
        _write(dual, path, text)
        _event(dual, "任务", path.name, "completed", "会话结束自动回写完成")
        return "completed"
    if decision == "failed":
        text = _patch_fm_field(text, "status", "todo")
        text = _patch_fm_field(text, "execution_finished_at", now.isoformat(timespec="seconds"))
        text = text.rstrip() + f"\n\n## 执行失败记录\n\n- {ts} 收到显式失败结果，自动恢复待办\n"
        _write(dual, path, text)
        _event(dual, "任务", path.name, "reset_execution", "会话异常自动恢复待办")
        return "failed"
    return "skipped"


def _write(dual, path: Path, text: str) -> None:
    if dual is not None:
        dual.write_text(path, text)
    else:
        path.write_text(text, encoding="utf-8")


def _event(dual, partition: str, filename: str, kind: str, payload: str) -> None:
    if dual is not None:
        dual.event(partition, filename, kind, payload)


def run_watch(
    root: Path,
    dual=None,
    now=None,
    extract_actions: bool = True,
) -> dict:
    """主流程：扫描 → 判定 → 回写 →（C3/P1-1）completed 后提取行动项 ingest 待验证。

    返回 {"scanned": N, "completed": N, "failed": N, "skipped": N, "pending": [文件名],
          "ingested": N, "duplicate": N, "capped": N, "merged": N}。
    """
    result = {"scanned": 0, "completed": 0, "failed": 0, "skipped": 0, "pending": [],
              "ingested": 0, "duplicate": 0, "capped": 0, "merged": 0}
    items = scan_in_progress(root)
    result["scanned"] = len(items)
    for item in items:
        decision = decide(item["text"])
        if decision == "unknown":
            result["pending"].append(item["path"].name)
            continue
        action = apply_result(item, decision, root, dual=dual, now=now)
        if action == "completed":
            result["completed"] += 1
            if extract_actions:
                sub = ingest_actions(item, dual)
                for k in ("ingested", "duplicate", "capped", "merged"):
                    result[k] += sub[k]
        elif action == "failed":
            result["failed"] += 1
        else:
            result["skipped"] += 1
    return result


# ── C3（P1-1）：会话 → 任务提取（行动项 → 待验证 ingest） ────────────────

def _extract_actions(text: str, limit: int = 5) -> list[str]:
    """解析「## 行动项」节列表项（- [ ] / - xxx）；无节 → []。每会话 ≤5 条防洪水。"""
    m = re.search(r"^##\s*行动项\s*$", text, re.M)
    if not m:
        return []
    seg = text[m.end():]
    nxt = re.search(r"^## ", seg, re.M)
    if nxt:
        seg = seg[: nxt.start()]
    out: list[str] = []
    in_fence = False
    for line in seg.splitlines():
        line = line.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        t = re.sub(r"^[-*]\s*(\[[ xX]\])?\s*", "", line).strip()
        if t and not t.startswith("#"):
            out.append(t)
        if len(out) >= limit:
            break
    return out


def _extract_summary(text: str) -> str | None:
    """「## 会话总结」节 → 单条文本（低置信合并用）。"""
    m = re.search(r"^##\s*会话总结\s*$", text, re.M)
    if not m:
        return None
    seg = text[m.end():]
    nxt = re.search(r"^## ", seg, re.M)
    if nxt:
        seg = seg[: nxt.start()]
    body = " ".join(
        l.strip() for l in seg.splitlines() if l.strip() and not l.strip().startswith("#") and not l.strip().startswith("```")
    ).strip()
    return body[:120] if body else None


def ingest_actions(item: dict, dual, daily_cap: int = 20) -> dict:
    """completed 会话 → 行动项逐条 ingest（待验证；Agent 源上限 20 条/日）。

    - 幂等：message_id = agent-{session_id}-{i}（ingest outbox 重放仅一条，API-B）
    - 低置信：无行动项但有「会话总结」→ 合并一条；两者皆无 → 不写
    - 写入走 plugin_api.ingest_message（与 HTTP /ingest-message 同一函数，P1-3 收敛）
    """
    import asyncio

    import plugin_api as _api

    sid = item.get("session_id") or ""
    text = item.get("text") or ""
    parent = Path(item["path"]).name
    result = {"ingested": 0, "duplicate": 0, "capped": 0, "merged": 0}

    actions = _extract_actions(text)
    if not actions:
        summary = _extract_summary(text)
        if summary:
            actions = [f"会话总结：{summary}"]
            result["merged"] = 1
        else:
            return result

    today = dt.date.today().isoformat()
    count = dual.db.agent_ingest_count(today) if dual and getattr(dual, "db", None) else 0

    for i, action in enumerate(actions):
        if count >= daily_cap:
            result["capped"] += 1
            continue
        mid = f"agent-{sid}-{i + 1}" if sid else f"agent-{Path(item['path']).stem}-{i + 1}"
        body = {
            "message_id": mid,
            "dir": "待验证",
            "title": action[:60],
            "content": f"（来自任务 {parent}，会话 {sid}）",
            "category": "agent_session",
        }
        r = asyncio.run(_api.ingest_message(body))
        if r.get("duplicate"):
            result["duplicate"] += 1
            continue
        if r.get("ok"):
            result["ingested"] += 1
            count += 1
        # 失败：outbox 保留 processing，下次同 message_id 重放（API-B）
    return result
