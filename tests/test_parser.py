import json
import os
from unittest.mock import MagicMock, patch

import pytest
from conftest import make_doc_response
from googleapiclient.errors import HttpError

import core.parser as prs
from core.google_docs import parse_entries, prepend_text


class TestExtractTags:
    def test_basic(self):
        assert prs.extract_tags("hello #world") == ["world"]

    def test_multiple(self):
        result = prs.extract_tags("#meeting #project_x #urgent")
        assert result == ["meeting", "project_x", "urgent"]

    def test_no_tags(self):
        assert prs.extract_tags("plain text without tags") == []

    def test_empty_string(self):
        assert prs.extract_tags("") == []

    def test_lowercase(self):
        assert prs.extract_tags("#Meeting") == ["meeting"]
        assert prs.extract_tags("#PROJECT") == ["project"]

    def test_inline_tags(self):
        result = prs.extract_tags("Met with team #meeting about #project_x")
        assert result == ["meeting", "project_x"]


class TestTagsIndex:
    def test_load_missing(self, tmp_tags_index_path):
        if os.path.exists(tmp_tags_index_path):
            os.unlink(tmp_tags_index_path)
        assert prs.load_tags_index() == {}

    def test_save_and_load(self, tmp_tags_index_path):
        index = {"test": [{"ts": "[01/01/26]", "doc_id": "d1", "preview": "hello"}]}
        prs.save_tags_index(index)
        loaded = prs.load_tags_index()
        assert loaded == index

    def test_overwrite(self, tmp_tags_index_path):
        prs.save_tags_index({"a": [{"ts": "t1", "doc_id": "d1", "preview": "p1"}]})
        prs.save_tags_index({"b": [{"ts": "t2", "doc_id": "d2", "preview": "p2"}]})
        loaded = prs.load_tags_index()
        assert "a" not in loaded
        assert "b" in loaded


class TestIndexNote:
    def test_indexes_tag(self, tmp_tags_index_path):
        prs.index_note("Some text #urgent", "[01/01/26]", "doc_1", "Some text #urgent")
        index = prs.load_tags_index()
        assert "urgent" in index
        assert len(index["urgent"]) == 1
        assert index["urgent"][0]["doc_id"] == "doc_1"

    def test_multiple_tags(self, tmp_tags_index_path):
        prs.index_note("#work #meeting notes", "[01/01/26]", "doc_1", "preview")
        index = prs.load_tags_index()
        assert "work" in index
        assert "meeting" in index
        assert len(index["work"]) == 1
        assert len(index["meeting"]) == 1

    def test_appends_to_existing(self, tmp_tags_index_path):
        prs.index_note("#bug first", "[01/01/26]", "doc_1", "first")
        prs.index_note("#bug second", "[01/02/26]", "doc_1", "second")
        index = prs.load_tags_index()
        assert len(index["bug"]) == 2

    def test_no_tags_does_nothing(self, tmp_tags_index_path):
        prs.index_note("plain text", "[01/01/26]", "doc_1", "plain")
        assert prs.load_tags_index() == {}

    def test_preview_truncated(self, tmp_tags_index_path):
        long_text = "x" * 100
        prs.index_note(f"#{long_text}", "[01/01/26]", "doc_1", long_text)
        index = prs.load_tags_index()
        assert len(index[long_text.lower()][0]["preview"]) <= 80

    def test_dedup_same_entry(self, tmp_tags_index_path):
        prs.index_note("#bug same", "[01/01/26]", "doc_1", "same")
        prs.index_note("#bug same", "[01/01/26]", "doc_1", "same")
        index = prs.load_tags_index()
        assert len(index["bug"]) == 1

    def test_dedup_allows_different_ts(self, tmp_tags_index_path):
        prs.index_note("#bug note", "[01/01/26]", "doc_1", "note")
        prs.index_note("#bug note", "[01/02/26]", "doc_1", "note")
        index = prs.load_tags_index()
        assert len(index["bug"]) == 2


