"""F3: /undo of the last note, against a fake doc that keeps real text, UTF-16
indexes and revision IDs, so the delete range and the revision check are
exercised end to end without Google."""
import json
import os
import stat
from unittest.mock import MagicMock, patch

import pytest
from googleapiclient.errors import HttpError

import main
from core import commands, config, google_docs, notes, undo
from core import parser as prs
from mydocbot_app import MyDocBotApp

DOC = "doc_id_123"
OFFLINE = [ConnectionError("offline")] * 3  # one call's worth: _api_call_with_retry tries 3 times


async def settle(app, pilot):
    """Wait for background Google calls and their UI callbacks (as in test_tui.py)."""
    await app.workers.wait_for_complete()
    await pilot.pause()


def _py_index(text, utf16_index):
    """Python string position of a Docs index (1-based body, UTF-16 units)."""
    units = 1
    for i, ch in enumerate(text):
        if units >= utf16_index:
            return i
        units += google_docs.utf16_len(ch)
    return len(text)


class FakeDoc:
    """A Docs service holding one doc's body text (from index 1). insertText and
    deleteContentRange edit it; every edit bumps the revision; a delete with a stale
    requiredRevisionId gets a 400, like the real API. `fail` holds exceptions to
    raise from the next calls, in order; `edit_before_delete` simulates someone
    editing the doc between the check and the delete."""

    def __init__(self, text="", leading_table=False) -> None:
        self.text = text
        self.rev = 1
        self.leading_table = leading_table
        self.fail: list[Exception] = []
        self.edit_before_delete: str | None = None
        self.deletes: list[dict] = []

    def documents(self):
        return self

    def get(self, documentId=None, fields=None):
        return _Call(self, self._doc)

    def batchUpdate(self, documentId=None, body=None):
        return _Call(self, lambda: self._apply(body))

    def _doc(self):
        content = [{"sectionBreak": {}}]
        index = 1
        if self.leading_table:
            content.append({"startIndex": index, "table": {}})
            index += 1
        for line in self.text.splitlines(keepends=True):
            content.append({"startIndex": index, "paragraph": {"elements": [{"textRun": {"content": line}}]}})
            index += google_docs.utf16_len(line)
        return {"title": "Doc", "revisionId": f"r{self.rev}", "body": {"content": content}}

    def _apply(self, body):
        if self.edit_before_delete is not None:
            self.text = self.edit_before_delete + self.text
            self.rev += 1
            self.edit_before_delete = None
        req = body["requests"][0]
        required = body.get("writeControl", {}).get("requiredRevisionId")
        if required is not None and required != f"r{self.rev}":
            raise HttpError(MagicMock(status=400), b"revision mismatch")
        if "insertText" in req:
            at = _py_index(self.text, req["insertText"]["location"]["index"])
            self.text = self.text[:at] + req["insertText"]["text"] + self.text[at:]
        else:
            rng = req["deleteContentRange"]["range"]
            self.deletes.append({"range": rng, "required": required})
            start, end = _py_index(self.text, rng["startIndex"]), _py_index(self.text, rng["endIndex"])
            self.text = self.text[:start] + self.text[end:]
        self.rev += 1
        return {}


class _Call:
    def __init__(self, doc, fn):
        self.doc, self.fn = doc, fn

    def execute(self):
        if self.doc.fail:
            raise self.doc.fail.pop(0)
        return self.fn()


@pytest.fixture
def isolated(tmp_tags_index_path, tmp_pending_path, monkeypatch):
    monkeypatch.setattr('core.google_docs.time.sleep', lambda s: None)


def _send(service, text, doc_id=DOC):
    result = notes.submit_note(service, doc_id, text)
    assert result.status == "sent"
    return result


# ---- the record ----

def test_sent_note_is_recorded_owner_only(isolated):
    svc = FakeDoc("older\n")
    result = _send(svc, "hello #work")
    record = undo.last_write(DOC)
    assert record == {"ts": result.timestamp, "text": "hello #work", "written": f"{result.timestamp} hello #work\n\n"}
    assert svc.text.startswith(record["written"])
    assert stat.S_IMODE(os.stat(undo.LAST_WRITE_PATH).st_mode) == 0o600


def test_queued_or_rejected_note_keeps_previous_record(isolated):
    svc = FakeDoc()
    _send(svc, "first")
    before = undo.last_write(DOC)
    assert notes.submit_note(svc, DOC, "").status == "rejected"
    svc.fail = list(OFFLINE)
    assert notes.submit_note(svc, DOC, "offline note").status == "queued"
    assert undo.last_write(DOC) == before


def test_record_save_failure_does_not_fail_the_note(isolated, monkeypatch, capsys):
    monkeypatch.setattr(undo, 'record_write', MagicMock(side_effect=OSError("disk full")))
    svc = FakeDoc()
    assert notes.submit_note(svc, DOC, "still sent").status == "sent"
    assert "Couldn't save the undo record" in capsys.readouterr().err


