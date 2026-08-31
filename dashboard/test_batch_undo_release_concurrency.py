"""WB-S1-065 A1/A2 focused RED for release and deterministic ownership races.

All state is under pytest's temporary directory. The tests deliberately target
private seams because the public endpoint must preserve the same operation claim
and exact ledger semantics.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import plugin_api as api


def _claim(operation_id: str):
    claim = api._acquire_batch_undo_claim(operation_id)
    assert claim is not None
    return claim


def _isolated(monkeypatch, tmp_path):
    root = tmp_path / "workbench"
    (root / ".batch-undo").mkdir(parents=True)
    monkeypatch.setattr(api, "WORKBENCH_ROOT", root)
    return root


def _expire(path, now):
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["created_at"] = (now - timedelta(minutes=20)).isoformat()
    payload["heartbeat_at"] = (now - timedelta(minutes=11)).isoformat()
    payload["expires_at"] = (now - timedelta(minutes=1)).isoformat()
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_release_retries_one_atomic_move_failure_and_returns_success(monkeypatch, tmp_path):
    _isolated(monkeypatch, tmp_path)
    operation_id = "1" * 32
    claim = _claim(operation_id)
    real_replace = api.os.replace
    attempts = []

    def fail_once(source, target):
        if str(source).endswith(".claim.json") and str(target).endswith(".released.json"):
            attempts.append(1)
            if len(attempts) == 1:
                raise OSError("transient move failure")
        return real_replace(source, target)

    monkeypatch.setattr(api.os, "replace", fail_once)
    assert api._release_batch_undo_claim(operation_id, claim) is True
    assert len(attempts) == 2
    assert not api._batch_undo_claim_path(operation_id).exists()


def test_release_persistent_move_failure_is_bounded_and_preserves_exact_claim(monkeypatch, tmp_path):
    _isolated(monkeypatch, tmp_path)
    operation_id = "2" * 32
    claim = _claim(operation_id)
    claim_path = api._batch_undo_claim_path(operation_id)
    before = claim_path.read_bytes()
    attempts = []

    real_replace = api.os.replace

    def always_fail(source, target):
        if str(source).endswith(".claim.json") and str(target).endswith(".released.json"):
            attempts.append(1)
            raise OSError("persistent move failure")
        return real_replace(source, target)

    monkeypatch.setattr(api.os, "replace", always_fail)
    assert api._release_batch_undo_claim(operation_id, claim) is False
    assert len(attempts) == 3
    assert claim_path.read_bytes() == before


def test_same_process_inactive_lease_converges_after_persistent_release_failure(monkeypatch, tmp_path):
    _isolated(monkeypatch, tmp_path)
    operation_id = "3" * 32
    claim = _claim(operation_id)
    real_replace = api.os.replace
    def release_move_fails(source, target):
        if str(source).endswith(".claim.json") and str(target).endswith(".released.json"):
            raise OSError("release down")
        return real_replace(source, target)
    monkeypatch.setattr(api.os, "replace", release_move_fails)
    assert api._release_batch_undo_claim(operation_id, claim) is False

    now = datetime.now(timezone.utc) + timedelta(seconds=1)
    monkeypatch.setattr(api, "_batch_undo_now", lambda: now)
    monkeypatch.setattr(api, "_claim_owner_liveness", lambda _owner: "live")
    monkeypatch.setattr(api.os, "replace", real_replace)
    replacement = api._acquire_batch_undo_claim(operation_id)
    assert replacement is not None
    assert replacement["claim_id"] != claim["claim_id"]


def test_live_and_unknown_foreign_owner_stays_busy(monkeypatch, tmp_path):
    _isolated(monkeypatch, tmp_path)
    for index, status in enumerate(("live", "unknown"), start=4):
        operation_id = str(index) * 32
        claim = _claim(operation_id)
        _expire(api._batch_undo_claim_path(operation_id), datetime.now(timezone.utc))
        monkeypatch.setattr(api, "_claim_owner_liveness", lambda _owner, value=status: value)
        assert api._acquire_batch_undo_claim(operation_id) is None
        assert api._batch_undo_claim_path(operation_id).read_bytes()
        monkeypatch.setattr(api, "_claim_owner_liveness", lambda _owner: "dead")
        assert api._release_batch_undo_claim(operation_id, claim) is True


def test_dead_owner_reclaims_and_late_old_release_cannot_delete_new_claim(monkeypatch, tmp_path):
    _isolated(monkeypatch, tmp_path)
    operation_id = "6" * 32
    old = _claim(operation_id)
    _expire(api._batch_undo_claim_path(operation_id), datetime.now(timezone.utc))
    monkeypatch.setattr(api, "_claim_owner_liveness", lambda _owner: "dead")
    fresh = api._acquire_batch_undo_claim(operation_id)
    assert fresh is not None and fresh["claim_id"] != old["claim_id"]
    assert api._release_batch_undo_claim(operation_id, old) is False
    current = json.loads(api._batch_undo_claim_path(operation_id).read_text(encoding="utf-8"))
    assert current["claim_id"] == fresh["claim_id"]
    assert api._release_batch_undo_claim(operation_id, fresh) is True


def test_two_recovery_workers_have_one_settlement_slot(monkeypatch, tmp_path):
    _isolated(monkeypatch, tmp_path)
    operation_id = "7" * 32
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait(timeout=2)
        return api._acquire_batch_undo_claim(operation_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _item: worker(), range(2)))
    assert sum(result is not None for result in results) == 1
    winner = next(result for result in results if result is not None)
    assert api._release_batch_undo_claim(operation_id, winner) is True


def test_prepared_stale_read_cannot_rollback_live_finalized_authority(monkeypatch, tmp_path):
    root = _isolated(monkeypatch, tmp_path)
    operation_id = "8" * 32
    source = root / "任务" / "race.md"
    trash = root / "回收站" / "race.md"
    trash.parent.mkdir(parents=True, exist_ok=True)
    source.parent.mkdir(parents=True, exist_ok=True)
    trash.write_text("finalized", encoding="utf-8")
    stat = trash.stat()
    record = {
        "schema": api._BATCH_UNDO_SCHEMA, "version": api._BATCH_UNDO_VERSION,
        "operation_id": operation_id, "action": "trash", "state": "inflight",
        "items": [{"dir": "任务", "file": "race.md", "trash_file": "race.md",
                   "state": "moved", "post_state": {"sha256": api._file_digest(trash), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}}],
    }
    prepared = api._batch_undo_prepared_path(operation_id)
    final = api._batch_undo_path(operation_id)
    api._write_batch_undo_record(record, prepared)
    real_acquire = api._acquire_batch_undo_claim
    entered = threading.Event()
    finalized = threading.Event()

    def acquire_after_live_finalize(op):
        entered.set()
        assert finalized.wait(2)
        return real_acquire(op)

    def live_finalize():
        assert entered.wait(2)
        authoritative = {**record, "state": "finalized"}
        api._write_batch_undo_record(authoritative, prepared)
        api.os.replace(prepared, final)
        finalized.set()

    monkeypatch.setattr(api, "_acquire_batch_undo_claim", acquire_after_live_finalize)
    worker = threading.Thread(target=live_finalize)
    worker.start()
    api._recover_batch_undo_operations()
    worker.join(2)
    assert final.is_file() and not prepared.exists()
    assert trash.is_file() and not source.exists()


def test_registry_rejects_owner_lease_mismatch(monkeypatch, tmp_path):
    _isolated(monkeypatch, tmp_path)
    operation_id = "9" * 32
    claim = _claim(operation_id)
    corrupt = {**claim, "owner": {**claim["owner"], "lease_id": "0" * 32}}
    api._mark_claim_inactive(corrupt)
    assert api._claim_registry_key(corrupt) is None
    assert api._is_same_process_inactive_claim(corrupt) is False