class TestParseEntries:
    def test_single_valid_entry(self):
        text = "[06/17/26] (14:30)| Meeting notes"
        doc = make_doc_response(text)
        entries = parse_entries(doc, count=5)
        assert len(entries) == 1
        ts, body = entries[0]
        assert ts == "[06/17/26] (14:30)|"
        assert body == "Meeting notes"

    def test_multiple_entries_count_respected(self):
        text = (
            "[06/17/26] (14:30)| First note\n\n"
            "[06/17/26] (15:00)| Second note\n\n"
            "[06/17/26] (15:30)| Third note"
        )
        doc = make_doc_response(text)
        entries = parse_entries(doc, count=2)
        assert len(entries) == 2
        assert entries[0][1] == "First note"
        assert entries[1][1] == "Second note"

    def test_multiple_entries_less_than_count(self):
        text = "[06/17/26] (14:30)| Only one"
        doc = make_doc_response(text)
        entries = parse_entries(doc, count=5)
        assert len(entries) == 1

    def test_no_timestamped_entries(self):
        text = "Plain text without any timestamp markers"
        doc = make_doc_response(text)
        entries = parse_entries(doc)
        assert entries == []

    def test_empty_doc(self):
        doc = {"body": {"content": []}}
        entries = parse_entries(doc)
        assert entries == []

    def test_malformed_content_does_not_match(self):
        text = "[06/17/26} (14:30)| Wrong bracket"
        doc = make_doc_response(text)
        entries = parse_entries(doc)
        assert entries == []

    def test_multiline_body_preserved(self):
        text = "[06/17/26] (14:30)| Line one\nLine two\nLine three"
        doc = make_doc_response(text)
        entries = parse_entries(doc, count=5)
        assert len(entries) == 1
        _, body = entries[0]
        assert body == "Line one\nLine two\nLine three"

    def test_leading_text_before_first_entry(self):
        text = "Garbage header\n\n[06/17/26] (14:30)| First real note"
        doc = make_doc_response(text)
        entries = parse_entries(doc, count=5)
        assert len(entries) == 1
        _, body = entries[0]
        assert body == "First real note"


class TestParseEntriesDatesInBody:
    """B5: only a full header at the start of a line starts a new entry."""

    def test_bare_date_in_body_stays_in_note(self):
        text = "[06/17/26] (14:30)| Due [01/02/03] then #review\n\n[06/16/26] (09:00)| Older"
        entries = parse_entries(make_doc_response(text), count=5)
        assert entries == [
            ("[06/17/26] (14:30)|", "Due [01/02/03] then #review"),
            ("[06/16/26] (09:00)|", "Older"),
        ]

    def test_full_header_mid_line_stays_in_note(self):
        text = "[06/17/26] (14:30)| As noted in [06/10/26] (08:00)| last week #x"
        entries = parse_entries(make_doc_response(text), count=5)
        assert entries == [("[06/17/26] (14:30)|", "As noted in [06/10/26] (08:00)| last week #x")]

    def test_date_at_start_of_body_line_without_time(self):
        text = "[06/17/26] (14:30)| Plan\n[07/01/26] kickoff #launch"
        entries = parse_entries(make_doc_response(text), count=5)
        assert entries == [("[06/17/26] (14:30)|", "Plan\n[07/01/26] kickoff #launch")]

    def test_count_none_returns_all(self):
        text = "\n\n".join(f"[06/{d:02d}/26] (10:00)| note {d}" for d in range(1, 8))
        assert len(parse_entries(make_doc_response(text), count=None)) == 7


