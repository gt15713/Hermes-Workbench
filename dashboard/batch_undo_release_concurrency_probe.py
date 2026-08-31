"""WB-S1-065 real Python RED/GREEN probe for release/concurrency seams.

Run from the Workbench root with ``python dashboard/...probe.py``.  It never
uses production paths and exits 1 while the current source misses the contract.
"""

from __future__ import annotations

import importlib
import json
import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path


def check(results, name, condition, details):
    results.append({"name": name, "ok": bool(condition), "details": details})


def expire(path: Path, now: datetime):
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["created_at"] = (now - timedelta(minutes=20)).isoformat()
    payload["heartbeat_at"] = (now - timedelta(minutes=11)).isoformat()
    payload["expires_at"] = (now - timedelta(minutes=1)).isoformat()
    path.write_text(json.dumps(payload), encoding="utf-8")


def run():
    results = []
    with tempfile.TemporaryDirectory(prefix="wb-s1-066-release-") as temp:
        root = Path(temp) / "workbench"
        probe_db = Path(temp) / "probe.db"
        os.environ["WORKBENCH_ROOT"] = str(root)
        os.environ["WORKBENCH_DB"] = str(probe_db)
        os.environ["WORKBENCH_CONFIG"] = str(Path(temp) / "probe-config.json")
        # Import-time singletons must be born isolated, exactly like the contract probe.
        repo_module = importlib.import_module("repo")
        api = importlib.import_module("plugin_api")
        if repo_module.WORKBENCH_DB_PATH.resolve() != probe_db.resolve():
            raise RuntimeError("probe isolation failed: repo database is not temporary")
        if repo_module.WORKBENCH_ROOT.resolve() != root.resolve() or api.WORKBENCH_ROOT.resolve() != root.resolve():
            raise RuntimeError("probe isolation failed: repo/root singleton is not temporary")
        saved_now = api._batch_undo_now
        saved_live = api._claim_owner_liveness
        saved_replace = api.os.replace
        saved_unlink = Path.unlink
        try:
            root = Path(temp) / "workbench"
            (root / ".batch-undo").mkdir(parents=True)
            api.WORKBENCH_ROOT = root

            op = "1" * 32
            claim = api._acquire_batch_undo_claim(op)
            attempts = []
            def fail_once(source, target):
                if str(source).endswith(".claim.json") and str(target).endswith(".released.json"):
                    attempts.append(1)
                    if len(attempts) == 1:
                        raise OSError("transient move failure")
                return saved_replace(source, target)
            api.os.replace = fail_once
            released = api._release_batch_undo_claim(op, claim)
            check(results, "transient_release_retries", released and len(attempts) == 2,
                  {"returned": released, "attempts": len(attempts)})

            op = "a" * 32
            claim = api._acquire_batch_undo_claim(op)
            released_path = api._batch_undo_claim_path(op).with_name(f".{op}.{claim['claim_id']}.released.json")
            attempts = []
            def fail_once_unlink(path, missing_ok=False):
                if path == released_path:
                    attempts.append(1)
                    if len(attempts) == 1:
                        raise OSError("transient unlink failure")
                return saved_unlink(path, missing_ok=missing_ok)
            api.Path.unlink = fail_once_unlink
            api.os.replace = saved_replace
            released = api._release_batch_undo_claim(op, claim)
            check(results, "transient_unlink_retries", released and len(attempts) == 2,
                  {"returned": released, "attempts": len(attempts)})
            api.Path.unlink = saved_unlink

            op = "b" * 32
            claim = api._acquire_batch_undo_claim(op)
            claim_path = api._batch_undo_claim_path(op)
            before = claim_path.read_bytes()
            released_path = claim_path.with_name(f".{op}.{claim['claim_id']}.released.json")
            attempts = []
            def persistent_unlink(path, missing_ok=False):
                if path == released_path:
                    attempts.append(1)
                    raise OSError("persistent unlink failure")
                return saved_unlink(path, missing_ok=missing_ok)
            api.Path.unlink = persistent_unlink
            api.os.replace = saved_replace
            released = api._release_batch_undo_claim(op, claim)
            check(results, "persistent_unlink_preserves_exact_ledger",
                  released is False and len(attempts) == 3 and released_path.read_bytes() == before,
                  {"returned": released, "attempts": len(attempts), "released_ledger_preserved": released_path.read_bytes() == before})
            api.Path.unlink = saved_unlink

            op = "2" * 32
            claim = api._acquire_batch_undo_claim(op)
            claim_path = api._batch_undo_claim_path(op)
            before = claim_path.read_bytes()
            attempts = []
            def persistent(source, target):
                if str(source).endswith(".claim.json") and str(target).endswith(".released.json"):
                    attempts.append(1)
                    raise OSError("persistent move failure")
                return saved_replace(source, target)
            api.os.replace = persistent
            released = api._release_batch_undo_claim(op, claim)
            check(results, "persistent_release_bounded_exact_ledger",
                  released is False and len(attempts) == 3 and claim_path.read_bytes() == before,
                  {"returned": released, "attempts": len(attempts), "claim_preserved": claim_path.read_bytes() == before})

            api.os.replace = persistent
            op = "3" * 32
            claim = api._acquire_batch_undo_claim(op)
            assert api._release_batch_undo_claim(op, claim) is False
            now = datetime.now(timezone.utc) + timedelta(seconds=1)
            api._batch_undo_now = lambda: now
            api._claim_owner_liveness = lambda _owner: "live"
            replacement = api._acquire_batch_undo_claim(op)
            check(results, "same_process_inactive_converges", replacement is not None,
                  {"replacement_claimed": replacement is not None})
            api._batch_undo_now = saved_now
            api._claim_owner_liveness = saved_live
            api.os.replace = saved_replace
            api.Path.unlink = saved_unlink

            for index, status in enumerate(("live", "unknown"), start=4):
                op = str(index) * 32
                claim = api._acquire_batch_undo_claim(op)
                now = datetime.now(timezone.utc)
                expire(api._batch_undo_claim_path(op), now)
                api._claim_owner_liveness = lambda _owner, value=status: value
                busy = api._acquire_batch_undo_claim(op) is None
                check(results, f"foreign_{status}_busy", busy, {"status": status, "busy": busy})
                api._claim_owner_liveness = lambda _owner: "dead"
                api._release_batch_undo_claim(op, claim)

            op = "6" * 32
            old = api._acquire_batch_undo_claim(op)
            expire(api._batch_undo_claim_path(op), datetime.now(timezone.utc))
            api._claim_owner_liveness = lambda _owner: "dead"
            fresh = api._acquire_batch_undo_claim(op)
            late = api._release_batch_undo_claim(op, old)
            current = json.loads(api._batch_undo_claim_path(op).read_text(encoding="utf-8"))
            check(results, "dead_reclaim_late_old_release_safe",
                  fresh is not None and late is False and current["claim_id"] == fresh["claim_id"],
                  {"reclaimed": fresh is not None, "late_release": late, "current_claim_id": current["claim_id"]})
            api._release_batch_undo_claim(op, fresh)

            op = "7" * 32
            barrier = threading.Barrier(2)
            def worker():
                barrier.wait(timeout=2)
                return api._acquire_batch_undo_claim(op)
            with ThreadPoolExecutor(max_workers=2) as pool:
                claims = list(pool.map(lambda _item: worker(), range(2)))
            winner = [claim for claim in claims if claim is not None]
            check(results, "two_workers_one_claim_one_settlement_slot", len(winner) == 1,
                  {"claimants": len(winner)})
            if winner:
                api._release_batch_undo_claim(op, winner[0])

            run_source = (Path(__file__).with_name("plugin_api.py"))
            source = run_source.read_text(encoding="utf-8")
            direct_release_lines = [
                line.strip() for line in source.splitlines()
                if "_release_batch_undo_claim(" in line and "def _release_batch_undo_claim" not in line
            ]
            ignored = [
                line for line in direct_release_lines
                if not line.startswith("if not") and "return" not in line and "released =" not in line
            ]
            check(results, "release_return_checked_at_callsites", not ignored,
                  {"direct_release_lines": len(direct_release_lines), "possibly_ignored": ignored[:8]})
        finally:
            api._batch_undo_now = saved_now
            api._claim_owner_liveness = saved_live
            api.os.replace = saved_replace
            api.Path.unlink = saved_unlink

    payload = {"probe": "WB-S1-065-release-concurrency", "results": results,
               "passed": sum(item["ok"] for item in results), "total": len(results)}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if all(item["ok"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(run())
