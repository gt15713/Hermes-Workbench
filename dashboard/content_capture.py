"""Reviewed content inbox domain boundary.

Capturing is intentionally local-only.  Obsidian is reachable solely through
the injected ``sink`` used by :func:`review_content`, after human review.
"""
from __future__ import annotations

import hashlib
import json
import posixpath
import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

PARTITION = "待验证"
ARCHIVE_PARTITION = "已处理"
_MARKER = re.compile(r"(?m)^<!-- wb_content: (\{.*\}) -->$")
_TRACKING_KEYS = {
    "fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid",
    "igshid", "yclid", "_hsenc", "_hsmi",
}


def canonicalize_url(url: str) -> str:
    """Return a stable HTTP(S) URL for deduplication, not navigation."""
    raw = str(url or "").strip()
    parsed = urlsplit(raw)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("source_url must be an absolute http(s) URL")
    host = parsed.hostname.lower()
    port = parsed.port
    if port and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        host = f"{host}:{port}"
    path = posixpath.normpath(parsed.path or "/")
    if parsed.path.endswith("/") and path != "/":
        path += "/"
    query = sorted(
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_KEYS
    )
    return urlunsplit((scheme, host, path, urlencode(query, doseq=True), ""))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse(path, repo, partition=PARTITION) -> dict | None:
    try:
        text = repo.read_text(path)
    except OSError:
        return None
    match = _MARKER.search(text)
    if not match:
        return None
    try:
        item = json.loads(match.group(1))
    except (TypeError, ValueError):
        return None
    source_id = item.pop("source_id", "")
    if source_id and not item.get("source_ref"):
        item["source_ref"] = hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:16]
    item["dir"] = partition
    item["file"] = path.name
    return item


def _render(item: dict) -> str:
    stored = {key: value for key, value in item.items() if key not in {"dir", "file"}}
    marker = json.dumps(stored, ensure_ascii=False, separators=(",", ":"))
    return (
        f"<!-- wb_content: {marker} -->\n\n"
        f"# {item['title']}\n\n"
        f"来源：{item['original_url']}\n\n"
        f"## 原始内容\n\n{item['original_text']}\n"
    )


def _find(repo, *, dirname=None, filename=None, capture_id=None):
    if filename:
        if dirname not in {PARTITION, ARCHIVE_PARTITION} or "/" in filename or "\\" in filename:
            return None, None
        path = repo.partition_dir(dirname) / filename
        return path, _parse(path, repo, dirname)
    if capture_id:
        for partition in (PARTITION, ARCHIVE_PARTITION):
            for path in repo.list_files(partition):
                item = _parse(path, repo, partition)
                if item and item.get("capture_id") == capture_id:
                    return path, item
    return None, None


def _event(repo, item: dict, kind: str, detail: str) -> None:
    repo.event(item["dir"], item["file"], kind, detail)


def capture_content(repo, body: dict) -> dict:
    for field in ("source_id", "source_url", "original_text", "title"):
        if field not in body or (
            field != "original_text" and not str(body.get(field) or "").strip()
        ):
            return {"ok": False, "error": f"{field} required"}
    original_url = str(body["source_url"]).strip()
    try:
        canonical_url = canonicalize_url(original_url)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    capture_id = hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:16]
    _, existing = _find(repo, capture_id=capture_id)
    if existing:
        _event(repo, existing, "content_duplicate", f"等价链接重复收录：{capture_id}")
        return {"ok": True, "duplicate": True, "item": existing}

    filename = f"content-{capture_id}.md"
    original_text = str(body["original_text"] or "").strip()
    item = {
        "capture_id": capture_id,
        "source_ref": hashlib.sha256(
            str(body["source_id"]).strip().encode("utf-8")
        ).hexdigest()[:16],
        "original_url": original_url,
        "canonical_url": canonical_url,
        "original_text": original_text,
        "title": str(body["title"]).strip(),
        "extraction_state": "extracted" if original_text else "pending",
        "review_state": "pending",
        "note_path": "",
        "last_error": "",
        "captured_at": _now(),
        "reviewed_at": "",
        "dir": PARTITION,
        "file": filename,
    }
    path = repo.partition_dir(PARTITION) / filename
    repo.write_text(path, _render(item))
    _event(repo, item, "content_captured", f"内容待复核：{capture_id}")
    return {"ok": True, "duplicate": False, "item": item}


