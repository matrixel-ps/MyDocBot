import os
import json
import tempfile
import core.parser as prs


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
