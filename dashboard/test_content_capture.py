from pathlib import Path

import content_capture as content_capture_module
import pytest
from content_capture import (
    canonicalize_url,
    capture_content,
    get_content_item,
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


def _capture(repo, url="https://Example.com/watch?id=7&utm_source=qq#comments"):
    return capture_content(
        repo,
        {
            "source_id": "qqbot:user-authorized",
            "source_url": url,
            "original_text": "值得复习的正文",
            "title": "学习资料",
        },
    )


def test_canonicalize_url_removes_tracking_query_and_fragment():
    assert canonicalize_url(
        "HTTPS://Example.COM:443/a/../watch?utm_medium=chat&id=7&fbclid=x&b=2#part"
    ) == "https://example.com/watch?b=2&id=7"


def test_capture_preserves_original_url_and_records_extracted_item(repo):
    result = _capture(repo)

    assert result["ok"] is True
    assert result["duplicate"] is False
    item = result["item"]
    assert item["original_url"] == "https://Example.com/watch?id=7&utm_source=qq#comments"
    assert item["canonical_url"] == "https://example.com/watch?id=7"
    assert item["extraction_state"] == "extracted"
    assert item["review_state"] == "pending"
    assert item["note_path"] == ""
    assert item["last_error"] == ""
    assert "source_id" not in item
    assert item["source_ref"]
    assert "qqbot:user-authorized" not in (repo.root / item["dir"] / item["file"]).read_text(encoding="utf-8")
    assert ("content_captured" in [event[2] for event in repo.events])


def test_capture_deduplicates_equivalent_urls_without_overwriting_original(repo):
    first = _capture(repo)
    second = _capture(repo, "https://example.com/watch?fbclid=other&id=7&utm_campaign=x")

    assert second["ok"] is True
    assert second["duplicate"] is True
    assert second["item"]["capture_id"] == first["item"]["capture_id"]
    assert second["item"]["original_url"] == first["item"]["original_url"]
    assert len(repo.list_files("待验证")) == 1
    assert "content_duplicate" in [event[2] for event in repo.events]


def test_capture_without_extracted_text_stays_pending(repo):
    result = capture_content(
        repo,
        {
            "source_id": "qqbot:user-authorized",
            "source_url": "https://example.com/pending",
            "original_text": "",
            "title": "稍后提取",
        },
    )

    assert result["ok"] is True
    assert result["item"]["extraction_state"] == "pending"


@pytest.mark.parametrize("missing", ["source_id", "source_url", "original_text", "title"])
def test_capture_rejects_missing_authorized_input(repo, missing):
    body = {
        "source_id": "weixin:user-authorized",
        "source_url": "https://example.com/x",
        "original_text": "正文",
        "title": "标题",
    }
    body.pop(missing)

    result = capture_content(repo, body)

    assert result == {"ok": False, "error": f"{missing} required"}
    assert repo.list_files("待验证") == []


def test_review_archive_only_never_calls_obsidian_sink(repo):
    item = _capture(repo)["item"]

    def forbidden_sink(_item):
        raise AssertionError("archive_only must not call sink")

    result = review_content(repo, item["dir"], item["file"], "archive_only", sink=forbidden_sink)

    assert result["ok"] is True
    assert result["item"]["review_state"] == "archived"
    assert result["item"]["dir"] == "已处理"
    assert not (repo.root / "待验证" / item["file"]).exists()
    assert (repo.root / "已处理" / result["item"]["file"]).exists()
    assert result["item"]["note_path"] == ""
    assert "content_archived" in [event[2] for event in repo.events]


def test_review_sink_rejects_synchronous_success_without_agent_queue(repo):
    item = _capture(repo)["item"]

    result = review_content(
        repo,
        item["dir"],
        item["file"],
        "sink_to_obsidian",
        sink=lambda captured: {"ok": True, "note_path": "Inbox/学习资料.md"},
    )

    assert result["ok"] is False
    assert result["retryable"] is True
    assert result["item"]["review_state"] == "sink_failed"
    assert result["item"]["note_path"] == ""
    assert "must queue an Agent task" in result["item"]["last_error"]
    assert "content_sunk" not in [event[2] for event in repo.events]


def test_review_sink_queue_never_claims_note_before_agent_receipt(repo):
    item = _capture(repo)["item"]

    result = review_content(
        repo,
        item["dir"],
        item["file"],
        "sink_to_obsidian",
        sink=lambda captured: {
            "ok": True,
            "status": "queued",
            "task_id": "WB-A1B2C3D4",
            "task_dir": "任务",
            "task_file": "摄入-学习资料.md",
            "task_path": "/example-vault/任务/摄入-学习资料.md",
        },
    )

    assert result["ok"] is True
    assert result["item"]["review_state"] == "sink_queued"
    assert result["item"]["note_path"] == ""
    assert result["item"]["sink_task_id"] == "WB-A1B2C3D4"
    assert "content_sink_queued" in [event[2] for event in repo.events]


def test_agent_receipt_is_bound_to_queued_task_and_archives_content(repo):
    item = _capture(repo)["item"]
    queued = review_content(
        repo,
        item["dir"],
        item["file"],
        "sink_to_obsidian",
        sink=lambda captured: {
            "ok": True,
            "status": "queued",
            "task_id": "WB-A1B2C3D4",
            "task_dir": "任务",
            "task_file": "摄入-学习资料.md",
            "task_path": "/example-vault/任务/摄入-学习资料.md",
        },
    )["item"]

    wrong = content_capture_module.complete_content_sink(
        repo, queued["capture_id"], "WB-WRONG000", note_path="AI工具/学习资料.md"
    )
    done = content_capture_module.complete_content_sink(
        repo, queued["capture_id"], queued["sink_task_id"], note_path="AI工具/学习资料.md"
    )

    assert wrong == {"ok": False, "error": "sink task mismatch"}
    assert done["ok"] is True
    assert done["item"]["review_state"] == "sunk"
    assert done["item"]["note_path"] == "AI工具/学习资料.md"
    assert done["item"]["dir"] == "已处理"
    assert not (repo.root / "待验证" / item["file"]).exists()
    assert (repo.root / "已处理" / item["file"]).exists()


def test_review_sink_failure_is_retryable_and_never_fakes_note_path(repo):
    item = _capture(repo)["item"]

    def failed_sink(_item):
        raise RuntimeError("Obsidian unavailable")

    result = review_content(
        repo, item["dir"], item["file"], "sink_to_obsidian", sink=failed_sink
    )

    assert result["ok"] is False
    assert result["retryable"] is True
    assert result["item"]["review_state"] == "sink_failed"
    assert result["item"]["note_path"] == ""
    assert result["item"]["last_error"] == "Obsidian unavailable"
    assert "content_sink_failed" in [event[2] for event in repo.events]


def test_get_content_item_supports_capture_id(repo):
    captured = _capture(repo)["item"]

    result = get_content_item(repo, capture_id=captured["capture_id"])

    assert result["ok"] is True
    assert result["item"]["canonical_url"] == "https://example.com/watch?id=7"
