"""workbench-view 插件包 — QQ Bot 任务信息流工作台后端。"""
from __future__ import annotations


def register(ctx) -> None:
    """插件注册入口：入站消息平台强制登记 + 内建调度器（55/57 号定义）。"""
    import sys
    from pathlib import Path

    # dashboard 为命名空间包且插件包名含连字符，绝对导入不可靠
    # （09:41 实测 Failed to load plugin: No module named 'dashboard'）。
    # 与 hermes_wb_ingest.py 同模式：显式把 dashboard 目录加入 sys.path。
    dashboard_dir = str(Path(__file__).resolve().parent / "dashboard")
    if dashboard_dir not in sys.path:
        sys.path.insert(0, dashboard_dir)

    from inbound_hook import register as _register_inbound_hook

    _register_inbound_hook(ctx)

    # 内建调度器：启动失败只记日志，绝不拖垮入站 hook（重启后先验 hook 再验 scheduler）。
    try:
        from scheduler import start_scheduler

        start_scheduler(ctx)
    except Exception as exc:  # noqa: BLE001 - 隔离失败面
        import logging

        logging.getLogger("workbench-view").warning(
            "scheduler start failed (hook unaffected): %s", exc
        )


def stop_scheduler() -> None:
    """测试/卸载兜底：停止本进程持有的调度器线程。"""
    from scheduler import stop_scheduler as _stop

    _stop()