class TestPrependText:
    def test_returns_true_on_success(self, mock_service):
        result = prepend_text(mock_service, "doc_1", "test note")
        assert result is True

    def test_returns_false_on_api_error(self):
        failing_service = MagicMock()
        failing_service.documents().batchUpdate().execute.side_effect = (
            Exception("API error")
        )
        result = prepend_text(failing_service, "doc_1", "test note")
        assert result is False

    def test_retries_on_429_then_succeeds(self):
        service = MagicMock()
        responses = [
            HttpError(MagicMock(status=429), b"rate limit"),
            HttpError(MagicMock(status=429), b"rate limit again"),
            MagicMock(),
        ]
        service.documents().batchUpdate().execute.side_effect = responses
        with patch('core.google_docs.time.sleep') as mock_sleep:
            result = prepend_text(service, "doc_1", "test note")
        assert result is True
        assert mock_sleep.call_count == 2

    def test_retries_on_503_then_succeeds(self):
        service = MagicMock()
        responses = [
            HttpError(MagicMock(status=503), b"unavailable"),
            MagicMock(),
        ]
        service.documents().batchUpdate().execute.side_effect = responses
        with patch('core.google_docs.time.sleep'):
            result = prepend_text(service, "doc_1", "test note")
        assert result is True

    def test_returns_false_after_max_retries(self):
        service = MagicMock()
        service.documents().batchUpdate().execute.side_effect = (
            HttpError(MagicMock(status=503), b"still down")
        )
        with patch('core.google_docs.time.sleep'):
            result = prepend_text(service, "doc_1", "test note")
        assert result is False

    def test_does_not_retry_non_transient_error(self):
        service = MagicMock()
        service.documents().batchUpdate().execute.side_effect = (
            HttpError(MagicMock(status=403), b"forbidden")
        )
        with patch('core.google_docs.time.sleep') as mock_sleep:
            result = prepend_text(service, "doc_1", "test note")
        assert result is False
        assert mock_sleep.call_count == 0

    def test_retry_on_connection_error(self):
        service = MagicMock()
        service.documents().batchUpdate().execute.side_effect = [
            ConnectionError("network down"),
            MagicMock(),
        ]
        with patch('core.google_docs.time.sleep'):
            result = prepend_text(service, "doc_1", "test note")
        assert result is True

    @pytest.mark.parametrize("error", [
        __import__('httplib2').ServerNotFoundError("Unable to find the server"),
        OSError(101, "Network is unreachable"),
        OSError(113, "No route to host"),
    ])
    def test_clearly_offline_errors_fail_fast(self, error):
        """B9 (decided: fail fast): no DNS / no route means the network is down, so the
        note is queued at once instead of after the backoff."""
        service = MagicMock()
        service.documents().batchUpdate().execute.side_effect = error
        with patch('core.google_docs.time.sleep') as mock_sleep:
            result = prepend_text(service, "doc_1", "test note")
        assert result is False
        assert mock_sleep.call_count == 0
        assert service.documents().batchUpdate().execute.call_count == 1

    def test_exponential_backoff_delays(self):
        service = MagicMock()
        service.documents().batchUpdate().execute.side_effect = (
            HttpError(MagicMock(status=503), b"busy")
        )
        with patch('core.google_docs.time.sleep') as mock_sleep:
            prepend_text(service, "doc_1", "test note")
        # 3 attempts, 2 sleeps: 1 s + 2 s (README used to say 1/2/4 s, ~7 s).
        assert [c.args[0] for c in mock_sleep.call_args_list] == [1, 2]


class TestSearchCache:
    def test_returns_empty_when_no_match(self):
        cache = [{"ts": "t1", "text": "hello world", "doc_id": "d1"}]
        result = prs.search_cache(cache, "d1", "nope")
        assert result == []

    def test_returns_matching_entries(self):
        cache = [
            {"ts": "t1", "text": "hello world", "doc_id": "d1"},
            {"ts": "t2", "text": "goodbye world", "doc_id": "d1"},
        ]
        result = prs.search_cache(cache, "d1", "hello")
        assert len(result) == 1
        assert result[0]["ts"] == "t1"

    def test_case_insensitive(self):
        cache = [{"ts": "t1", "text": "Hello World", "doc_id": "d1"}]
        result = prs.search_cache(cache, "d1", "hello")
        assert len(result) == 1

    def test_respects_doc_id(self):
        cache = [
            {"ts": "t1", "text": "hello", "doc_id": "d1"},
            {"ts": "t2", "text": "hello", "doc_id": "d2"},
        ]
        result = prs.search_cache(cache, "d1", "hello")
        assert len(result) == 1
        assert result[0]["doc_id"] == "d1"

    def test_partial_word_match(self):
        cache = [{"ts": "t1", "text": "hello there", "doc_id": "d1"}]
        result = prs.search_cache(cache, "d1", "ello")
        assert len(result) == 1

    def test_multi_word_keyword(self):
        cache = [{"ts": "t1", "text": "hello world today", "doc_id": "d1"}]
        result = prs.search_cache(cache, "d1", "world today")
        assert len(result) == 1

    def test_empty_cache(self):
        result = prs.search_cache([], "d1", "hello")
        assert result == []


