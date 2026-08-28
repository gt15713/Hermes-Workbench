# -*- coding: utf-8 -*-
"""WB-P0-S1-006 Workstream B：日报事实性 RED 测试。

覆盖审查要求的 7-12 项：
7.  空壳 待回看/待验证 产生零 pending
8.  聚合文件只算真实条目
9.  已处理 只返回链接/列表条目，不返回 `任务（1 条）` 分类标题
10. 空任务目录产生零剩余任务
11. 不支持的 LLM 标题/数量被事实校验拒绝
12. 有效生成投递一次；无效生成回退确定性模板一次
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import scheduler

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _run(script: str, root: Path, db: Path, extra_args: list[str] | None = None) -> tuple[int, str]:
    env = dict(os.environ)
    env["WORKBENCH_ROOT"] = str(root)
    env["WORKBENCH_DB"] = str(db)
    for d in ("待验证", "待回看", "任务", "心理学随想", "梦中的邮件", "已处理", "回收站", "日志"):
        (root / d).mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / script), "--data", *(extra_args or [])],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=30,
    )
    return r.returncode, (r.stdout or "").strip()


def _json(out: str) -> dict:
    return json.loads(out)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ---- 7. 空壳 待回看/待验证 产生零 pending ----

def test_empty_shells_produce_zero_pending(tmp_path):
    # 只有标题的空壳 aggregate 文件
    _write(tmp_path / "待回看" / "2026-08-18.md", "# 待回看 2026-08-18\n---\ntype: queued\nstatus: pending\n---\n")
    _write(tmp_path / "待验证" / "2026-08-19.md", "# 待验证收录 2026-08-19\n---\ntype: queued\nstatus: pending\n---\n")
    code, out = _run("workbench_daily_report.py", tmp_path, tmp_path / "wb.db")
    assert code == 0, out
    d = _json(out)
    # 空壳不应产生任何 pending 条目（旧实现会回退 path.stem 产生伪待办）
    assert d["pending"] == [], f"空壳不应产生 pending: {d['pending']}"


# ---- 8. 聚合文件只算真实条目 ----

def test_aggregate_files_count_only_real_entries(tmp_path):
    _write(tmp_path / "待回看" / "2026-08-20.md",
           "# 待回看 2026-08-20\n---\nstatus: pending\n---\n\n## 一个真实的待回看条目\n")
    _write(tmp_path / "待回看" / "2026-08-18.md", "# 待回看 2026-08-18\n")
    code, out = _run("workbench_daily_report.py", tmp_path, tmp_path / "wb.db")
    assert code == 0, out
    d = _json(out)
    titles = [q["title"] for q in d["pending"]]
    assert "一个真实的待回看条目" in titles, titles
    # 空壳日期文件名不得成为条目
    assert "2026-08-18" not in titles, titles
    assert "2026-08-20" not in titles, titles


# ---- 9. 已处理 返回条目而非分类标题 ----

def test_completed_returns_linked_item_titles_not_heading(tmp_path):
    _write(tmp_path / "已处理" / "2026-08-26.md",
           "# 已处理 2026-08-26\n\n## 任务（1 条）\n\n- [[真实完成的任务]] — 完成\n\n## 待回看（1 条）\n\n- [[已回看的视频]]\n")
    code, out = _run("workbench_daily_report.py", tmp_path, tmp_path / "wb.db", ["--date", "2026-08-26"])
    assert code == 0, out
    d = _json(out)
    processed = d["processed"]
    # 分类标题 `任务（1 条）`/`待回看（1 条）` 不得进入 processed
    assert not any("条" in x and "（" in x for x in processed), f"分类标题混入 processed: {processed}"
    # 真实链接条目应进入 week.completed
    week_completed = d["week"]["completed"]
    assert any("真实完成的任务" in x for x in week_completed), week_completed


# ---- 10. 空任务目录产生零剩余任务 ----

def test_empty_task_dir_yields_zero_remaining(tmp_path):
    # 任务目录为空（无任何 .md）
    code, out = _run("workbench_daily_report.py", tmp_path, tmp_path / "wb.db")
    assert code == 0, out
    d = _json(out)
    assert d["week"]["remaining_count"] == 0, d["week"]["remaining_count"]
    titles = [q["title"] for q in d["pending"]]
    assert all(q["label"] != "待办" for q in d["pending"]), f"空任务目录不应有待办: {titles}"


# ---- S1-007 RED: user-facing alias titles & canonical weekly item counts ----

def test_wiki_link_alias_is_user_facing_title(tmp_path):
    """S1-007 RED: completed items show the user-facing ALIAS, not the wiki target.
    `[[2026-08-19-启动-video-分类积压处理|启动 video 分类积压处理]]` must yield
    `启动 video 分类积压处理`. Current list_items() returns the target (pre-|),
    so this FAILS before the fix.
    """
    # Direct script import path (same as test_b5_scripts SCRIPTS dir)
    import sys as _sys
    _sys.path.insert(0, str(SCRIPTS))
    import workbench_daily_report as w
    text = "# 已处理 2026-08-26\n\n## 任务（1 条）\n\n- [[2026-08-19-启动-video-分类积压处理|启动 video 分类积压处理]] — 条目级，来自 待验证\n"
    items = w.list_items(text)
    assert items == ["启动 video 分类积压处理"], f"alias expected, got {items}"


def test_weekly_totals_count_items_not_files(tmp_path):
    """S1-007 RED: a week aggregate with 2 real entries counts 2, not 1."""
    import sys as _sys
    _sys.path.insert(0, str(SCRIPTS))
    import workbench_daily_report as w
    # Re-point ROOT to the sandbox
    old_root = w.ROOT
    w.ROOT = tmp_path
    try:
        for d in ("待回看", "已处理"):
            (tmp_path / d).mkdir(parents=True, exist_ok=True)
        (tmp_path / "待回看" / "2026-08-24.md").write_text(
            "# 待回看 2026-08-24\n---\nstatus: pending\n---\n\n## 待确认条目A\n\n## 待确认条目B\n",
            encoding="utf-8",
        )
        import datetime as _dt
        week = w.collect_week(_dt.date.fromisoformat("2026-08-26"))
        assert week["new_count"] == 2, f"items not files expected 2, got {week['new_count']}"
        assert week["remaining_count"] == 2, week["remaining_count"]
    finally:
        w.ROOT = old_root



# ---- 11/12. LLM 事实校验拒绝与回退（scheduler 侧） ----

def _scheduler_module():
    import sys
    from pathlib import Path
    dash = Path(__file__).resolve().parent
    if str(dash) not in sys.path:
        sys.path.insert(0, str(dash))
    import scheduler
    return scheduler

def test_unsupported_titles_fail_factual_validation(tmp_path):
    # 真实 scheduler._validate_generated_text：数量不匹配 → 必须拒绝
    sched = _scheduler_module()
    data = {"processed": ["真实任务A"], "pending": []}
    text = "✅ 已处理（2 条）\n1. 真实任务A\n2. 不存在的任务B\n📌 待处理（0 条）"
    result = sched._validate_generated_text(text, data)
    assert result["ok"] is False, result
    assert any("数量不匹配" in x for x in result["issues"]), result["issues"]


def test_valid_generated_output_passes_validation(tmp_path):
    sched = _scheduler_module()
    data = {"processed": ["真实任务A"], "pending": []}
    text = "✅ 已处理（1 条）\n1. 真实任务A\n📌 待处理（0 条）"
    result = sched._validate_generated_text(text, data)
    assert result["ok"] is True, result


# ---- 确定性回退：无效生成 → 模板输出一次 ----

def test_invented_title_rejected_even_when_counts_match(tmp_path):
    """S1-007 RED: an invented recommendation/title with CORRECT counts must be rejected.
    Old validator only compared optional count phrases, so this passes counts and
    still sneaks an unsupported title through -> must FAIL before the fix.
    """
    sched = _scheduler_module()
    data = {"processed": ["真实任务A"], "pending": []}
    text = "✅ 已处理（1 条）\n1. 真实任务A\n2. 不存在的任务B\n📌 待处理（0 条）"
    result = sched._validate_generated_text(text, data)
    assert result["ok"] is False, result
    assert any("数据外标题" in x for x in result["issues"]), result["issues"]


def test_duplicate_title_rejected(tmp_path):
    """S1-007 RED: the same data title repeated in output must be rejected as duplicate."""
    sched = _scheduler_module()
    data = {"processed": ["真实任务A"], "pending": []}
    text = "✅ 已处理（2 条）\n1. 真实任务A\n2. 真实任务A\n📌 待处理（0 条）"
    result = sched._validate_generated_text(text, data)
    assert result["ok"] is False, result
    assert any("重复" in x for x in result["issues"]), result["issues"]


def test_omitted_title_rejected(tmp_path):
    """S1-007 RED: a data pending title absent from the output must be rejected as omission."""
    sched = _scheduler_module()
    data = {
        "processed": [],
        "pending": [
            {"label": "待看", "title": "真实待看B", "due": "", "blocked": False},
        ],
    }
    text = "✅ 已处理（0 条）\n📌 待处理（1 条）\n【待看】真实待看B"
    result = sched._validate_generated_text(text, data)
    assert result["ok"] is True, result
    # Now omit it
    text2 = "✅ 已处理（0 条）\n📌 待处理（1 条）\n【待看】别的标题"
    result2 = sched._validate_generated_text(text2, data)
    assert result2["ok"] is False, result2
    assert any("遗漏" in x for x in result2["issues"]), result2["issues"]


def test_deterministic_fallback_used_on_invalid_generation(tmp_path):
    # 无参数主函数输出确定性模板（scheduler no_agent 回退）
    env = dict(os.environ)
    env["WORKBENCH_ROOT"] = str(tmp_path)
    env["WORKBENCH_DB"] = str(tmp_path / "wb.db")
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "workbench_daily_report.py")],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=30,
    )
    assert r.returncode == 0, r.stderr
    assert "📋 今日处理日报" in r.stdout, r.stdout


def test_invalid_generation_not_delivered_and_fallback_delivered_once(tmp_path, monkeypatch):
    # scheduler._job_daily_report：数据通过校验但 LLM 文本数量错误 → 拒绝投递 → 回退模板投递一次
    sched = _scheduler_module()
    delivered = []
    healthy_data = {
        "today": "2026-08-26",
        "is_sunday": False,
        "processed": ["真实任务A"],
        "pending": [{"label": "待看", "title": "真实待看B", "due": "", "blocked": False}],
        "week": {"monday": "2026-08-24", "completed": [], "completed_count": 0,
                 "new_count": 0, "remaining_count": 0, "due_next_week": 0, "blocked_count": 0},
        "data_validated": True,
        "factual_validation": {"ok": True, "issues": []},
        "link_health": {"status": "green"},
    }
    monkeypatch.setattr(sched, "_script_data", lambda _n: dict(healthy_data))
    monkeypatch.setattr(
        sched, "_generate",
        lambda _ctx, _prompt, _data: "<WORKLOG></WORKLOG><QQMSG>✅ 已处理（9 条）总量错误</QQMSG>",
    )
    monkeypatch.setattr(sched, "_current_health_snapshot", lambda: {"status": "green", "label": "链路正常"})
    monkeypatch.setattr(sched, "_deliver", lambda text: delivered.append(text) or "sent")
    monkeypatch.setattr("workbench_config.get_write_worklog", lambda: False)
    monkeypatch.setattr(sched, "_deterministic_daily_text", lambda: "📋 确定性回退模板")

    result = sched._job_daily_report(None)

    assert result["generated"] == "fallback-invalid"
    assert result["factual_validation"].get("note") == "deterministic fallback"
    assert result["factual_validation"].get("ok") is True
    # 错误文本绝不投递；只投递确定性回退一次
    assert delivered == ["📋 确定性回退模板"], delivered
    assert result["delivery"] == "sent"
    assert result["data_validated"] is True

# ===== S1-008: structured output seam (prompt -> parse -> validate -> render) =====

class TestStructuredDailyOutput:
    """Structured records with IDs -> model JSON -> validate -> deterministic render."""

    def _records(self, processed=None, pending=None, week_completed=None):
        """Canonical records for tests."""
        return {
            "processed": [
                {"id": "D1", "title": "完成跨平台验收"},
                {"id": "D2", "title": "修复消息链路"},
            ] if processed is None else processed,
            "pending": [
                {"id": "P1", "title": "推进视频分类", "label": "待回看", "due": ""},
                {"id": "P2", "title": "整理决策记录", "label": "", "due": "2026-08-30"},
            ] if pending is None else pending,
            "week_completed": [
                {"id": "W1", "title": "周完成项A"},
                {"id": "W2", "title": "周完成项B"},
            ] if week_completed is None else week_completed,
        }

    def test_1_valid_structured_response_renders_sections(self):
        """Valid JSON with allowed IDs renders real user-facing sections."""
        records = self._records()
        # Today's processed/pending are mandatory: both D1,D2 and P1,P2 present.
        text = '{"processed": ["D1", "D2"], "pending": ["P1", "P2"], "week_completed": ["W1"]}'
        parsed = scheduler._parse_structured_output(text, records)
        assert parsed["ok"] is True, parsed["issues"]
        wl = scheduler._render_worklog(records, parsed["parsed"], "2026-08-26")
        qq = scheduler._render_qqmsg(records, parsed["parsed"], "2026-08-26")
        assert "完成跨平台验收" in wl
        assert "推进视频分类" in wl
        assert "今日推进 2 项" in wl  # deterministic judgement derived from counts
        assert "待处理 2 项" in wl

    def test_2_unknown_duplicate_wrong_category_ids_fallback(self):
        """Unknown/duplicate/wrong-category IDs are rejected."""
        records = self._records()
        # unknown ID
        r1 = scheduler._parse_structured_output(
            '{"processed": ["D9"], "pending": ["P1", "P2"], "week_completed": []}', records)
        assert r1["ok"] is False
        assert any("未知 ID" in i for i in r1["issues"])
        # duplicate ID
        r2 = scheduler._parse_structured_output(
            '{"processed": ["D1", "D1", "D2"], "pending": ["P1", "P2"], "week_completed": []}', records)
        assert r2["ok"] is False
        assert any("重复" in i for i in r2["issues"])
        # wrong category (pending ID in processed)
        r3 = scheduler._parse_structured_output(
            '{"processed": ["P1", "D2"], "pending": ["P1", "P2"], "week_completed": []}', records)
        assert r3["ok"] is False
        assert any("未知 ID" in i for i in r3["issues"])
        # unknown JSON key (prose smuggling channel) is rejected
        r4 = scheduler._parse_structured_output(
            '{"processed": ["D1", "D2"], "pending": ["P1", "P2"], "extra": "今天新增任务X"}', records)
        assert r4["ok"] is False
        assert any("未知键" in i for i in r4["issues"])

    def test_3_punctuation_url_title_does_not_break_validation(self):
        """Titles with punctuation/URL chars are never candidates; IDs only matter."""
        records = self._records(
            processed=[{"id": "D1", "title": "原生家庭受过伤的人，大多都会活成这三种样子。-哔哩哔哩-https-b23."}],
            pending=[],
        )
        text = '{"processed": ["D1"], "pending": [], "week_completed": []}'
        parsed = scheduler._parse_structured_output(text, records)
        assert parsed["ok"] is True, parsed["issues"]

    def test_4_invented_prose_rejected_and_never_rendered(self):
        """Free-text judgement/recommendation cannot smuggle invented facts."""
        records = self._records()
        # The regression fixture that used to pass with ok=True must now be rejected.
        text = '{"processed": ["D1", "D2"], "pending": ["P1", "P2"], "judgement": "今天新增任务X", "recommendation": "必须完成【任务X】"}'
        parsed = scheduler._parse_structured_output(text, records)
        assert parsed["ok"] is False
        assert any("未知键" in i for i in parsed["issues"])
        # Not rendered into any channel under any path.
        wl = scheduler._render_worklog(
            records,
            {"processed": [], "pending": [], "week_completed": []},
            "2026-08-26",
        )
        qq = scheduler._render_qqmsg(
            records,
            {"processed": [], "pending": [], "week_completed": []},
            "2026-08-26",
        )
        assert "任务X" not in wl
        assert "【任务X】" not in wl
        assert "今天新增" not in wl
        assert "今天新增" not in qq
        # determinism: judgement derives only from validated data, never free text
        judge, rec = scheduler._generate_deterministic_judgement(
            records,
            {"processed": ["D1", "D2"], "pending": ["P1", "P2"], "week_completed": []},
            None,
        )
        assert "今天新增任务X" not in judge

    def test_5_malformed_json_and_prose_fallback(self):
        """Malformed JSON and prose-only output are rejected (fall back)."""
        records = self._records()
        r1 = scheduler._parse_structured_output("not json at all", records)
        assert r1["ok"] is False
        r2 = scheduler._parse_structured_output('{broken json', records)
        assert r2["ok"] is False
        r3 = scheduler._parse_structured_output('{"processed": "D1", "pending": []}', records)
        assert r3["ok"] is False  # processed not an array
        # prose-only output (no JSON at all) cannot become a judgement line
        r4 = scheduler._parse_structured_output("今天新增任务X，必须完成【任务X】", records)
        assert r4["ok"] is False

    def test_6_worklog_qqmsg_separate_no_boilerplate(self):
        """WORKLOG and QQMSG are separate, contain no Cron/job/system boilerplate."""
        records = self._records()
        text = '{"processed": ["D1", "D2"], "pending": ["P1", "P2"], "week_completed": []}'
        parsed = scheduler._parse_structured_output(text, records)
        wl = scheduler._render_worklog(records, parsed["parsed"], "2026-08-26")
        qq = scheduler._render_qqmsg(records, parsed["parsed"], "2026-08-26")
        for word in ("scheduler", "cron", "WORKLOG", "QQMSG", "Hermes", "job"):
            assert word.lower() not in wl.lower()
            assert word.lower() not in qq.lower()
        assert wl != qq

    def test_7_zero_item_day_no_fabrication(self):
        """Zero-item day produces no fabricated progress or advice."""
        records = {"processed": [], "pending": [], "week_completed": []}
        text = '{"processed": [], "pending": [], "week_completed": []}'
        parsed = scheduler._parse_structured_output(text, records)
        assert parsed["ok"] is True, parsed["issues"]
        qq = scheduler._render_qqmsg(records, parsed["parsed"], "2026-08-26")
        wl = scheduler._render_worklog(records, parsed["parsed"], "2026-08-26")
        assert "今天没有收录和待办事项" in qq
        # No judgement line is fabricated when no source field exists.
        assert "判断" not in wl

    def test_8_fixed_2026_08_26_data_renders_truthfully(self):
        """Fixed 2026-08-26 data renders WITHOUT unsupported '已收尾/无需整理' claims."""
        # Representative of real vault data (from S1-007 preview evidence)
        records = {
            "processed": [],
            "pending": [],
            "week_completed": [
                {"id": "W1", "title": "原生家庭受过伤的人，大多都会活成这三种样子。"},
                {"id": "W2", "title": "链接：https://bot.q.qq.com/wiki/develop/api-v2"},
                {"id": "W3", "title": "跨平台验收-2026-08-25"},
            ],
        }
        data = {
            "week": {"completed_count": 5, "remaining_count": 0, "blocked_count": 0, "new_count": 0, "due_next_week": 0},
            "link_health": {"status": "green"},
        }
        text = '{"processed": [], "pending": [], "week_completed": ["W1", "W2", "W3"]}'
        parsed = scheduler._parse_structured_output(text, records)
        assert parsed["ok"] is True, parsed["issues"]
        qq = scheduler._render_qqmsg(records, parsed["parsed"], "2026-08-26", data)
        wl = scheduler._render_worklog(records, parsed["parsed"], "2026-08-26", data)
        assert "链接：https://bot.q.qq.com/wiki/develop/api-v2" in qq
        assert "原生家庭受过伤的人，大多都会活成这三种样子。" in wl
        # The S1-008 preview claims that are NOT supported by source fields:
        assert "已收尾" not in qq
        assert "已收尾" not in wl
        assert "无需额外整理" not in qq
        assert "无需额外整理" not in wl
        # Deterministic judgement counts only from collector fields:
        assert "本周完成 5 项" in qq
        # unlisted week ID is rejected
        bad = '{"processed": [], "pending": [], "week_completed": ["W9"]}'
        r2 = scheduler._parse_structured_output(bad, records)
        assert r2["ok"] is False
        assert any("未知 ID" in i for i in r2["issues"])

    def test_9_over_limit_arrays_rejected(self):
        """Production maximums enforced in the parser: >10 processed, >5 pending, >8 week."""
        records = self._records()
        many_processed = ["D1", "D2"] * 6  # 12 entries
        r1 = scheduler._parse_structured_output(
            json.dumps({"processed": many_processed, "pending": ["P1", "P2"], "week_completed": []}), records)
        assert r1["ok"] is False
        assert any("上限" in i for i in r1["issues"])
        many_pending = ["P1", "P2"] * 4  # >5
        r2 = scheduler._parse_structured_output(
            json.dumps({"processed": ["D1", "D2"], "pending": many_pending, "week_completed": []}), records)
        assert r2["ok"] is False
        assert any("上限" in i for i in r2["issues"])
        many_week = ["W1", "W2"] * 5  # 10 > 8
        r3 = scheduler._parse_structured_output(
            json.dumps({"processed": ["D1", "D2"], "pending": ["P1", "P2"], "week_completed": many_week}), records)
        assert r3["ok"] is False
        assert any("上限" in i for i in r3["issues"])

    def test_10_mandatory_today_ids_cannot_be_omitted(self):
        """processed/pending representing today's facts are mandatory."""
        records = self._records()
        # Omitting D2 / P2 is a violation even though the arrays are well-formed.
        r1 = scheduler._parse_structured_output(
            '{"processed": ["D1"], "pending": ["P1"], "week_completed": []}', records)
        assert r1["ok"] is False
        assert any("遗漏今日完成项" in i for i in r1["issues"])
        assert any("遗漏今日待办" in i for i in r1["issues"])
        # Complete selection passes.
        r2 = scheduler._parse_structured_output(
            '{"processed": ["D1", "D2"], "pending": ["P1", "P2"], "week_completed": []}', records)
        assert r2["ok"] is True, r2["issues"]

    def test_11_deterministic_judgement_has_direct_source_fields(self):
        """Judgement/action lines derive from collector fields (due, blocked)."""
        records = self._records(
            processed=[],
            pending=[
                {"id": "P1", "title": "推进视频分类", "label": "待回看", "due": ""},
                {"id": "P2", "title": "整理决策记录", "label": "", "due": "2026-08-30"},
            ],
        )
        data = {
            "week": {"completed_count": 1, "remaining_count": 1, "blocked_count": 1, "new_count": 0, "due_next_week": 1},
            "link_health": {"status": "yellow", "label": "QQ 链路待观察"},
        }
        parsed = scheduler._parse_structured_output(
            '{"processed": [], "pending": ["P1", "P2"], "week_completed": []}', records)
        judge, rec = scheduler._generate_deterministic_judgement(records, parsed["parsed"], data)
        assert "待处理 2 项" in judge
        assert "到期 1 项" in judge
        assert "阻塞 1 项" in judge
        assert "整理决策记录 到期 2026-08-30" in judge
        assert "整理决策记录" in rec


