# -*- coding: utf-8 -*-
"""A5：FileLock 跨进程并发测试（Windows msvcrt 路径，CI windows-latest 覆盖）。"""
from __future__ import annotations

import multiprocessing as mp
import os
import sys
import time
from pathlib import Path

import pytest  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))

from repo import FileLock  # noqa: E402


def _hold_lock(lock_path: str, ready, release) -> None:  # pragma: no cover - 子进程
    with FileLock(Path(lock_path), timeout=5):
        ready.set()
        release.wait(5)


def test_filelock_blocks_cross_process(tmp_path):
    """子进程持锁 → 父进程短超时被拒；释放后可获取（Windows msvcrt 生效路径）。"""
    if os.name != "nt":
        pytest.skip("msvcrt 锁仅 Windows")
    lock_path = tmp_path / "a.lock"
    ctx = mp.get_context("spawn")
    ready = ctx.Event()
    release = ctx.Event()
    proc = ctx.Process(target=_hold_lock, args=(str(lock_path), ready, release))
    proc.start()
    try:
        assert ready.wait(10), "子进程未获取锁"
        start = time.monotonic()
        with pytest.raises(TimeoutError):
            with FileLock(lock_path, timeout=0.5):
                pass
        assert time.monotonic() - start >= 0.3
    finally:
        release.set()
        proc.join(10)
    # 释放后可正常获取
    with FileLock(lock_path, timeout=1):
        pass
