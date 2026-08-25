"""workbench-view 解析/转换工具层（阶段 1 分层）。

从 plugin_api.py 抽出的纯解析工具：frontmatter 解析、条目拆分、任务匹配、
顺延逻辑、文件名清洗。不涉及存储（存储走 repo.py）。

plugin_api.py re-export 本模块符号，保持既有测试与调用兼容。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

import yaml
from contract import SCHEMA_VERSION, SCHEMA_VERSION_FIELD

_log = logging.getLogger("workbench-view")

from workbench_config import get_partition_names, get_root  # noqa: E402

WORKBENCH_ROOT = Path(get_root())

# 工作台日志目录（每天一个 YYYY-MM-DD.md，记录所有动作）
LOG_DIR = WORKBENCH_ROOT / "日志"

# 元信息小节前缀：不作为独立条目出现在选择器/被转任务
_META_PREFIXES = ("原始消息", "备注", "处理记录")
# 子内容小节前缀：属于所属条目的子内容（如原始消息/备注），拆分时一起带走
_SECTION_CHILD_PREFIXES = ("原始消息", "备注")

# ── 08-21 研究≠摄入治理（B1）：任务范围判定 ─────────────────────────────
# 优先级：否定 > 摄入 > 研究 > 执行 > 默认 research。
# 词表与 GT 终审 v2 对齐：组合否定覆盖「不要存进Obsidian/先别存进/别入库/
# 不需要摄入/无需收录」；存|归档 只在否定动作侧（防「存个文件」误判 ingest）。
_NEG_COMBINED_RE = re.compile(
    r"(?:不|别|不要|先别|不用|勿|无需|不需要)(?:需要)?\s*"
    r"(?:吃进|摄入|收录|存进|入库|收进来|录入|记入知识库|整理进笔记|写进Obsidian|存|归档)"
)
_NEG_LITERAL_WORDS = (
    "不吃进", "别吃进", "不要吃进", "不摄入", "不用收录", "不收录",
    "不存", "不写笔记", "不用记", "先别存", "不归档", "不写进Obsidian", "不用存知识库",
)
_INGEST_WORDS = (
    "吃进", "摄入", "收录", "记入知识库", "存进Obsidian", "整理进笔记",
    "入库", "存进", "收进来", "录入",
)
_RESEARCH_WORDS = (
    "调研", "研究", "查一下", "看看", "了解", "评估", "分析",
    "是什么", "怎么样", "值不值得", "能不能用", "给出看法和建议", "给看法",
    "值得", "判断", "怎么看", "总结",
)
_EXEC_WORDS = ("执行", "部署", "安装", "落地", "实现", "按视频做", "按照视频做", "照着做", "配置", "搭建")
_VIDEO_URL_RE = re.compile(
    r"(?:b23\.tv|youtu\.be|youtube\.com/watch\?v=|bilibili\.com/video/)[A-Za-z0-9_/-]+"
)
_ANY_URL_RE = re.compile(r"https?://[^\s，。]+")
_AUTO_REGISTER_MIN_RESEARCH_LEN = 8  # 无链接研究类最短长度（过滤「最近怎么样」类寒暄）


def should_auto_register(text: str) -> bool:
    """平台强制登记判定（P2，2026-08-22）：有链接 → 是；无链接命中 scope 词表 → 是
    （研究类要求 ≥8 字过滤寒暄）；否定词 → 否；纯闲聊 → 否。"""
    t = text or ""
    if _NEG_COMBINED_RE.search(t) or any(w in t for w in _NEG_LITERAL_WORDS):
        return False
    if any(w in t for w in _INGEST_WORDS) or any(w in t for w in _EXEC_WORDS):
        return True
    if any(w in t for w in _RESEARCH_WORDS):
        return len(t.strip()) >= _AUTO_REGISTER_MIN_RESEARCH_LEN
    if _VIDEO_URL_RE.search(t) or _ANY_URL_RE.search(t):
        return True
    return False


def auto_register_dir(text: str) -> str | None:
    """平台强制登记目标分区：任务（有处理意图）/ 待回看（仅链接）/ None（不登记）。"""
    t = text or ""
    if not should_auto_register(t):
        return None
    if any(w in t for w in _INGEST_WORDS) or any(w in t for w in _EXEC_WORDS) or any(w in t for w in _RESEARCH_WORDS):
        return "任务"
    if _VIDEO_URL_RE.search(t) or _ANY_URL_RE.search(t):
        return "待回看"
    return None


def detect_task_scope(text: str) -> str:
    """任务范围判定：research | ingest | execute。

    否定 > 摄入 > 研究 > 执行 > 默认 research。判定范围 = 任务正文 + 执行前补充全文。
    """
    t = text or ""
    if _NEG_COMBINED_RE.search(t) or any(w in t for w in _NEG_LITERAL_WORDS):
        return "research"
    if any(w in t for w in _INGEST_WORDS):
        return "ingest"
    if any(w in t for w in _RESEARCH_WORDS):
        return "research"
    if any(w in t for w in _EXEC_WORDS):
        return "execute"
    return "research"


def existing_video_url(root, text: str) -> str | None:
    """跨分区全局 URL 去重（08-21，OThqZGc 类同链接被收进不同分区/日期 → 看板重复卡）。

    从 text 提取视频短链，若任一短链已存在于任一分区文件内容，返回该短链。
    """
    codes = set(_VIDEO_URL_RE.findall(text or ""))
    if not codes:
        return None
    for part in ("待验证", "待回看", "任务", "梦中的邮件", "心理学随想", "已处理", "回收站"):
        d = root / part
        if not d.is_dir():
            continue
        for f in d.glob("*.md"):
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for code in codes:
                if code in content:
                    return code
    return None


def _safe_resolve(dirname: str, filename: str) -> Path | None:
    """校验 dirname/filename 后返回安全路径；非法返回 None。"""
    if dirname not in get_partition_names():
        return None
    p = (WORKBENCH_ROOT / dirname / filename).resolve()
    # 必须留在指定分区内；仅限制到工作台根会允许 回收站/../任务 的跨分区穿越。
    partition_root = (WORKBENCH_ROOT / dirname).resolve()
    if not p.is_relative_to(partition_root):
        return None
    return p


def _yaml_value(v):
    """yaml 解析出的值转可序列化类型：date/datetime → iso 字符串。"""
    import datetime as _dt
    if isinstance(v, (_dt.date, _dt.datetime)):
        return v.isoformat()
    if isinstance(v, list):
        return [_yaml_value(x) for x in v]
    if isinstance(v, dict):
        return {k: _yaml_value(x) for k, x in v.items()}
    return v


def _parse_tags(raw) -> list[str]:
    """frontmatter tags → 规范化标签列表（A5 标签体系）。

    兼容三种写法：
      tags: [a, b]        # YAML 内联列表
      tags: a, b          # 逗号分隔字符串
      tags: a             # 单标签
    返回去空、去重、保留原大小写的字符串列表；无 tags → []。
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, str):
        items = re.split(r"[,\s]+", raw.strip("[]'\""))
    else:
        items = [raw]
    out: list[str] = []
    for t in items:
        s = str(t).strip().strip("[]'\"")
        if s and s not in out:
            out.append(s)
    return out


