# -*- coding: utf-8 -*-
"""Hermes Workbench 本地完成器（D1 Step 1.5）— QQ 状态更新指令 → 标记任务完成并归档。

设计依据：Step 1.5 设计稿（work/s1/Step1.5-设计稿-20260819.md）。
与 hermes_wb_ingest.py 同构：直接调用 plugin_api.complete（与 /complete 端点函数体
100% 同源，argv 替代 body）；无 HTTP、无 token、不读 state.db。

用法：
    python hermes_wb_complete.py --title "XX"                  # 标题匹配
    python hermes_wb_complete.py --dir 任务 --file "xx.md"     # 精确定位（优先）

输出：单行 JSON；异常退出码非 0。不打印敏感信息。
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


def main() -> int:
    ap = argparse.ArgumentParser(description="Hermes Workbench 本地完成器")
    ap.add_argument("--title", default="", help="任务标题（模糊匹配）")
    ap.add_argument("--dir", default="", help="精确定位：分区（任务）")
    ap.add_argument("--file", default="", help="精确定位：文件名")
    args = ap.parse_args()

    if args.dir and args.file:
        body = {"dir": args.dir, "file": args.file}
    elif args.title:
        body = {"title": args.title}
    else:
        print(json.dumps({"ok": False, "error": "必须提供 --title 或 --dir+--file"}, ensure_ascii=False))
        return 2

    import plugin_api  # noqa: PLC0415 - 与端点函数体同源

    try:
        result = asyncio.run(plugin_api.complete(body))
    except Exception as e:  # noqa: BLE001 - 输出可诊断 JSON
        print(json.dumps({"ok": False, "error": f"execution failed: {e}"}, ensure_ascii=False))
        return 3

    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