class TestFilterTagEntriesByDate:
    def test_no_filters_returns_all(self):
        entries = [{"ts": "[06/01/26] (10:00)|", "doc_id": "d1", "preview": "a"}]
        result = prs.filter_tag_entries_by_date(entries)
        assert len(result) == 1

    def test_since_filters_older(self):
        entries = [
            {"ts": "[05/01/26] (10:00)|", "doc_id": "d1", "preview": "old"},
            {"ts": "[06/15/26] (10:00)|", "doc_id": "d1", "preview": "new"},
        ]
        result = prs.filter_tag_entries_by_date(entries, since="06/01/26")
        assert len(result) == 1
        assert result[0]["preview"] == "new"

    def test_until_filters_newer(self):
        entries = [
            {"ts": "[05/01/26] (10:00)|", "doc_id": "d1", "preview": "old"},
            {"ts": "[06/15/26] (10:00)|", "doc_id": "d1", "preview": "new"},
        ]
        result = prs.filter_tag_entries_by_date(entries, until="06/01/26")
        assert len(result) == 1
        assert result[0]["preview"] == "old"

    def test_both_since_and_until(self):
        entries = [
            {"ts": "[04/01/26] (10:00)|", "doc_id": "d1", "preview": "too old"},
            {"ts": "[05/15/26] (10:00)|", "doc_id": "d1", "preview": "just right"},
            {"ts": "[06/15/26] (10:00)|", "doc_id": "d1", "preview": "too new"},
        ]
        result = prs.filter_tag_entries_by_date(entries, since="05/01/26", until="06/01/26")
        assert len(result) == 1
        assert result[0]["preview"] == "just right"

    def test_empty_entries(self):
        result = prs.filter_tag_entries_by_date([], since="06/01/26")
        assert result == []

    def test_malformed_entry_ts_is_skipped(self, capsys):
        """Entries with corrupt timestamps are skipped, not crashes (Fix 5)."""
        entries = [
            {"ts": "BADTS", "doc_id": "d1", "preview": "corrupt"},
            {"ts": "[06/15/26] (10:00)|", "doc_id": "d1", "preview": "valid"},
        ]
        result = prs.filter_tag_entries_by_date(entries, since="06/01/26")
        assert len(result) == 1
        assert result[0]["preview"] == "valid"
        assert "Warning" in capsys.readouterr().err

    def test_malformed_entry_ts_skipped_no_crash_empty_ts(self, capsys):
        """Entry with empty ts does not raise."""
        entries = [{"ts": "", "doc_id": "d1", "preview": "no ts"}]
        result = prs.filter_tag_entries_by_date(entries, since="06/01/26")
        assert result == []

    def test_invalid_since_filter_returns_all(self, capsys):
        """Malformed --since date string falls back to returning all entries."""
        entries = [{"ts": "[06/15/26] (10:00)|", "doc_id": "d1", "preview": "ok"}]
        result = prs.filter_tag_entries_by_date(entries, since="not-a-date")
        assert len(result) == 1
        assert "Warning" in capsys.readouterr().err


class TestParseDateFlags:
    def test_no_flags(self):
        rest, since, until = prs.parse_date_flags(["meeting"])
        assert rest == ["meeting"]
        assert since is None
        assert until is None

    def test_since_flag(self):
        rest, since, until = prs.parse_date_flags(["meeting", "--since", "06/01/26"])
        assert rest == ["meeting"]
        assert since == "06/01/26"
        assert until is None

    def test_until_flag(self):
        rest, since, until = prs.parse_date_flags(["meeting", "--until", "06/15/26"])
        assert rest == ["meeting"]
        assert until == "06/15/26"

    def test_both_flags(self):
        rest, since, until = prs.parse_date_flags(
            ["meeting", "--since", "06/01/26", "--until", "06/15/26"]
        )
        assert rest == ["meeting"]
        assert since == "06/01/26"
        assert until == "06/15/26"


