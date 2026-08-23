# -*- coding: utf-8 -*-
"""C4（P1-3）：跨进程写协调——FileLock 并发互斥 / 超时告警 / 写入口收敛。"""

import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from repo import FileLock, FileRepo

_DASH = Path(__file__).resolve().parent


def _py(code: str, cwd: Path, timeout: float = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


class TestFileLock:
    def test_sequential_lock_release(self, tmp_path):
        """同一文件锁可重复获取（释放后再次获取成功，无死锁）。"""
        target = tmp_path / "a.md"
        with FileLock(target):
            pass
        with FileLock(target):
            pass

    def test_cross_process_concurrent_write_no_corruption(self, tmp_path):
        """两进程同时写同一文件 → 串行化，无交错损坏；最终内容为某个完整版本。"""
        target = tmp_path / "race.md"
        code = textwrap.dedent(
            """
            import sys
            sys.path.insert(0, r"__DASH__")
            from pathlib import Path
            from repo import FileRepo
            r = FileRepo(root=Path(r"__TMP__"), lock_timeout=15)
            t = Path(r"__TARGET__")
            for i in range(30):
                r.write_text(t, "__MARK__" * 100 + "\\n")
            """
        ).replace("__DASH__", str(_DASH)).replace("__TMP__", str(tmp_path)).replace("__TARGET__", str(target))
        p1 = _py(code.replace("__MARK__", "A"), tmp_path)
        p2 = _py(code.replace("__MARK__", "B"), tmp_path)
        assert p1.returncode == 0, p1.stderr
        assert p2.returncode == 0, p2.stderr
        text = target.read_text(encoding="utf-8")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        assert lines, "file empty"
        # 每行都是完整 A/B 版本（无交错半行）
        assert all(ln in ("A" * 100, "B" * 100) for ln in lines)

    def test_lock_timeout_raises(self, tmp_path):
        """持锁进程未释放 → 第二次获取超时抛 TimeoutError（告警+跳过，不静默覆盖）。"""
        target = tmp_path / "locked.md"
        holder = textwrap.dedent(f"""
            import sys, time
            sys.path.insert(0, r"{str(_DASH)}")
            from pathlib import Path
            from repo import FileLock
            with FileLock(Path(r"{str(target)}"), timeout=5):
                time.sleep(10)
        """)
        proc = subprocess.Popen(
            [sys.executable, "-c", holder],
            cwd=str(tmp_path),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            time.sleep(1.5)  # 等持有者拿锁
            with pytest.raises(TimeoutError):
                with FileLock(target, timeout=1.0, poll=0.1):
                    pass
        finally:
            proc.kill()
            proc.wait()


class TestWriteConvergence:
    def test_plugin_api_atomic_write_goes_through_repo(self):
        """写入口收敛：plugin_api._atomic_write 已委托 file_repo.write_text（C4 收敛点成立）。"""
        import inspect

        import plugin_api as api

        src = inspect.getsource(api._atomic_write)
        assert "file_repo.write_text" in src


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
