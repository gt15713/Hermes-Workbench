"""每日任务顺延（no_agent cron 用）。

规则：
- 扫描 任务/*.md，status: todo 且 due < 今天 → 顺延到明天
- 保留 orig_due（原始日期）+ defer_count（顺延次数）+ last_deferred（上次顺延日）
- 无到期任务则静默（输出空 = cron 不投递）
- 输出摘要给 cron 投递

符合「保留事实时间，不静默改写截止日」：orig_due 永久保留，due 变更是可追溯的。
"""
import datetime
import os
import re
import sys
from pathlib import Path

# P0-A：env 注入优先；手动运行回落中立默认
ROOT = Path(os.environ.get("WORKBENCH_ROOT", str(Path.home() / "Workbench"))) / "任务"
TODAY = datetime.date.today()
TOMORROW = TODAY + datetime.timedelta(days=1)

# 阶段 1.5：接入插件 DualRepo 双写（DB 镜像）。import 失败 → 降级纯文件。
_dual = None
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dashboard"))
    from repo import DualRepo, FileRepo, SqliteRepo  # noqa: E402

    _dual = DualRepo(FileRepo(root=ROOT.parent), SqliteRepo(root=ROOT.parent))
except Exception as _e:  # noqa: BLE001
    print(f"[workbench_defer] dual-repo 不可用，降级纯文件：{_e}")


def bump_due(text: str, old_due: str) -> str:
    """把 due 从 old_due 顺延到明天，保留 orig_due/defer_count。"""
    # 已有 orig_due 则保留，没有则记录当前 due 为原始
    if "orig_due:" not in text:
        text = text.replace("due: " + old_due, f"due: {TOMORROW}\norig_due: {old_due}\ndefer_count: 1\nlast_deferred: {TODAY}", 1)
    else:
        # 已有 orig_due：更新 due + 递增 defer_count
        m = re.search(r"defer_count:\s*(\d+)", text)
        n = int(m.group(1)) + 1 if m else 2
        text = re.sub(r"due: [^\n]+", f"due: {TOMORROW}", text, count=1)
        if m:
            text = re.sub(r"defer_count:\s*\d+", f"defer_count: {n}", text, count=1)
        else:
            text = text.replace("---\n", f"---\ndefer_count: {n}\n", 1)
        if "last_deferred:" in text:
            text = re.sub(r"last_deferred:\s*[^\n]+", f"last_deferred: {TODAY}", text, count=1)
        else:
            text = text.replace("---\n", f"---\nlast_deferred: {TODAY}\n", 1)
    return text


def main():
    deferred = []
    if not ROOT.is_dir():
        print("")
        return
    for f in sorted(ROOT.glob("*.md")):
        text = f.read_text(encoding="utf-8", errors="replace")
        if "status: todo" not in text:
            continue
        m = re.search(r"^due:\s*(\d{4}-\d{2}-\d{2})", text, re.M)
        if not m:
            continue
        try:
            due = datetime.date.fromisoformat(m.group(1))
        except ValueError:
            continue
        if due < TODAY:
            new_text = bump_due(text, m.group(1))
            if new_text != text:
                if _dual is not None:
                    _dual.write_text(f, new_text)
                else:
                    f.write_text(new_text, encoding="utf-8")
                deferred.append((f.stem, str(due), str(TOMORROW)))

    if not deferred:
        print("")
        return
    lines = [f"📅 任务顺延（{TODAY}）", ""]
    for name, old, new in deferred:
        lines.append(f"- {name}：{old} → {new}")
    lines.append("")
    lines.append("（保留 orig_due 原始日期，可追溯顺延历史）")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