class TestPendingQueue:
    def test_empty_queue(self, tmp_pending_path):
        assert prs.count_pending() == 0
        assert prs.load_pending_notes() == []

    def test_queue_note(self, tmp_pending_path):
        prs.queue_note("test note", "doc_1", "[06/17/26] (14:30)|")
        assert prs.count_pending() == 1
        notes = prs.load_pending_notes()
        assert notes[0]["text"] == "test note"
        assert notes[0]["doc_id"] == "doc_1"

    def test_multiple_queued_notes(self, tmp_pending_path):
        prs.queue_note("first", "doc_1", "t1")
        prs.queue_note("second", "doc_1", "t2")
        assert prs.count_pending() == 2

    def test_save_pending_removes_file_when_empty(self, tmp_pending_path):
        prs.queue_note("test", "doc_1", "t1")
        prs.save_pending_notes([])
        assert not os.path.exists(tmp_pending_path)
        assert prs.count_pending() == 0

    def test_flush_empty_queue(self, tmp_pending_path, mock_service):
        result = prs.flush_pending_notes(mock_service)
        assert result == []


class TestFlushOrder:
    """B1: flush writes oldest first and stops per doc at the first failure."""

    def test_returns_sent_entries_oldest_first(self, tmp_pending_path, tmp_tags_index_path):
        from conftest import RecordingService
        prs.queue_note("first", "doc_1", "t1")
        prs.queue_note("second", "doc_1", "t2")
        service = RecordingService()
        sent = prs.flush_pending_notes(service)
        assert [e["text"] for e in sent] == ["first", "second"]
        assert service.calls == [("doc_1", "t1 first"), ("doc_1", "t2 second")]
        assert prs.count_pending() == 0

    def test_stops_at_first_failure_per_doc(self, tmp_pending_path, tmp_tags_index_path, monkeypatch):
        from conftest import RecordingService
        monkeypatch.setattr('core.google_docs.time.sleep', lambda s: None)
        prs.queue_note("a1", "doc_a", "t1")
        prs.queue_note("b1", "doc_b", "t2")
        prs.queue_note("a2", "doc_a", "t3")
        service = RecordingService(failing={"doc_a"})
        sent = prs.flush_pending_notes(service)
        assert [e["text"] for e in sent] == ["b1"]
        # a2 was never tried, so the failing doc cost one retry cycle, not two.
        assert service.calls == [("doc_b", "t2 b1")]
        assert [e["text"] for e in prs.load_pending_notes()] == ["a1", "a2"]

    def test_count_pending_per_doc(self, tmp_pending_path):
        prs.queue_note("a1", "doc_a", "t1")
        prs.queue_note("b1", "doc_b", "t2")
        prs.queue_note("a2", "doc_a", "t3")
        assert prs.count_pending() == 3
        assert prs.count_pending("doc_a") == 2
        assert prs.count_pending("doc_c") == 0


class TestFlushIndexesTags:
    """B2: notes written offline get their #tags indexed once flushed."""

    def test_flushed_note_is_indexed_with_queued_timestamp(self, tmp_pending_path, tmp_tags_index_path):
        from conftest import RecordingService
        prs.queue_note("offline #work note", "doc_1", "[10/23/26] (09:00)|")
        assert len(prs.flush_pending_notes(RecordingService())) == 1
        entries = prs.load_tags_index()["work"]
        assert entries == [{"ts": "[10/23/26] (09:00)|", "doc_id": "doc_1", "preview": "offline #work note"}]

    def test_failed_flush_is_not_indexed(self, tmp_pending_path, tmp_tags_index_path, monkeypatch):
        from conftest import RecordingService
        monkeypatch.setattr('core.google_docs.time.sleep', lambda s: None)
        prs.queue_note("offline #work note", "doc_1", "[10/23/26] (09:00)|")
        assert prs.flush_pending_notes(RecordingService(failing={"doc_1"})) == []
        assert prs.load_tags_index() == {}
        assert prs.count_pending() == 1

    def test_reindexing_same_note_does_not_duplicate(self, tmp_pending_path, tmp_tags_index_path):
        from conftest import RecordingService
        prs.index_note("offline #work note", "[10/23/26] (09:00)|", "doc_1", "offline #work note")
        prs.queue_note("offline #work note", "doc_1", "[10/23/26] (09:00)|")
        prs.flush_pending_notes(RecordingService())
        assert len(prs.load_tags_index()["work"]) == 1


