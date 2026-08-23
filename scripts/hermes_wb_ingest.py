# -*- coding: utf-8 -*-
"""Hermes Workbench 本地收录器（D1 Step 1）— QQ 群消息收录的幂等落盘。

设计依据：Hermes GT D1 方案修正（2026-08-19）——agent 子进程拿不到
HERMES_DASHBOARD_SESSION_TOKEN（_ALWAYS_STRIP_KEYS Tier-1 剥离），HTTP API 通道
在 agent 侧必然 401；改为本地脚本复用 dashboard 幂等 outbox，无 HTTP、无 token。

实现：直接调用 `plugin_api.ingest_message`（与 HTTP 端点函数体 100% 同源，
argv 替代 body），幂等从「模型自觉」变「代码保证」：
- message_id 已消费（done）→ duplicate=true，不重复写；
- 崩溃残留（processing）→ 允许重放；
- 写失败 → 保留 processing 待重试。

用法：
    python hermes_wb_ingest.py --message_id <id> --dir <白名单> --title <标题> \
        [--content <原文>] [--category <分类>] [--due <YYYY-MM-DD>] [--priority P0|P1|P2|P3]

输出：单行 JSON（{"ok": bool, "duplicate": bool, "file": "...", "dir": "...", "error": "..."}）
退出码：0=成功（含 duplicate）；2=参数错误；3=执行异常。不打印敏感信息。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# P0-A：脚本随插件包发布，dashboard 即同级目录
_DASHBOARD = Path(__file__).resolve().parent.parent / "dashboard"
if str(_DASHBOARD) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD))

DIR_WHITELIST = {"待验证", "待回看", "任务", "梦中的邮件", "心理学随想"}
CATEGORY_WHITELIST = {"video_pending", "thought_pending", "psych_pending", "dream_mail", ""}


def main() -> int:
    ap = argparse.ArgumentParser(description="Hermes Workbench 本地收录器")
    ap.add_argument("--message_id", required=True, help="群消息原样 message_id（唯一标识）")
    ap.add_argument("--dir", required=True, help="目标分区（5 值白名单）")
    ap.add_argument("--title", required=True, help="简短标题/任务标题")
    ap.add_argument("--content", default="", help="原始消息全文（可选）")
    ap.add_argument("--category", default="", help="分类（可选）")
    ap.add_argument("--due", default="", help="任务截止日期 YYYY-MM-DD（可选）")
    ap.add_argument("--priority", default="", help="P0/P1/P2/P3（可选，仅任务）")
    args = ap.parse_args()

    if args.dir not in DIR_WHITELIST:
        print(json.dumps({"ok": False, "error": f"dir 不在白名单：{args.dir}"}, ensure_ascii=False))
        return 2
    if args.category not in CATEGORY_WHITELIST:
        print(json.dumps({"ok": False, "error": f"category 非法：{args.category}"}, ensure_ascii=False))
        return 2
    if args.priority and args.priority.upper() not in {"P0", "P1", "P2", "P3"}:
        print(json.dumps({"ok": False, "error": f"priority 非法：{args.priority}"}, ensure_ascii=False))
        return 2

    import plugin_api  # noqa: PLC0415 - 与端点函数体同源

    body = {
        "message_id": args.message_id,
        "dir": args.dir,
        "title": args.title,
        "content": args.content,
        "category": args.category,
        "due": args.due,
        "priority": args.priority,
    }
    try:
        result = asyncio.run(plugin_api.ingest_message(body))
    except Exception as e:  # noqa: BLE001 - 输出可诊断 JSON
        print(json.dumps({"ok": False, "error": f"execution failed: {e}"}, ensure_ascii=False))
        return 3

    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