def _extract_frontmatter(text: str) -> tuple[dict | None, int, int, str]:
    """定位 frontmatter 块（兼容 CRLF/LF、标题在前/在后）。

    返回 (fm_dict, fm_start, fm_end, newline)：
    - fm_dict：yaml 解析结果；yaml 失败 → 回退正则行解析并告警
    - 无 frontmatter → (None, 0, 0, "\\n")
    """
    m = re.search(r"(^|\n)---[ \t]*\r?\n(.*?)\r?\n---", text, re.S)
    if not m:
        return None, 0, 0, "\n"
    fm_text = m.group(2)
    newline = "\r\n" if "\r\n" in fm_text else "\n"
    fm: dict = {}
    try:
        parsed = yaml.safe_load(fm_text)
        if not isinstance(parsed, dict):
            raise ValueError("frontmatter is not a mapping")
        fm = {k: _yaml_value(v) for k, v in parsed.items()}
    except Exception as e:
        # 回退：正则行级解析（保持旧行为），并告警便于后续修复
        _log.warning("workbench: yaml frontmatter parse failed (regex fallback): %s", e)
        for line in fm_text.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                fm[k.strip()] = v.strip()
    return fm, m.start(2), m.end(2), newline


def _patch_frontmatter(text: str, updates: dict) -> str:
    """统一 frontmatter 字段注入/更新。兼容 CRLF/LF。

    updates: {field: value} 要写入的字段。
    - 字段已存在 → 覆盖值
    - 字段不存在 → 追加到 frontmatter 末尾（--- 之前）
    - 无 frontmatter → 返回原文本不变

    实现：用 _extract_frontmatter 定位（yaml 解析验证 + 回退告警），
    写入保持行级替换/追加（不重排字段、不加引号，格式零破坏）。
    """
    _fm, fm_start, fm_end, newline = _extract_frontmatter(text)
    if _fm is None:
        return text

    fm_text = text[fm_start:fm_end]
    for field, value in updates.items():
        # 检查字段是否已存在
        field_pattern = re.compile(rf"^{re.escape(field)}:[ \t]*.*?$", re.M)
        if field_pattern.search(fm_text):
            # 覆盖
            fm_text = field_pattern.sub(f"{field}: {value}", fm_text)
        else:
            # 追加到末尾
            fm_text = fm_text.rstrip() + newline + f"{field}: {value}"

    return text[:fm_start] + fm_text + text[fm_end:]


