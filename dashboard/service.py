"""workbench-view 服务层（阶段 1：动作编排接口）。

分层目标（设计文档 v2 §2.1）：
- API 层：plugin_api.py（参数解析 + 错误信封）——当前保留全部端点逻辑
- 服务层：本文件（WorkbenchService，动作编排契约）
- 存储层：repo.py（WorkbenchRepo 抽象 + FileRepo 实现，后端可替换）
- 解析层：wb_utils.py（frontmatter/条目解析，纯函数）

阶段 1 现状：Service 接口 + 默认实现转发到 plugin_api 端点函数
（保持行为不变、测试全绿；避免重复代码）。
阶段 1.5（SQLite 双写）：在本类方法内实现「文件 + DB 双写」编排，
再逐步把端点逻辑收敛到本层——存储操作只经 repo 抽象，切换 SqliteRepo 即切换后端。
"""
from __future__ import annotations

from typing import Any, Callable


class WorkbenchService:
    """动作编排服务。注入 repo（存储后端）+ 动作实现（当前为 plugin_api 端点）。"""

    def __init__(
        self,
        repo: Any,
        actions: dict[str, Callable] | None = None,
    ) -> None:
        self.repo = repo
        # 动作映射：action_name -> callable(body) -> dict
        # 阶段 1：指向 plugin_api 端点函数；阶段 1.5：替换为双写实现
        self._actions = actions or {}

    def register(self, name: str, fn: Callable) -> None:
        """注册动作实现（1.5 双写时按需替换）。"""
        self._actions[name] = fn

    def execute(self, name: str, body: dict) -> dict:
        """执行动作；未知动作返回统一错误信封。"""
        fn = self._actions.get(name)
        if fn is None:
            return {"ok": False, "error": f"unknown action: {name}"}
        return fn(body)

    # ---------- 便捷方法（与端点一一对应，供 1.5 双写替换锚点） ----------

    def board(self) -> dict:
        return self.execute("board", {})

    def recent(self, limit: int = 10) -> dict:
        return self.execute("recent", {"limit": limit})

    def complete(self, body: dict) -> dict:
        return self.execute("complete", body)

    def resolve(self, body: dict) -> dict:
        return self.execute("resolve", body)

    def to_task(self, body: dict) -> dict:
        return self.execute("to-task", body)

    def trash(self, body: dict) -> dict:
        return self.execute("trash", body)

    def restore(self, body: dict) -> dict:
        return self.execute("restore", body)

    def defer(self, body: dict) -> dict:
        return self.execute("defer", body)

    def abandon(self, body: dict) -> dict:
        return self.execute("abandon", body)

    def reopen(self, body: dict) -> dict:
        return self.execute("reopen", body)

    def execute_task(self, body: dict) -> dict:
        return self.execute("execute", body)

    def bind_session(self, body: dict) -> dict:
        return self.execute("bind-session", body)

    def reset_execution(self, body: dict) -> dict:
        return self.execute("reset-execution", body)

    def add(self, body: dict) -> dict:
        return self.execute("add", body)

    def batch(self, body: dict) -> dict:
        return self.execute("batch", body)


def build_service(repo: Any) -> WorkbenchService:
    """工厂：装配服务。默认动作映射指向 plugin_api 端点（延迟 import 避免循环）。

    阶段 1.5：在此注入 SQLite 双写实现。
    """
    import plugin_api as _api

    svc = WorkbenchService(repo)
    # 只注册「需要存储编排」的动作（board/recent 为纯读，可直通）
    svc.register("board", lambda body: _api.board())
    svc.register("recent", lambda body: _api.recent(int(body.get("limit", 10))))
    svc.register("complete", _api.complete)
    svc.register("resolve", _api.resolve)
    svc.register("to-task", _api.to_task)
    svc.register("trash", _api.trash)
    svc.register("restore", _api.restore)
    svc.register("defer", _api.defer_task)
    svc.register("abandon", _api.abandon)
    svc.register("reopen", _api.reopen)
    svc.register("execute", _api.execute_task)
    svc.register("bind-session", _api.bind_session)
    svc.register("reset-execution", _api.reset_execution)
    svc.register("add", _api.add_entry)
    svc.register("batch", _api.batch)
    return svc