# ===== S1-008 Workstream B: title normalization regression fixtures =====

class TestTitleNormalization:
    """URL/文件名残片等不可读标题 → 可读标题（确定性规则）。"""

    def _normalize(self, title):
        import subprocess, sys, os
        code = (
            "import sys; sys.path.insert(0, r'{SCRIPTS}'); "
            "import workbench_daily_report as w; "
            f"print(w.normalize_title({title!r}))".replace("{SCRIPTS}", str(SCRIPTS))
        )
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, r.stderr
        return r.stdout.strip()

    def test_fixture_1_bilibili_transport_suffix(self):
        """S1-007 preview 丑陋标题1：-哔哩哔哩-https-b23. 后缀残留 → 剥离。"""
        ugly = "原生家庭受过伤的人，大多都会活成这三种样子。-哔哩哔哩-https-b23."
        title = self._normalize(ugly)
        assert title == "原生家庭受过伤的人，大多都会活成这三种样子。", title

    def test_fixture_2_bare_url_gets_link_prefix(self):
        """S1-007 preview 丑陋标题2：裸 URL 别名 → 不发明页面标题，中性「链接：」前缀。"""
        ugly = "https://bot.q.qq.com/wiki/develop/api-v2"
        title = self._normalize(ugly)
        assert title == "链接：https://bot.q.qq.com/wiki/develop/api-v2", title

    def test_fixture_3_date_prefix_stripped(self):
        """已知日期前缀（YYYY-MM-DD-）剥离。"""
        slug = "2026-08-23-启动-video-分类积压处理"
        assert self._normalize(slug) == "启动-video-分类积压处理"

    def test_fixture_4_plain_cjk_title_untouched(self):
        """普通中文标题/句号不被截断。"""
        assert self._normalize("普通标题") == "普通标题"
        assert self._normalize("普通标题。") == "普通标题。"

    def test_fixture_5_bilibili_english_domain_suffix(self):
        """-bilibili-https://www.bilibili.com/... 完整域名后缀也可剥离。"""
        ugly = "视频标题 -bilibili-https://www.bilibili.com/video/BV1xx411c7mD"
        assert self._normalize(ugly) == "视频标题"

    def test_list_items_aliases_pass_through_normalization(self):
        """list_items 输出经 normalize_title：日期前缀与传输后缀在展示前剥离。"""
        import subprocess, sys, os
        env = dict(os.environ)
        env["WORKBENCH_ROOT"] = str(os.path.dirname(SCRIPTS))
        env["WORKBENCH_DB"] = str(SCRIPTS)
        code = (
            "import sys; sys.path.insert(0, r'{SCRIPTS}'); "
            "import workbench_daily_report as w; "
            "items = w.list_items('- [[原生家庭受过伤的人，大多都会活成这三种样子。-哔哩哔哩-https-b23.|原生家庭受过伤的人，大多都会活成这三种样子。-哔哩哔哩-https-b23.]] — 标记完成\\n- [[2026-08-23-xxx|https://bot.q.qq.com/wiki/develop/api-v2]]'); "
            "print(repr(items))".replace("{SCRIPTS}", str(SCRIPTS))
        )
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, r.stderr
        print("list_items:", r.stdout.strip())
        assert r.stdout.strip() != "[]"