def _parse_md(path: Path) -> dict:
    """解析单个工作台 md 文件 → 条目列表（frontmatter 字段 + 各 ## 小节标题）。

    兼容两种 frontmatter 位置：
    A) 文件开头（frontmatter 在最前，任务文件形态）
    B) 标题在前 → frontmatter 在后（聚合日文件形态：`# 待验证收录 YYYY-MM-DD` 后跟 frontmatter）

    阶段 2：内容与 mtime 走 repo（读切 DB 事实源）；文件降级为镜像。
    """
    from repo import file_repo

    try:
        text = file_repo.read_text(path)
        mtime_ts = file_repo.mtime(path)
    except OSError:
        return {"file": path.name, "entries": [], "error": "read failed"}

    fm = {}
    _fm, _start, _end, _newline = _extract_frontmatter(text)
    if _fm is not None:
        fm = _fm

    # 提取 ## 小节标题（每个 ## 是一条例目）
    entries = []
    for em in re.finditer(r"^## (.+)$", text, re.M):
        title = em.group(1).strip()
        if title and not title.startswith(_META_PREFIXES):
            entries.append(title)

    # title 解析（Task 5.2 批次 2 修复）：frontmatter title > 首个 # 一级标题 > 文件 stem
    raw_title = str(fm.get("title", "")).strip()
    if not raw_title:
        m_h1 = re.search(r"^# (.+)$", text, re.M)
        raw_title = m_h1.group(1).strip() if m_h1 else ""
    if not raw_title:
        raw_title = path.stem

    return {
        "file": path.name,
        "path": str(path).replace("\\", "/"),  # 正斜杠绝对路径
        "dir": path.parent.name,
        "title": raw_title,
        "mtime": datetime.fromtimestamp(mtime_ts).strftime("%m-%d %H:%M"),
        "type": str(fm.get("type", "")),
        "category": str(fm.get("category", "")),
        "status": str(fm.get("status", "")),
        "task_id": str(fm.get("task_id", "")).strip().upper(),
        "execution_result": str(fm.get("execution_result", "")),
        "received_at": str(fm.get("received_at", "")),
        "due": str(fm.get("due", "")),
        "defer_count": str(fm.get("defer_count", "")),
        "session_id": str(fm.get("session_id", "")),
        # Task 5.2 批次 1：优先级（P0-P3）/ 尺寸（S/M/L）徽标数据源
        "priority": str(fm.get("priority", "")).strip().upper(),
        "size": str(fm.get("size", "")).strip().upper(),
        # A5 标签体系：frontmatter tags → 规范化列表（[] 表示无标签）
        "tags": _parse_tags(fm.get("tags")),
        # 返回完整条目；前端负责展示截断，统计不能使用展示截断后的数据。
        "entries": entries,
    }


def _match_task(title: str) -> list[Path]:
    """在 任务/ 目录中按标题匹配任务文件，返回所有候选（多候选=歧义，调用方处理）。

    P1 修复（2026-08-14）：精确匹配优先——完整文件名 / 完整标题完全相等时
    直接返回单候选，避免「整理Skill」包含匹配误伤「整理Skill2」这类歧义。
    """
    t = title.strip()
    task_dir = WORKBENCH_ROOT / "任务"
    if not task_dir.is_dir():
        return []
    files = sorted(task_dir.glob("*.md"))
    # 1) 精确文件名匹配（去扩展名）——命中即唯一
    for f in files:
        if f.stem == t:
            return [f]
    # 2) 精确标题行匹配（# 标题 == t，只匹配一级标题）——命中即唯一
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            if line.startswith("# "):
                if line[2:].strip() == t:
                    return [f]
                break  # 只检查首个一级标题
    # 3) 降级：包含匹配（保持向后兼容，多候选由调用方反问）
    candidates: list[Path] = []
    seen: set[Path] = set()
    for f in files:
        if t in f.stem or t in f.name:
            if f not in seen:
                candidates.append(f)
                seen.add(f)
    if not candidates:
        for f in files:
            text = f.read_text(encoding="utf-8", errors="replace")
            for line in text.splitlines():
                if line.startswith("# ") and t in line:
                    if f not in seen:
                        candidates.append(f)
                        seen.add(f)
                    break
    return candidates


