"""Cron governance regressions for Workbench maintenance entrypoints."""

import ast
import importlib.util
import os
from datetime import date, timedelta
from pathlib import Path

# P0-A：脚本随插件包分发；memory-audit.py 属 Hermes 侧脚本（非插件资产）
SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "workbench_archive.py"
MEMORY_AUDIT = Path(os.environ.get("HERMES_HOME", "")) / "scripts" / "memory-audit.py"


def load_archive_module(root: Path):
    spec = importlib.util.spec_from_file_location("governed_workbench_archive", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.WORKBENCH = root
    module.TASK_DIR = root / "任务"
    module.DONE_DIR = root / "已处理"
    module.TRASH_DIR = root / "回收站"
    module.LOG_DIR = root / "日志"
    module._dual = None
    return module


def test_completed_task_archiver_never_processes_trash(tmp_path):
    """Trash TTL has one owner: workbench_trash_ttl.py, not the task archiver."""
    task_dir = tmp_path / "任务"
    trash_dir = tmp_path / "回收站"
    task_dir.mkdir()
    trash_dir.mkdir()
    old = (date.today() - timedelta(days=60)).isoformat()
    trashed = trash_dir / "must-survive.md"
    trashed.write_text(
        f"---\nstatus: abandoned\ntrashed_at: {old}\n---\n\n# Must survive\n",
        encoding="utf-8",
    )

    module = load_archive_module(tmp_path)
    assert module.main() == 0
    assert trashed.exists()


def test_confidence_audit_never_writes_reviewed_concept_pages():
    """A confidence timer may write its report, but never the reviewed note."""
    if not MEMORY_AUDIT.is_file():
        import pytest

        pytest.skip("memory-audit.py 属 Hermes 侧脚本，非插件资产")
    tree = ast.parse(MEMORY_AUDIT.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "run_confidence_decay"
    )
    forbidden = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "open" or len(node.args) < 2:
            continue
        path_arg, mode_arg = node.args[:2]
        if (
            isinstance(path_arg, ast.Name)
            and path_arg.id == "path"
            and isinstance(mode_arg, ast.Constant)
            and "w" in str(mode_arg.value)
        ):
            forbidden.append(node.lineno)
    assert forbidden == []
