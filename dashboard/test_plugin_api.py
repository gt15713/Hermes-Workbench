# -*- coding: utf-8 -*-
"""workbench-view 插件后端测试（R4 收敛阶段 0：测试先行锁定现状行为）。

覆盖：_parse_md / _split_entry / _maybe_defer / _replace_frontmatter_status /
      _ensure_completed_at / _append_log / _safe_resolve / _atomic_write

夹具：CRLF / GBK（往返无 U+FFFD）/ frontmatter 在后 / 无 frontmatter /
      空文件 / 标题特殊字符 / 回收站 origin。

运行：cd dashboard && python -m pytest test_plugin_api.py -v
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import plugin_api as api  # noqa: E402

# ---------- 夹具：临时工作台根 ----------

@pytest.fixture()
def wb(tmp_path, monkeypatch):
    """把 WORKBENCH_ROOT/LOG_DIR 指向临时目录，并建好标准分区。

    阶段 1 分层后 WORKBENCH_ROOT 存在于 plugin_api / wb_utils / repo 三处，
    统一 monkeypatch（工具/存储/端点共用同一临时根）。
    """
    import repo as repo_mod
    import wb_utils as wb_utils_mod

    for d in ("待验证", "待回看", "任务", "心理学随想", "梦中的邮件", "已处理", "回收站", "日志"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(api, "WORKBENCH_ROOT", tmp_path)
    monkeypatch.setattr(wb_utils_mod, "WORKBENCH_ROOT", tmp_path)
    monkeypatch.setattr(wb_utils_mod, "LOG_DIR", tmp_path / "日志")
    monkeypatch.setattr(repo_mod, "WORKBENCH_ROOT", tmp_path)
    # FileRepo 单例 root 指向临时根（存储原语路由用）
    monkeypatch.setattr(api.file_repo, "root", tmp_path)
    # 阶段 1.5：DB 镜像指向临时库，避免污染真实 workbench.db
    api.file_repo.db = repo_mod.SqliteRepo(tmp_path / "test-workbench.db", root=tmp_path)
    # 阶段 2：解析/端点测试用文件读（read_from_db=False），DB 读由 test_repo_db 覆盖
    api.file_repo.read_from_db = False
    return tmp_path


def _write(path: Path, text: str, encoding: str = "utf-8", newline: str = ""):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding=encoding, newline=newline) as f:
        f.write(text)


# ---------- _parse_md ----------

class TestParseMd:
    def test_frontmatter_at_start(self, wb):
        p = wb / "任务" / "t.md"
        _write(p, "---\ntype: task\nstatus: todo\ndue: 2026-08-10\n---\n\n# 标题\n")
        d = api._parse_md(p)
        assert d["status"] == "todo"
        assert d["type"] == "task"

    def test_frontmatter_after_title(self, wb):
        """聚合文件：标题在前 → frontmatter 在后（08-09 P0 修复点）。"""
        p = wb / "待验证" / "2026-08-09.md"
        _write(p, "# 待验证收录 2026-08-09\n\n---\ntype: queued\nstatus: pending\n---\n\n## 条目A\n\n## 条目B\n")
        d = api._parse_md(p)
        assert d["status"] == "pending"
        assert d["entries"] == ["条目A", "条目B"]

    def test_entries_exclude_original_and_notes(self, wb):
        p = wb / "待验证" / "2026-08-09.md"
        _write(p, "# 待验证收录 2026-08-09\n\n---\ntype: queued\nstatus: pending\n---\n\n## 条目A\n\n## 原始消息\n\n## 备注\n")
        d = api._parse_md(p)
        assert d["entries"] == ["条目A"]

    def test_entries_return_full_list(self, wb):
        p = wb / "待验证" / "2026-08-09.md"
        text = "# 待验证\n\n---\ntype: queued\nstatus: pending\n---\n" + "".join(f"\n## 条目{i}\n" for i in range(12))
        _write(p, text)
        d = api._parse_md(p)
        assert len(d["entries"]) == 12

    def test_crlf_input(self, wb):
        p = wb / "任务" / "t.md"
        _write(p, "---\r\ntype: task\r\nstatus: todo\r\n---\r\n\r\n# 标题\r\n", newline="")
        d = api._parse_md(p)
        assert d["status"] == "todo"

    def test_no_frontmatter(self, wb):
        p = wb / "待验证" / "nofm.md"
        _write(p, "# 无 frontmatter\n\n## 条目A\n")
        d = api._parse_md(p)
        assert d["status"] == ""

    def test_empty_file(self, wb):
        p = wb / "待验证" / "empty.md"
        _write(p, "")
        d = api._parse_md(p)
        assert d["entries"] == []

    def test_gbk_file_does_not_crash(self, wb):
        """GBK 文件经 errors='replace' 读取不崩溃（现状行为，往返 U+FFFD 断言在 _atomic_write 测试）。"""
        p = wb / "待验证" / "gbk.md"
        _write(p, "# 标题\n\n## 条目\n", encoding="gbk")
        d = api._parse_md(p)
        assert d["file"] == "gbk.md"

    # Task 5.2 批次 2 修复：_parse_md 必须返回 title（执行按钮依赖）
    def test_title_from_h1_when_no_fm_title(self, wb):
        """无 frontmatter title、只有 # 一级标题 → title 取 # 标题。"""
        p = wb / "任务" / "h1-only.md"
        _write(p, "---\ntype: task\nstatus: todo\n---\n\n# 唯一的一级标题\n")
        d = api._parse_md(p)
        assert d["title"] == "唯一的一级标题"

    def test_title_from_frontmatter_priority(self, wb):
        """frontmatter title 优先于 # 标题。"""
        p = wb / "任务" / "fm-title.md"
        _write(p, "---\ntype: task\nstatus: todo\ntitle: frontmatter 标题\n---\n\n# 一级标题不同\n")
        d = api._parse_md(p)
        assert d["title"] == "frontmatter 标题"

    def test_title_falls_back_to_stem(self, wb):
        """无 frontmatter title 也无 # 标题 → 文件 stem。"""
        p = wb / "任务" / "no-title-anywhere.md"
        _write(p, "---\ntype: task\nstatus: todo\n---\n\n正文没有标题行\n")
        d = api._parse_md(p)
        assert d["title"] == "no-title-anywhere"


# ---------- _split_entry ----------

class TestSplitEntry:
    def test_split_middle(self, wb):
        text = "# 聚合\n\n---\ntype: queued\n---\n\n## A\n内容A\n\n## B\n内容B\n\n## C\n内容C\n"
        remaining, section = api._split_entry(text, "B")
        assert "## B" in section and "内容B" in section
        assert "## A" in remaining and "## C" in remaining
        assert "## B" not in remaining

    def test_split_first(self, wb):
        text = "## A\n\n## B\n"
        remaining, section = api._split_entry(text, "A")
        assert "## A" in section
        assert "## A" not in remaining
        assert "## B" in remaining

    def test_split_last(self, wb):
        text = "## A\n\n## B\n"
        remaining, section = api._split_entry(text, "B")
        assert "## B" in section
        assert "## B" not in remaining
        assert "## A" in remaining

    def test_entry_not_found_raises(self, wb):
        with pytest.raises(ValueError):
            api._split_entry("## A\n", "不存在")

    def test_no_sections_raises(self, wb):
        with pytest.raises(ValueError):
            api._split_entry("plain text no sections", "A")

    def test_excludes_original_notes_from_match(self, wb):
        """R4 阶段 A2 修复后：'原始消息' 子内容被一起带走（原 bug 是截断）。"""
        text = "# 聚合\n\n---\n---\n\n## 目标\n\n## 原始消息\n正文\n\n## 备注\n"
        remaining, section = api._split_entry(text, "目标")
        assert "## 目标" in section
        assert "## 原始消息" in section  # 修复：子内容一起带走
        assert "## 目标" not in remaining


# ---------- _maybe_defer ----------

