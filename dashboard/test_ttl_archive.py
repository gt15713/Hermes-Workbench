# -*- coding: utf-8 -*-
"""Phase 0-6（A3）：TTL_MODE=archive 双分支测试（ttl.py）。

覆盖：get_ttl_mode 默认/覆盖；archive_overdue（移入已处理 + status: deleted + 保留实体）；
同名冲突后缀；delete 分支仍可用；缺 frontmatter status 时插入。
"""

import datetime as dt
from pathlib import Path

from ttl import archive_overdue, delete_overdue, get_ttl_mode, scan_trash_overdue


def _make_trash_file(root: Path, name: str, trashed_days_ago: int) -> None:
    trash = root / "回收站"
    trash.mkdir(parents=True, exist_ok=True)
    ta = (dt.date.today() - dt.timedelta(days=trashed_days_ago)).isoformat()
    (trash / name).write_text(
        f"---\ntype: task\nstatus: abandoned\ntrashed_at: {ta}\n---\n\n# {name}\n\n原内容\n",
        encoding="utf-8",
    )


def test_get_ttl_mode_default_archive(monkeypatch):
    monkeypatch.delenv("WORKBENCH_TTL_MODE", raising=False)
    assert get_ttl_mode() == "archive"


def test_get_ttl_mode_delete(monkeypatch):
    monkeypatch.setenv("WORKBENCH_TTL_MODE", "delete")
    assert get_ttl_mode() == "delete"


def test_archive_overdue_moves_and_marks(tmp_path):
    (tmp_path / "已处理").mkdir()
    _make_trash_file(tmp_path, "old.md", trashed_days_ago=31)
    overdue = scan_trash_overdue(30, root=tmp_path)
    assert len(overdue) == 1
    archived = archive_overdue(overdue, root=tmp_path)
    assert archived == ["old.md"]
    assert not (tmp_path / "回收站" / "old.md").exists()
    dst = tmp_path / "已处理" / "old.md"
    assert dst.exists()
    text = dst.read_text(encoding="utf-8")
    assert "status: deleted" in text
    assert "trashed_at:" in text
    assert "TTL 归档保留" in text


def test_archive_overdue_name_conflict(tmp_path):
    (tmp_path / "已处理").mkdir()
    (tmp_path / "已处理" / "old.md").write_text("existing", encoding="utf-8")
    _make_trash_file(tmp_path, "old.md", trashed_days_ago=31)
    overdue = scan_trash_overdue(30, root=tmp_path)
    archived = archive_overdue(overdue, root=tmp_path)
    assert archived == ["old-2.md"]
    assert (tmp_path / "已处理" / "old.md").read_text(encoding="utf-8") == "existing"
    assert (tmp_path / "已处理" / "old-2.md").exists()


def test_delete_overdue_still_works(tmp_path):
    _make_trash_file(tmp_path, "old.md", trashed_days_ago=31)
    overdue = scan_trash_overdue(30, root=tmp_path)
    deleted = delete_overdue(overdue, root=tmp_path)
    assert deleted == ["old.md"]
    assert not (tmp_path / "回收站" / "old.md").exists()


def test_archive_inserts_status_when_missing(tmp_path):
    (tmp_path / "已处理").mkdir()
    (tmp_path / "回收站").mkdir()
    ta = (dt.date.today() - dt.timedelta(days=31)).isoformat()
    (tmp_path / "回收站" / "nofm.md").write_text(
        f"---\ntrashed_at: {ta}\n---\n\n# nofm\n", encoding="utf-8"
    )
    overdue = scan_trash_overdue(30, root=tmp_path)
    assert len(overdue) == 1
    archived = archive_overdue(overdue, root=tmp_path)
    assert archived == ["nofm.md"]
    text = (tmp_path / "已处理" / "nofm.md").read_text(encoding="utf-8")
    assert "status: deleted" in text
