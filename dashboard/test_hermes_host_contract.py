# -*- coding: utf-8 -*-
"""宿主替身 vs 真实 Hermes 宿主的最小接口防漂移检查（WB-S1-021）。

插件行为测试在干净 checkout 用 test_support/hermes_doubles 的替身跑；本文件
保证替身不偏离真实宿主契约——仅当显式 HERMES_AGENT_SOURCE 指向真实源码树时
执行（干净环境 skip，因为无真实模块可比对；本地/真实宿主环境必须跑）。

检查面刻意最小（防漂移，不镜像全实现）：
- 三个被消费函数的签名一致性（参数名与默认值）；
- 环境变量名 -> ContextVar 映射键集一致（替身声明的键必须是真实键集的子集，
  且插件消费的键必须全部在替身映射内）；
- set/clear/get 的三态语义行为等价（显式绑定 → 读到值；clear → 读到 ""；
  未绑定 → 回落 os.environ）。
"""

import importlib.util
import inspect
import os
from pathlib import Path

import pytest

_DOUBLE_SC = (
    Path(__file__).resolve().parent
    / "test_support"
    / "hermes_doubles"
    / "gateway"
    / "session_context.py"
)

# 插件生产代码与行为测试实际消费的宿主符号/环境变量。
CONSUMED_ENV_VARS = (
    "HERMES_SESSION_PLATFORM",
    "HERMES_SESSION_ID",
    "HERMES_SESSION_MESSAGE_ID",
)

CONSUMED_FUNCS = ("set_session_vars", "clear_session_vars", "get_session_env")


def _load_doubles():
    spec = importlib.util.spec_from_file_location("_wb_double_session_context", _DOUBLE_SC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.hermes_host_integration
def test_doubles_session_context_signature_matches_host(host_integration_source):
    del host_integration_source
    from gateway import session_context as real

    def _sentinel_like(v) -> bool:
        # 哨兵对象（_UNSET）：非 None/str/bool 的裸 object——跨模块无法比身份，
        # 只能比"同为哨兵"这一语义。
        return v is not None and not isinstance(v, (str, bool, int))

    doubles = _load_doubles()
    for fn_name in CONSUMED_FUNCS:
        real_sig = inspect.signature(getattr(real, fn_name))
        dbl_sig = inspect.signature(getattr(doubles, fn_name))
        assert list(real_sig.parameters) == list(dbl_sig.parameters), fn_name
        for pname, p in dbl_sig.parameters.items():
            real_default = real_sig.parameters[pname].default
            if _sentinel_like(real_default) and _sentinel_like(p.default):
                continue  # 双方均为哨兵默认值 → 语义一致
            assert real_default == p.default, f"{fn_name}:{pname}"


@pytest.mark.hermes_host_integration
def test_doubles_var_map_covers_consumed_env_vars(host_integration_source):
    del host_integration_source
    from gateway import session_context as real

    doubles = _load_doubles()
    real_keys = set(real._VAR_MAP)
    dbl_keys = set(doubles._VAR_MAP)
    assert dbl_keys <= real_keys, f"替身键不在真实键集: {dbl_keys - real_keys}"
    missing = {k for k in CONSUMED_ENV_VARS if k not in dbl_keys}
    assert not missing, f"插件消费的键缺替身: {missing}"


@pytest.mark.hermes_host_integration
def test_doubles_tristate_semantics_match_host(host_integration_source):
    del host_integration_source
    from gateway import session_context as real

    doubles = _load_doubles()
    for var in real._VAR_MAP.values():
        var.set(real._UNSET)
    for var in doubles._VAR_MAP.values():
        var.set(doubles._UNSET)

    probe = "HERMES_SESSION_MESSAGE_ID"
    try:
        os.environ[probe] = "env-fallback-value"

        # 未绑定：双方都回落 os.environ
        assert real.get_session_env(probe, "") == "env-fallback-value"
        assert doubles.get_session_env(probe, "") == "env-fallback-value"

        # 显式绑定：双方都读到绑定值（ContextVar 权威）
        rtokens = real.set_session_vars(platform="qqbot", message_id="real-msg")
        dtokens = doubles.set_session_vars(platform="qqbot", message_id="real-msg")
        assert real.get_session_env(probe, "") == "real-msg"
        assert doubles.get_session_env(probe, "") == "real-msg"

        # 显式清空：双方都读 ""（压制 os.environ 回落）
        real.clear_session_vars(rtokens)
        doubles.clear_session_vars(dtokens)
        assert real.get_session_env(probe, "") == ""
        assert doubles.get_session_env(probe, "") == ""
    finally:
        for var in real._VAR_MAP.values():
            var.set(real._UNSET)
        for var in doubles._VAR_MAP.values():
            var.set(doubles._UNSET)
        os.environ.pop(probe, None)
