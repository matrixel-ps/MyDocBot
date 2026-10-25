"""B11: a data file that can't be parsed is moved aside before starting fresh."""
import glob
import json
import os
import stat

import pytest

import core.config as cfg
import core.parser as prs
from core import storage

BAD = b'{"aliases": {"log": "doc_id_1234567890",'   # truncated JSON


def _backups(path):
    return sorted(glob.glob(f"{path}.corrupt-*"))


def _write(path, data):
    with open(path, 'wb') as f:
        f.write(data)


CASES = {
    "config": (lambda: cfg.load_config(), 'tmp_config_path', {"default": "", "aliases": {}}, "Corrupt config"),
    "read config": (lambda: cfg.load_read_config(), 'tmp_read_config_path', {"default": "", "aliases": {}},
                    "Corrupt read config"),
    "pending queue": (lambda: prs.load_pending_notes(), 'tmp_pending_path', [], "Corrupt pending queue"),
    "tags index": (lambda: prs.load_tags_index(), 'tmp_tags_index_path', {}, "Corrupt tags index"),
}


@pytest.mark.parametrize("name", CASES)
def test_corrupt_file_is_moved_aside_with_its_bytes(name, request, capsys):
    load, fixture, empty, label = CASES[name]
    path = request.getfixturevalue(fixture)
    _write(path, BAD)
    assert load() == empty
    backups = _backups(path)
    assert len(backups) == 1
    with open(backups[0], 'rb') as f:
        assert f.read() == BAD
    assert stat.S_IMODE(os.stat(backups[0]).st_mode) == 0o600
    err = capsys.readouterr().err
    assert f"Warning: {label}" in err and backups[0] in err


@pytest.mark.parametrize("name", CASES)
def test_second_load_does_not_warn_or_back_up_again(name, request, capsys):
    load, fixture, empty, _ = CASES[name]
    path = request.getfixturevalue(fixture)
    _write(path, BAD)
    load()
    capsys.readouterr()
    assert load() == empty
    assert capsys.readouterr().err == ""
    assert len(_backups(path)) == 1


@pytest.mark.parametrize("name", ["config", "read config"])
def test_config_is_reset_to_a_fresh_valid_file(name, request):
    load, fixture, empty, _ = CASES[name]
    path = request.getfixturevalue(fixture)
    _write(path, BAD)
    load()
    with open(path) as f:
        assert json.load(f) == empty


@pytest.mark.parametrize("name", ["pending queue", "tags index"])
def test_queue_and_index_file_is_gone_until_next_save(name, request):
    load, fixture, _, _ = CASES[name]
    path = request.getfixturevalue(fixture)
    _write(path, BAD)
    load()
    assert not os.path.exists(path)


def test_invalid_schema_config_is_moved_aside(tmp_config_path, capsys):
    original = json.dumps({"default": 5, "aliases": "not a dict"}).encode()
    _write(tmp_config_path, original)
    cfg.load_config()
    backups = _backups(tmp_config_path)
    assert len(backups) == 1
    with open(backups[0], 'rb') as f:
        assert f.read() == original
    assert backups[0] in capsys.readouterr().err


@pytest.mark.parametrize("name", ["pending queue", "tags index"])
def test_empty_file_is_not_corrupt(name, request, capsys):
    load, fixture, empty, _ = CASES[name]
    path = request.getfixturevalue(fixture)
    _write(path, b"")
    assert load() == empty
    assert _backups(path) == [] and capsys.readouterr().err == ""


def test_two_corruptions_in_the_same_second_keep_both(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, '_stamp', lambda: "20261024-201500")
    path = tmp_path / "x.json"
    for content in (b"first", b"second"):
        path.write_bytes(content)
        storage.quarantine(str(path))
    backups = sorted(glob.glob(f"{path}.corrupt-*"))
    assert [open(b, 'rb').read() for b in backups] == [b"first", b"second"]


def test_read_error_is_not_quarantined(tmp_pending_path, monkeypatch, capsys):
    _write(tmp_pending_path, b'[]')
    real_open = open

    def denied(path, *a, **k):
        if path == tmp_pending_path:
            raise PermissionError(13, "Permission denied")
        return real_open(path, *a, **k)
    monkeypatch.setattr('builtins.open', denied)
    assert prs.load_pending_notes() == []
    assert _backups(tmp_pending_path) == []
    assert os.path.exists(tmp_pending_path)


@pytest.mark.parametrize("load,fixture", [(cfg.load_config, 'tmp_config_path'),
                                          (cfg.load_read_config, 'tmp_read_config_path')])
def test_unreadable_config_is_not_overwritten(load, fixture, request, monkeypatch, capsys):
    """An unreadable config may be fine: don't move it, and don't save over it.
    (Since A6 an atomic save would succeed even where reading failed.)"""
    path = request.getfixturevalue(fixture)
    original = b'{"default": "log", "aliases": {"log": "doc_id_1234567890"}}'
    _write(path, original)
    real_open = open

    def denied(p, *a, **k):
        if p == path and (not a or 'r' in a[0]):
            raise PermissionError(13, "Permission denied")
        return real_open(p, *a, **k)
    monkeypatch.setattr('builtins.open', denied)
    assert load() == {"default": "", "aliases": {}}
    monkeypatch.setattr('builtins.open', real_open)  # not undo(): that would drop the data-dir isolation
    with open(path, 'rb') as f:
        assert f.read() == original
    assert _backups(path) == []
    assert "Can't read" in capsys.readouterr().err