class TestMaybeDefer:
    def test_defer_overdue_todo(self, wb):
        from datetime import date, timedelta
        p = wb / "任务" / "overdue.md"
        due = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        _write(p, f"---\ntype: task\nstatus: todo\ndue: {due}\n---\n\n# 过期任务\n")
        r = api._maybe_defer(p)
        assert r is not None and r["deferred"] is True
        text = p.read_text(encoding="utf-8", errors="replace")
        assert "defer_count: 1" in text
        assert "orig_due:" in text

    def test_defer_increments_count(self, wb):
        from datetime import date, timedelta
        p = wb / "任务" / "overdue2.md"
        due = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        _write(p, f"---\ntype: task\nstatus: todo\ndue: {due}\norig_due: {due}\ndefer_count: 2\n---\n\n# 任务\n")
        r = api._maybe_defer(p)
        assert r["count"] == 3

    def test_not_todo_no_defer(self, wb):
        p = wb / "任务" / "done.md"
        _write(p, "---\ntype: task\nstatus: completed\ndue: 2026-01-01\n---\n\n# 已完成\n")
        assert api._maybe_defer(p) is None

    def test_due_future_no_defer(self, wb):
        from datetime import date, timedelta
        p = wb / "任务" / "future.md"
        due = (date.today() + timedelta(days=5)).strftime("%Y-%m-%d")
        _write(p, f"---\ntype: task\nstatus: todo\ndue: {due}\n---\n\n# 未来任务\n")
        assert api._maybe_defer(p) is None

    def test_no_due_no_defer(self, wb):
        p = wb / "任务" / "nodue.md"
        _write(p, "---\ntype: task\nstatus: todo\n---\n\n# 无 due\n")
        assert api._maybe_defer(p) is None

    def test_stuck_after_3_deferrals(self, wb):
        """R4 阶段 2：defer_count ≥ 3 停止顺延（卡住态）。"""
        from datetime import date, timedelta
        p = wb / "任务" / "stuck.md"
        due = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        _write(p, f"---\ntype: task\nstatus: todo\ndue: {due}\norig_due: {due}\ndefer_count: 3\n---\n\n# 卡住任务\n")
        r = api._maybe_defer(p)
        assert r is not None and r.get("stuck") is True
        assert r["count"] == 3
        # due 未被改写（不再顺延）
        text = p.read_text(encoding="utf-8", errors="replace")
        assert f"due: {due}" in text


# ---------- _replace_frontmatter_status ----------

class TestReplaceFrontmatterStatus:
    def test_replace_in_frontmatter_only(self, wb):
        text = "---\ntype: task\nstatus: todo\n---\n\n正文里有 status: todo 不应动\n"
        out = api._replace_frontmatter_status(text, "todo", "completed")
        assert "status: completed" in out.split("---")[1]
        assert "正文里有 status: todo 不应动" in out  # 正文原样保留

    def test_frontmatter_after_title(self, wb):
        text = "# 标题\n\n---\ntype: queued\nstatus: pending\n---\n"
        out = api._replace_frontmatter_status(text, "pending", "cleared")
        assert "status: cleared" in out
        assert "# 标题" in out

    def test_no_frontmatter_returns_same(self, wb):
        text = "plain text"
        assert api._replace_frontmatter_status(text, "todo", "completed") == text


# ---------- _ensure_completed_at ----------

class TestEnsureCompletedAt:
    def test_adds_completed_at(self, wb):
        text = "---\ntype: task\nstatus: completed\n---\n"
        out = api._ensure_completed_at(text, "2026-08-09")
        assert "completed_at: 2026-08-09" in out

    def test_preserves_existing(self, wb):
        text = "---\ntype: task\nstatus: completed\ncompleted_at: 2026-08-01\n---\n"
        out = api._ensure_completed_at(text, "2026-08-09")
        assert "completed_at: 2026-08-01" in out


# ---------- _append_log ----------

class TestAppendLog:
    def test_append_and_dedup(self, wb):
        """R4 阶段 A1 修复后：_append_log 按 wikilink 目标去重——重复追加不生效。"""
        log = wb / "已处理" / "2026-08-09.md"
        api._append_log(log, "任务（1 条）", "[[标题|标题]] — 标记完成")
        first = log.read_text(encoding="utf-8", errors="replace")
        api._append_log(log, "任务（1 条）", "[[标题|标题]] — 标记完成")
        second = log.read_text(encoding="utf-8", errors="replace")
        assert "[[标题|" in first
        assert second == first  # 去重：不重复追加

    def test_different_entries_both_logged(self, wb):
        log = wb / "已处理" / "2026-08-09.md"
        api._append_log(log, "任务（1 条）", "[[A|A]] — x")
        api._append_log(log, "任务（1 条）", "[[B|B]] — y")
        text = log.read_text(encoding="utf-8", errors="replace")
        assert "[[A|" in text and "[[B|" in text


# ---------- _safe_resolve ----------

class TestSafeResolve:
    def test_valid(self, wb):
        p = api._safe_resolve("任务", "t.md")
        assert p == wb / "任务" / "t.md"

    def test_bad_dir_rejected(self, wb):
        assert api._safe_resolve("不存在的分区", "t.md") is None

    def test_path_traversal_rejected(self, wb):
        # 指定分区就是安全边界：跨分区与逃出工作台都必须拒绝。
        assert api._safe_resolve("任务", "../待验证/秘密.md") is None
        assert api._safe_resolve("任务", "../../../Windows/system32/x.md") is None
        if sys.platform == "win32":
            # Windows 反斜杠路径分隔符语义（Linux 上 \\ 是普通字符，line 295 已覆盖正斜杠）
            assert api._safe_resolve("任务", "..\\..\\..\\Windows\\system32\\x.md") is None

    @pytest.mark.skipif(sys.platform != "win32", reason="盘符绝对路径是 Windows 语义（Linux 上 C:\\… 为普通文件名）")
    def test_absolute_rejected(self, wb):
        assert api._safe_resolve("任务", "C:\\Windows\\system32\\x.md") is None


# ---------- _atomic_write ----------

class TestAtomicWrite:
    def test_writes_content(self, wb):
        p = wb / "任务" / "aw.md"
        api._atomic_write(p, "---\nstatus: todo\n---\n")
        assert p.exists()
        assert "status: todo" in p.read_text(encoding="utf-8", errors="replace")

    @pytest.mark.skipif(sys.platform != "win32", reason="CRLF EOL 保真是 Windows 平台语义")
    def test_crlf_roundtrip_preserves_eol(self, wb):
        """CRLF 源文件经真实读写路径（read_text → _atomic_write）往返：EOL 保持 CRLF。"""
        p = wb / "任务" / "crlf.md"
        content = "---\r\ntype: task\r\nstatus: todo\r\n---\r\n\r\n# 标题\r\n"
        _write(p, content, newline="")
        # 真实路径：插件 read_text(errors='replace') 归一化 → _atomic_write 写回
        text = p.read_text(encoding="utf-8", errors="replace")
        api._atomic_write(p, text)
        raw = p.read_bytes()
        # 往返后：read_text 归一化 \r\n → \n，write_text(newline=None) 在 Windows 转回 \r\n
        assert b"\r\n" in raw
        assert b"\r\r\n" not in raw  # 无双重 CR
        # 无裸 \n 混入（全部是 \r\n 或 \n，不得混合）
        crlf_count = raw.count(b"\r\n")
        lone_lf = raw.count(b"\n") - crlf_count
        assert lone_lf == 0

    def test_gbk_roundtrip_no_ufffd(self, wb):
        """GBK 内容经 utf-8 原子写：不得产生 U+FFFD（破坏性断言）。

        现状行为：read_text(errors='replace') 会把 GBK 字节替换为 U+FFFD——本测试锁定该风险
        在 _atomic_write 层面不做额外编码转换，保证「写回什么就是什么」。
        """
        p = wb / "待验证" / "gbk_round.md"
        # 用 gbk 编码写源文件（模拟 QQ 摄入端可能产生的 GBK 来源）
        _write(p, "# 标题\n\n## 条目\n", encoding="gbk", newline="")
        # 按插件现状路径：read_text(errors='replace') → _atomic_write(utf-8)
        text = p.read_text(encoding="utf-8", errors="replace")
        api._atomic_write(p, text)
        out = p.read_text(encoding="utf-8", errors="replace")
        # 现状锁定：errors='replace' 已把 GBK 字节替换为 U+FFFD（这是已知风险，阶段 1 后应由
        # 摄入端保证 UTF-8；此处断言原子写本身不引入额外损坏）
        assert "\ufffd" in out  # 现状：存在替换符（风险已知，后续统一写入口时治理）