def _split_entry(text: str, entry_title: str) -> tuple[str, str]:
    """从聚合文件中拆出指定 ## 小节。

    返回 (剩余文本, 拆出的小节全文)。找不到精确匹配时抛 ValueError（绝不静默降级）。
    """
    lines = text.splitlines(keepends=True)
    # 定位所有 ## 小节边界
    section_starts: list[int] = []
    for i, line in enumerate(lines):
        if re.match(r"^##\s+", line):
            section_starts.append(i)
    if not section_starts:
        raise ValueError("no sections in file")
    # 精确定位目标条目（排除 原始消息/备注 等二级小节）
    target_idx = None
    for si, start in enumerate(section_starts):
        m = re.match(r"^##\s+(.+?)\s*$", lines[start].rstrip("\r\n"))
        if not m:
            continue
        title = m.group(1).strip()
        if title.startswith(_META_PREFIXES):
            continue
        if title == entry_title.strip():
            target_idx = si
            break
    if target_idx is None:
        raise ValueError(f"entry not found: {entry_title}")
    # 小节范围：从目标 start 到下一个 ## 之前（或文件尾）
    start = section_starts[target_idx]
    end = section_starts[target_idx + 1] if target_idx + 1 < len(section_starts) else len(lines)
    # R4 阶段 A2 修复：目标条目后紧跟的「原始消息/备注」等二级小节属于该条目的子内容，
    # 应一起带走（原实现把下一个 ## 当边界 → 子内容被截断）。向前推进 end 跳过子内容小节。
    j = target_idx + 1
    while j < len(section_starts):
        m_sub = re.match(r"^##\s+(.+?)\s*$", lines[section_starts[j]].rstrip("\r\n"))
        if m_sub and m_sub.group(1).strip().startswith(_SECTION_CHILD_PREFIXES):
            end = section_starts[j + 1] if j + 1 < len(section_starts) else len(lines)
            j += 1
        else:
            break
    section_text = "".join(lines[start:end])
    remaining = "".join(lines[:start]) + "".join(lines[end:])
    # 清理剩余文本尾部多余空行（保留最多 2 个换行）
    remaining = re.sub(r"\n{3,}", "\n\n", remaining).rstrip("\n") + "\n"
    return remaining, section_text.strip() + "\n"


