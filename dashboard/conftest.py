# -*- coding: utf-8 -*-
"""workbench-view 测试收集期隔离（阶段 4 小修 2 + WB-S1-021 自包含宿主替身）。

repo.py 模块级 `_repo = DualRepo()` 在 import 时即打开 workbench.db（无参构造
SqliteRepo → 真实 DB 路径）。CI/沙箱环境没有真实 DB 会导致测试收集失败。

方案：本 conftest 在 pytest 收集前（import repo 之前）注入 WORKBENCH_ROOT /
WORKBENCH_DB 指向会话级临时目录——模块级 _repo 落到临时库，不碰真实数据。

- 外部显式设置的环境变量优先（CI 可自定义隔离路径）；空字符串同样视为未设置（P3 兜底）
- 会话结束清理临时目录（pytest_sessionfinish）

WB-S1-021：干净 checkout（CI）没有 Hermes 宿主源码树，插件行为测试依赖的
`gateway.session_context` 会 ModuleNotFound。本 conftest 仅在真实模块**不可用**
时，把 dashboard/test_support/hermes_doubles 追加（append，不是 insert——
真实模块一旦在路径上即保持优先）到 sys.path，让替身补位。真实宿主集成测试
（marker: hermes_host_integration）不用替身，需显式 HERMES_AGENT_SOURCE 才执行。
"""
import importlib.util
import os
import shutil
import sys
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

# --- WB-S1-021 宿主替身注入（仅真实 gateway 缺失时） --------------------------
_DUBBLE_ROOT = Path(__file__).resolve().parent / "test_support" / "hermes_doubles"
HERMES_DOUBLES_ACTIVE = importlib.util.find_spec("gateway") is None
if HERMES_DOUBLES_ACTIVE:
    if str(_DUBBLE_ROOT) not in sys.path:
        sys.path.append(str(_DUBBLE_ROOT))


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "hermes_host_integration: 需要真实 Hermes Agent 源码树（显式 "
        "HERMES_AGENT_SOURCE），不用替身；干净环境自动 skip",
    )


@pytest.fixture()
def host_integration_source() -> str:
    """真实宿主集成用例的门控 fixture：未显式提供可导入的源码根则 skip。

    HERMES_AGENT_SOURCE 必须指向含 gateway/ + hermes_cli/ 的目录（本地开发
    显式导出；CI 默认不设置 → 对应用例 skip 而非假通过）。
    """
    src = os.environ.get("HERMES_AGENT_SOURCE", "").strip()
    if not src or not (Path(src) / "gateway" / "session_context.py").is_file():
        pytest.skip("HERMES_AGENT_SOURCE 未显式指向可导入的 Hermes 源码树")
    if src not in sys.path:
        sys.path.insert(0, src)
    return src



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
