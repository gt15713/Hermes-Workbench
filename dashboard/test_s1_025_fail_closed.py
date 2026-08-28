# -*- coding: utf-8 -*-
"""WB-S1-025 fail-closed 日报契约（CoderX CI_GREEN_REVIEW_REJECTED_FOR_RUNTIME 修复）。

A1：真实脚本（scripts/workbench_daily_report.py）无参数路径
    - 事实/schema 未过 → 非零退出、无可投递 stdout、精确 issues 进 stderr；
    - 有效数据 → 两个显式非空区段 <WORKLOG> 与 <QQMSG>，内容适配各自用途。
A2：scheduler 对确定性 fallback 做真实结构与事实验证（唯一解析入口 _split_output）；
    malformed/partial tag、仅 WORKLOG、仅 QQ、空段、exit!=0、脚本异常 → ok=false，
    fallback 无效时零 sink 调用，原始 input/render 验证不被覆盖。
A3：delivery_validation 真实语义：仅 sent 为 ok；failed/unconfigured/skipped-empty/
    error-no-hermes/unknown 一律 ok=false 且保留 exact status/reason；无需投递用
    required=false/not_applicable，不得冒充已发送成功。
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import scheduler

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"

_WORKLOG_RE = re.compile(r"<WORKLOG>(.*?)</WORKLOG>", re.S)
_QQ_RE = re.compile(r"<QQMSG>(.*?)</QQMSG>", re.S)


def _run_real_script(root: Path, args: list[str] | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["WORKBENCH_ROOT"] = str(root)
    env["WORKBENCH_DB"] = str(root / "wb.db")
    for d in ("待验证", "待回看", "任务", "心理学随想", "梦中的邮件", "已处理", "回收站", "日志"):
        (root / d).mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "workbench_daily_report.py"), *(args or [])],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=60,
    )


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _valid_data() -> dict:
    return {
        "today": "2026-08-28",
        "is_sunday": False,
        "processed": ["完成跨平台验收"],
        "pending": [{"label": "待回看", "title": "推进视频分类", "due": "", "blocked": False}],
        "week": {"monday": "2026-08-24", "completed": ["完成跨平台验收"], "completed_count": 1,
                 "new_count": 1, "remaining_count": 1, "due_next_week": 0, "blocked_count": 0},
        "data_validated": True,
        "factual_validation": {"ok": True, "issues": []},
        "link_health": {"status": "green"},
    }


def _patch_daily_run(monkeypatch, exit_code: int, stdout: str, stderr: str = "") -> None:
    monkeypatch.setattr(
        scheduler, "_deterministic_daily_run",
        lambda: {"exit": exit_code, "stdout": stdout, "stderr": stderr},
    )


def _patch_sinks(monkeypatch) -> dict:
    calls = {"worklog": [], "qq": []}
    monkeypatch.setattr(scheduler, "_deliver", lambda msg: calls["qq"].append(msg) or "sent")
    monkeypatch.setattr(scheduler, "_write_daily_worklog", lambda text: calls["worklog"].append(text) or "written")
    import workbench_config  # noqa: PLC0415
    monkeypatch.setattr(workbench_config, "get_write_worklog", lambda: True)
    return calls


def _patch_render_invalid(monkeypatch, data: dict) -> None:
    monkeypatch.setattr(scheduler, "_script_data", lambda name: dict(data))
    monkeypatch.setattr(
        scheduler, "_generate",
        lambda ctx, prompt, data=None: '<WORKLOG></WORKLOG><QQMSG>总量错误文本</QQMSG>',
    )
    monkeypatch.setattr(scheduler, "_current_health_snapshot", lambda: {"status": "green"})


# ---------- A1：真实脚本集成 ----------


def test_real_script_valid_data_emits_both_tagged_sections(tmp_path):
    """有效数据 → <WORKLOG> 与 <QQMSG> 两个显式且非空的区段，内容适配各自用途。"""
    _write(tmp_path / "已处理" / "2026-08-26.md",
           "# 已处理 2026-08-26\n\n## 任务（1 条）\n\n- [[完成跨平台验收]] — 完成\n")
    r = _run_real_script(tmp_path, ["--date", "2026-08-26"])
    assert r.returncode == 0, r.stderr
    assert "<WORKLOG>" in r.stdout and "</WORKLOG>" in r.stdout, r.stdout
    assert "<QQMSG>" in r.stdout and "</QQMSG>" in r.stdout, r.stdout
    wl = (_WORKLOG_RE.search(r.stdout).group(1)).strip()
    qq = (_QQ_RE.search(r.stdout).group(1)).strip()
    assert wl, "WORKLOG 段不得为空"
    assert qq, "QQMSG 段不得为空"
    assert wl != qq, "两段内容必须适配各自用途而非同一全文复制"
    assert len(wl) >= 20, "WORKLOG 段须满足工作日志写入门槛（>=20 字符）"
    assert "完成跨平台验收" in wl and "完成跨平台验收" in qq


def test_real_script_invalid_facts_fail_closed(tmp_path):
    """事实无效（日期文件名伪条目）→ 非零退出、stdout 无可投递正文、issues 在 stderr。"""
    _write(tmp_path / "任务" / "2026-08-18.md", "---\nstatus: todo\n---\n")
    r = _run_real_script(tmp_path)
    assert r.returncode != 0, f"事实无效必须非零退出，stdout={r.stdout!r}"
    assert r.stdout.strip() == "", "事实无效时 stdout 不得产生可投递日报正文"
    assert r.stderr.strip(), "精确 issues 必须保留在 stderr"
    assert "2026-08-18" in r.stderr or "伪条目" in r.stderr, r.stderr
    # --data 与无参数路径必须遵守同一事实/schema 门
    r2 = _run_real_script(tmp_path, ["--data"])
    assert r2.returncode != 0, "--data 路径同样必须失败关闭"
    assert r2.stdout.strip() == ""


def test_real_script_empty_valid_data_still_emits_sections(tmp_path):
    """空但有效的报告：两段仍显式非空（不因‘没有事项’而制造空段）。"""
    r = _run_real_script(tmp_path, ["--date", "2026-08-26"])
    assert r.returncode == 0, r.stderr
    wl = (_WORKLOG_RE.search(r.stdout).group(1)).strip()
    qq = (_QQ_RE.search(r.stdout).group(1)).strip()
    assert wl and qq, "空报告也必须有非空的 WORKLOG/QQMSG 段"


# ---------- A2：fallback 结构/事实验证（唯一解析入口 _split_output） ----------


def test_validate_fallback_text_malformed_tag():
    v = scheduler._validate_fallback_text("<WORKLOG>a</WORKLOG><QQMSG>缺闭合")
    assert v["ok"] is False
    assert any("QQMSG" in i for i in v["issues"]), v["issues"]


def test_validate_fallback_text_partial_tag():
    v = scheduler._validate_fallback_text("<WORKLOG>abc")
    assert v["ok"] is False
    assert any("WORKLOG" in i for i in v["issues"]), v["issues"]


def test_validate_fallback_text_worklog_only():
    v = scheduler._validate_fallback_text("<WORKLOG>abc</WORKLOG>")
    assert v["ok"] is False
    assert any("<QQMSG>" in i for i in v["issues"]), v["issues"]


def test_validate_fallback_text_qq_only():
    v = scheduler._validate_fallback_text("<QQMSG>abc</QQMSG>")
    assert v["ok"] is False
    assert any("<WORKLOG>" in i for i in v["issues"]), v["issues"]


def test_validate_fallback_text_empty_section():
    v = scheduler._validate_fallback_text("<WORKLOG></WORKLOG><QQMSG>abc</QQMSG>")
    assert v["ok"] is False
    assert any("WORKLOG" in i and "empty" in i for i in v["issues"]), v["issues"]


def test_validate_fallback_text_valid_both_sections():
    v = scheduler._validate_fallback_text("<WORKLOG>\n# 工作台日报\n正文\n</WORKLOG>\n<QQMSG>\n📋 QQ\n</QQMSG>")
    assert v["ok"] is True, v["issues"]
    assert v["worklog"].startswith("# 工作台日报")
    assert v["qq"].startswith("📋")


def test_validate_fallback_run_exit_nonzero():
    v = scheduler._validate_fallback_run({"exit": 3, "stdout": "残片", "stderr": "traceback boom"})
    assert v["ok"] is False
    assert any("exit=3" in i for i in v["issues"]), v["issues"]
    assert v["worklog"] == "" and v["qq"] == ""


def test_fallback_invalid_skips_both_sinks(monkeypatch):
    """仅 QQ 段（无 WORKLOG）→ fallback 无效 → 两个 sink 均零调用。"""
    _patch_render_invalid(monkeypatch, _valid_data())
    _patch_daily_run(monkeypatch, 0, "<QQMSG>只有qq</QQMSG>")
    calls = _patch_sinks(monkeypatch)
    result = scheduler._job_daily_report(None)
    assert calls["qq"] == [] and calls["worklog"] == [], "fallback 无效时不得写 sink"
    assert result["fallback_validation"]["ok"] is False, result["fallback_validation"]
    assert result["delivery_validation"]["ok"] is False
    assert result["worklog"] == "skipped-empty" and result["delivery"] == "skipped-empty"


def test_fallback_exit_nonzero_skips_both_sinks(monkeypatch):
    _patch_render_invalid(monkeypatch, _valid_data())
    _patch_daily_run(monkeypatch, 1, "", "validation failed")
    calls = _patch_sinks(monkeypatch)
    result = scheduler._job_daily_report(None)
    assert calls["qq"] == [] and calls["worklog"] == []
    assert result["fallback_validation"]["ok"] is False
    assert any("exit=1" in i for i in result["fallback_validation"]["issues"]), result["fallback_validation"]
    assert "input_validation" in result and "render_validation" in result, "原始验证证据不得被覆盖"


def test_malformed_fallback_does_not_overwrite_input_render_validation(monkeypatch):
    """fallback 无效时 input/render 原始失败证据保留（四态分离不被覆盖）。"""
    _patch_render_invalid(monkeypatch, _valid_data())
    _patch_daily_run(monkeypatch, 0, "无标签文本")
    _patch_sinks(monkeypatch)
    result = scheduler._job_daily_report(None)
    assert result["render_validation"]["ok"] is False
    assert result["render_validation"].get("issues"), "render_validation 必须保留原始失败"
    assert result["fallback_validation"]["ok"] is False
    assert "input_validation" in result


# ---------- A3：delivery_validation 真实状态语义 ----------


def test_delivery_validation_sent_only_success():
    v = scheduler._delivery_validation(True, "sent", "model")
    assert v["ok"] is True and v["status"] == "sent" and v["required"] is True


@pytest.mark.parametrize(
    "status",
    ["failed", "unconfigured", "skipped-empty", "error-no-hermes", "unknown-status"],
)
def test_delivery_validation_matrix_non_sent_false(status):
    """failed/unconfigured/skipped-empty/error-no-hermes/unknown → ok=false 且保留精确 status/reason。"""
    v = scheduler._delivery_validation(True, status, "model")
    assert v["ok"] is False, status
    assert v["status"] == status, "exact status 必须保留"
    assert v["required"] is True
    assert v.get("reason"), f"必须保存精确 reason: {status}"
    assert any(status in i for i in v["issues"]), v["issues"]


def test_delivery_validation_not_required():
    """无需投递 → required=false/not_applicable，不得冒充已发送成功。"""
    v = scheduler._delivery_validation(False, "not_applicable", "deterministic")
    assert v["ok"] is True
    assert v["required"] is False
    assert v["status"] == "not_applicable"
    assert "no qq message" in v["reason"]


def test_delivery_non_sent_integration_maps_to_false(monkeypatch):
    """scheduler 集成：_deliver 返回 unconfigured → delivery_validation ok=false + 精确状态。"""
    delivered = []
    monkeypatch.setattr(scheduler, "_script_data", lambda name: _valid_data())
    monkeypatch.setattr(
        scheduler, "_generate",
        lambda ctx, prompt, data=None: json.dumps(
            {"processed": ["D1"], "pending": ["P1"], "week_completed": ["W1"]},
            ensure_ascii=False,
        ),
    )
    monkeypatch.setattr(scheduler, "_current_health_snapshot", lambda: {"status": "green"})
    monkeypatch.setattr(
        scheduler, "_deliver",
        lambda msg: delivered.append(msg) or "unconfigured",
    )
    monkeypatch.setattr(
        scheduler, "_write_daily_worklog",
        lambda text: "written",
    )
    import workbench_config  # noqa: PLC0415
    monkeypatch.setattr(workbench_config, "get_write_worklog", lambda: True)
    result = scheduler._job_daily_report(None)
    dv = result["delivery_validation"]
    assert dv["ok"] is False
    assert dv["status"] == "unconfigured" and dv["required"] is True
    assert dv["source"] == "model"
    assert "unconfigured" in dv["reason"]
    assert result["delivery"] == "unconfigured", "生命周期字段保留真实投递状态"


def test_sent_delivery_integration_maps_to_true(monkeypatch):
    """scheduler 集成：_deliver 返回 sent → delivery_validation.ok=true。"""
    monkeypatch.setattr(scheduler, "_script_data", lambda name: _valid_data())
    monkeypatch.setattr(
        scheduler, "_generate",
        lambda ctx, prompt, data=None: json.dumps(
            {"processed": ["D1"], "pending": ["P1"], "week_completed": ["W1"]},
            ensure_ascii=False,
        ),
    )
    monkeypatch.setattr(scheduler, "_current_health_snapshot", lambda: {"status": "green"})
    monkeypatch.setattr(scheduler, "_deliver", lambda msg: "sent")
    monkeypatch.setattr(scheduler, "_write_daily_worklog", lambda text: "written")
    import workbench_config  # noqa: PLC0415
    monkeypatch.setattr(workbench_config, "get_write_worklog", lambda: True)
    result = scheduler._job_daily_report(None)
    assert result["delivery_validation"]["ok"] is True
    assert result["delivery_validation"]["status"] == "sent"