def _maybe_defer(path: Path) -> dict | None:
    """惰性顺延：任务被读取时检查 due < 今天且未完成 → 顺延到明天。

    返回 {deferred, from, to, count} 或 None（无需顺延）。不依赖定时任务——
    顺延发生在「被看见」的瞬间。

    R4 阶段 2（已拍板：手动顺延 + 3 次卡住态）：defer_count ≥ 3 时**停止顺延**，
    返回 {"stuck": True, "count": N}（前端显示「卡住」红色标记）。
    """
    import threading
    from datetime import date as _date
    from datetime import timedelta as _td

    _WRITE_LOCK = threading.RLock()

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if "status: todo" not in text:
        return None
    m = re.search(r"^due:\s*(\d{4}-\d{2}-\d{2})\s*$", text, re.M)
    if not m:
        return None
    due = m.group(1)
    today = _date.today()
    try:
        due_date = _date.fromisoformat(due)
    except ValueError:
        return None
    if due_date >= today:
        return None

    # 读取当前 defer_count（卡住判定）
    m_count = re.search(r"^defer_count:\s*(\d+)\s*$", text, re.M)
    cur_count = int(m_count.group(1)) if m_count else 0
    if cur_count >= 3:
        return {"stuck": True, "count": cur_count, "from": due}

    # 需要顺延：due → 明天（保留 orig_due + defer_count 递增）
    # 阶段 1.5：用模块级双写单例（文件 + DB 镜像），不再新建 FileRepo 绕过 DB
    from repo import file_repo
    _repo = file_repo
    with _WRITE_LOCK:
        new_due = (today + _td(days=1)).strftime("%Y-%m-%d")
        new_text = text
        # 保留首次 orig_due + 更新 due
        if "orig_due:" not in new_text:
            new_text = new_text.replace(
                f"due: {due}",
                f"due: {new_due}\norig_due: {due}",
                1,
            )
        else:
            new_text = new_text.replace(f"due: {due}", f"due: {new_due}", 1)
        # defer_count 递增
        m2 = re.search(r"^defer_count:\s*(\d+)\s*$", new_text, re.M)
        if m2:
            n = int(m2.group(1)) + 1
            new_text = re.sub(r"^defer_count:\s*\d+\s*$", f"defer_count: {n}", new_text, count=1, flags=re.M)
        else:
            new_text = new_text.replace(f"due: {new_due}", f"due: {new_due}\ndefer_count: 1", 1)
        # last_deferred
        new_text = re.sub(r"^last_deferred:.*$", f"last_deferred: {today:%Y-%m-%d}", new_text, count=1, flags=re.M)
        if "last_deferred:" not in new_text:
            new_text = new_text.replace("defer_count:", f"last_deferred: {today:%Y-%m-%d}\ndefer_count:", 1)
        _repo.write_text(path, new_text)

    m3 = re.search(r"^defer_count:\s*(\d+)\s*$", new_text, re.M)
    count = int(m3.group(1)) if m3 else 1
    return {"deferred": True, "from": due, "to": new_due, "count": count}


def _slugify(title: str) -> str:
    """条目标题 → 文件名片段（去特殊字符，截断）。"""
    import re as _re
    s = _re.sub(r"[\\/:*?\"<>|\s]+", "-", title).strip("-")
    return s[:40] or "entry"


def _replace_frontmatter_status(text: str, old: str, new: str) -> str:
    """仅替换 frontmatter 内的 status 行（不误伤正文）。"""
    # 找 frontmatter 块（兼容开头或标题在后两种位置）
    m = re.search(r"(^|\n)---\s*\n(.*?)\n---", text, re.S)
    if not m:
        return text
    fm_block = m.group(2)
    new_block = re.sub(
        rf"^(status:\s*){re.escape(old)}\s*$",
        rf"\g<1>{new}",
        fm_block,
        flags=re.M,
    )
    if new_block == fm_block:
        return text
    return text[: m.start(2)] + new_block + text[m.end(2):]


def _ensure_completed_at(text: str, today: str) -> str:
    """在 frontmatter 内补 completed_at（若缺失）。"""
    if "completed_at" in text:
        return text
    m = re.search(r"(^|\n)---\s*\n(.*?)\n---", text, re.S)
    if not m:
        return text
    # 插到 frontmatter 末尾（--- 之前）
    fm_end = text.rfind("\n---", m.start(1), m.end(0))
    if fm_end == -1:
        return text
    return text[:fm_end] + f"\ncompleted_at: {today}" + text[fm_end:]


def _ensure_schema_version(text: str) -> str:
    """写入前确保 frontmatter 带 schema_version（缺失 → 补当前版本）。"""
    _fm, _start, _end, _nl = _extract_frontmatter(text)
    if _fm is None:
        return text
    if SCHEMA_VERSION_FIELD not in _fm:
        return _patch_frontmatter(text, {SCHEMA_VERSION_FIELD: SCHEMA_VERSION})
    return text


def _migrate_schema(text: str) -> str:
    """读路径迁移钩子：schema_version 低于当前 → 迁移。

    目前仅 v1（无迁移路径），作为框架保留；未来新增版本在此扩展：
    if v == 1: text = _migrate_v1_to_v2(text)
    """
    _fm, _start, _end, _nl = _extract_frontmatter(text)
    if _fm is None:
        return text
    ver = _fm.get(SCHEMA_VERSION_FIELD)
    if ver is None:
        return text  # 旧文件无版本字段，写入时由 _ensure_schema_version 补齐
    try:
        v = int(ver)
    except (TypeError, ValueError):
        return text
    if v < SCHEMA_VERSION:
        # 未来迁移点（当前无历史版本）
        return _patch_frontmatter(text, {SCHEMA_VERSION_FIELD: SCHEMA_VERSION})
    return text