class TestLoadTagsIndexCorrupt:
    """load_tags_index() must handle corrupt JSON gracefully (Fix 2)."""

    def test_corrupt_json_returns_empty(self, tmp_tags_index_path):
        with open(tmp_tags_index_path, 'w') as f:
            f.write("{not valid json!!!")
        result = prs.load_tags_index()
        assert result == {}

    def test_corrupt_json_prints_warning(self, tmp_tags_index_path, capsys):
        with open(tmp_tags_index_path, 'w') as f:
            f.write("}{broken")
        prs.load_tags_index()
        assert "Warning" in capsys.readouterr().err

    def test_empty_file_returns_empty(self, tmp_tags_index_path):
        with open(tmp_tags_index_path, 'w') as f:
            f.write("")
        assert prs.load_tags_index() == {}

    def test_valid_file_still_loads(self, tmp_tags_index_path):
        prs.save_tags_index({"bug": [{"ts": "t1", "doc_id": "d1", "preview": "p"}]})
        result = prs.load_tags_index()
        assert "bug" in result


class TestLoadPendingNotesCorrupt:
    """load_pending_notes() must handle corrupt JSON gracefully (Fix 2)."""

    def test_corrupt_json_returns_empty(self, tmp_pending_path):
        with open(tmp_pending_path, 'w') as f:
            f.write("[not valid json!!!")
        result = prs.load_pending_notes()
        assert result == []

    def test_corrupt_json_prints_warning(self, tmp_pending_path, capsys):
        with open(tmp_pending_path, 'w') as f:
            f.write("][broken")
        prs.load_pending_notes()
        assert "Warning" in capsys.readouterr().err

    def test_empty_file_returns_empty(self, tmp_pending_path):
        with open(tmp_pending_path, 'w') as f:
            f.write("")
        assert prs.load_pending_notes() == []

    def test_valid_file_still_loads(self, tmp_pending_path):
        prs.queue_note("hello", "doc_1", "t1")
        result = prs.load_pending_notes()
        assert len(result) == 1
        assert result[0]["text"] == "hello"