def test_records_are_per_doc(isolated):
    svc = FakeDoc()
    _send(svc, "a", "doc_a")
    _send(svc, "b", "doc_b")
    assert undo.last_write("doc_a")["text"] == "a"
    assert undo.last_write("doc_b")["text"] == "b"


def test_corrupt_record_is_moved_aside(isolated, capsys):
    with open(undo.LAST_WRITE_PATH, "w") as f:
        f.write("{not json")
    assert undo.last_write(DOC) is None
    assert "Corrupt undo record" in capsys.readouterr().err
    assert not os.path.exists(undo.LAST_WRITE_PATH)


# ---- try_undo / undo_last ----

def test_undo_removes_exactly_the_note(isolated):
    svc = FakeDoc("[01/01/26] (09:00)| older note\n\n")
    _send(svc, "oops")
    result = undo.undo_last(svc, DOC)
    assert result.status == "undone"
    assert svc.text == "[01/01/26] (09:00)| older note\n\n"
    assert svc.deletes[0]["required"] is not None
    assert undo.last_write(DOC) is None
    assert undo.undo_last(svc, DOC).status == "nothing"  # one level only


@pytest.mark.parametrize("text", ["emoji 🎉 note", "café crème", "multi\nline\nnote"])
def test_delete_range_counts_utf16_units(isolated, text):
    svc = FakeDoc("keep me\n")
    _send(svc, text)
    assert undo.undo_last(svc, DOC).status == "undone"
    assert svc.text == "keep me\n"


def test_utf16_len():
    assert google_docs.utf16_len("a") == 1
    assert google_docs.utf16_len("é") == 1
    assert google_docs.utf16_len("🎉") == 2


@pytest.mark.parametrize("edit", [
    lambda svc: setattr(svc, "text", "someone else's line\n" + svc.text),  # text added on top
    lambda svc: setattr(svc, "text", svc.text.replace("oops", "oops, fixed")),  # note edited
    lambda svc: setattr(svc, "text", ""),  # doc emptied
])
def test_changed_top_deletes_nothing(isolated, edit):
    svc = FakeDoc("older\n")
    _send(svc, "oops")
    edit(svc)
    before = svc.text
    result = undo.undo_last(svc, DOC)
    assert result.status == "changed"
    assert svc.text == before
    assert svc.deletes == []
    assert undo.last_write(DOC) is None  # can't succeed later, so it's dropped


def test_another_mydocbot_note_on_top_blocks_undo_of_older(isolated):
    """A flushed or other-process note written after the recorded one is on top."""
    svc = FakeDoc()
    _send(svc, "mine")
    record = undo.last_write(DOC)
    svc.text = "[01/02/26] (10:00)| flushed later\n\n" + svc.text
    assert google_docs.try_undo(svc, DOC, record["written"]) == "changed"


def test_text_after_a_leading_table_doesnt_count(isolated):
    svc = FakeDoc("[01/01/26] (09:00)| note\n\n", leading_table=True)
    assert google_docs.try_undo(svc, DOC, "[01/01/26] (09:00)| note\n\n") == "changed"
    assert svc.deletes == []


def test_edit_between_check_and_delete_is_rejected(isolated):
    svc = FakeDoc("older\n")
    _send(svc, "oops")
    svc.edit_before_delete = "sneaky edit\n"
    result = undo.undo_last(svc, DOC)
    assert result.status == "changed"
    assert svc.text.startswith("sneaky edit\n")
    assert "oops" in svc.text  # nothing deleted


def test_failed_delete_keeps_record_for_retry(isolated):
    svc = FakeDoc()
    _send(svc, "oops")
    svc.fail = list(OFFLINE)  # the fetch fails
    result = undo.undo_last(svc, DOC)
    assert result.status == "failed" and result.failure.kind == "transient"
    assert undo.last_write(DOC) is not None
    assert undo.undo_last(svc, DOC).status == "undone"


def test_permanent_delete_error_is_failed_not_changed(isolated, monkeypatch):
    svc = FakeDoc()
    _send(svc, "oops")

    def deny(body):  # the fetch works; the delete gets a 403 (only a 400 is re-checked)
        raise HttpError(MagicMock(status=403), b"no")
    monkeypatch.setattr(svc, "_apply", deny)
    result = undo.undo_last(svc, DOC)
    assert result.status == "failed" and result.failure.kind == "permanent"
    assert undo.last_write(DOC) is not None


def test_queued_notes_block_undo(isolated):
    svc = FakeDoc()
    _send(svc, "sent one")
    prs.queue_note("queued one", DOC, "[01/03/26] (11:00)|")
    result = undo.undo_last(svc, DOC)
    assert result.status == "queued"
    assert "/queue drop" in undo.undo_message(result)
    assert "sent one" in svc.text


