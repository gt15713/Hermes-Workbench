def test_privacy_gate_detects_local_markers_without_self_matching(tmp_path):
    from scripts.workbench_privacy_gate import scan_paths

    clean = tmp_path / "clean.md"
    dirty = tmp_path / "dirty.md"
    clean.write_text("generic documentation", encoding="utf-8")
    dirty.write_text("C:" + "/Users/example/private", encoding="utf-8")

    hits = scan_paths([clean, dirty], root=tmp_path)

    assert hits == ["dirty.md:1"]
