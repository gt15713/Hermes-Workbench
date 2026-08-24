def test_privacy_gate_detects_local_markers_without_self_matching(tmp_path):
    from scripts.workbench_privacy_gate import scan_paths

    clean = tmp_path / "clean.md"
    dirty = tmp_path / "dirty.md"
    clean.write_text("generic documentation", encoding="utf-8")
    dirty.write_text("C:" + "/Users/example/private", encoding="utf-8")

    hits = scan_paths([clean, dirty], root=tmp_path)

    assert hits == ["dirty.md:1"]


def test_privacy_gate_detects_windows_backslash_vault_path(tmp_path):
    from scripts.workbench_privacy_gate import scan_paths

    dirty = tmp_path / "dirty.md"
    dirty.write_text("D:" + "\\Obsidian\\private", encoding="utf-8")

    assert scan_paths([dirty], root=tmp_path) == ["dirty.md:1"]


def test_privacy_gate_fails_closed_when_a_tracked_file_is_unreadable(tmp_path, monkeypatch):
    from pathlib import Path

    from scripts.workbench_privacy_gate import scan_paths

    unreadable = tmp_path / "unreadable.md"
    unreadable.write_text("placeholder", encoding="utf-8")
    original = Path.read_text

    def guarded_read_text(self, *args, **kwargs):
        if self == unreadable:
            raise OSError("permission denied")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)

    assert scan_paths([unreadable], root=tmp_path) == ["unreadable.md:unreadable"]