class TestReindexDoc:
    """F4: rebuild one doc's tag entries from the doc text."""

    DOC = (
        "[06/18/26] (10:00)| Newest #standup with Sam\n\n"
        "[06/17/26] (09:00)| Untagged note\n\n"
        "[06/16/26] (08:00)| Oldest #standup #design\n"
    )

    @pytest.fixture
    def index_path(self, tmp_path, monkeypatch):
        path = tmp_path / 'tags_index.json'
        monkeypatch.setattr(prs, 'TAGS_INDEX_PATH', str(path))
        return path

    def _service(self, text=None, error=None):
        service = MagicMock()
        execute = service.documents.return_value.get.return_value.execute
        if error:
            execute.side_effect = error
        else:
            execute.return_value = make_doc_response(text)
        return service

    def _write(self, path, index):
        path.write_text(json.dumps(index))

    def test_rebuilds_tags_oldest_first(self, index_path):
        result = prs.reindex_doc(self._service(self.DOC), "doc_a")
        index = json.loads(index_path.read_text())
        assert [e["ts"] for e in index["standup"]] == ["[06/16/26] (08:00)|", "[06/18/26] (10:00)|"]
        assert index["design"] == [{"ts": "[06/16/26] (08:00)|", "doc_id": "doc_a",
                                    "preview": "Oldest #standup #design"}]
        assert result == prs.ReindexResult("reindexed", notes=3, tagged_notes=2, tags=2,
                                           entries_before=0, entries_after=3)

    def test_other_docs_untouched(self, index_path):
        other = {"ts": "[01/01/26] (00:00)|", "doc_id": "doc_b", "preview": "elsewhere"}
        self._write(index_path, {"standup": [other], "solo": [other]})
        prs.reindex_doc(self._service(self.DOC), "doc_a")
        index = json.loads(index_path.read_text())
        assert index["solo"] == [other]
        assert index["standup"][0] == other
        assert len(index["standup"]) == 3

    def test_stale_entries_removed(self, index_path):
        stale = {"ts": "[05/01/26] (00:00)|", "doc_id": "doc_a", "preview": "deleted note #gone"}
        self._write(index_path, {"gone": [stale]})
        result = prs.reindex_doc(self._service(self.DOC), "doc_a")
        index = json.loads(index_path.read_text())
        assert "gone" not in index
        assert result.entries_before == 1 and result.entries_after == 3

    def test_untagged_doc_clears_its_entries(self, index_path):
        old = {"ts": "[05/01/26] (00:00)|", "doc_id": "doc_a", "preview": "x #old"}
        self._write(index_path, {"old": [old]})
        result = prs.reindex_doc(self._service("[06/18/26] (10:00)| no tags here\n"), "doc_a")
        assert json.loads(index_path.read_text()) == {}
        assert result.tagged_notes == 0 and result.entries_after == 0

    def test_backup_written(self, index_path):
        original = {"keep": [{"ts": "[01/01/26] (00:00)|", "doc_id": "doc_a", "preview": "#keep"}]}
        self._write(index_path, original)
        prs.reindex_doc(self._service(self.DOC), "doc_a")
        assert json.loads((index_path.parent / 'tags_index.json.bak').read_text()) == original

    def test_no_backup_when_no_index_yet(self, index_path):
        prs.reindex_doc(self._service(self.DOC), "doc_a")
        assert not (index_path.parent / 'tags_index.json.bak').exists()

    def test_fetch_error_leaves_index_alone(self, index_path, monkeypatch):
        monkeypatch.setattr('core.google_docs.time.sleep', lambda s: None)  # skip retry backoff
        original = {"keep": [{"ts": "[01/01/26] (00:00)|", "doc_id": "doc_a", "preview": "#keep"}]}
        self._write(index_path, original)
        with pytest.raises(ConnectionError):
            prs.reindex_doc(self._service(error=ConnectionError("offline")), "doc_a")
        assert json.loads(index_path.read_text()) == original
        assert not (index_path.parent / 'tags_index.json.bak').exists()

    def test_zero_notes_leaves_index_alone(self, index_path):
        original = {"keep": [{"ts": "[01/01/26] (00:00)|", "doc_id": "doc_a", "preview": "#keep"}]}
        self._write(index_path, original)
        result = prs.reindex_doc(self._service("Some doc in another format #keep"), "doc_a")
        assert result.status == "no_notes"
        assert result.entries_before == 1
        assert json.loads(index_path.read_text()) == original

    def test_date_in_body_keeps_later_tags(self, index_path):
        """B5 + F4: tags after a date in the body are still indexed."""
        prs.reindex_doc(self._service("[06/18/26] (10:00)| Due [07/01/26] then #review\n"), "doc_a")
        assert "review" in json.loads(index_path.read_text())