def get_content_item(
    repo, *, dirname=None, filename=None, entry_title=None, capture_id=None
) -> dict:
    if entry_title:
        return {"ok": False, "error": "entry_title is not supported for reviewed content"}
    _, item = _find(repo, dirname=dirname, filename=filename, capture_id=capture_id)
    if not item:
        return {"ok": False, "error": "content item not found"}
    return {"ok": True, "item": item}


def review_content(
    repo, dirname, filename, action, *, entry_title=None, sink=None
) -> dict:
    if action not in {"archive_only", "sink_to_obsidian"}:
        return {"ok": False, "error": "bad review action"}
    found = get_content_item(
        repo, dirname=dirname, filename=filename, entry_title=entry_title
    )
    if not found["ok"]:
        return found
    item = found["item"]
    path = repo.partition_dir(PARTITION) / item["file"]
    now = _now()
    if action == "archive_only":
        item.update(review_state="archived", reviewed_at=now, last_error="")
        repo.write_text(path, _render(item))
        destination = repo.partition_dir(ARCHIVE_PARTITION) / item["file"]
        repo.move(path, destination)
        item["dir"] = ARCHIVE_PARTITION
        _event(repo, item, "content_archived", f"仅归档：{item['capture_id']}")
        return {"ok": True, "item": item}

    if sink is None:
        error = "Obsidian sink unavailable"
    else:
        try:
            sink_result = sink(dict(item))
            if not isinstance(sink_result, dict) or not sink_result.get("ok"):
                raise RuntimeError(str((sink_result or {}).get("error") or "Obsidian sink failed"))
            if sink_result.get("status") == "queued":
                required = ("task_id", "task_dir", "task_file", "task_path")
                if any(not str(sink_result.get(key) or "").strip() for key in required):
                    raise RuntimeError("Obsidian sink queue returned incomplete task receipt")
                item.update(
                    review_state="sink_queued",
                    sink_task_id=str(sink_result["task_id"]),
                    sink_task_dir=str(sink_result["task_dir"]),
                    sink_task_file=str(sink_result["task_file"]),
                    sink_task_path=str(sink_result["task_path"]),
                    reviewed_at=now,
                    last_error="",
                )
                repo.write_text(path, _render(item))
                _event(repo, item, "content_sink_queued", f"已创建摄入任务：{item['sink_task_id']}")
                return {"ok": True, "item": item}
            raise RuntimeError("Obsidian sink must queue an Agent task and await its receipt")
        except Exception as exc:
            error = str(exc) or exc.__class__.__name__

    item.update(review_state="sink_failed", reviewed_at=now, last_error=error)
    repo.write_text(path, _render(item))
    _event(repo, item, "content_sink_failed", f"沉淀失败：{item['capture_id']}（可重试）")
    return {"ok": False, "error": error, "retryable": True, "item": item}


def complete_content_sink(repo, capture_id, task_id, *, note_path="", error="") -> dict:
    """Apply one Agent receipt; only its bound queued task may complete the item."""
    path, item = _find(repo, capture_id=str(capture_id or "").strip())
    if not item or not path:
        return {"ok": False, "error": "content item not found"}
    if item.get("review_state") != "sink_queued":
        return {"ok": False, "error": "content item is not awaiting sink receipt"}
    if str(item.get("sink_task_id") or "") != str(task_id or "").strip():
        return {"ok": False, "error": "sink task mismatch"}

    now = _now()
    failure = str(error or "").strip()
    durable_path = str(note_path or "").strip()
    if failure or not durable_path:
        failure = failure or "Obsidian sink returned no note_path"
        item.update(review_state="sink_failed", reviewed_at=now, last_error=failure, note_path="")
        repo.write_text(path, _render(item))
        _event(repo, item, "content_sink_failed", f"摄入任务失败：{item['sink_task_id']}（可重试）")
        return {"ok": False, "error": failure, "retryable": True, "item": item}

    item.update(review_state="sunk", note_path=durable_path, reviewed_at=now, last_error="")
    repo.write_text(path, _render(item))
    destination = repo.partition_dir(ARCHIVE_PARTITION) / item["file"]
    repo.move(path, destination)
    item["dir"] = ARCHIVE_PARTITION
    _event(repo, item, "content_sunk", f"已沉淀：{item['capture_id']} -> {durable_path}")
    return {"ok": True, "item": item}
