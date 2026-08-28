# -*- coding: utf-8 -*-
"""WB-S1-023：日报渲染事实契约 + 重启 reconcile 证据契约（TDD RED→GREEN）。

核心契约（修复「输入正确、输出漏项仍假绿」与「重启误标 interrupted」根因）：
1. LLM 返回 week_completed 子集（count=5 只列 2）→ 渲染验证必须 RED，不沿用 data_validated=true；
2. 输出中的待处理/今日处理/本周完成必须与结构化源数据逐集合相等：不漏、不增、不改写标题；
3. 「链路状态/健康检查」只允许出现在唯一 footer，不得进入判断、建议或任务清单；
4. 渲染不合格 → fail-closed 到确定性 fallback（不再次调用模型），记录 render_fallback=deterministic + 失败原因；
5. 写文件前与投递前复用同一 post-render validator（禁「文件正确、QQ错误」）；
6. 已有成功日志的 lifecycle attempt 经重启不得被 reconcile 为 interrupted；真正 started 无完成证据仍必须 interrupted。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402
import scheduler  # noqa: E402

# ---------------------------------------------------------------------------
# 冻结的 2026-08-28 20:00 自然运行数据（脱敏：结构保真）
# ---------------------------------------------------------------------------

FROZEN_RECORDS = {
    "processed": [],
    "pending": [
        {"id": "t1", "title": "QQ私聊跨平台验收", "due": None},
        {"id": "t2", "title": "WB任务测试", "due": None},
    ],
    "week_completed": [
        {"id": "w1", "title": "原生家庭受过伤的人，大多都会活成这三种样子。"},
        {"id": "w2", "title": "链接：https://bot.q.qq.com/wiki/develop/api-v2"},
        {"id": "w3", "title": "因为这段话-我护住了一生财富"},
        {"id": "w4", "title": "评估-hermes-chatgpt-desktop-bridge-项目"},
        {"id": "w5", "title": "跨平台验收-2026-08-25"},
    ],
    "stats": {"completed_count": 5},
}

FROZEN_DATA = {
    "today": "2026-08-28",
    "week": {"completed_count": 5},
    "link_health": {"status": "red"},
}


def _parsed_subset() -> dict:
    """LLM 典型坏输出：week_completed 只选 2/5，其余合法。"""
    return {
        "ok": True,
        "parsed": {
            "processed": [],
            "pending": ["t1", "t2"],
            "week_completed": ["w4", "w5"],
        },
        "issues": [],
    }


def _valid_script_data() -> dict:
    """data_validated 源数据（与 _parsed_full 选择集对齐）。"""
    return {
        "data_validated": True,
        "today": "2026-08-28",
        "processed": [],
        "pending": ["待办一", "待办二"],
        "week": {"completed_count": 5, "completed": ["完成一", "完成二", "完成三", "完成四", "完成五"],
                 "new_count": 0, "remaining_count": 0, "blocked_count": 0, "due_next_week": 0},
        "factual_validation": {"ok": True, "issues": []},
    }


def _parsed_full() -> dict:
    return {
        "ok": True,
        "parsed": {
            "processed": [],
            "pending": ["t1", "t2"],
            "week_completed": ["w1", "w2", "w3", "w4", "w5"],
        },
        "issues": [],
    }


def _parsed_full_real_ids() -> dict:
    """真实 _build_daily_records id 方案（D/P/W），供 _job_daily_report 全链路测试。"""
    return {
        "ok": True,
        "parsed": {
            "processed": [],
            "pending": ["P1", "P2"],
            "week_completed": ["W1", "W2", "W3", "W4", "W5"],
        },
        "issues": [],
    }


# ---------------------------------------------------------------------------
# 契约 2：集合相等渲染校验器（post-render validator，唯一实现）
# ---------------------------------------------------------------------------


class TestRenderValidation:
    def test_week_subset_is_red(self):
        """契约 1/2：week_completed 子集 → 校验失败，不假绿。"""
        p = _parsed_subset()
        result = scheduler.validate_rendered_output(
            FROZEN_RECORDS, p["parsed"], FROZEN_DATA
        )
        assert result["ok"] is False
        assert any("week_completed" in i for i in result["issues"])

    def test_full_sets_are_green(self):
        p = _parsed_full()
        result = scheduler.validate_rendered_output(
            FROZEN_RECORDS, p["parsed"], FROZEN_DATA
        )
        assert result["ok"] is True, result["issues"]

    def test_missing_pending_is_red(self):
        p = _parsed_full()
        p["parsed"]["pending"] = ["t1"]
        result = scheduler.validate_rendered_output(
            FROZEN_RECORDS, p["parsed"], FROZEN_DATA
        )
        assert result["ok"] is False

    def test_invented_title_is_red(self):
        p = _parsed_full()
        p["parsed"]["week_completed"] = [
            "w1", "w2", "w3", "w4", "发明的标题"
        ]
        result = scheduler.validate_rendered_output(
            FROZEN_RECORDS, p["parsed"], FROZEN_DATA
        )
        assert result["ok"] is False

    def test_counter_matches_list_length(self):
        """判断文案计数必须等于通过校验的列表长度，不允许 5 项只列 2。"""
        wl = scheduler._render_worklog(
            FROZEN_RECORDS, _parsed_full()["parsed"], "2026-08-28", FROZEN_DATA
        )
        assert "本周完成 5 项" in wl
        # 5 个周完成标题必须全部出现在工作日志正文（FROZEN_RECORDS 脱敏标题）
        for r in FROZEN_RECORDS["week_completed"]:
            assert r["title"] in wl

    def test_renamed_title_is_red(self):
        p = _parsed_full()
        p["parsed"]["week_completed"] = [
            "w1", "w2", "w3", "w4改写", "w5"
        ]
        result = scheduler.validate_rendered_output(
            FROZEN_RECORDS, p["parsed"], FROZEN_DATA
        )
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# 契约 3：健康只进唯一 footer
# ---------------------------------------------------------------------------


class TestHealthFooterOnly:
    def test_health_red_not_in_judgement(self):
        judgement, recommendation = scheduler._generate_deterministic_judgement(
            FROZEN_RECORDS, _parsed_full()["parsed"], FROZEN_DATA
        )
        assert "链路状态" not in judgement
        assert "链路状态" not in recommendation

    def test_worklog_body_has_no_health_when_red(self):
        wl = scheduler._render_worklog(
            FROZEN_RECORDS, _parsed_full()["parsed"], "2026-08-28", FROZEN_DATA
        )
        body_lines = [
            line for line in wl.splitlines()
            if not line.startswith("<!--") and "footer" not in line
        ]
        # 正文（判断/建议/清单）不得含健康短语；footer 由 _health_report_line 单独拼接
        for line in body_lines:
            if line.startswith(("#", "- ", "**", "今天")) or line == "":
                assert "链路状态" not in line

    def test_footer_still_reports_health(self):
        """健康信息仍必须可达：_health_report_line 独立 footer 保留。"""
        line = scheduler._health_report_line({"status": "red", "errors": ["x"]})
        assert line  # footer 存在
        assert "链路状态" in line or "健康" in line


# ---------------------------------------------------------------------------
# 契约 4/5：fail-closed fallback + 同一 validator 双侧复用
# ---------------------------------------------------------------------------


class TestFailClosed:
    def test_bad_render_falls_back_without_model(self, monkeypatch):
        """渲染不合格 → 确定性 fallback，不再调用模型，记录 render_fallback。"""
        calls = {"model": 0}

        def fake_generate(ctx, prompt, data=None):
            calls["model"] += 1
            # 真实 id 子集：P1P2 但只选 W1W2（复现 5 项只列 2）
            return json.dumps({"processed": [], "pending": ["P1", "P2"], "week_completed": ["W1", "W2"]}, ensure_ascii=False)

        monkeypatch.setattr(scheduler, "_script_data", lambda name: _valid_script_data())
        monkeypatch.setattr(scheduler, "_current_health_snapshot", lambda: {"status": "green"})
        monkeypatch.setattr(scheduler, "_generate", fake_generate)
        monkeypatch.setattr(
            scheduler, "_deterministic_daily_text",
            lambda: "<QQMSG>\n📋 确定性日报\n</QQMSG>"
        )
        monkeypatch.setattr(scheduler, "_deliver", lambda msg: "sent")
        monkeypatch.setattr(
            scheduler, "_write_daily_worklog", lambda text: "written"
        )
        import workbench_config  # noqa: PLC0415
        monkeypatch.setattr(workbench_config, "get_write_worklog", lambda: True)
        result = scheduler._job_daily_report(ctx=None)
        assert calls["model"] == 1  # 初次调用后不再重试模型
        assert result.get("render_fallback") == "deterministic"
        assert result.get("render_validation", {}).get("ok") is False
        assert result["factual_validation"].get("ok") is not None

    def test_good_render_records_render_validation(self, monkeypatch):
        def fake_generate(ctx, prompt, data=None):
            return json.dumps(_parsed_full_real_ids()["parsed"], ensure_ascii=False)

        monkeypatch.setattr(scheduler, "_script_data", lambda name: _valid_script_data())
        monkeypatch.setattr(scheduler, "_current_health_snapshot", lambda: {"status": "green"})
        monkeypatch.setattr(scheduler, "_generate", fake_generate)
        monkeypatch.setattr(scheduler, "_deliver", lambda msg: "sent")
        monkeypatch.setattr(
            scheduler, "_write_daily_worklog", lambda text: "written"
        )
        import workbench_config  # noqa: PLC0415
        monkeypatch.setattr(workbench_config, "get_write_worklog", lambda: True)
        result = scheduler._job_daily_report(ctx=None)
        assert result.get("render_validation", {}).get("ok") is True
        assert "render_fallback" not in result


# ---------------------------------------------------------------------------
# 契约 6：重启 reconcile 以日志证据为准
# ---------------------------------------------------------------------------


class TestReconcileRespectsLogEvidence:
    @pytest.fixture()
    def isolated_state(self, monkeypatch, tmp_path):
        state_file = tmp_path / "scheduler-state.json"
        log_file = tmp_path / "workbench-scheduler.log"
        monkeypatch.setattr(scheduler, "_STATE_FILE", state_file)
        monkeypatch.setattr(scheduler, "_LOG_FILE", log_file)
        return {"state_file": state_file, "log_file": log_file}

    def test_completed_attempt_with_ok_log_survives_restart(self, isolated_state):
        """8-28 20:07 场景：非终态内存态 + 日志 ok → 不得标 interrupted。"""
        rec = {"job": "lifecycle", "started_at": "2026-08-28T19:50:01", "ok": True}
        isolated_state["log_file"].write_text(
            json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        state = {
            "job_states": {
                "lifecycle": {
                    "phase": "delivery_sent",  # 重启时进程被杀留下的中间态
                    "attempt_key": "lifecycle|2026-08-28 19:50",
                    "started_at": "2026-08-28T19:50:01",
                }
            }
        }
        state.setdefault("last_runs", {})
        scheduler._STATE_FILE.write_text(json.dumps(state), encoding="utf-8")
        scheduler._reconcile_stale_states()
        loaded = json.loads(scheduler._STATE_FILE.read_text(encoding="utf-8"))
        js = loaded["job_states"]["lifecycle"]
        assert js["phase"] == "completed", js
        assert "interrupted_at" not in js

    def test_started_without_log_evidence_still_interrupted(self, isolated_state):
        rec = {"job": "daily_report", "started_at": "2026-08-28T19:58:01", "ok": False}
        isolated_state["log_file"].write_text(
            json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        state = {
            "job_states": {
                "daily_report": {
                    "phase": "started",
                    "attempt_key": "daily_report|2026-08-28 20:00",
                    "started_at": "2026-08-28T19:58:01",
                }
            }
        }
        state.setdefault("last_runs", {})
        scheduler._STATE_FILE.write_text(json.dumps(state), encoding="utf-8")
        scheduler._reconcile_stale_states()
        loaded = json.loads(scheduler._STATE_FILE.read_text(encoding="utf-8"))
        js = loaded["job_states"]["daily_report"]
        assert js["phase"] == "interrupted"

    def test_no_log_line_leaves_interrupted(self, isolated_state):
        state = {
            "job_states": {
                "nudge": {
                    "phase": "started",
                    "attempt_key": "nudge|2026-08-28 12:15",
                    "started_at": "2026-08-28T12:15:00",
                }
            }
        }
        state.setdefault("last_runs", {})
        scheduler._STATE_FILE.write_text(json.dumps(state), encoding="utf-8")
        scheduler._reconcile_stale_states()
        loaded = json.loads(scheduler._STATE_FILE.read_text(encoding="utf-8"))
        assert loaded["job_states"]["nudge"]["phase"] == "interrupted"

    def test_completed_phase_clears_stale_interrupted_at(self, isolated_state):
        """_set_phase(COMPLETED) 必须清除残留 interrupted_at（8-28 实证矛盾终态）。"""
        state = {
            "job_states": {
                "lifecycle": {
                    "phase": "interrupted",
                    "attempt_key": "lifecycle|2026-08-28 20:20",
                    "interrupted_at": "2026-08-28T20:07:27",
                }
            }
        }
        scheduler._STATE_FILE.write_text(json.dumps(state), encoding="utf-8")
        scheduler._set_phase(
            state, "lifecycle", scheduler.PHASE_COMPLETED,
            "lifecycle|2026-08-28 20:20",
        )
        js = state["job_states"]["lifecycle"]
        assert "interrupted_at" not in js


# ---------------------------------------------------------------------------
# WB-S1-024 A1：fallback 必须保留 WORKLOG 与 QQMSG 双通道
# ---------------------------------------------------------------------------


class TestFallbackDualChannel:
    def _patch_common(self, monkeypatch, deterministic_text, model_raw):
        calls = {"model": 0, "worklog": [], "qq": []}

        def fake_generate(ctx, prompt, data=None):
            calls["model"] += 1
            return model_raw  # 坏输出：week 子集 → 渲染失败

        def fake_worklog(text):
            calls["worklog"].append(text)
            return "written"

        def fake_deliver(msg):
            calls["qq"].append(msg)
            return "sent"

        monkeypatch.setattr(scheduler, "_script_data", lambda name: _valid_script_data())
        monkeypatch.setattr(scheduler, "_current_health_snapshot", lambda: {"status": "green"})
        monkeypatch.setattr(scheduler, "_generate", fake_generate)
        monkeypatch.setattr(scheduler, "_deterministic_daily_text", lambda: deterministic_text)
        monkeypatch.setattr(scheduler, "_deliver", fake_deliver)
        monkeypatch.setattr(scheduler, "_write_daily_worklog", fake_worklog)
        import workbench_config  # noqa: PLC0415
        monkeypatch.setattr(workbench_config, "get_write_worklog", lambda: True)
        return calls

    def test_fallback_delivers_both_channels(self, monkeypatch):
        """确定性 fallback 产出双通道 tagged text：worklog 收 WORKLOG，QQ 收 QQMSG。"""
        deterministic_text = (
            "<WORKLOG>\n# 工作台日报（确定性）\n本周完成 5 项\n</WORKLOG>\n"
            "<QQMSG>\n📋 确定性日报 QQ 正文\n</QQMSG>"
        )
        model_raw = json.dumps(
            {"processed": [], "pending": ["P1", "P2"], "week_completed": ["W1", "W2"]},
            ensure_ascii=False,
        )
        calls = self._patch_common(monkeypatch, deterministic_text, model_raw)
        result = scheduler._job_daily_report(ctx=None)
        assert calls["model"] == 1
        assert len(calls["worklog"]) == 1 and calls["worklog"][0].strip(), "worklog 通道不得为空"
        assert len(calls["qq"]) == 1 and calls["qq"][0].strip(), "QQ 通道不得为空"
        assert "工作台日报（确定性）" in calls["worklog"][0], "worklog 必须收到 WORKLOG 内容"
        assert "确定性日报 QQ 正文" in calls["qq"][0], "QQ 必须收到 QQMSG 内容"
        assert calls["worklog"][0].strip() != calls["qq"][0].strip(), "两通道内容不得相同"
        assert result.get("render_fallback") == "deterministic"

    def test_fallback_untagged_text_goes_to_qq_only(self, monkeypatch):
        """无标记 fallback 输出：按 _split_output 兜底语义只走 QQ，worklog 允许 skipped-empty。"""
        deterministic_text = "# 工作台日报\n## 今日完成\n- x\n"
        model_raw = json.dumps(
            {"processed": [], "pending": ["P1", "P2"], "week_completed": ["W1", "W2"]},
            ensure_ascii=False,
        )
        calls = self._patch_common(monkeypatch, deterministic_text, model_raw)
        scheduler._job_daily_report(ctx=None)
        assert calls["model"] == 1
        assert calls["qq"][0].strip(), "QQ 通道不得为空"


# ---------------------------------------------------------------------------
# WB-S1-024 A2：失败证据不得被 fallback 成功覆盖（四态分离 + delivery_validation）
# ---------------------------------------------------------------------------


class TestValidationStateSeparation:
    def _patch_fallback(self, monkeypatch, deterministic_text):
        monkeypatch.setattr(
            scheduler, "_deterministic_daily_text", lambda: deterministic_text
        )
        monkeypatch.setattr(scheduler, "_deliver", lambda msg: "sent")
        monkeypatch.setattr(
            scheduler, "_write_daily_worklog", lambda text: "written"
        )
        import workbench_config  # noqa: PLC0415
        monkeypatch.setattr(workbench_config, "get_write_worklog", lambda: True)

    def test_input_failure_not_overridden_by_fallback(self, monkeypatch):
        """data_validated=False：即使 fallback 可产出，输入事实失败必须保持。"""
        bad_data = {
            "data_validated": False,
            "today": "2026-08-28",
            "factual_validation": {"ok": False, "issues": ["完成数与列表不一致"]},
        }
        monkeypatch.setattr(scheduler, "_script_data", lambda name: bad_data)
        monkeypatch.setattr(scheduler, "_current_health_snapshot", lambda: {"status": "green"})
        self._patch_fallback(
            monkeypatch,
            "<WORKLOG>\n# 工作台日报（确定性）\n内容足够长用于写入\n</WORKLOG>\n"
            "<QQMSG>\n📋 QQ 正文\n</QQMSG>",
        )
        result = scheduler._job_daily_report(ctx=None)
        fv = result["factual_validation"]
        assert fv.get("ok") is False, f"输入失败不得被 fallback 翻成 ok=True: {fv}"
        assert "完成数与列表不一致" in fv.get("issues", [])

    def test_render_failure_preserves_four_states(self, monkeypatch):
        """模型渲染失败但输入有效：input/render/fallback 三态分别留证 + delivery_validation。"""
        monkeypatch.setattr(scheduler, "_script_data", lambda name: _valid_script_data())
        monkeypatch.setattr(scheduler, "_current_health_snapshot", lambda: {"status": "green"})
        monkeypatch.setattr(
            scheduler,
            "_generate",
            lambda ctx, prompt, data=None: json.dumps(
                {"processed": [], "pending": ["P1", "P2"], "week_completed": ["W1", "W2"]},
                ensure_ascii=False,
            ),
        )
        self._patch_fallback(
            monkeypatch,
            "<WORKLOG>\n# 工作台日报（确定性）\n内容足够长用于写入\n</WORKLOG>\n"
            "<QQMSG>\n📋 QQ 正文\n</QQMSG>",
        )
        result = scheduler._job_daily_report(ctx=None)
        inp = result["input_validation"]
        ren = result["render_validation"]
        fb = result["fallback_validation"]
        dv = result["delivery_validation"]
        assert inp["ok"] is True, "input_validation 必须保留首次数据验证事实"
        assert ren["ok"] is False and ren["issues"], "render_validation 必须保留模型渲染失败"
        assert fb["ok"] is True, "fallback_validation 只描述确定性产物"
        assert dv["ok"] is True and dv["source"] == "deterministic", dv
        # 旧字段兼容：factual_validation 仍存在
        assert "factual_validation" in result

    def test_model_success_delivery_source_is_model(self, monkeypatch):
        """模型渲染成功路径：delivery_validation.source == model。"""
        monkeypatch.setattr(scheduler, "_script_data", lambda name: _valid_script_data())
        monkeypatch.setattr(scheduler, "_current_health_snapshot", lambda: {"status": "green"})
        monkeypatch.setattr(
            scheduler,
            "_generate",
            lambda ctx, prompt, data=None: json.dumps(
                _parsed_full_real_ids()["parsed"], ensure_ascii=False
            ),
        )
        self._patch_fallback(
            monkeypatch,
            "<QQMSG>\n不应被使用\n</QQMSG>",
        )
        result = scheduler._job_daily_report(ctx=None)
        assert result["delivery_validation"]["source"] == "model"
        assert result["delivery_validation"]["ok"] is True


# ---------------------------------------------------------------------------
# WB-S1-024 A3：同一 attempt 多条日志 → 以最后一条终态证据结算
# ---------------------------------------------------------------------------


class TestReconcileUsesFinalRecord:
    @pytest.fixture()
    def isolated_state(self, monkeypatch, tmp_path):
        state_file = tmp_path / "scheduler-state.json"
        log_file = tmp_path / "workbench-scheduler.log"
        monkeypatch.setattr(scheduler, "_STATE_FILE", state_file)
        monkeypatch.setattr(scheduler, "_LOG_FILE", log_file)
        return {"state_file": state_file, "log_file": log_file}

    def _state(self, job, attempt, phase="started"):
        return {
            "job_states": {
                job: {
                    "phase": phase,
                    "attempt_key": attempt,
                    "started_at": attempt.split("|", 1)[1] + ":00",
                }
            },
            "last_runs": {},
        }

    def test_old_fail_new_ok_settles_completed(self, isolated_state):
        """同一 attempt 分钟：先 ok=false 后 ok=true → 以最后一条为准 completed。"""
        lines = [
            {"job": "daily_report", "started_at": "2026-08-28T19:58:01", "ok": False},
            {"job": "daily_report", "started_at": "2026-08-28T19:58:05", "ok": True},
        ]
        isolated_state["log_file"].write_text(
            "\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n",
            encoding="utf-8",
        )
        scheduler._STATE_FILE.write_text(
            json.dumps(self._state("daily_report", "daily_report|2026-08-28 19:58")),
            encoding="utf-8",
        )
        scheduler._reconcile_stale_states()
        loaded = json.loads(scheduler._STATE_FILE.read_text(encoding="utf-8"))
        js = loaded["job_states"]["daily_report"]
        assert js["phase"] == "completed", js

    def test_old_ok_new_fail_settles_interrupted_with_error(self, isolated_state):
        """同一 attempt 分钟：先 ok=true 后 ok=false → interrupted + 保留失败证据。"""
        lines = [
            {"job": "lifecycle", "started_at": "2026-08-28T20:20:01", "ok": True},
            {"job": "lifecycle", "started_at": "2026-08-28T20:20:09", "ok": False},
        ]
        isolated_state["log_file"].write_text(
            "\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n",
            encoding="utf-8",
        )
        scheduler._STATE_FILE.write_text(
            json.dumps(self._state("lifecycle", "lifecycle|2026-08-28 20:20")),
            encoding="utf-8",
        )
        scheduler._reconcile_stale_states()
        loaded = json.loads(scheduler._STATE_FILE.read_text(encoding="utf-8"))
        js = loaded["job_states"]["lifecycle"]
        assert js["phase"] == "interrupted", js
        assert "log shows failed attempt" in js.get("last_error", "")

    def test_no_matching_log_remains_interrupted(self, isolated_state):
        """同 job 不同分钟日志 ≠ 匹配；无匹配 → interrupted。"""
        rec = {"job": "daily_report", "started_at": "2026-08-27T19:58:01", "ok": True}
        isolated_state["log_file"].write_text(
            json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        scheduler._STATE_FILE.write_text(
            json.dumps(self._state("daily_report", "daily_report|2026-08-28 19:58")),
            encoding="utf-8",
        )
        scheduler._reconcile_stale_states()
        loaded = json.loads(scheduler._STATE_FILE.read_text(encoding="utf-8"))
        js = loaded["job_states"]["daily_report"]
        assert js["phase"] == "interrupted", js
