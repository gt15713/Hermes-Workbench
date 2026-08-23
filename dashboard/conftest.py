# -*- coding: utf-8 -*-
"""workbench-view 测试收集期隔离（阶段 4 小修 2）。

repo.py 模块级 `_repo = DualRepo()` 在 import 时即打开 workbench.db（无参构造
SqliteRepo → 真实 DB 路径）。CI/沙箱环境没有真实 DB 会导致测试收集失败。

方案：本 conftest 在 pytest 收集前（import repo 之前）注入 WORKBENCH_ROOT /
WORKBENCH_DB 指向会话级临时目录——模块级 _repo 落到临时库，不碰真实数据。

- 外部显式设置的环境变量优先（CI 可自定义隔离路径）；空字符串同样视为未设置（P3 兜底）
- 会话结束清理临时目录（pytest_sessionfinish）
"""
import os
import shutil
import tempfile
from pathlib import Path

import pytest  # noqa: E402

_FAKE_ROOT = Path(tempfile.mkdtemp(prefix="wb-test-root-"))
for _d in ("待验证", "待回看", "任务", "心理学随想", "梦中的邮件", "已处理", "回收站", "日志"):
    (_FAKE_ROOT / _d).mkdir(parents=True, exist_ok=True)

# P3 兜底：环境变量存在但为空串时同样注入（Path("") 会解析到当前目录，污染收集期）
os.environ["WORKBENCH_ROOT"] = os.environ.get("WORKBENCH_ROOT") or str(_FAKE_ROOT)
os.environ["WORKBENCH_DB"] = os.environ.get("WORKBENCH_DB") or str(_FAKE_ROOT / "test-workbench.db")
# 2026-08-22 设置面板：测试隔离配置（不读/不写真实 workbench-config.json）
os.environ["WORKBENCH_CONFIG"] = os.environ.get("WORKBENCH_CONFIG") or str(
    _FAKE_ROOT / "test-workbench-config.json"
)


@pytest.fixture()
def legacy_partitions():
    """模拟旧 7 分区用户配置（心理/梦邮保留为可删用户分区）。

    P0-B 默认收敛为 5 固定分区后，依赖「心理学随想/梦中的邮件」白名单的
    存量用例（to_task/resolve）需要此 fixture 恢复旧分区上下文。
    """
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import workbench_config as wc

    cfg = wc.default_config()
    cfg["partitions"] = [
        {"name": "待验证", "type": "thought", "fixed": False},
        {"name": "待回看", "type": "video", "fixed": True},
        {"name": "任务", "type": "task", "fixed": True},
        {"name": "心理学随想", "type": "psych", "fixed": False},
        {"name": "梦中的邮件", "type": "dream", "fixed": False},
        {"name": "已处理", "type": "done", "fixed": True},
        {"name": "回收站", "type": "trash", "fixed": True},
    ]
    wc.save_config(cfg)
    yield cfg
    # 用完删除，恢复「无配置 → 默认 5 分区」状态，避免污染后续用例
    try:
        Path(wc.CONFIG_FILE).unlink()
    except OSError:
        pass


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    shutil.rmtree(_FAKE_ROOT, ignore_errors=True)
