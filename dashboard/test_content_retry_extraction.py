"""Task 5（2026-08-27 批次2）— 独立重试抽取 transition + sink 幂等守卫。

CoderX §5 边界：
- 抽取重试是独立入口，绝不允许用「重试沉淀」冒充；
- 幂等：重复点击不产生重复 sink event / 不重复落盘；
- 沉淀前确认由 UI 层负责（window.confirm 已在 drawer）；后端保持最小 transition。
"""
from pathlib import Path

import content_capture as content_capture_module
import pytest
from content_capture import (
    capture_content,
    get_content_item,
    retry_extraction,
    review_content,
)


class MemoryRepo:
    def __init__(self, root: Path):
        self.root = root
        self.events = []

    def partition_dir(self, dirname):
        return self.root / dirname

    def list_files(self, dirname):
        return sorted((self.root / dirname).glob("*.md"))

    def read_text(self, path):
        return path.read_text(encoding="utf-8")

    def write_text(self, path, text, expected_mtime=None):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def move(self, src, dst):
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.replace(dst)
        return dst

    def event(self, partition, filename, kind, payload=""):
        self.events.append((partition, filename, kind, payload))


@pytest.fixture()
def repo(tmp_path):
    return MemoryRepo(tmp_path)


def _capture_pending(repo):
    result = capture_content(
        repo,
        {
            "source_id": "guild-1:chan-1:user-9",
            "source_url": "https://example.com/watch?v=retry",
            "title": "待抽取内容",
            "original_text": "",
        },
    )
    assert result["ok"], result
    return result["item"]


# ---------- 独立重试抽取 transition ----------

def test_retry_extraction_rehydrates_text_and_marks_extracted(repo):
    item = _capture_pending(repo)

    def extractor(current):
        assert current["capture_id"] == item["capture_id"]
        return {"ok": True, "original_text": "重新抽取到的正文", "canonical_url": "https://example.com/watch?v=retry"}

    result = retry_extraction(repo, item["dir"], item["file"], extract=extractor)
    assert result["ok"] is True
    refreshed = get_content_item(repo, dirname=result["item"]["dir"], filename=result["item"]["file"])
    assert refreshed["item"]["extraction_state"] == "extracted"
    assert refreshed["item"]["original_text"] == "重新抽取到的正文"
    kinds = [e[2] for e in repo.events]
    assert kinds.count("content_retry_extraction_ok") == 1


def test_retry_extraction_failure_records_real_reason_and_stays_retryable(repo):
    item = _capture_pending(repo)

    def extractor(current):
        raise RuntimeError("B站风控 412，稍后再试")

    result = retry_extraction(repo, item["dir"], item["file"], extract=extractor)
    assert result["ok"] is False
    assert "412" in result["error"]
    refreshed = get_content_item(repo, dirname=item["dir"], filename=item["file"])
    assert refreshed["item"]["extraction_state"] == "failed"
    assert "412" in (refreshed["item"].get("last_error") or "")
    # 失败保持可重试：再次调用允许
    again = retry_extraction(repo, item["dir"], item["file"], extract=lambda c: {"ok": True, "original_text": "第二轮成功"})
    assert again["ok"] is True


def test_retry_extraction_rejects_sunk_item(repo):
    item = _capture_pending(repo)
    queued = review_content(
        repo,
        item["dir"],
        item["file"],
        "sink_to_obsidian",
        sink=lambda i: {
            "ok": True,
            "status": "queued",
            "task_id": "WB-RETRY01",
            "task_dir": "任务",
            "task_file": "content-ingest-retry01.md",
            "task_path": "/v/任务/content-ingest-retry01.md",
        },
    )
    assert queued["ok"] is True
    done = content_capture_module.complete_content_sink(repo, item["capture_id"], "WB-RETRY01", note_path="知识库/x.md")
    assert done["ok"] is True

    moved = get_content_item(repo, capture_id=item["capture_id"])["item"]
    result = retry_extraction(repo, moved["dir"], moved["file"], extract=lambda c: {"ok": True, "original_text": "x"})
    assert result["ok"] is False


def test_retry_extraction_requires_extractor(repo):
    item = _capture_pending(repo)
    result = retry_extraction(repo, item["dir"], item["file"], extract=None)
    assert result["ok"] is False


# ---------- 审核动作幂等守卫（重复点击不产生重复 sink event） ----------

def _queue_sink(repo, item):
    return review_content(
        repo,
        item["dir"],
        item["file"],
        "sink_to_obsidian",
        sink=lambda i: {
            "ok": True,
            "status": "queued",
            "task_id": "WB-IDEM001",
            "task_dir": "任务",
            "task_file": "content-ingest-idem001.md",
            "task_path": "/v/任务/content-ingest-idem001.md",
        },
    )


def test_duplicate_sink_queue_is_rejected_without_second_event(repo):
    item = _capture_pending(repo)
    first = _queue_sink(repo, item)
    assert first["ok"] is True

    second = _queue_sink(repo, first["item"])
    assert second["ok"] is False
    assert second["idempotent_no_op"] is True
    assert second["item"]["sink_task_id"] == first["item"]["sink_task_id"]

    kinds = [e[2] for e in repo.events]
    assert kinds.count("content_sink_queued") == 1  # 幂等：任务只建一次


def test_archive_then_repeat_action_is_idempotent_no_op(repo):
    item = _capture_pending(repo)
    first = review_content(repo, item["dir"], item["file"], "archive_only")
    assert first["ok"] is True

    second = review_content(repo, first["item"]["dir"], first["item"]["file"], "archive_only")
    assert second["ok"] is False

    kinds = [e[2] for e in repo.events]
    assert kinds.count("content_archived") == 1