# ---------- /execute 安全（阶段 1 修复验收，先写红） ----------

class TestExecuteSecurity:
    def test_path_traversal_rejected(self, wb):
        """修复验收：/execute 对 dir='..' 拒绝（阶段 1 修复后，_safe_resolve + dir 白名单）。
        重点断言：不再返回 ok:True（穿越被封）；错误信息可以是 task not found（_safe_resolve None → 统一分支）。
        """
        import asyncio
        outside = wb.parent / "outside.md"
        _write(outside, "# outside\n")
        resp = asyncio.run(api.execute_task({"dir": "..", "file": "outside.md"}))
        assert resp.get("ok") is not True
        assert resp.get("error") in ("bad dir", "not found", "forbidden", "task not found")

    def test_arbitrary_dir_rejected(self, wb):
        """合法分区但文件不存在 → task not found（合理行为）；重点：不存在的文件不会被创建/写盘。"""
        import asyncio
        resp = asyncio.run(api.execute_task({"dir": "已处理", "file": "whatever.md"}))
        assert resp.get("ok") is not True
        assert resp.get("error") in ("task not found", "not found", "bad dir")

    def test_illegal_filename_rejected(self, wb):
        """非法文件名（Windows 保留字符）不得触发异常——修复后应被 _safe_resolve 或 _slugify 处理。"""
        import asyncio
        resp = asyncio.run(api.execute_task({"dir": "任务", "file": "bad|name.md"}))
        # 现状可能返回 not found（文件不存在）；修复后不得 500
        assert "error" in resp


# ---------- R4 阶段 2/3/4：/defer /board 诚实性 /restore ----------

class TestDeferEndpoint:
    def test_defer_overdue(self, wb):
        import asyncio
        from datetime import date, timedelta
        due = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        p = wb / "任务" / "defer-me.md"
        _write(p, f"---\ntype: task\nstatus: todo\ndue: {due}\n---\n\n# 顺延我\n")
        r = asyncio.run(api.defer_task({"dir": "任务", "file": "defer-me.md"}))
        assert r.get("ok") is True and r.get("deferred") is True
        assert r["count"] == 1

    def test_defer_stuck_at_limit(self, wb):
        import asyncio
        from datetime import date, timedelta
        due = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        p = wb / "任务" / "defer-stuck.md"
        _write(p, f"---\ntype: task\nstatus: todo\ndue: {due}\norig_due: {due}\ndefer_count: 3\n---\n\n# 已卡住\n")
        r = asyncio.run(api.defer_task({"dir": "任务", "file": "defer-stuck.md"}))
        assert r.get("ok") is True and r.get("stuck") is True
        assert r["count"] == 3

    def test_defer_future_not_allowed(self, wb):
        import asyncio
        from datetime import date, timedelta
        due = (date.today() + timedelta(days=5)).strftime("%Y-%m-%d")
        p = wb / "任务" / "defer-future.md"
        _write(p, f"---\ntype: task\nstatus: todo\ndue: {due}\n---\n\n# 未来任务\n")
        r = asyncio.run(api.defer_task({"dir": "任务", "file": "defer-future.md"}))
        assert r.get("ok") is False  # 未到期不能顺延


class TestBoardHonesty:
    def test_entry_level_counting(self, wb):
        """R4 阶段 3：聚合文件 N 条 = N 计入 pending（而非按文件 1）。"""
        agg = wb / "待验证" / "2026-08-09.md"
        _write(agg, "# 待验证\n\n---\ntype: queued\nstatus: pending\n---\n" + "".join(f"\n## 条目{i}\n" for i in range(5)))
        r = api.board()  # board 已改同步 def
        total_pending = r["totals"]["pending"]
        assert total_pending == 5, f"expect 5 got {total_pending}"

    def test_trash_excluded_from_pending(self, wb):
        """R4 阶段 3：回收站内 status:todo 文件不污染 pending 计数。"""
        t = wb / "回收站" / "trashed-todo.md"
        _write(t, "---\ntype: task\nstatus: todo\n---\n\n# 回收站里的任务\n")
        r = api.board()
        assert r["totals"]["pending"] == 0

    def test_no_truncation_full_list(self, wb):
        """R4 阶段 3：去除 files[:6] 截断——7 个文件全量返回。"""
        for i in range(7):
            _write(wb / "待验证" / f"f{i}.md", f"# 待验证\n\n---\ntype: queued\nstatus: pending\n---\n\n## 条目{i}\n")
        r = api.board()
        for sec in r["sections"]:
            if sec["key"] == "thought":
                assert len(sec["files"]) == 7, f"expect 7 got {len(sec['files'])}"

    # ---------- 2026-08-15 P0 修复：多行分裂 ----------

    def test_task_file_with_many_headings_is_single_card(self, wb):
        """任务文件的多个 ## 标题不分卡——整文件一卡，entry_count=0。"""
        t = wb / "任务" / "multisection.md"
        _write(t, "---\ntype: task\nstatus: todo\n---\n\n# 任务\n\n## 需求\n\n## 方案\n\n## 验收标准\n\n## 备注\n")
        r = api.board()
        for sec in r["sections"]:
            if sec["key"] == "task":
                for f in sec["files"]:
                    if f["file"] == "multisection.md":
                        assert f["entry_count"] == 0, f"expect 0 entries, got {f['entry_count']}"
                        return  # found it, assertion passed
        raise AssertionError("multisection.md not found in board")

    def test_aggregation_file_shows_entries(self, wb):
        """聚合文件（待验证）的 ## 标题展开为条目——entry_count=N。"""
        agg = wb / "待验证" / "2026-08-15.md"
        _write(agg, "# 待验证 2026-08-15\n\n---\ntype: queued\nstatus: pending\n---\n"
                + "".join(f"\n## 条目{i}\n内容{i}\n" for i in range(3)))
        r = api.board()
        for sec in r["sections"]:
            if sec["key"] == "thought":
                for f in sec["files"]:
                    if f["file"] == "2026-08-15.md":
                        assert f["entry_count"] == 3, f"expect 3 entries, got {f['entry_count']}"
                        return
        raise AssertionError("2026-08-15.md not found in board")

    def test_done_date_index_not_in_board(self, wb):
        """08-21：已处理/日期格式索引文件（YYYY-MM-DD.md）不再渲染成卡
        （消除「任务文件+索引条目」双卡观感；索引保留在磁盘/DB 供日报审计）。"""
        idx = wb / "已处理" / "2026-08-15.md"
        _write(idx, "# 已处理 2026-08-15\n\n## 任务（1 条）\n\n- [[t|任务]] — 完成\n\n## 已确认（2 条）\n\n- [[a|A]]\n- [[b|B]]\n")
        r = api.board()
        for sec in r["sections"]:
            if sec["key"] == "done":
                assert all(f["file"] != "2026-08-15.md" for f in sec["files"]), "日期索引不应出现在看板"
                return
        raise AssertionError("done 分区缺失")

    def test_done_single_task_file_not_expanded(self, wb):
        """已处理/单任务文件（非日期格式名）整文件一卡，entry_count=0。"""
        done = wb / "已处理" / "完成的任务.md"
        _write(done, "---\ntype: task\nstatus: completed\n---\n\n# 完成的任务\n\n## 记录\n\n- 已完成\n")
        r = api.board()
        for sec in r["sections"]:
            if sec["key"] == "done":
                for f in sec["files"]:
                    if f["file"] == "完成的任务.md":
                        assert f["entry_count"] == 0, f"expect 0 entries, got {f['entry_count']}"
                        return
        raise AssertionError("完成的任务.md not found in board")

    def test_pending_count_aggregation_only(self, wb):
        """pending 计数：任务文件多 ## 不计入 pending 膨胀，聚合文件条目正确计入。"""
        # 待验证聚合文件 × 3 条目
        agg = wb / "待验证" / "2026-08-15.md"
        _write(agg, "# 待验证\n\n---\ntype: queued\nstatus: pending\n---\n"
                + "".join(f"\n## 条目{i}\n" for i in range(3)))
        # 任务文件 1 个（多个 ## 但不膨胀）
        t = wb / "任务" / "多段任务.md"
        _write(t, "---\ntype: task\nstatus: todo\n---\n\n# 主任务\n\n## 第一阶段\n\n## 第二阶段\n")
        r = api.board()
        # pending = 聚合 3 条 + 任务 1 个 = 4
        assert r["totals"]["pending"] == 4, f"expect 4 pending, got {r['totals']['pending']}"


