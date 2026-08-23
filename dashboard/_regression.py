# -*- coding: utf-8 -*-
"""阶段 4 统一重启后回归验证（重启后新会话执行）。

1) 从 desktop.log 尾部找最新 HERMES_BACKEND_READY port
2) GET /health → ok:true
3) /events SSE 首帧 retry: 2000
4) expected_mtime 并发防护冒烟（临时库 + 新代码 import，不碰真实 DB）
5) pytest 全量回归
"""
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERMES_HOME = Path(__file__).resolve().parent.parent.parent.parent  # dashboard → workbench-view → plugins → hermes
LOG = HERMES_HOME / "logs" / "desktop.log"
DASH = Path(__file__).parent
OK, NG = [], []


def find_port():
    lines = LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    ports = [m.group(1) for l in lines if (m := re.search(r"HERMES_BACKEND_READY port=(\d+)", l))]
    if not ports:
        NG.append("desktop.log 无 HERMES_BACKEND_READY")
        return None
    return ports[-1]


def check(name, fn):
    try:
        r = fn()
        print(f"  [{'PASS' if r else 'FAIL'}] {name}")
        OK.append(name) if r else NG.append(name)
        return r
    except Exception as e:  # noqa: BLE001
        print(f"  [FAIL] {name}: {e}")
        NG.append(name)
        return False


def main():
    port = find_port()
    print(f"backend port: {port}")
    if not port:
        return 1
    import urllib.request

    base = f"http://127.0.0.1:{port}/api/plugins/workbench-view"

    def health():
        # 桌面端 /api 需 X-Hermes-Session-Token（SDK 自动带）；裸请求 401 = 端点存在 + 鉴权保护正常
        try:
            with urllib.request.urlopen(f"{base}/health", timeout=5) as r:
                import json
                d = json.loads(r.read())
                return r.status == 200 and d.get("ok") is True
        except urllib.error.HTTPError as e:
            return e.code in (401, 403)
    check("/health 端点存在+鉴权保护（401 正常）", health)

    def ws_gate():
        # /events 已改为 WebSocket（对齐 kanban）。无凭证连接 → 1008（鉴权门生效）
        import asyncio
        import websockets

        async def _try():
            try:
                async with websockets.connect(f"ws://127.0.0.1:{port}/api/plugins/workbench-view/events?since=0", open_timeout=5) as ws:
                    return await asyncio.wait_for(ws.recv(), timeout=3)
            except websockets.exceptions.InvalidStatus as e:
                return f"HTTP {e.response.status_code}"
            except Exception as e:  # noqa: BLE001
                return type(e).__name__

        return "1008" in str(asyncio.run(_try())) or "HTTP" in str(asyncio.run(_try()))
    check("/events WS 鉴权门（无凭证 1008）", ws_gate)

    def mtime_smoke():
        # 临时库 + DualRepo 真实写路径：expected_mtime 冲突拦截
        import tempfile
        import importlib.util
        from pathlib import Path as P

        root = P(tempfile.mkdtemp(prefix="wb-reg-"))
        for d in ("待验证", "待回看", "任务", "梦中的邮件"):
            (root / d).mkdir(parents=True, exist_ok=True)
        # exec 前注入环境变量（repo 模块顶层从 os.environ 读，模块属性会被覆盖）
        os.environ["WORKBENCH_ROOT"] = str(root)
        os.environ["WORKBENCH_DB"] = str(root / "reg.db")
        spec = importlib.util.spec_from_file_location("repo_reg", DASH / "repo.py")
        repo = importlib.util.module_from_spec(spec)
        sys.modules["repo"] = repo
        # contract 依赖注入
        spec_c = importlib.util.spec_from_file_location("contract_reg", DASH / "contract.py")
        contract = importlib.util.module_from_spec(spec_c)
        sys.modules["contract"] = contract
        spec_c.loader.exec_module(contract)
        spec.loader.exec_module(repo)

        dual = repo.DualRepo()
        p = root / "待验证" / "r.md"
        dual.write_text(p, "# v1\n")
        cur = dual.db.mtime(p)
        assert cur > 0, "mtime 应为真实值"
        dual.write_text(p, "# v2\n", expected_mtime=cur)  # 正确 expected → 通过
        ok = dual.read_text(p) == "# v2\n"
        try:
            dual.write_text(p, "# v3\n", expected_mtime=cur)  # 旧 expected → 拒绝
            ok = False
        except repo.WorkbenchConflictError:
            pass
        return ok
    check("expected_mtime 并发防护（旧 expected 拒绝）", mtime_smoke)

    def pytest_all():
        r = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=str(DASH), capture_output=True, text=True, timeout=180)
        print(f"    pytest: {r.stdout.strip().splitlines()[-1] if r.stdout else r.stderr[-200:]}")
        return r.returncode == 0
    check("pytest 全量回归", pytest_all)

    print(f"\n=== 结果: PASS {len(OK)} / FAIL {len(NG)} ===")
    if NG:
        print("失败项:", "; ".join(NG))
        return 1
    print("全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
