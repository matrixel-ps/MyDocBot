"""Atomic data-file writes (A6): readers never see an empty or partial file."""
import json
import os
import stat

import pytest

import core.config as cfg
import core.parser as prs
from core import storage


def _mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


class TestWriteJson:
    def test_round_trip_and_trailing_newline(self, tmp_path):
        path = tmp_path / "x.json"
        storage.write_json(str(path), {"a": [1, 2]})
        assert json.loads(path.read_text()) == {"a": [1, 2]}
        assert path.read_text().endswith("}\n")

    def test_new_file_is_owner_only(self, tmp_path):
        path = tmp_path / "x.json"
        storage.write_json(str(path), {})
        assert _mode(path) == 0o600

    def test_replacing_a_world_readable_file_makes_it_owner_only(self, tmp_path):
        path = tmp_path / "x.json"
        path.write_text("{}")
        os.chmod(path, 0o644)
        storage.write_json(str(path), {"b": 1})
        assert _mode(path) == 0o600

    def test_no_temp_file_left_on_success(self, tmp_path):
        storage.write_json(str(tmp_path / "x.json"), {})
        assert os.listdir(tmp_path) == ["x.json"]

    def test_failed_write_keeps_original_and_cleans_up(self, tmp_path):
        path = tmp_path / "x.json"
        path.write_text('{"keep": true}\n')
        with pytest.raises(TypeError):
            storage.write_json(str(path), {"bad": object()})
        assert path.read_text() == '{"keep": true}\n'
        assert os.listdir(tmp_path) == ["x.json"]

    def test_write_text(self, tmp_path):
        path = tmp_path / "token.json"
        storage.write_text(str(path), "secret")
        assert path.read_text() == "secret" and _mode(path) == 0o600


class TestReadersNeverSeeATruncatedFile:
    """A6: a save used to open(path, 'w') first, emptying the file. A reader in
    that window (the CLI and a TUI at once) read it as empty, then saved over
    it: the queue lost every other note, the tag index emptied, and the config
    was reset. The hook reads the file *during* the save."""

    @pytest.fixture
    def reader_during_dump(self, monkeypatch):
        """Read the file at every point a save could expose it: while serialising
        (old code wrote straight into the emptied file) and just before the
        temp file replaces the target (new code)."""
        seen = []
        self.reader = None  # set (arming the hook) only after the test's setup save
        real_dump, real_dumps, real_replace = json.dump, json.dumps, os.replace

        def peek():
            reader, self.reader = self.reader, None  # no re-entry if the reader itself saves
            if reader is not None:
                seen.append(reader())
                self.reader = reader

        def dump(obj, fp, *args, **kwargs):
            peek()
            return real_dump(obj, fp, *args, **kwargs)

        def dumps(obj, *args, **kwargs):
            peek()
            return real_dumps(obj, *args, **kwargs)

        def replace(src, dst):
            peek()
            return real_replace(src, dst)
        monkeypatch.setattr(json, 'dump', dump)
        monkeypatch.setattr(json, 'dumps', dumps)
        monkeypatch.setattr(os, 'replace', replace)
        return seen

    def test_pending_queue(self, tmp_pending_path, reader_during_dump):
        prs.save_pending_notes([{"text": "old", "doc_id": "d", "ts": "t"}])
        self.reader = prs.load_pending_notes
        prs.queue_note("new", "d", "t2")
        assert reader_during_dump  # the hook really ran during the save
        assert all(r == [{"text": "old", "doc_id": "d", "ts": "t"}] for r in reader_during_dump)

    def test_tags_index(self, tmp_tags_index_path, reader_during_dump):
        prs.save_tags_index({"old": [{"ts": "t", "doc_id": "d", "preview": "p"}]})
        self.reader = prs.load_tags_index
        prs.index_note("new #fresh", "t2", "d", "new #fresh")
        assert reader_during_dump
        assert all(list(r) == ["old"] for r in reader_during_dump)

    def test_config(self, tmp_config_path, reader_during_dump, capsys):
        cfg.save_config({"default": "log", "aliases": {"log": "doc_id_1234567890"}})
        self.reader = cfg.load_config
        cfg.save_config({"default": "log", "aliases": {"log": "doc_id_1234567890", "w": "doc_id_0987654321"}})
        assert reader_during_dump
        assert all(r["aliases"] == {"log": "doc_id_1234567890"} for r in reader_during_dump)
        assert "Starting fresh" not in capsys.readouterr().err


@pytest.mark.parametrize("save,path_attr", [
    (lambda: prs.save_tags_index({"t": []}), 'tmp_tags_index_path'),
    (lambda: prs.save_pending_notes([{"text": "n", "doc_id": "d", "ts": "t"}]), 'tmp_pending_path'),
    (lambda: cfg.save_config({"default": "", "aliases": {}}), 'tmp_config_path'),
    (lambda: cfg.save_read_config({"default": "", "aliases": {}}), 'tmp_read_config_path'),
])
def test_every_data_file_is_owner_only(save, path_attr, request):
    path = request.getfixturevalue(path_attr)
    os.chmod(path, 0o644)
    save()
    assert _mode(path) == 0o600