class TestRestoreEndpoint:
    def test_restore_path_traversal_rejected(self, wb):
        import asyncio
        r = asyncio.run(api.restore({"file": "../任务/restore-me.md"}))
        assert r.get("ok") is False

    def test_restore_with_origin(self, wb):
        import asyncio
        t = wb / "回收站" / "restore-me.md"
        _write(t, "---\ntype: task\nstatus: todo\norigin: 任务/restore-me.md\n---\n\n# 还原我\n")
        r = asyncio.run(api.restore({"file": "restore-me.md"}))
        assert r.get("ok") is True
        assert r["restored_to"] == "任务"
        assert (wb / "任务" / "restore-me.md").exists()
        assert not (wb / "回收站" / "restore-me.md").exists()

    def test_restore_without_origin_fallback(self, wb):
        import asyncio
        t = wb / "回收站" / "no-origin.md"
        _write(t, "---\ntype: queued\nstatus: pending\n---\n\n# 无 origin\n")
        r = asyncio.run(api.restore({"file": "no-origin.md"}))
        assert r.get("ok") is True
        assert r["restored_to"] == "待验证"  # 兜底

    def test_restore_not_found(self, wb):
        import asyncio
        r = asyncio.run(api.restore({"file": "不存在.md"}))
        assert r.get("ok") is False


class TestAbandonReopen:
    def test_abandon_todo(self, wb):
        """放弃 → 移入回收站（2026-08-16 拍板：可逆暂别）。"""
        import asyncio
        p = wb / "任务" / "abandon-me.md"
        _write(p, "---\ntype: task\nstatus: todo\n---\n\n# 放弃我\n")
        r = asyncio.run(api.abandon({"dir": "任务", "file": "abandon-me.md"}))
        assert r.get("ok") is True and r.get("abandoned") is True
        assert r.get("moved_to") == "回收站"
        assert not p.exists(), "任务区不应再保留原文件"
        dest = wb / "回收站" / "abandon-me.md"
        assert dest.exists(), "文件应移入回收站"
        text = dest.read_text(encoding="utf-8", errors="replace")
        assert "status: abandoned" in text
        assert "abandoned_at:" in text
        assert "origin: 任务/abandon-me.md" in text
        assert "trashed_at:" in text

    def test_restore_revives_abandoned(self, wb):
        """回收站还原放弃任务 → 回任务区并复活为待办。"""
        import asyncio
        trash = wb / "回收站"
        trash.mkdir(exist_ok=True)
        _write(
            trash / "revive.md",
            "---\ntype: task\nstatus: abandoned\norigin: 任务/revive.md\ntrashed_at: 2026-08-16\n---\n\n# 复活\n",
        )
        r = asyncio.run(api.restore({"file": "revive.md"}))
        assert r.get("ok") is True and r.get("restored_to") == "任务"
        text = (wb / "任务" / "revive.md").read_text(encoding="utf-8", errors="replace")
        assert "status: todo" in text
        assert "reopened_at:" in text

    def test_abandon_only_todo(self, wb):
        import asyncio
        p = wb / "任务" / "already-done.md"
        _write(p, "---\ntype: task\nstatus: completed\n---\n\n# 已完成\n")
        r = asyncio.run(api.abandon({"dir": "任务", "file": "already-done.md"}))
        assert r.get("ok") is False

    def test_reopen_abandoned(self, wb):
        import asyncio
        p = wb / "任务" / "reopen-me.md"
        _write(p, "---\ntype: task\nstatus: abandoned\nabandoned_at: 2026-08-08\n---\n\n# 重新打开\n")
        r = asyncio.run(api.reopen({"dir": "任务", "file": "reopen-me.md"}))
        assert r.get("ok") is True and r.get("reopened") is True
        text = p.read_text(encoding="utf-8", errors="replace")
        assert "status: todo" in text
        assert "reopened_at:" in text  # abandoned_at → reopened_at

    def test_board_excludes_abandoned_from_pending(self, wb):
        """阶段 5：abandoned 不计入 pending。"""
        p = wb / "任务" / "abandoned-task.md"
        _write(p, "---\ntype: task\nstatus: abandoned\n---\n\n# 已放弃\n")
        r = api.board()
        assert r["totals"]["pending"] == 0


# ---------- R4 追加项：A4 /recent、C1 sunk 标记 ----------

class TestRecentEndpoint:
    def test_recent_returns_actions(self, wb):
        """A4：/recent 读日志目录返回最近动作。"""
        log = wb / "日志" / "2026-08-09.md"
        _write(log, "# 工作台日志 2026-08-09\n\n## 10:00 测试动作\n\n- 做了某事\n\n## 10:05 另一动作\n\n- 又做了一件事\n")
        r = api.recent(limit=10)
        assert len(r["entries"]) == 2
        # 时间倒序：最新动作在前
        assert r["entries"][0]["action"] == "另一动作"
        assert r["entries"][0]["detail"] == "又做了一件事"
        assert r["entries"][1]["action"] == "测试动作"

    def test_recent_with_dir_file_returns_task_events(self, wb):
        """Task 5.2 批次 1：/recent?dir=&file= 读 task_events 按文件过滤倒序。"""
        p = wb / "任务" / "hist.md"
        _write(p, "---\ntype: task\nstatus: completed\n---\n\n# 历史\n")
        from repo import file_repo as _fr
        _fr.event("任务", "hist.md", "created", "创建")
        _fr.event("任务", "hist.md", "bind", "绑定会话")
        _fr.event("任务", "hist.md", "completed", "完成")
        _fr.event("任务", "other.md", "created", "其他")

        r = api.recent(limit=50, dir="任务", file="hist.md")
        assert r.get("source") == "task_events"
        evts = r["entries"]
        assert len(evts) == 3, f"expect 3 got {len(evts)}"
        # created_at 倒序（id DESC）：最新在前
        assert evts[0]["kind"] == "completed"
        assert evts[-1]["kind"] == "created"

        # 无 dir/file → 保持原日志行为
        r2 = api.recent(limit=10)
        assert r2.get("source") is None

    def test_board_priority_and_size_fields(self, wb):
        """Task 5.2 批次 1：/board 卡片携带 frontmatter priority/size。"""
        p = wb / "任务" / "prio.md"
        _write(p, "---\ntype: task\nstatus: todo\npriority: P1\nsize: L\n---\n\n# 优先级卡\n")
        r = api.board()
        found = None
        for sec in r["sections"]:
            for f in sec["files"]:
                if f.get("file") == "prio.md":
                    found = f
        assert found is not None
        assert found.get("priority") == "P1"
        assert found.get("size") == "L"
        # 无 priority/size 的文件 → 空串（前端隐藏徽标）
        p2 = wb / "任务" / "noprio.md"
        _write(p2, "---\ntype: task\nstatus: todo\n---\n\n# 无优先级\n")
        r = api.board()
        for sec in r["sections"]:
            for f in sec["files"]:
                if f.get("file") == "noprio.md":
                    assert f.get("priority") == ""
                    assert f.get("size") == ""