class TestQueueErrors:
    """F6: queued entries remember why they failed; permanent failures wait for /flush."""

    @pytest.fixture(autouse=True)
    def _paths(self, tmp_path, monkeypatch):
        monkeypatch.setattr(prs, 'PENDING_PATH', str(tmp_path / 'pending_queue.json'))
        monkeypatch.setattr(prs, 'TAGS_INDEX_PATH', str(tmp_path / 'tags_index.json'))
        monkeypatch.setattr('core.google_docs.time.sleep', lambda s: None)

    def _fail(self, kind="permanent", message="document not found (404)"):
        from core.google_docs import WriteFailure
        return WriteFailure(kind, message)

    def _attempts(self, monkeypatch, results):
        """Patch try_prepend: record (doc_id, text) and return results[doc_id] (default success)."""
        attempts = []

        def fake(service, doc_id, text):
            attempts.append((doc_id, text))
            return results.get(doc_id)
        monkeypatch.setattr('core.google_docs.try_prepend', fake)
        return attempts

    def test_queue_note_stores_error(self):
        prs.queue_note("n", "doc_a", "t1", self._fail())
        assert prs.load_pending_notes()[0]["error"] == {"kind": "permanent", "message": "document not found (404)"}

    def test_old_entries_without_error_load(self):
        prs.save_pending_notes([{"text": "old", "doc_id": "doc_a", "ts": "t0"}])
        assert prs.entry_failure(prs.load_pending_notes()[0]) is None
        assert prs.first_pending_failure("doc_a") is None

    def test_auto_flush_skips_permanent_head_but_flushes_others(self, monkeypatch):
        prs.queue_note("stuck", "doc_a", "t1", self._fail())
        prs.queue_note("behind", "doc_a", "t2")
        prs.queue_note("fine", "doc_b", "t3", self._fail("transient", "offline"))
        attempts = self._attempts(monkeypatch, {})
        sent = prs.flush_pending_notes(MagicMock())
        assert attempts == [("doc_b", "t3 fine")]
        assert [e["text"] for e in sent] == ["fine"]
        assert [e["text"] for e in prs.load_pending_notes()] == ["stuck", "behind"]

    def test_explicit_flush_retries_permanent(self, monkeypatch):
        prs.queue_note("stuck", "doc_a", "t1", self._fail())
        attempts = self._attempts(monkeypatch, {})
        sent = prs.flush_pending_notes(MagicMock(), include_permanent=True)
        assert attempts == [("doc_a", "t1 stuck")]
        assert len(sent) == 1 and prs.load_pending_notes() == []

    @pytest.mark.parametrize("kind", ["auth", "transient"])
    def test_auth_and_transient_retried_automatically(self, monkeypatch, kind):
        prs.queue_note("n", "doc_a", "t1", self._fail(kind, "x"))
        attempts = self._attempts(monkeypatch, {})
        prs.flush_pending_notes(MagicMock())
        assert attempts == [("doc_a", "t1 n")]

    def test_failed_flush_updates_stored_error(self, monkeypatch):
        prs.queue_note("n", "doc_a", "t1", self._fail("transient", "offline"))
        self._attempts(monkeypatch, {"doc_a": self._fail("permanent", "no permission (403)")})
        prs.flush_pending_notes(MagicMock())
        assert prs.first_pending_failure("doc_a") == self._fail("permanent", "no permission (403)")

    def test_first_pending_failure_is_oldest_for_doc(self):
        prs.queue_note("x", "doc_b", "t0", self._fail("transient", "offline"))
        prs.queue_note("a1", "doc_a", "t1", self._fail())
        prs.queue_note("a2", "doc_a", "t2")
        assert prs.first_pending_failure("doc_a") == self._fail()


class TestQueueEditing:
    @pytest.fixture(autouse=True)
    def _paths(self, tmp_path, monkeypatch):
        monkeypatch.setattr(prs, 'PENDING_PATH', str(tmp_path / 'pending_queue.json'))
        prs.save_pending_notes([
            {"text": "one", "doc_id": "doc_a", "ts": "t1", "error": {"kind": "permanent", "message": "404"}},
            {"text": "two", "doc_id": "doc_b", "ts": "t2"},
            {"text": "three", "doc_id": "doc_a", "ts": "t3"},
        ])

    def test_drop_returns_entry_and_keeps_order(self):
        assert prs.drop_pending(1)["text"] == "one"
        assert [e["text"] for e in prs.load_pending_notes()] == ["two", "three"]

    def test_drop_last_deletes_file(self):
        for _ in range(3):
            prs.drop_pending(1)
        assert not os.path.exists(prs.PENDING_PATH)

    @pytest.mark.parametrize("position", [0, 4, -1])
    def test_drop_out_of_range(self, position):
        with pytest.raises(IndexError):
            prs.drop_pending(position)
        assert len(prs.load_pending_notes()) == 3

    def test_move_retargets_and_clears_error(self):
        entry = prs.move_pending(1, "doc_c")
        assert entry["doc_id"] == "doc_c" and "error" not in entry
        queue = prs.load_pending_notes()
        assert [(e["text"], e["doc_id"]) for e in queue] == [("one", "doc_c"), ("two", "doc_b"), ("three", "doc_a")]
        assert "error" not in queue[0]

    def test_move_out_of_range(self):
        with pytest.raises(IndexError):
            prs.move_pending(9, "doc_c")
