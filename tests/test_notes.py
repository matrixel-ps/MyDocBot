"""Tests for core.notes.submit_note(), the single write path shared by the CLI
and the read/write TUI."""
import json
from datetime import datetime

from conftest import RecordingService

from core import notes
from core import parser as prs

NOW = datetime(2026, 10, 23, 14, 30)
TS = "[10/23/26] (14:30)|"


def _no_sleep(monkeypatch):
    monkeypatch.setattr('core.google_docs.time.sleep', lambda s: None)


class TestSubmitNote:
    def test_sent_prepends_timestamped_text(self, tmp_pending_path, tmp_tags_index_path):
        service = RecordingService()
        result = notes.submit_note(service, "doc_1", "hello #work", now=NOW)
        assert result.status == "sent"
        assert result.timestamp == TS
        assert service.calls == [("doc_1", f"{TS} hello #work")]

    def test_sent_indexes_tags(self, tmp_pending_path, tmp_tags_index_path):
        notes.submit_note(RecordingService(), "doc_1", "hello #work", now=NOW)
        index = prs.load_tags_index()
        assert index["work"][0]["ts"] == TS
        assert index["work"][0]["doc_id"] == "doc_1"

    def test_queued_when_write_fails(self, tmp_pending_path, tmp_tags_index_path, monkeypatch):
        _no_sleep(monkeypatch)
        service = RecordingService(failing={"doc_1"})
        result = notes.submit_note(service, "doc_1", "offline #work", now=NOW)
        assert result.status == "queued"
        assert result.failure is not None and result.failure.kind == "transient"
        assert prs.load_pending_notes() == [{"text": "offline #work", "doc_id": "doc_1", "ts": TS,
                                             "error": {"kind": "transient",
                                                       "message": result.failure.message}}]
        assert prs.load_tags_index() == {}

    def test_rejects_empty_without_api_call(self, tmp_pending_path, tmp_tags_index_path):
        service = RecordingService()
        result = notes.submit_note(service, "doc_1", "   ", now=NOW)
        assert result.status == "rejected"
        assert result.reason
        assert service.calls == []
        assert prs.load_pending_notes() == []

    def test_rejects_oversized_without_api_call(self, tmp_pending_path, tmp_tags_index_path):
        service = RecordingService()
        result = notes.submit_note(service, "doc_1", "x" * (51 * 1024), now=NOW)
        assert result.status == "rejected"
        assert service.calls == []

    def test_flushes_queued_notes_for_all_docs(self, tmp_pending_path, tmp_tags_index_path):
        """B3: a submit flushes the queue for every doc, not just its own."""
        prs.queue_note("other doc note", "doc_2", "[10/23/26] (09:00)|")
        service = RecordingService()
        result = notes.submit_note(service, "doc_1", "new", now=NOW)
        assert result.status == "sent"
        assert ("doc_2", "[10/23/26] (09:00)| other doc note") in service.calls
        assert prs.load_pending_notes() == []


class TestSubmitOrder:
    """B1: notes reach the doc in the order they were written."""

    def test_queued_notes_written_before_new_note(self, tmp_pending_path, tmp_tags_index_path):
        prs.queue_note("queued 1", "doc_1", "[10/23/26] (10:00)|")
        prs.queue_note("queued 2", "doc_1", "[10/23/26] (10:05)|")
        service = RecordingService()
        result = notes.submit_note(service, "doc_1", "new", now=NOW)
        # Each write goes to the top of the doc, so this call order leaves
        # "new" on top with the queued notes below it, newest first.
        assert service.calls == [
            ("doc_1", "[10/23/26] (10:00)| queued 1"),
            ("doc_1", "[10/23/26] (10:05)| queued 2"),
            ("doc_1", f"{TS} new"),
        ]
        assert result.status == "sent"
        assert [e["text"] for e in result.flushed] == ["queued 1", "queued 2"]
        assert prs.load_pending_notes() == []

    def test_new_note_queued_behind_when_flush_fails(self, tmp_pending_path, tmp_tags_index_path, monkeypatch):
        _no_sleep(monkeypatch)
        prs.queue_note("queued 1", "doc_1", "t1")
        prs.queue_note("queued 2", "doc_1", "t2")
        service = RecordingService(failing={"doc_1"})
        attempts = []
        real_try = notes.google_docs.try_prepend
        monkeypatch.setattr('core.google_docs.try_prepend',
                            lambda s, d, t: attempts.append(t) or real_try(s, d, t))
        result = notes.submit_note(service, "doc_1", "new", now=NOW)
        assert result.status == "queued"
        assert result.queued_behind == 2
        # Only queued #1 was tried: not #2, and not the new note.
        assert attempts == ["t1 queued 1"]
        assert [e["text"] for e in prs.load_pending_notes()] == ["queued 1", "queued 2", "new"]

    def test_failing_other_doc_does_not_block(self, tmp_pending_path, tmp_tags_index_path, monkeypatch):
        _no_sleep(monkeypatch)
        prs.queue_note("stuck", "doc_2", "t1")
        service = RecordingService(failing={"doc_2"})
        result = notes.submit_note(service, "doc_1", "new", now=NOW)
        assert result.status == "sent"
        assert result.queued_behind == 0
        assert service.calls == [("doc_1", f"{TS} new")]
        assert [e["text"] for e in prs.load_pending_notes()] == ["stuck"]


def test_timestamp_format_round_trips_through_queue_file(tmp_pending_path, tmp_tags_index_path, monkeypatch):
    _no_sleep(monkeypatch)
    notes.submit_note(RecordingService(failing={"doc_1"}), "doc_1", "n", now=NOW)
    with open(tmp_pending_path) as f:
        assert json.load(f)[0]["ts"] == TS