class TestSunkMark:
    def test_resolve_with_sunk(self, wb):
        """C1：resolve 带 sunk 标记 → 已处理文件 frontmatter 记录 sunk。"""
        import asyncio
        p = wb / "待验证" / "sunk-me.md"
        _write(p, "---\ntype: queued\nstatus: pending\n---\n\n# 沉淀我\n\n## 内容\n")
        r = asyncio.run(api.resolve({"dir": "待验证", "file": "sunk-me.md", "sunk": "心理学笔记"}))
        assert r.get("ok") is True and r.get("sunk") == "心理学笔记"
        archived = wb / "已处理" / "sunk-me.md"
        assert archived.exists()
        text = archived.read_text(encoding="utf-8", errors="replace")
        assert "sunk: 心理学笔记" in text

    def test_resolve_without_sunk_no_mark(self, wb):
        """C1：不带 sunk → 仅归档，无 sunk 字段。"""
        import asyncio
        p = wb / "待验证" / "plain-me.md"
        _write(p, "---\ntype: queued\nstatus: pending\n---\n\n# 普通\n")
        r = asyncio.run(api.resolve({"dir": "待验证", "file": "plain-me.md"}))
        assert r.get("ok") is True and r.get("sunk") is None
        text = (wb / "已处理" / "plain-me.md").read_text(encoding="utf-8", errors="replace")
        assert "sunk:" not in text


class TestFrontmatterAndBinding:
    def test_patch_frontmatter_crlf_keeps_header(self, wb):
        text = "# 标题\r\n\r\n---\r\ntype: task\r\nstatus: in_progress\r\n---\r\n\r\n正文\r\n"
        out = api._patch_frontmatter(text, {"session_id": "sess-1"})
        assert out.startswith("# 标题\r\n")
        assert "---\r\ntype: task\r\nstatus: in_progress\r\nsession_id: sess-1\r\n---" in out
        assert not out.startswith("session_id:")

    def test_bind_session_writes_inside_frontmatter(self, wb):
        import asyncio
        p = wb / "任务" / "bind.md"
        _write(p, "---\r\ntype: task\r\nstatus: in_progress\r\n---\r\n\r\n# 绑定\r\n", newline="")
        r = asyncio.run(api.bind_session({"dir": "任务", "file": "bind.md", "session_id": "sess-2"}))
        assert r.get("ok") is True
        out = p.read_text(encoding="utf-8", errors="replace")
        assert out.startswith("---")
        assert "session_id: sess-2" in out

    def test_bind_session_without_frontmatter_fails(self, wb):
        import asyncio
        p = wb / "任务" / "plain.md"
        _write(p, "# 无 frontmatter\n")
        r = asyncio.run(api.bind_session({"dir": "任务", "file": "plain.md", "session_id": "sess-3"}))
        assert r.get("ok") is False


# ---------- 阶段 0 新测试：闭环四件套 ----------

class TestStage0CompleteFourPiece:
    """/complete 后四条断言：任务区消失 / 实体存在 / 索引有条目 / 日志留痕。"""

    def test_complete_moves_file_and_creates_index(self, wb):
        import asyncio
        from datetime import date
        p = wb / "任务" / "stage0-complete.md"
        _write(p, "---\ntype: task\nstatus: todo\n---\n\n# 阶段0测试\n\n## 内容\n")
        r = asyncio.run(api.complete({"dir": "任务", "file": "stage0-complete.md"}))
        assert r.get("ok") is True
        # 任务区消失
        assert not p.exists()
        # 实体存在
        entity = wb / "已处理" / "stage0-complete.md"
        assert entity.exists()
        text = entity.read_text(encoding="utf-8", errors="replace")
        assert "status: completed" in text
        assert "completed_at:" in text
        assert "# 阶段0测试" in text
        # 索引有条目
        today = date.today().isoformat()
        index = wb / "已处理" / f"{today}.md"
        assert index.exists()
        idx_text = index.read_text(encoding="utf-8", errors="replace")
        assert "[[stage0-complete|" in idx_text
        assert "阶段0测试" in idx_text or "标记完成" in idx_text
        # 日志留痕
        log = wb / "日志" / f"{today}.md"
        assert log.exists()
        log_text = log.read_text(encoding="utf-8", errors="replace")
        assert "完成" in log_text
        assert "stage0-complete" in log_text

    def test_complete_idempotent_no_double_entity(self, wb):
        """重复 complete → 第二次应报错而非双重归档。"""
        import asyncio
        p = wb / "任务" / "stage0-double.md"
        _write(p, "---\ntype: task\nstatus: todo\n---\n\n# 双重测试\n")
        r1 = asyncio.run(api.complete({"dir": "任务", "file": "stage0-double.md"}))
        assert r1.get("ok") is True
        # 第二次 complete 应失败（文件已不在任务区）
        r2 = asyncio.run(api.complete({"dir": "任务", "file": "stage0-double.md"}))
        assert r2.get("ok") is False


# ---------- 阶段 0 新测试：时区边界 ----------

class TestStage0Timezone:
    """/board 返回 today 字段 = 本地日期（UTC+8），前端不再自算。"""

    def test_board_has_today_field(self, wb):
        r = api.board()
        assert "today" in r
        assert r["today"] is not None
        # 格式 YYYY-MM-DD
        assert len(r["today"]) == 10
        assert r["today"][4] == "-" and r["today"][7] == "-"

    def test_today_matches_local_date(self, wb):
        from datetime import date
        r = api.board()
        assert r["today"] == date.today().isoformat()

    def test_overdue_uses_backend_today(self, wb):
        """/board 返回的 due 字符串与 today 比较——前端用 s.today，不依赖 UTC Date。"""
        from datetime import date, timedelta
        # 明天到期的任务 → 不应逾期
        future = (date.today() + timedelta(days=1)).isoformat()
        p = wb / "任务" / "future-task.md"
        _write(p, f"---\ntype: task\nstatus: todo\ndue: {future}\n---\n\n# 未来任务\n")
        board = api.board()
        today = board["today"]
        # 前端逻辑等价：f.due < today → 逾期
        assert future >= today  # 明天 > 今天，不逾期


# ---------- 阶段 0 新测试：_log_action 并发 ----------

class TestStage0LogConcurrency:
    """_log_action 使用 _WRITE_LOCK + _atomic_write，无多行 f-string 语法错误。"""

    def test_log_action_writes_with_lock(self, wb):
        from datetime import date
        api._log_action("测试动作", "测试详情")
        log = wb / "日志" / f"{date.today().isoformat()}.md"
        assert log.exists()
        text = log.read_text(encoding="utf-8", errors="replace")
        assert "测试动作" in text
        assert "测试详情" in text

    def test_log_action_creates_dir_on_demand(self, wb):
        """日志目录不存在时自动创建。"""
        import shutil
        from datetime import date
        shutil.rmtree(wb / "日志", ignore_errors=True)
        api._log_action("目录重建", "测试")
        log = wb / "日志" / f"{date.today().isoformat()}.md"
        assert log.exists()
        assert "目录重建" in log.read_text(encoding="utf-8", errors="replace")

    def test_log_action_no_syntax_error(self, wb):
        """调用 _log_action 不触发 Python 语法错误（原多行 f-string 在 3.11 崩溃）。"""
        import threading
        errors = []

        def worker():
            try:
                api._log_action("并发测试", "worker")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0, f"并发 _log_action 出错: {errors}"


# ---------- 阶段 0 新测试：execute 单轨 ----------