def test_undo_removes_only_this_notes_tags(isolated):
    svc = FakeDoc()
    _send(svc, "keep #work")
    result = _send(svc, "oops #work #typo")
    assert undo.undo_last(svc, DOC).status == "undone"
    index = prs.load_tags_index()
    assert "typo" not in index
    assert [e["preview"] for e in index["work"]] == ["keep #work"]
    assert all(e["ts"] != result.timestamp or e["preview"] == "keep #work" for e in index["work"])


# ---- CLI /undo and --undo ----

def test_cli_undo_asks_and_removes(isolated, capsys):
    svc = FakeDoc("older\n")
    _send(svc, "oops")
    with patch('builtins.input', return_value='y') as ask:
        commands.dispatch(svc, {"aliases": {"log": DOC}}, "/undo", "log", DOC)
    assert "oops" in ask.call_args.args[0]
    out = capsys.readouterr().out
    assert "Removed the note" in out and "oops" in out
    assert svc.text == "older\n"


def test_cli_undo_cancel_keeps_note(isolated, capsys):
    svc = FakeDoc()
    _send(svc, "oops")
    with patch('builtins.input', return_value='n'):
        commands.cmd_undo(svc, DOC)
    assert "Canceled." in capsys.readouterr().out
    assert "oops" in svc.text and undo.last_write(DOC) is not None


def test_cli_undo_nothing_doesnt_call_google(isolated, capsys):
    svc = MagicMock()
    commands.cmd_undo(svc, DOC)
    assert "Nothing to undo" in capsys.readouterr().out
    svc.documents.assert_not_called()


def test_help_lists_undo(capsys):
    commands.cmd_help()
    assert "/undo" in capsys.readouterr().out


@pytest.fixture
def one_shot_config(tmp_config_path):
    config.save_config({"default": "log", "aliases": {"log": DOC}})
    return config.load_config()


def test_one_shot_undo_exit_codes(isolated, one_shot_config, monkeypatch):
    monkeypatch.setattr('sys.stdin', None)  # not a terminal: no prompt
    svc = FakeDoc()
    monkeypatch.setattr(main.google_docs, 'get_service', lambda: svc)
    assert main.one_shot_undo(one_shot_config, None) == main.EXIT_ERROR  # nothing yet
    _send(svc, "oops")
    svc.fail = list(OFFLINE)
    assert main.one_shot_undo(one_shot_config, None) == main.EXIT_QUEUED  # offline: try again
    assert main.one_shot_undo(one_shot_config, None) == main.EXIT_SENT
    assert svc.text == ""
    assert main.one_shot_undo(one_shot_config, "nope") == main.EXIT_ERROR


def test_one_shot_undo_skips_sign_in_when_nothing(isolated, one_shot_config, monkeypatch):
    sign_in = MagicMock()
    monkeypatch.setattr(main.google_docs, 'get_service', sign_in)
    assert main.one_shot_undo(one_shot_config, None) == main.EXIT_ERROR
    sign_in.assert_not_called()


def test_undo_flag_rejects_a_note(monkeypatch):
    monkeypatch.setattr('sys.argv', ['mydocbot', '--undo', 'some', 'note'])
    with pytest.raises(SystemExit) as exc:
        main.main()
    assert exc.value.code == 2


# ---- TUI /undo ----

@pytest.mark.asyncio
async def test_tui_undo_drops_note_from_list_and_doc(isolated, tmp_config_path, sample_config):
    config.save_config(sample_config)
    svc = FakeDoc("[01/01/26] (09:00)| older note\n\n")
    with patch('mydocbot_app.google_docs.get_service', return_value=svc):
        app = MyDocBotApp()
    async with app.run_test() as pilot:
        await settle(app, pilot)
        app.query_one("#input-bar").text = "oops #typo"
        app.submit_note()
        await settle(app, pilot)
        assert app.notes_cache[0]["text"] == "oops #typo"
        app.handle_command("/undo")
        await settle(app, pilot)
        assert [n["text"] for n in app.notes_cache] == ["older note"]
        assert svc.text == "[01/01/26] (09:00)| older note\n\n"
        assert "typo" not in app.all_tags
        assert "Removed the note" in str(app.query_one("#status-bar").render())


@pytest.mark.asyncio
async def test_tui_undo_nothing(isolated, tmp_config_path, sample_config):
    config.save_config(sample_config)
    svc = FakeDoc()
    with patch('mydocbot_app.google_docs.get_service', return_value=svc):
        app = MyDocBotApp()
    async with app.run_test() as pilot:
        await settle(app, pilot)
        app.handle_command("/undo")
        await settle(app, pilot)
        assert "Nothing to undo" in str(app.query_one("#status-bar").render())


def test_record_file_is_json_dict(isolated):
    _send(FakeDoc(), "x")
    with open(undo.LAST_WRITE_PATH) as f:
        assert isinstance(json.load(f), dict)
