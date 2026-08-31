"""WB-S1-058 RED/GREEN — crash-safe batch trash/Undo recovery state machine."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import plugin_api as api
import pytest
import repo as repo_module
import wb_utils


@pytest.fixture()
def wb(tmp_path, monkeypatch):
    root = tmp_path / "w"
    for dirname in ("待验证", "待回看", "任务", "心理学随想", "梦中的邮件", "已处理", "回收站", "日志"):
        (root / dirname).mkdir(parents=True, exist_ok=True)
    isolated = repo_module.DualRepo(
        file_repo=repo_module.FileRepo(root),
        sqlite_repo=repo_module.SqliteRepo(tmp_path / "w.db"),
        read_from_db=False,
    )
    monkeypatch.setattr(api, "WORKBENCH_ROOT", root)
    monkeypatch.setattr(api, "file_repo", isolated)
    monkeypatch.setattr(wb_utils, "WORKBENCH_ROOT", root)
    monkeypatch.setattr(wb_utils, "LOG_DIR", root / "日志")
    monkeypatch.setattr(repo_module, "WORKBENCH_ROOT", root)
    monkeypatch.setattr(repo_module, "_repo", isolated)
    monkeypatch.setattr(
        api,
        "_current_claim_owner",
        lambda: {"pid": 4242, "process_start_identity": "1788129694.000000", "lease_id": "fixture-owner"},
    )
    return root


def run(value):
    return asyncio.run(value)


def task(root: Path, name: str):
    path = root / "任务" / name
    path.write_text(f"---\ntype: task\nstatus: todo\n---\n\n# {name}\n", encoding="utf-8")
    return path


def batch(*names: str):
    return run(api.batch({"action": "trash", "items": [{"dir": "任务", "file": name} for name in names]}))


def undo(receipt: dict):
    return run(api.undo_batch_trash(receipt))


def test_public_receipt_v2_and_request_schema_fails_before_claim(wb, monkeypatch):
    task(wb, "one.md")
    receipt = batch("one.md")["undo_receipt"]
    assert receipt["schema"] == "workbench.batch-trash-undo"
    assert receipt["version"] == 2
    called = []
    monkeypatch.setattr(api, "_acquire_batch_undo_claim", lambda *_: called.append(True))
    for bad in ({k: v for k, v in receipt.items() if k != "schema"}, {**receipt, "version": 99}):
        result = undo(bad)
        assert result["ok"] is False and result["restored"] == []
    assert called == []


def test_v1_ledger_is_server_read_compatibility_not_v1_public_receipt(wb):
    task(wb, "legacy.md")
    receipt = batch("legacy.md")["undo_receipt"]
    path = api._batch_undo_path(receipt["operation_id"])
    record = json.loads(path.read_text(encoding="utf-8"))
    record.pop("schema")
    record["version"] = 1
    for item in record["items"]:
        item.update(item.pop("post_state"))
    path.write_text(json.dumps(record), encoding="utf-8")
    assert receipt["version"] == 2
    result = undo(receipt)
    assert result["receipt"]["consumed"] is True


def test_claim_contains_owner_liveness_and_compare_release(wb):
    operation_id = "a" * 32
    claim = api._acquire_batch_undo_claim(operation_id)
    assert claim and claim["owner"] and claim["claim_id"]
    assert claim["owner"]["pid"] > 0
    assert claim["owner"]["process_start_identity"]
    assert claim["owner"]["lease_id"] == claim["claim_id"]
    assert claim["created_at"] and claim["heartbeat_at"] and claim["expires_at"]
    replacement = {**claim, "owner": {**claim["owner"], "lease_id": "new-owner"}, "claim_id": "b" * 32}
    api._batch_undo_claim_path(operation_id).write_text(json.dumps(replacement), encoding="utf-8")
    assert api._release_batch_undo_claim(operation_id, claim) is False
    assert json.loads(api._batch_undo_claim_path(operation_id).read_text(encoding="utf-8"))["owner"]["lease_id"] == "new-owner"


def test_live_owner_over_ttl_renews_atomically_and_stays_busy(wb, monkeypatch):
    operation_id = "b" * 32
    first = datetime(2026, 8, 31, 1, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(api, "_batch_undo_now", lambda: first)
    claim = api._acquire_batch_undo_claim(operation_id)
    assert claim
    later = first + timedelta(minutes=11)
    monkeypatch.setattr(api, "_batch_undo_now", lambda: later)
    monkeypatch.setattr(api, "_claim_owner_liveness", lambda _owner: "live")
    assert api._acquire_batch_undo_claim(operation_id) is None
    assert api._renew_batch_undo_claim(operation_id, claim) is True
    renewed = json.loads(api._batch_undo_claim_path(operation_id).read_text(encoding="utf-8"))
    assert renewed["heartbeat_at"] == later.isoformat()
    assert datetime.fromisoformat(renewed["expires_at"]) > later


def test_release_and_reclaim_interleave_cannot_delete_replacement(wb, monkeypatch):
    operation_id = "c" * 32
    claim = api._acquire_batch_undo_claim(operation_id)
    assert claim
    monkeypatch.setattr(api, "_claim_owner_liveness", lambda _owner: "dead")
    original_replace = api.os.replace
    interleaved = {"done": False}

    def replace_with_new_claim(source, target):
        original_replace(source, target)
        if not interleaved["done"] and str(source).endswith(".claim.json"):
            interleaved["done"] = True
            replacement = {**claim, "claim_id": "d" * 32, "owner": {**claim["owner"], "lease_id": "replacement"}}
            api._write_claim_file(replacement, api._batch_undo_claim_path(operation_id))

    monkeypatch.setattr(api.os, "replace", replace_with_new_claim)
    assert api._release_batch_undo_claim(operation_id, claim) is True
    current = json.loads(api._batch_undo_claim_path(operation_id).read_text(encoding="utf-8"))
    assert current["owner"]["lease_id"] == "replacement"


def test_recovery_skips_live_transaction_claim(wb, monkeypatch):
    operation_id = "e" * 32
    prepared = {
        "schema": api._BATCH_UNDO_SCHEMA, "version": 2, "operation_id": operation_id,
        "state": "inflight", "items": [{"dir": "任务", "file": "live.md", "trash_file": "live.md", "state": "moved"}],
    }
    api._batch_undo_prepared_path(operation_id).parent.mkdir(parents=True, exist_ok=True)
    api._write_batch_undo_record(prepared, api._batch_undo_prepared_path(operation_id))
    claim = api._acquire_batch_undo_claim(operation_id)
    assert claim
    monkeypatch.setattr(api, "_claim_owner_liveness", lambda _owner: "live")
    monkeypatch.setattr(api, "_rollback_batch_trash_record", lambda _record: (_ for _ in ()).throw(AssertionError("live transaction touched")))
    api._recover_batch_undo_operations()
    assert api._batch_undo_prepared_path(operation_id).is_file()


def test_live_claim_never_reclaimed_and_invalid_clock_stays_busy(wb):
    task(wb, "one.md")
    receipt = batch("one.md")["undo_receipt"]
    claim = api._acquire_batch_undo_claim(receipt["operation_id"])
    assert claim
    assert undo(receipt)["error"] == "operation busy"
    payload = json.loads(api._batch_undo_claim_path(receipt["operation_id"]).read_text(encoding="utf-8"))
    payload["created_at"] = "not-a-time"
    payload["expires_at"] = "not-a-time"
    api._batch_undo_claim_path(receipt["operation_id"]).write_text(json.dumps(payload), encoding="utf-8")
    assert undo(receipt)["error"].startswith("operation busy")


def test_stale_claim_reclaimed_with_provenance_and_old_release_cannot_win(wb, monkeypatch):
    now = datetime(2026, 8, 31, 1, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(api, "_batch_undo_now", lambda: now)
    monkeypatch.setattr(api, "_claim_owner_liveness", lambda _owner: "dead")
    task(wb, "one.md")
    receipt = batch("one.md")["undo_receipt"]
    operation_id = receipt["operation_id"]
    old = api._acquire_batch_undo_claim(operation_id)
    payload = json.loads(api._batch_undo_claim_path(operation_id).read_text(encoding="utf-8"))
    payload["created_at"] = (now - timedelta(minutes=10)).isoformat()
    payload["heartbeat_at"] = payload["created_at"]
    payload["expires_at"] = (now - timedelta(minutes=1)).isoformat()
    api._batch_undo_claim_path(operation_id).write_text(json.dumps(payload), encoding="utf-8")
    fresh = api._acquire_batch_undo_claim(operation_id)
    assert fresh and fresh["claim_id"] != old["claim_id"]
    assert fresh["recovery"]["reclaimed_claim_id"] == old["claim_id"]
    assert list((wb / ".batch-undo").glob("*.claim-recovery.json"))
    assert api._release_batch_undo_claim(operation_id, old) is False
    assert api._release_batch_undo_claim(operation_id, fresh) is True


def test_finalized_prepared_promotes_and_sync_failure_keeps_receipt(wb, monkeypatch):
    task(wb, "one.md")
    real_replace = api.os.replace
    crashed = {"done": False}

    def crash_between(source, target):
        if str(source).endswith(".prepared.json") and str(target).endswith(".json") and not crashed["done"]:
            crashed["done"] = True
            raise OSError("crash after finalized-prepared")
        return real_replace(source, target)

    monkeypatch.setattr(api.os, "replace", crash_between)
    failed = batch("one.md")
    assert failed["summary"]["ok"] == 0
    monkeypatch.setattr(api.os, "replace", real_replace)
    api._recover_batch_undo_operations()
    finals = list((wb / ".batch-undo").glob("[0-9a-f]*.json"))
    assert any(json.loads(p.read_text(encoding="utf-8")).get("state") == "finalized" for p in finals)

    task(wb, "two.md")
    monkeypatch.setattr(api, "_sync_conversation", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("sync down")))
    result = batch("two.md")
    assert result["summary"] == {"ok": 1, "fail": 0}
    assert result["undo_receipt"]["version"] == 2
    assert result["warnings"]


def test_finalized_prepared_tamper_becomes_recovery_required_without_promote(wb):
    task(wb, "tampered.md")
    receipt = batch("tampered.md")["undo_receipt"]
    final = api._batch_undo_path(receipt["operation_id"])
    prepared = api._batch_undo_prepared_path(receipt["operation_id"])
    final.replace(prepared)
    (wb / "回收站" / "tampered.md").write_text("tampered", encoding="utf-8")
    api._recover_batch_undo_operations()
    current = json.loads(prepared.read_text(encoding="utf-8"))
    assert current["state"] == "recovery-required"
    assert not final.exists()
    assert not (wb / "任务" / "tampered.md").exists()


def test_recovery_evidence_is_read_merged_and_converges(wb):
    operation_id = "f" * 32
    prepared = {"schema": api._BATCH_UNDO_SCHEMA, "version": 2, "operation_id": operation_id, "state": "recovery-required", "items": []}
    prepared_path = api._batch_undo_prepared_path(operation_id)
    api._write_batch_undo_record(prepared, prepared_path)
    evidence = {**prepared, "recorded_at": api._batch_undo_now().isoformat(), "error": "replayed", "items": []}
    evidence_path = api._batch_undo_dir() / f"{operation_id}.recovery-evidence.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    api._recover_batch_undo_operations()
    current = json.loads(prepared_path.read_text(encoding="utf-8"))
    assert current["recovery_evidence"]["error"] == "replayed"
    assert not evidence_path.exists()


@pytest.mark.parametrize("failure_point", ["intent", "outcome"])
def test_multi_item_checkpoint_and_settle_failure_returns_full_terminal_identities(wb, monkeypatch, failure_point):
    task(wb, "one.md")
    task(wb, "two.md")
    receipt = batch("one.md", "two.md")["undo_receipt"]
    real_write = api._write_batch_undo_record

    def fail_after_restore(record, *args, **kwargs):
        state = record.get("state")
        has_restored = bool((record.get("outcome") or {}).get("restored"))
        second_intent = any(i.get("file") == "two.md" and i.get("undo_state") == "intent" for i in record["items"])
        if state == "consumed" or (state == "claimed" and ((failure_point == "intent" and second_intent) or (failure_point == "outcome" and has_restored))):
            raise OSError(f"injected {failure_point}/settle write failure")
        return real_write(record, *args, **kwargs)

    monkeypatch.setattr(api, "_write_batch_undo_record", fail_after_restore)
    result = undo(receipt)
    assert result["receipt"]["consumed"] is True
    assert result["receipt"]["operation_id"] == receipt["operation_id"]
    assert {(row["dir"], row["file"]) for row in result["restored"] + result["failed"]} == {
        ("任务", "one.md"), ("任务", "two.md")
    }
    assert not (wb / "回收站" / "one.md").exists()
    assert (wb / "任务" / "one.md").is_file()


def test_double_durability_failure_preserves_claimed_truth_and_restart_reclaims(wb, monkeypatch):
    task(wb, "one.md")
    task(wb, "two.md")
    receipt = batch("one.md", "two.md")["undo_receipt"]
    real_write = api._write_batch_undo_record
    real_evidence = api._write_batch_recovery_evidence

    def fail_terminal(record, *args, **kwargs):
        if record.get("state") == "consumed":
            raise OSError("injected terminal ledger write failure")
        return real_write(record, *args, **kwargs)

    monkeypatch.setattr(api, "_write_batch_undo_record", fail_terminal)
    monkeypatch.setattr(api, "_write_batch_recovery_evidence", lambda *_a, **_k: (_ for _ in ()).throw(OSError("injected sidecar failure")))
    with pytest.raises(OSError, match="sidecar failure"):
        undo(receipt)

    path = api._batch_undo_path(receipt["operation_id"])
    claimed = json.loads(path.read_text(encoding="utf-8"))
    assert claimed["state"] == "claimed"
    assert [(item["dir"], item["file"]) for item in claimed["items"]] == [("任务", "one.md"), ("任务", "two.md")]

    claim_path = api._batch_undo_claim_path(receipt["operation_id"])
    assert not claim_path.exists()
    stale = {
        "schema": api._BATCH_UNDO_SCHEMA,
        "version": api._BATCH_UNDO_VERSION,
        "state": "claimed",
        "operation_id": receipt["operation_id"],
        "claim_id": "d" * 32,
        "owner": {"pid": 1, "process_start_identity": "1.000000", "lease_id": "d" * 32},
        "created_at": datetime(1999, 1, 1, tzinfo=timezone.utc).isoformat(),
        "heartbeat_at": datetime(1999, 6, 1, tzinfo=timezone.utc).isoformat(),
        "expires_at": datetime(2000, 1, 1, tzinfo=timezone.utc).isoformat(),
    }
    api._write_claim_file(stale, claim_path)
    monkeypatch.setattr(api, "_claim_owner_liveness", lambda _owner: "dead")
    monkeypatch.setattr(api, "_write_batch_undo_record", real_write)
    monkeypatch.setattr(api, "_write_batch_recovery_evidence", real_evidence)
    api._recover_batch_undo_operations()
    settled = json.loads(path.read_text(encoding="utf-8"))
    assert settled["state"] == "consumed"
    assert {(row["dir"], row["file"]) for row in settled["outcome"]["restored"] + settled["outcome"]["failed"]} == {
        ("任务", "one.md"), ("任务", "two.md")
    }


def test_real_busy_expired_collision_rejections_use_v2_actionable_envelope(wb):
    for index, expected_error in enumerate(("operation busy", "operation expired", "original path collision")):
        name = f"reject-{index}.md"
        task(wb, name)
        receipt = batch(name)["undo_receipt"]
        claim = None
        if expected_error == "operation busy":
            claim = api._acquire_batch_undo_claim(receipt["operation_id"])
        elif expected_error == "operation expired":
            path = api._batch_undo_path(receipt["operation_id"])
            record = json.loads(path.read_text(encoding="utf-8"))
            record["expires_at"] = datetime(2000, 1, 1, tzinfo=timezone.utc).isoformat()
            api._write_batch_undo_record(record, path)
        else:
            task(wb, name)
        response = undo(receipt)
        assert response["error"] == expected_error
        assert response["receipt"] == {
            "schema": api._BATCH_UNDO_SCHEMA,
            "version": api._BATCH_UNDO_VERSION,
            "operation_id": receipt["operation_id"],
            "action": "trash",
            "consumed": False,
        }
        if claim is not None:
            api._release_batch_undo_claim(receipt["operation_id"], claim)


def test_rollback_failure_becomes_recovery_required_and_double_write_keeps_evidence(wb, monkeypatch):
    task(wb, "one.md")
    real_move = api._rename_with_retry
    moved = {"done": False}

    def fail_rollback(source, target):
        if "回收站" in str(source) and "任务" in str(target):
            raise OSError("rollback blocked")
        result = real_move(source, target)
        moved["done"] = True
        return result

    real_write = api._write_batch_undo_record
    real_digest = api._file_digest

    def fail_recovery_write(record, *args, **kwargs):
        if record.get("state") == "recovery-required":
            raise OSError("ledger unavailable")
        return real_write(record, *args, **kwargs)

    def fail_after_move(path):
        if "回收站" in str(path):
            raise OSError("post-state digest unavailable")
        return real_digest(path)

    monkeypatch.setattr(api, "_rename_with_retry", fail_rollback)
    monkeypatch.setattr(api, "_write_batch_undo_record", fail_recovery_write)
    monkeypatch.setattr(api, "_file_digest", fail_after_move)
    result = batch("one.md")
    assert result["summary"]["ok"] == 0
    assert moved["done"]
    evidence = list((wb / ".batch-undo").glob("*.recovery-evidence.json"))
    assert evidence
    assert json.loads(evidence[0].read_text(encoding="utf-8"))["state"] == "recovery-required"


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="Windows MAX_PATH prepare failure only; POSIX supports this path",
)
def test_long_root_prepare_fails_before_first_move(tmp_path, monkeypatch):
    root = tmp_path
    while len(str(root / ".batch-undo" / ("a" * 32 + ".prepared.json"))) < 270:
        root = root / ("long-segment-" + "x" * 20)
    for dirname in ("任务", "回收站", "日志"):
        (root / dirname).mkdir(parents=True, exist_ok=True)
    isolated = repo_module.DualRepo(repo_module.FileRepo(root), repo_module.SqliteRepo(tmp_path / "long.db"), False)
    monkeypatch.setattr(api, "WORKBENCH_ROOT", root)
    monkeypatch.setattr(api, "file_repo", isolated)
    monkeypatch.setattr(wb_utils, "WORKBENCH_ROOT", root)
    task(root, "one.md")
    moves = []
    monkeypatch.setattr(api, "_rename_with_retry", lambda *_: moves.append(True))
    result = batch("one.md")
    assert result["summary"] == {"ok": 0, "fail": 1}
    assert moves == []
    assert (root / "任务" / "one.md").is_file()


def test_two_recovery_workers_enter_recovery_and_only_one_settles(wb, monkeypatch):
    task(wb, "settle.md")
    receipt = batch("settle.md")["undo_receipt"]
    path = api._batch_undo_path(receipt["operation_id"])
    record = json.loads(path.read_text(encoding="utf-8"))
    record["state"] = "claimed"
    record["outcome"] = {"restored": [], "failed": []}
    api._write_batch_undo_record(record, path)
    entered = threading.Barrier(2)
    settle_entered = threading.Event()
    allow_settle = threading.Event()
    real_recover = api._recover_batch_undo_operations
    real_settle = api._settle_claimed_record
    recover_count = 0
    count_lock = threading.Lock()

    def observed_recover():
        nonlocal recover_count
        with count_lock:
            recover_count += 1
        entered.wait(timeout=2)
        return real_recover()

    def blocked_settle(current):
        settle_entered.set()
        assert allow_settle.wait(2)
        return real_settle(current)

    monkeypatch.setattr(api, "_settle_claimed_record", blocked_settle)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(observed_recover) for _ in range(2)]
        assert settle_entered.wait(2)
        allow_settle.set()
        for future in futures:
            future.result(timeout=3)
    settled = json.loads(path.read_text(encoding="utf-8"))
    assert recover_count == 2
    assert settled["state"] == "consumed"


def test_recovery_claim_interleaves_with_live_undo_fail_closed_then_converges(wb, monkeypatch):
    task(wb, "live-race.md")
    receipt = batch("live-race.md")["undo_receipt"]
    path = api._batch_undo_path(receipt["operation_id"])
    record = json.loads(path.read_text(encoding="utf-8"))
    record["state"] = "claimed"
    record["outcome"] = {"restored": [], "failed": []}
    api._write_batch_undo_record(record, path)
    settle_entered = threading.Event()
    allow_settle = threading.Event()
    real_settle = api._settle_claimed_record

    def blocked_settle(current):
        settle_entered.set()
        assert allow_settle.wait(2)
        return real_settle(current)

    monkeypatch.setattr(api, "_settle_claimed_record", blocked_settle)
    with ThreadPoolExecutor(max_workers=2) as pool:
        recovery = pool.submit(api._recover_batch_undo_operations)
        assert settle_entered.wait(2)
        live = pool.submit(undo, receipt)
        allow_settle.set()
        recovery.result(timeout=3)
        live_result = live.result(timeout=3)
    assert live_result["ok"] is False
    assert live_result["error"] in {"operation busy", "operation already consumed"}
    assert json.loads(path.read_text(encoding="utf-8"))["state"] == "consumed"


def test_persistent_release_tombstone_and_registry_converge_on_next_acquire(wb, monkeypatch):
    operation_id = "1" * 32
    claim = api._acquire_batch_undo_claim(operation_id)
    assert claim is not None
    released_path = api._batch_undo_claim_path(operation_id).with_name(
        f".{operation_id}.{claim['claim_id']}.released.json"
    )
    real_unlink = Path.unlink

    def fail_released_unlink(path, missing_ok=False):
        if path == released_path:
            raise OSError("persistent unlink")
        return real_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(api.Path, "unlink", fail_released_unlink)
    assert api._release_batch_undo_claim(operation_id, claim) is False
    key = api._claim_registry_key(claim)
    assert released_path.is_file() and key in api._INACTIVE_BATCH_UNDO_CLAIMS
    monkeypatch.setattr(api.Path, "unlink", real_unlink)
    replacement = api._acquire_batch_undo_claim(operation_id)
    assert replacement is not None
    assert not released_path.exists()
    assert key not in api._INACTIVE_BATCH_UNDO_CLAIMS
    assert api._release_batch_undo_claim(operation_id, replacement) is True


def test_access_denied_owner_is_unknown_and_never_reclaimed(wb, monkeypatch):
    import psutil

    operation_id = "2" * 32
    claim = api._acquire_batch_undo_claim(operation_id)
    assert claim is not None
    claim_path = api._batch_undo_claim_path(operation_id)
    payload = json.loads(claim_path.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    payload["created_at"] = (now - timedelta(minutes=20)).isoformat()
    payload["heartbeat_at"] = (now - timedelta(minutes=11)).isoformat()
    payload["expires_at"] = (now - timedelta(minutes=1)).isoformat()
    claim_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(psutil, "Process", lambda _pid: (_ for _ in ()).throw(psutil.AccessDenied(_pid)))
    assert api._claim_owner_liveness(claim["owner"]) == "unknown"
    assert api._acquire_batch_undo_claim(operation_id) is None


def test_terminal_settlement_and_sidecar_failure_converge_with_two_recovery_workers(wb, monkeypatch):
    task(wb, "sidecar-race.md")
    receipt = batch("sidecar-race.md")["undo_receipt"]
    path = api._batch_undo_path(receipt["operation_id"])
    record = json.loads(path.read_text(encoding="utf-8"))
    record["state"] = "claimed"
    record["outcome"] = {"restored": [], "failed": []}
    api._write_batch_undo_record(record, path)
    real_write = api._write_batch_undo_record
    both_entered = threading.Barrier(2)
    first_terminal = threading.Event()
    allow_failure = threading.Event()
    failed_once = False
    failure_lock = threading.Lock()

    def fail_first_terminal(current, *args, **kwargs):
        nonlocal failed_once
        if current.get("state") == "consumed":
            with failure_lock:
                should_fail = not failed_once
                if should_fail:
                    failed_once = True
            if should_fail:
                first_terminal.set()
                assert allow_failure.wait(2)
                raise OSError("first terminal write failed")
        return real_write(current, *args, **kwargs)

    monkeypatch.setattr(api, "_write_batch_undo_record", fail_first_terminal)
    monkeypatch.setattr(
        api,
        "_write_batch_recovery_evidence",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("sidecar failed")),
    )

    def worker():
        both_entered.wait(timeout=2)
        try:
            api._recover_batch_undo_operations()
            return "settled"
        except OSError:
            return "fail-closed"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker) for _ in range(2)]
        assert first_terminal.wait(2)
        allow_failure.set()
        outcomes = [future.result(timeout=3) for future in futures]
    # A sidecar failure cannot erase the claimed ledger.  If the concurrent
    # worker observed the claim as busy, the immediately next recovery settles.
    if json.loads(path.read_text(encoding="utf-8"))["state"] != "consumed":
        api._recover_batch_undo_operations()
    assert "fail-closed" in outcomes
    assert json.loads(path.read_text(encoding="utf-8"))["state"] == "consumed"