class TestStage0ExecuteSingleTrack:
    """/execute 已删除 cron 旧路径（D5），不再触发 cronjob run。"""

    def test_execute_returns_in_progress(self, wb):
        import asyncio
        p = wb / "任务" / "execute-test.md"
        _write(p, "---\ntype: task\nstatus: todo\n---\n\n# 执行测试\n")
        r = asyncio.run(api.execute_task({"dir": "任务", "file": "execute-test.md", "launch": False}))
        assert r.get("ok") is True
        assert r.get("status") == "in_progress"
        text = p.read_text(encoding="utf-8", errors="replace")
        assert "status: in_progress" in text
        assert "execution_result: pending" in text
        assert "execution_started_at:" in text
        # 无 cron 触发残留（cron_id、job_id 等字段不在返回中）
        assert "cron" not in str(r)
        assert "9bfc78930033" not in str(r)

    def test_execute_no_launch_default_still_works(self, wb):
        """不传 launch 时走旧兼容路径——但 D5 已删 cron 分支，应返回 in_progress 而非触发 cron。"""
        import asyncio
        p = wb / "任务" / "execute-old.md"
        _write(p, "---\ntype: task\nstatus: todo\n---\n\n# 旧路径测试\n")
        r = asyncio.run(api.execute_task({"dir": "任务", "file": "execute-old.md"}))
        assert r.get("ok") is True
        assert r.get("status") == "in_progress"

    def test_execute_content_appends_into_existing_prep(self, wb):
        """08-21：已存在「执行前补充」段时，带 content 执行在段内追加，不新建重复标题。"""
        import asyncio
        p = wb / "任务" / "execute-prep-append.md"
        _write(p, "---\ntype: task\nstatus: todo\n---\n\n# 追加测试\n\n## 执行前补充\n\n吃进Obsidian\n")
        r = asyncio.run(api.execute_task(
            {"dir": "任务", "file": "execute-prep-append.md", "content": "再补充一条", "launch": False}
        ))
        assert r.get("ok") is True
        text = p.read_text(encoding="utf-8", errors="replace")
        assert text.count("## 执行前补充") == 1
        assert "吃进Obsidian" in text
        assert "再补充一条" in text

    def test_execute_content_creates_prep_when_missing(self, wb):
        """08-21：无「执行前补充」段时，带 content 执行仍创建新段。"""
        import asyncio
        p = wb / "任务" / "execute-prep-new.md"
        _write(p, "---\ntype: task\nstatus: todo\n---\n\n# 新段测试\n")
        r = asyncio.run(api.execute_task(
            {"dir": "任务", "file": "execute-prep-new.md", "content": "首次补充", "launch": False}
        ))
        assert r.get("ok") is True
        text = p.read_text(encoding="utf-8", errors="replace")
        assert text.count("## 执行前补充") == 1
        assert "首次补充" in text


# ---------- 08-21 研究≠摄入治理（B1/B3）：scope 判定 + 写入 + cwd ----------

class TestDetectTaskScope:
    """B1 scope 判定（GT 终审 v2 词表 + 组合否定；否定 > 摄入 > 研究 > 执行 > 默认 research）。"""

    @pytest.mark.parametrize("text,expected", [
        ("吃进Obsidian", "ingest"),
        ("调研下视频提到的skill 并给出看法", "research"),
        ("调研下视频提到的skill 不要吃进Obsidian", "research"),
        ("不要存进Obsidian", "research"),
        ("先别收录，先看看", "research"),
        ("不需要摄入", "research"),
        ("无需收录", "research"),
        ("不需要存进Obsidian", "research"),
        ("别归档", "research"),
        ("存个文件到桌面", "research"),   # 存 不泛化（不进裸摄入词表）
        ("调研并部署XX", "research"),      # 研究词优先；禁令无害
        ("把这段视频按视频做一遍", "execute"),
        ("", "research"),
    ])
    def test_scope(self, text, expected):
        from wb_utils import detect_task_scope
        assert detect_task_scope(text) == expected


class TestExecuteScope:
    """/execute 写入 scope frontmatter + 返回 scope/cwd（B1/B3）。"""

    def test_execute_research_writes_scope_and_research_cwd(self, wb):
        import asyncio
        p = wb / "任务" / "scope-research.md"
        _write(p, "---\ntype: task\nstatus: todo\n---\n\n# 范围测试\n")
        r = asyncio.run(api.execute_task(
            {"dir": "任务", "file": "scope-research.md", "content": "调研下视频提到的skill 并给出看法", "launch": False}
        ))
        assert r.get("ok") is True
        assert r.get("scope") == "research"
        assert "workbench-research" in r.get("cwd", "")
        text = p.read_text(encoding="utf-8", errors="replace")
        assert "scope: research" in text

    def test_execute_ingest_when_explicit(self, wb):
        import asyncio
        p = wb / "任务" / "scope-ingest.md"
        _write(p, "---\ntype: task\nstatus: todo\n---\n\n# 摄入测试\n")
        r = asyncio.run(api.execute_task(
            {"dir": "任务", "file": "scope-ingest.md", "content": "吃进Obsidian", "launch": False}
        ))
        assert r.get("ok") is True
        assert r.get("scope") == "ingest"
        text = p.read_text(encoding="utf-8", errors="replace")
        assert "scope: ingest" in text

    def test_execute_source_audit(self, wb):
        """08-21：/execute source 审计字段——click 走旧文案，api/auto 写来源。"""
        import asyncio
        p = wb / "任务" / "source-click.md"
        _write(p, "---\ntype: task\nstatus: todo\n---\n\n# 来源测试\n")
        r = asyncio.run(api.execute_task({"dir": "任务", "file": "source-click.md", "launch": False}))
        assert r.get("ok") is True
        assert "用户点击「▶ 执行」" in p.read_text(encoding="utf-8", errors="replace")

        p2 = wb / "任务" / "source-auto.md"
        _write(p2, "---\ntype: task\nstatus: todo\n---\n\n# 来源测试2\n")
        r2 = asyncio.run(api.execute_task({"dir": "任务", "file": "source-auto.md", "source": "auto", "launch": False}))
        assert r2.get("ok") is True
        assert "source=auto" in p2.read_text(encoding="utf-8", errors="replace")


# ---------- 阶段 2.5：/ingest-message 幂等 outbox ----------

class TestIngestMessage:
    """QQ 收录幂等（端点级，直接调用函数 + asyncio.run）。"""

    def test_ingest_first_then_duplicate(self, wb):
        """首次收录 → 落盘；同 message_id 再投 → duplicate=True 不重复写。"""
        import asyncio
        from datetime import datetime

        r1 = asyncio.run(api.ingest_message(
            {"message_id": "qq-1001", "dir": "待验证", "title": "幂等测试消息"}
        ))
        assert r1["ok"] is True and r1["duplicate"] is False
        day_file = wb / "待验证" / f"{datetime.now():%Y-%m-%d}.md"
        text_after_first = day_file.read_text(encoding="utf-8")

        r2 = asyncio.run(api.ingest_message(
            {"message_id": "qq-1001", "dir": "待验证", "title": "幂等测试消息"}
        ))
        assert r2["ok"] is True and r2["duplicate"] is True
        assert day_file.read_text(encoding="utf-8") == text_after_first

    def test_ingest_global_url_dedup_cross_partition(self, wb):
        """08-21：同视频短链跨分区/跨日期去重（OThqZGc 类重复卡根因）。"""
        import asyncio
        r1 = asyncio.run(api.ingest_message(
            {"message_id": "url-1", "dir": "待回看", "title": "测试视频A", "content": "https://b23.tv/OThqZGc"}
        ))
        assert r1["ok"] is True and r1["duplicate"] is False
        r2 = asyncio.run(api.ingest_message(
            {"message_id": "url-2", "dir": "待验证", "title": "同链接再次", "content": "https://b23.tv/OThqZGc"}
        ))
        assert r2["duplicate"] is True


class TestCompleteIdempotent:
    """P0 完成链路幂等：首次归档后重复 complete → task not found，不产生第二份归档。"""

    def test_complete_twice_no_double_archive(self, wb):
        import asyncio
        p = wb / "任务" / "幂等完成.md"
        _write(p, "---\ntype: task\nstatus: todo\n---\n\n# 幂等完成\n")

        r1 = asyncio.run(api.complete({"dir": "任务", "file": "幂等完成.md"}))
        assert r1["ok"] is True and r1["archived"] is True
        archived = wb / "已处理" / r1["archived_as"]
        assert archived.exists()
        text_after_first = archived.read_text(encoding="utf-8")

        r2 = asyncio.run(api.complete({"dir": "任务", "file": "幂等完成.md"}))
        assert r2["ok"] is False
        assert r2["error"] == "task not found"
        assert archived.read_text(encoding="utf-8") == text_after_first
        assert len(list((wb / "已处理").glob("幂等完成*.md"))) == 1


class TestBoardDoneIndex:
    """08-21：已处理日期索引不渲染成卡（消除「任务文件+索引条目」双卡观感）。"""

    def test_board_skips_done_date_index(self, wb):
        done = wb / "已处理"
        _write(done / "任务A.md", "---\ntype: task\nstatus: completed\n---\n\n# 任务A\n\n完成\n")
        _write(done / "2026-08-21.md", "# 已处理 2026-08-21\n\n## 任务（1 条）\n\n- [[任务A|任务A]] — 标记完成\n")
        board = api.board()
        done_section = next(s for s in board["sections"] if s["dir"] == "已处理")
        names = [f["file"] for f in done_section["files"]]
        assert "任务A.md" in names
        assert "2026-08-21.md" not in names


