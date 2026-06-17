import os
import json
import tempfile
import core.parser as prs
from unittest.mock import MagicMock, patch
from googleapiclient.errors import HttpError
from core.google_docs import parse_entries, prepend_text
from conftest import make_doc_response


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
        tag_name = long_text.lower()[:80]
        # tag name from re.findall(r'#(\w+)', ...) is the matched group, 
        # not the full text. The preview is truncated to 80.
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

    def test_exponential_backoff_delays(self):
        service = MagicMock()
        service.documents().batchUpdate().execute.side_effect = (
            HttpError(MagicMock(status=503), b"busy")
        )
        with patch('core.google_docs.time.sleep') as mock_sleep:
            prepend_text(service, "doc_1", "test note")
        assert mock_sleep.call_args_list[0][0][0] == 1
        assert mock_sleep.call_args_list[1][0][0] == 2


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
