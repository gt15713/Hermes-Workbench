# -*- coding: utf-8 -*-
"""测试专用 Hermes 宿主替身包（WB-S1-021 自包含 CI）。

真实 hermes-agent 源码树可用时（PYTHONPATH / HERMES_AGENT_SOURCE），本包不会
进入解析路径；仅当干净 checkout 缺少真实 `gateway` 包时，由 dashboard/conftest.py
把本目录追加到 sys.path 末尾（append——真实模块一旦存在即优先）。

只实现插件测试所需的最小面；与真实宿主的接口一致性由
dashboard/test_hermes_host_contract.py 防漂移。
"""