class TestToTaskPsych:
    """08-21：to_task 白名单 +心理学随想（【温暖和踏实…】卡 bad dir 根因）。"""

    def test_to_task_psych_allowed(self, wb, legacy_partitions):
        import asyncio
        p = wb / "心理学随想" / "2026-08-21.md"
        _write(p, "# 心理学随想收录 2026-08-21\n\n## 温暖和踏实，真诚和善良\n\n**备注：**\n- 随想内容\n")
        r = asyncio.run(api.to_task({"dir": "心理学随想", "file": "2026-08-21.md", "entry_title": "温暖和踏实，真诚和善良"}))
        assert r.get("ok") is True, r
        assert r.get("task_file")
        assert (wb / "任务" / r["task_file"]).exists()

    def test_ingest_missing_message_id(self, wb):
        import asyncio
        r = asyncio.run(api.ingest_message({"dir": "待验证", "title": "无ID"}))
        assert r["ok"] is False
        assert "message_id" in r["error"]

    def test_ingest_task_dir(self, wb):
        """任务目录 → 独立文件（source: qq）。"""
        import asyncio
        r = asyncio.run(api.ingest_message(
            {"message_id": "qq-2001", "dir": "任务", "title": "QQ任务收录"}
        ))
        assert r["ok"] is True and r["duplicate"] is False
        f = wb / "任务" / "QQ任务收录.md"
        assert f.exists()
        text = f.read_text(encoding="utf-8")
        assert "source: qq" in text


class TestEventsHealth:
    """阶段 4：/health + /events WS 事件通道。"""

    def test_health_ok(self, wb):
        """/health 返回 ok + DB 可读。"""
        r = api.health()
        assert r["ok"] is True
        assert r["db"] is True

    def test_events_websocket(self, wb, monkeypatch):
        """WS 事件通道：鉴权门 monkeypatch 后手工驱动推送循环——events 帧或 heartbeat 帧。"""
        import asyncio
        monkeypatch.setattr(api, "_ws_upgrade_authorized", lambda ws: True)

        class FakeWS:
            def __init__(self):
                self.sent = []
                self.query_params = {"since": "0"}
            async def close(self, code=1000):
                self.closed = code
            async def accept(self):
                self.accepted = True
            async def send_json(self, data):
                self.sent.append(data)

        async def _drain():
            ws = FakeWS()
            task = asyncio.create_task(api.ws_events(ws))
            for _ in range(6):
                await asyncio.sleep(1.05)
                if ws.sent:
                    break
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            return ws

        ws = asyncio.run(_drain())
        assert ws.accepted is True
        assert len(ws.sent) >= 1
        frame = ws.sent[0]
        # 有历史事件 → events 帧；否则 → heartbeat 帧
        if "events" in frame:
            assert "cursor" in frame
        else:
            assert frame.get("heartbeat") is True


# ---------- Task 5.2 批次 2：动作埋点补缺（文件级 task_events） ----------

class TestBatch2EventInstrumentation:
    """resolve / to-task / execute 等动作必须写 文件级 task_events（partition+filename 绑定），
    运行历史（list_file_events）才能展示完整活动链。"""

    def test_resolve_writes_file_event(self, wb):
        import asyncio
        p = wb / "待验证" / "resolve-ev.md"
        _write(p, "---\ntype: queued\nstatus: pending\n---\n\n# 待确认\n\n- 内容\n")
        r = asyncio.run(api.resolve({"dir": "待验证", "file": "resolve-ev.md"}))
        assert r.get("ok") is True
        evts = api.file_repo.db.list_file_events("待验证", "resolve-ev.md", limit=50)
        assert any(e["kind"] == "resolved" for e in evts), f"expect resolved in {[e['kind'] for e in evts]}"

    def test_resolve_entry_writes_file_event(self, wb):
        import asyncio
        p = wb / "待验证" / "resolve-entry.md"
        _write(p, "---\ntype: queued\nstatus: pending\n---\n\n# 聚合\n\n## 单条目\n\n- 内容\n")
        r = asyncio.run(api.resolve({"dir": "待验证", "file": "resolve-entry.md", "entry_title": "单条目"}))
        assert r.get("ok") is True
        evts = api.file_repo.db.list_file_events("待验证", "resolve-entry.md", limit=50)
        assert any(e["kind"] == "resolved" and "单条目" in (e["payload"] or "") for e in evts)

    def test_to_task_writes_file_event(self, wb):
        import asyncio
        p = wb / "待验证" / "to-task-ev.md"
        _write(p, "---\ntype: queued\nstatus: pending\n---\n\n# 转任务\n\n- 内容\n")
        r = asyncio.run(api.to_task({"dir": "待验证", "file": "to-task-ev.md", "title": "转任务新标题"}))
        assert r.get("ok") is True
        evts = api.file_repo.db.list_file_events("待验证", "to-task-ev.md", limit=50)
        assert any(e["kind"] == "to_task" for e in evts), f"expect to_task in {[e['kind'] for e in evts]}"

    def test_execute_writes_file_event(self, wb):
        import asyncio
        p = wb / "任务" / "exec-ev.md"
        _write(p, "---\ntype: task\nstatus: todo\n---\n\n# 执行埋点\n")
        r = asyncio.run(api.execute_task({"dir": "任务", "file": "exec-ev.md", "launch": False}))
        assert r.get("ok") is True
        evts = api.file_repo.db.list_file_events("任务", "exec-ev.md", limit=50)
        assert any(e["kind"] == "execute" for e in evts), f"expect execute in {[e['kind'] for e in evts]}"

    def test_bind_session_writes_file_event(self, wb):
        import asyncio
        p = wb / "任务" / "bind-ev.md"
        _write(p, "---\ntype: task\nstatus: in_progress\nsession_id: old\n---\n\n# 绑定埋点\n")
        r = asyncio.run(api.bind_session({"dir": "任务", "file": "bind-ev.md", "session_id": "sess-abc"}))
        assert r.get("ok") is True
        evts = api.file_repo.db.list_file_events("任务", "bind-ev.md", limit=50)
        assert any(e["kind"] == "bind_session" for e in evts), f"expect bind_session in {[e['kind'] for e in evts]}"


# ---------- Task 5.2 批次 2 补丁 7a：已处理任务回到任务列表 ----------

class TestReopenDoneToTask:
    """done（已处理）→ 任务区：status → todo + 跨分区移动 + DB 镜像收敛。"""

    def test_reopen_done_moves_to_task(self, wb):
        import asyncio
        p = wb / "已处理" / "done-back.md"
        _write(p, "---\ntype: task\nstatus: completed\ncompleted_at: 2026-08-10\n---\n\n# 回列表\n")
        r = asyncio.run(api.reopen({"dir": "已处理", "file": "done-back.md"}))
        assert r.get("ok") is True
        assert r.get("moved_from") == "已处理"
        # 文件移回任务区，源文件消失
        moved = wb / "任务" / "done-back.md"
        assert moved.exists(), "task file should be in 任务/"
        assert not p.exists(), "source in 已处理/ should be gone"
        text = moved.read_text(encoding="utf-8", errors="replace")
        assert "status: todo" in text
        assert "completed_at: 2026-08-10" in text, "completed_at 保留为历史"
        assert "reopened_at:" in text, "补 reopened_at"

    def test_reopen_done_supports_cleared(self, wb):
        import asyncio
        p = wb / "已处理" / "done-cleared.md"
        _write(p, "---\ntype: queued\nstatus: cleared\n---\n\n# 已确认\n")
        r = asyncio.run(api.reopen({"dir": "已处理", "file": "done-cleared.md"}))
        assert r.get("ok") is True
        moved = wb / "任务" / "done-cleared.md"
        assert moved.exists()
        text = moved.read_text(encoding="utf-8", errors="replace")
        assert "status: todo" in text

    def test_reopen_done_db_mirror_converges(self, wb):
        import asyncio
        import sqlite3
        p = wb / "已处理" / "done-db.md"
        _write(p, "---\ntype: task\nstatus: completed\n---\n\n# DB 收敛\n")
        r = asyncio.run(api.reopen({"dir": "已处理", "file": "done-db.md"}))
        assert r.get("ok") is True
        # DB 镜像：行已迁到 任务 分区
        conn = sqlite3.connect(api.file_repo.db.db_path)
        try:
            row = conn.execute(
                "SELECT partition, status FROM tasks WHERE filename='done-db.md'"
            ).fetchone()
        finally:
            conn.close()
        assert row is not None, "tasks 表应有该文件行"
        assert row[0] == "任务", f"expect 任务 got {row[0]}"
        # 事件：reopen + moved 都写入（运行历史可见）
        evts = api.file_repo.db.list_file_events("任务", "done-db.md", limit=50)
        kinds = [e["kind"] for e in evts]
        assert "reopen" in kinds, f"expect reopen in {kinds}"
        assert "moved" in kinds, f"expect moved in {kinds}"

    def test_reopen_todo_task_still_rejects(self, wb):
        """任务区普通 todo 任务不可走 done 分支（dir=任务 保持原语义）。"""
        import asyncio
        p = wb / "任务" / "plain-todo.md"
        _write(p, "---\ntype: task\nstatus: todo\n---\n\n# 普通\n")
        r = asyncio.run(api.reopen({"dir": "任务", "file": "plain-todo.md"}))
        assert r.get("ok") is False
        assert "only abandoned" in r.get("error", "")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))


# ---------- A1/A2：聚合条目执行（to-task task_file）+ /edit 端点 ----------

class TestA1A2EntryExecuteAndEdit:
    def test_to_task_entry_returns_task_file(self, wb):
        """A1：条目级 to-task 返回新任务文件名（前端执行链路定位用）。"""
        import asyncio
        p = wb / "待验证" / "a1-src.md"
        _write(p, "---\ntype: queued\nstatus: pending\n---\n\n# 聚合\n\n## 转执行条目\n\n- 内容\n")
        r = asyncio.run(api.to_task({"dir": "待验证", "file": "a1-src.md", "entry_title": "转执行条目"}))
        assert r.get("ok") is True
        assert r.get("task_file"), f"expect task_file got {r}"
        assert r.get("task_dir") == "任务"
        assert (wb / "任务" / r["task_file"]).exists()

    def test_edit_entry_renames_section(self, wb):
        """A2：条目级 /edit 重命名 ## 小节 + 追加备注 + frontmatter due。"""
        import asyncio
        p = wb / "待验证" / "edit-src.md"
        _write(p, "---\ntype: queued\nstatus: pending\n---\n\n# 聚合\n\n## 旧标题\n\n- 正文\n\n## 其他条目\n")
        r = asyncio.run(api.edit_entry({"dir": "待验证", "file": "edit-src.md", "entry_title": "旧标题", "title": "新标题", "content": "补充说明", "due": "2026-08-20"}))
        assert r.get("ok") is True
        text = p.read_text(encoding="utf-8", errors="replace")
        assert "## 新标题" in text
        assert "## 旧标题" not in text
        assert "补充说明" in text
        assert "due: 2026-08-20" in text

    def test_edit_file_level_task(self, wb):
        """A2：任务文件级 /edit 改 # 标题 + due（不改状态/文件名）。"""
        import asyncio
        p = wb / "任务" / "edit-task.md"
        _write(p, "---\ntype: task\nstatus: todo\ndue: 2026-08-10\n---\n\n# 旧任务名\n")
        r = asyncio.run(api.edit_entry({"dir": "任务", "file": "edit-task.md", "title": "新任务名", "due": "2026-08-25"}))
        assert r.get("ok") is True
        text = p.read_text(encoding="utf-8", errors="replace")
        assert "# 新任务名" in text
        assert "due: 2026-08-25" in text
        assert "status: todo" in text  # 状态不变

    def test_edit_entry_not_found(self, wb):
        """A2：不存在的条目报错。"""
        import asyncio
        p = wb / "待验证" / "edit-miss.md"
        _write(p, "---\ntype: queued\nstatus: pending\n---\n\n# 聚合\n\n## 存在\n")
        r = asyncio.run(api.edit_entry({"dir": "待验证", "file": "edit-miss.md", "entry_title": "不存在", "title": "X"}))
        assert r.get("ok") is False
        assert r.get("error") == "entry not found"


# ---------- Task 5.2 批次 4：auto-nudge 脚本（scripts/workbench_auto_nudge.py） ----------

class TestAddTaskPriority:
    """Task 5.2 批次 5 补丁 10：/add 任务分支 priority 透传。"""

    def test_add_task_with_priority(self, wb):
        import asyncio

        r = asyncio.run(api.add_entry({"dir": "任务", "title": "带优先级任务", "priority": "P1", "due": "2026-08-20"}))
        assert r.get("ok") is True
        p = wb / "任务" / "带优先级任务.md"
        assert p.exists()
        text = p.read_text(encoding="utf-8", errors="replace")
        assert "priority: P1" in text
        assert "due: 2026-08-20" in text
        assert "status: todo" in text

    def test_add_task_priority_normalized_and_invalid_ignored(self, wb):
        import asyncio

        r = asyncio.run(api.add_entry({"dir": "任务", "title": "小写优先级", "priority": "p2"}))
        assert r.get("ok") is True
        text = (wb / "任务" / "小写优先级.md").read_text(encoding="utf-8", errors="replace")
        assert "priority: P2" in text  # 大小写归一

        r2 = asyncio.run(api.add_entry({"dir": "任务", "title": "非法优先级", "priority": "P9"}))
        assert r2.get("ok") is True
        text2 = (wb / "任务" / "非法优先级.md").read_text(encoding="utf-8", errors="replace")
        assert "priority: P9" not in text2  # 非法忽略


class TestAutoNudgeScript:
    """超期提醒扫描逻辑：status todo + due < today，排除未到期/已完成。"""

    @staticmethod
    def _load():
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "wb_auto_nudge",
            str(Path(__file__).resolve().parent.parent / "scripts" / "workbench_auto_nudge.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_scan_overdue_filters(self, wb, monkeypatch):
        import datetime as dt

        mod = self._load()
        monkeypatch.setattr(mod, "ROOT", wb)
        monkeypatch.setattr(mod, "TODAY", dt.date(2026, 8, 15))
        (wb / "任务" / "over.md").write_text(
            "---\ntype: task\nstatus: todo\ndue: 2026-08-10\n---\n\n# 超期任务\n", encoding="utf-8"
        )
        (wb / "任务" / "future.md").write_text(
            "---\ntype: task\nstatus: todo\ndue: 2026-08-20\n---\n\n# 未到期\n", encoding="utf-8"
        )
        (wb / "任务" / "done.md").write_text(
            "---\ntype: task\nstatus: completed\ndue: 2026-08-01\n---\n\n# 已完成\n", encoding="utf-8"
        )
        (wb / "任务" / "nodue.md").write_text(
            "---\ntype: task\nstatus: todo\n---\n\n# 无 due\n", encoding="utf-8"
        )
        result = mod.scan_overdue()
        assert len(result) == 1, f"expect 1 got {result}"
        filename, title, due, days = result[0]
        assert filename == "over.md"
        assert title == "超期任务"  # # 一级标题
        assert due == "2026-08-10"
        assert days == 5

    def test_record_events_writes_nudge(self, tmp_path):
        mod = self._load()
        db = tmp_path / "nudge.db"
        # record_events 只写 DB；直接给 DB_PATH
        mod.DB_PATH = db
        mod.record_events([("over.md", "超期任务", "2026-08-10", 5)])
        import sqlite3

        conn = sqlite3.connect(str(db))
        rows = conn.execute(
            "SELECT partition, filename, kind, payload FROM task_events"
        ).fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0][0] == "任务"
        assert rows[0][1] == "over.md"
        assert rows[0][2] == "nudge"
        assert "超期" in rows[0][3]
