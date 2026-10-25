"""
Smoke/regression tests for the Textual TUI apps in mydocbot_app.py.

These tests mount MyDocBotApp / ReadOnlyApp headlessly via Textual's
`run_test()` harness, with `google_docs.get_service()` patched to return a
mocked Google Docs service (no real network/OAuth is used).

Regression coverage: `MyDocBotApp.cmd_config` previously had a control-flow
bug where `/config set history_size <n>` was unreachable dead code (an
unconditional `return` after the `show` branch made the `elif` for `set`
unreachable, and would have raised UnboundLocalError on `preview` if the
`if` guard were ever removed). See CHANGELOG.md.
"""
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from conftest import RecordingService, make_doc_response
from textual.widgets import Label

from core import config, google_docs
from core import parser as prs
from mydocbot_app import MyDocBotApp, ReadOnlyApp


async def settle(app, pilot):
    """Wait for background Google calls (A3) and let their UI callbacks run."""
    await app.workers.wait_for_complete()
    await pilot.pause()


@asynccontextmanager
async def mounted(app):
    """run_test(), plus waiting for the startup load so commands aren't refused as busy."""
    async with app.run_test() as pilot:
        await settle(app, pilot)
        yield pilot


@pytest.fixture
def write_app(tmp_config_path, sample_config, mock_service, tmp_tags_index_path, tmp_pending_path):
    config.save_config(sample_config)
    with patch('mydocbot_app.google_docs.get_service', return_value=mock_service):
        app = MyDocBotApp()
        yield app


def _recording_app(sample_config, service):
    config.save_config(sample_config)
    with patch('mydocbot_app.google_docs.get_service', return_value=service):
        return MyDocBotApp()


@pytest.fixture
def read_app(tmp_read_config_path, mock_service):
    config.save_read_config({"default": "log", "aliases": {"log": "doc_id_123"}})
    with patch('mydocbot_app.google_docs.get_service', return_value=mock_service):
        app = ReadOnlyApp()
        yield app


@pytest.mark.asyncio
async def test_cmd_config_show_does_not_crash(write_app):
    async with mounted(write_app):
        write_app.cmd_config([])
        write_app.cmd_config(['show'])


@pytest.mark.asyncio
async def test_cmd_config_set_history_size_updates_config(write_app):
    async with mounted(write_app):
        write_app.cmd_config(['set', 'history_size', '50'])
        assert write_app.svc_config['history_size'] == 50
        assert write_app._history_size == 50
        # Persisted to disk, not just in-memory.
        reloaded = config.load_config()
        assert reloaded['history_size'] == 50


@pytest.mark.asyncio
async def test_cmd_config_set_invalid_history_size_is_rejected(write_app):
    async with mounted(write_app):
        before = write_app._history_size
        write_app.cmd_config(['set', 'history_size', '99999'])
        assert write_app._history_size == before


@pytest.mark.asyncio
async def test_cmd_config_unknown_key(write_app):
    async with mounted(write_app):
        # Should not raise; just reports an "unknown key" status message.
        write_app.cmd_config(['set', 'bogus', 'value'])


@pytest.mark.asyncio
async def test_cmd_config_usage_message_on_bad_args(write_app):
    async with mounted(write_app):
        write_app.cmd_config(['nonsense'])


@pytest.mark.asyncio
async def test_cmd_add_rejects_invalid_alias(write_app):
    async with mounted(write_app):
        before = dict(write_app.svc_config.get("aliases", {}))
        write_app.cmd_add(['bad alias', 'doc_id_0000000000'])
        assert write_app.svc_config.get("aliases", {}) == before


@pytest.mark.asyncio
async def test_cmd_add_accepts_valid_alias(write_app):
    async with mounted(write_app):
        write_app.cmd_add(['newdoc', 'doc_id_0000000000'])
        assert write_app.svc_config["aliases"]["newdoc"] == "doc_id_0000000000"


@pytest.mark.asyncio
async def test_read_only_app_mounts_and_lists(read_app):
    async with mounted(read_app):
        read_app.cmd_list()
        read_app.cmd_current()


@pytest.mark.asyncio
async def test_read_only_app_rejects_invalid_alias(read_app):
    async with mounted(read_app):
        before = dict(read_app.svc_config.get("aliases", {}))
        read_app.cmd_add(['bad alias', 'doc_id_0000000000'])
        assert read_app.svc_config.get("aliases", {}) == before


@pytest.mark.asyncio
async def test_submit_note_sends_and_caches(tmp_config_path, sample_config, tmp_tags_index_path, tmp_pending_path):
    service = RecordingService()
    app = _recording_app(sample_config, service)
    async with mounted(app) as pilot:
        app.query_one("#input-bar").text = "tui note #work"
        app.submit_note()
        await settle(app, pilot)
        assert [c[1].split("| ", 1)[1] for c in service.calls] == ["tui note #work"]
        assert service.calls[0][0] == app.current_doc_id
        assert app.notes_cache[0]["text"] == "tui note #work"
        assert app.query_one("#input-bar").text == ""
        assert "work" in prs.load_tags_index()


@pytest.mark.asyncio
async def test_submit_note_queues_when_write_fails(tmp_config_path, sample_config, tmp_tags_index_path,
                                                   tmp_pending_path, monkeypatch):
    monkeypatch.setattr('core.google_docs.time.sleep', lambda s: None)
    service = RecordingService(failing={"doc_id_123"})
    app = _recording_app(sample_config, service)
    async with mounted(app) as pilot:
        app.query_one("#input-bar").text = "offline tui note"
        app.submit_note()
        await settle(app, pilot)
        assert [q["text"] for q in prs.load_pending_notes()] == ["offline tui note"]
        assert app.notes_cache == []


@pytest.mark.asyncio
async def test_submit_flushes_into_list_in_doc_order(tmp_config_path, sample_config, tmp_tags_index_path,
                                                     tmp_pending_path):
    """B1: flushed notes for the current doc show up right away, below the new
    note, in the same order as the doc. Notes for other docs are written (B3)
    but don't appear in this doc's list."""
    prs.queue_note("queued 1", "doc_id_123", "[10/23/26] (10:00)|")
    prs.queue_note("other doc", "doc_id_456", "[10/23/26] (10:01)|")
    prs.queue_note("queued 2", "doc_id_123", "[10/23/26] (10:05)|")
    service = RecordingService()
    app = _recording_app(sample_config, service)
    async with mounted(app) as pilot:
        app.query_one("#input-bar").text = "new"
        app.submit_note()
        await settle(app, pilot)
        assert [d for d, _ in service.calls] == ["doc_id_123", "doc_id_456", "doc_id_123", "doc_id_123"]
        doc_list = [n["text"] for n in app.notes_cache if n["doc_id"] == "doc_id_123"]
        # The doc reads top-down in reverse write order; the cache is newest first.
        doc_top_down = [t.split("| ", 1)[1] for d, t in reversed(service.calls) if d == "doc_id_123"]
        assert doc_list == doc_top_down == ["new", "queued 2", "queued 1"]
        assert all(n["doc_id"] == "doc_id_123" for n in app.notes_cache)
        assert prs.count_pending() == 0


@pytest.mark.asyncio
async def test_submit_note_rejected_keeps_input(tmp_config_path, sample_config, tmp_tags_index_path,
                                                tmp_pending_path):
    service = RecordingService()
    app = _recording_app(sample_config, service)
    async with mounted(app):
        app.query_one("#input-bar").text = "x" * (51 * 1024)
        app.submit_note()
        assert service.calls == []
        assert app.query_one("#input-bar").text != ""


@pytest.mark.asyncio
async def test_tag_reindex_updates_status_and_tags(write_app, monkeypatch):
    from core.parser import ReindexResult
    monkeypatch.setattr(prs, 'reindex_doc', lambda service, doc_id: ReindexResult("reindexed", 5, 2, 3, 1, 4))
    monkeypatch.setattr(prs, 'load_tags_index', lambda: {"fresh": []})
    async with mounted(write_app) as pilot:
        with patch.object(write_app, 'update_status') as status:
            write_app.handle_command('/tag reindex')
            await settle(write_app, pilot)
        assert "Reindexed" in status.call_args.args[0]
        assert "5 notes, 2 tagged, 3 tags" in status.call_args.args[0]
        assert write_app.all_tags == {"fresh": []}


@pytest.mark.asyncio
async def test_tag_reindex_failure_shows_error(write_app, monkeypatch):
    def fail(service, doc_id):
        raise ConnectionError("offline")
    monkeypatch.setattr(prs, 'reindex_doc', fail)
    async with mounted(write_app) as pilot:
        with patch.object(write_app, 'show_error') as error:
            write_app.handle_command('/tag reindex')
            await settle(write_app, pilot)
        assert "Reindex failed" in error.call_args.args[0]


@pytest.mark.asyncio
async def test_queue_list_and_drop(write_app):
    prs.save_pending_notes([
        {"text": "stuck [x] note", "doc_id": "doc_old", "ts": "[10/24/26] (09:00)|",
         "error": {"kind": "permanent", "message": "document not found (404)"}},
        {"text": "second", "doc_id": "doc_id_123", "ts": "[10/24/26] (09:05)|"},
    ])
    async with mounted(write_app):
        shown = []
        with patch.object(write_app, '_show_in_preview', side_effect=shown.append), \
                patch.object(write_app, 'update_status') as status:
            write_app.handle_command('/queue')
            assert "Queued notes" in shown[-1] and "document not found (404)" in shown[-1]
            assert "stuck \\[x] note" in shown[-1]  # markup in note text is escaped
            write_app.handle_command('/queue drop 1')
        assert "stuck \\[x] note" in shown[-1]
        assert "Dropped note #1. 1 pending." in status.call_args.args[0]
        assert [e["text"] for e in prs.load_pending_notes()] == ["second"]


@pytest.mark.asyncio
async def test_queue_move_and_usage(write_app):
    prs.save_pending_notes([{"text": "n", "doc_id": "doc_old", "ts": "t"}])
    async with mounted(write_app):
        with patch.object(write_app, 'update_status') as status:
            write_app.handle_command('/queue move 1 work')
            assert "now goes to 'work'" in status.call_args.args[0]
            write_app.handle_command('/queue bogus')
            assert "Usage: /queue" in status.call_args.args[0]
    assert prs.load_pending_notes()[0]["doc_id"] == "doc_id_456"


@pytest.mark.asyncio
async def test_queued_status_explains_permanent(write_app):
    from core.google_docs import WriteFailure
    from core.notes import SubmitResult
    async with mounted(write_app):
        text = write_app._queued_status(SubmitResult("queued", "t", failure=WriteFailure("permanent", "no permission (403)")))
        assert text.startswith("Not sent: no permission (403). Queued.")


# ---------------------------------------------------------------------------
# Background Google calls (A3)
# ---------------------------------------------------------------------------

class BlockingService:
    """Mock Docs service whose execute() waits for `release` while `armed`, so a
    test can inspect the UI mid-call. Tracks how many calls overlap."""

    def __init__(self, armed=False, doc_text=""):
        import threading
        self.armed = armed
        self.release = threading.Event()
        self.entered = threading.Event()
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.calls = []
        self._doc = make_doc_response(doc_text)
        self._kind = ("get", None)

    def documents(self):
        return self

    def get(self, documentId=None):
        self._kind = ("get", documentId)
        return self

    def batchUpdate(self, documentId=None, body=None):
        self._kind = ("write", documentId)
        return self

    def execute(self):
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            kind = self._kind
            self.entered.set()
            if self.armed:
                assert self.release.wait(5), "test never released the call"
            self.calls.append(kind)
            return self._doc if kind[0] == "get" else {}
        finally:
            with self._lock:
                self.active -= 1


async def _wait_entered(service):
    import asyncio
    assert await asyncio.get_running_loop().run_in_executor(None, service.entered.wait, 5)


def _blocking_app(sample_config, service, cls=None):
    config.save_config(sample_config)
    with patch('mydocbot_app.google_docs.get_service', return_value=service):
        return (cls or MyDocBotApp)()


@pytest.mark.asyncio
async def test_ui_stays_usable_while_a_write_runs(tmp_config_path, sample_config, tmp_tags_index_path,
                                                  tmp_pending_path):
    service = BlockingService()
    app = _blocking_app(sample_config, service)
    prs.queue_note("someone else's", "doc_id_456", "[10/24/26] (08:00)|",
                   google_docs.WriteFailure("permanent", "document not found (404)"))
    async with mounted(app) as pilot:
        service.armed = True
        service.entered.clear()
        app.query_one("#input-bar").text = "slow note"
        app.submit_note()
        await _wait_entered(service)
        await pilot.pause()

        status = str(app.query_one("#status-bar").render())
        header = str(app.query_one("#header-bar").render())
        assert "Saving note" in status and "Working" in header
        assert app.query_one("#input-bar").read_only
        assert app.query_one("#input-bar").text == "slow note"

        # Still responsive: non-API commands and focus changes work.
        app.handle_command('/help')
        await pilot.press("ctrl+n")
        assert app.focused is app.query_one("#notes-list")

        # Another Google call, a queue edit, and /edit are refused, not started.
        for cmd in ('/refresh', '/queue drop 1', '/edit', '/remove log'):
            app.handle_command(cmd)
            assert "Still saving note" in str(app.query_one("#status-bar").render()), cmd
        assert len(prs.load_pending_notes()) == 1
        assert "log" in app.svc_config["aliases"]

        service.release.set()
        await settle(app, pilot)
        assert app.query_one("#input-bar").text == ""
        assert not app.query_one("#input-bar").read_only
        assert app._api_busy is None
        assert "Prepended" in str(app.query_one("#status-bar").render())
        assert "Connected" in str(app.query_one("#header-bar").render())
        assert app.notes_cache[0]["text"] == "slow note"
    assert service.max_active == 1


@pytest.mark.asyncio
async def test_startup_draws_before_notes_load(tmp_config_path, sample_config, tmp_tags_index_path,
                                               tmp_pending_path):
    service = BlockingService(armed=True, doc_text="[10/24/26] (09:00)| loaded note")
    app = _blocking_app(sample_config, service)
    async with app.run_test() as pilot:
        await _wait_entered(service)
        await pilot.pause()
        assert "Loading notes" in str(app.query_one("#status-bar").render())
        assert app.notes_cache == []
        service.release.set()
        await settle(app, pilot)
        assert [n["text"] for n in app.notes_cache] == ["loaded note"]
        assert "Ready" in str(app.query_one("#status-bar").render())


@pytest.mark.asyncio
async def test_unexpected_submit_error_keeps_text(tmp_config_path, sample_config, tmp_tags_index_path,
                                                  tmp_pending_path, monkeypatch):
    app = _blocking_app(sample_config, BlockingService())

    def boom(service, doc_id, text):
        raise RuntimeError("kaboom")
    async with mounted(app) as pilot:
        monkeypatch.setattr('mydocbot_app.notes.submit_note', boom)
        app.query_one("#input-bar").text = "keep me"
        app.submit_note()
        await settle(app, pilot)
        assert app.query_one("#input-bar").text == "keep me"
        assert not app.query_one("#input-bar").read_only
        assert app._api_busy is None
        assert "kaboom" in str(app.query_one("#status-bar").render())


@pytest.mark.asyncio
async def test_startup_error_is_shown_not_overwritten(tmp_config_path, sample_config, tmp_tags_index_path,
                                                      tmp_pending_path, monkeypatch):
    monkeypatch.setattr(MyDocBotApp, '_fetch_recent', lambda self, doc_id, count: (_ for _ in ()).throw(OSError("dns")))
    app = _blocking_app(sample_config, BlockingService())
    async with mounted(app):
        assert "Startup error: dns" in str(app.query_one("#status-bar").render())
        assert app.current_title == "(error)"


@pytest.mark.asyncio
async def test_switch_list_refresh_more_run_in_background(tmp_config_path, sample_config, tmp_tags_index_path,
                                                          tmp_pending_path):
    service = BlockingService(doc_text="[10/24/26] (09:00)| a\n[10/23/26] (09:00)| b\n")
    app = _blocking_app(sample_config, service)
    async with mounted(app) as pilot:
        app.handle_command('/switch work')
        await settle(app, pilot)
        assert app.current_alias == "work" and app.current_doc_id == "doc_id_456"
        assert [n["text"] for n in app.notes_cache if n["doc_id"] == "doc_id_456"] == ["a", "b"]

        shown = []
        with patch.object(app.query_one("#preview-pane"), 'write', side_effect=shown.append):
            app.handle_command('/list')
            await settle(app, pilot)
        assert "Configured Documents" in shown[-1] and "← active" in shown[-1]

        app.handle_command('/refresh')
        await settle(app, pilot)
        assert "No new notes" in str(app.query_one("#status-bar").render())

        app.handle_command('/more')
        await settle(app, pilot)
        assert "No more notes to load" in str(app.query_one("#status-bar").render())
    assert service.max_active == 1


@pytest.mark.asyncio
async def test_flush_runs_in_background(tmp_config_path, sample_config, tmp_tags_index_path, tmp_pending_path):
    prs.queue_note("queued", "doc_id_123", "[10/24/26] (08:00)|")
    service = BlockingService()
    app = _blocking_app(sample_config, service)
    async with mounted(app) as pilot:
        app.handle_command('/flush')
        await settle(app, pilot)
        assert "Flushed 1" in str(app.query_one("#status-bar").render())
        assert app.notes_cache[0]["text"] == "queued"
        assert prs.count_pending() == 0


@pytest.mark.asyncio
async def test_remove_active_alias_switches_in_background(tmp_config_path, sample_config, tmp_tags_index_path,
                                                          tmp_pending_path):
    app = _blocking_app(sample_config, BlockingService())
    async with mounted(app) as pilot:
        app.handle_command('/remove log')
        await settle(app, pilot)
        assert "log" not in app.svc_config["aliases"]
        assert app.current_alias == "work"


@pytest.mark.asyncio
async def test_read_only_app_switch_in_background(tmp_read_config_path):
    config.save_read_config({"default": "a", "aliases": {"a": "doc_r1", "b": "doc_r2"}})
    service = BlockingService(doc_text="24/10/2026\n[9.30]\nread note\n")
    with patch('mydocbot_app.google_docs.get_service', return_value=service):
        app = ReadOnlyApp()
    async with mounted(app) as pilot:
        assert [n["text"] for n in app.notes_cache] == ["read note"]
        app.handle_command('/switch b')
        await settle(app, pilot)
        assert app.current_doc_id == "doc_r2"
    assert service.max_active == 1


# ---------------------------------------------------------------------------
# /search over the whole doc (B8) and retried note fetches (B10)
# ---------------------------------------------------------------------------

# 25 notes, newest first; the needle is the oldest, beyond the default
# history_size (20), so it is never in the startup cache.
SEARCH_DOC = "\n".join(f"[06/{d:02d}/26] (10:00)| note {d}" for d in range(25, 1, -1)) + \
    "\n[05/01/26] (09:00)| the needle note\n"


@pytest.mark.asyncio
async def test_search_finds_notes_not_loaded(tmp_config_path, sample_config, tmp_tags_index_path, tmp_pending_path):
    app = _blocking_app(sample_config, BlockingService(doc_text=SEARCH_DOC))
    async with mounted(app) as pilot:
        assert not any("needle" in n["text"] for n in app.notes_cache)
        shown = []
        with patch.object(app, '_show_search_results', side_effect=lambda k, r, note=None: shown.append((r, note))):
            app.handle_command('/search NEEDLE')
            await settle(app, pilot)
        assert shown == [([("[05/01/26] (09:00)|", "the needle note")], None)]


@pytest.mark.asyncio
async def test_search_falls_back_to_loaded_notes(tmp_config_path, sample_config, tmp_tags_index_path,
                                                 tmp_pending_path, monkeypatch):
    app = _blocking_app(sample_config, BlockingService(doc_text=SEARCH_DOC))
    async with mounted(app) as pilot:
        def offline(doc_id, count):
            raise OSError(101, "Network is unreachable")
        monkeypatch.setattr(app, '_fetch_recent', offline)
        app.handle_command('/search note 2')
        await settle(app, pilot)
        status = str(app.query_one("#status-bar").render())
        assert "searched the 20 loaded notes only" in status
        assert "match(es) for 'note 2'" in status


@pytest.mark.asyncio
async def test_read_only_search_covers_whole_doc(tmp_read_config_path):
    old = "\n".join(f"{d:02d}/06/2026\n[10.00]\nread note {d}" for d in range(25, 1, -1))
    config.save_read_config({"default": "a", "aliases": {"a": "doc_r1"}})
    with patch('mydocbot_app.google_docs.get_service',
               return_value=BlockingService(doc_text=old + "\n01/05/2026\n[9.00]\nancient needle\n")):
        app = ReadOnlyApp()
    async with mounted(app) as pilot:
        shown = []
        with patch.object(app, '_show_search_results', side_effect=lambda k, r, note=None: shown.append(r)):
            app.handle_command('/search needle')
            await settle(app, pilot)
        assert [body for _, body in shown[0]] == ["ancient needle"]


def test_cli_and_tui_search_give_same_results(tmp_config_path, sample_config, capsys):
    """B8 parity: same doc, same keyword, same notes in the same order."""
    from core.commands import cmd_search
    service = BlockingService(doc_text=SEARCH_DOC)
    cmd_search(service, sample_config, "doc_id_123", ["note", "1"])
    cli_ts = [line.strip().split("| ", 1)[0] + "|"
              for line in capsys.readouterr().out.splitlines() if line.startswith("  [")]
    app = _blocking_app(sample_config, service)
    tui_ts = [ts for ts, _ in prs.search_entries(app._fetch_recent("doc_id_123", None), "note 1")]
    assert cli_ts == tui_ts and len(cli_ts) > 1


@pytest.mark.parametrize("cls", [MyDocBotApp, ReadOnlyApp])
def test_fetch_recent_retries_transient_errors(cls, tmp_config_path, tmp_read_config_path, sample_config, monkeypatch):
    """B10: note fetches go through fetch_doc(), so a 503 is retried like a write."""
    from unittest.mock import MagicMock

    from googleapiclient.errors import HttpError
    monkeypatch.setattr('core.google_docs.time.sleep', lambda s: None)
    service = MagicMock()
    service.documents.return_value.get.return_value.execute.side_effect = [
        HttpError(MagicMock(status=503), b"busy"), make_doc_response("")]
    config.save_config(sample_config)
    with patch('mydocbot_app.google_docs.get_service', return_value=service):
        app = cls()
    assert app._fetch_recent("doc_x", 5) == []
    assert service.documents.return_value.get.return_value.execute.call_count == 2


@pytest.mark.asyncio
async def test_help_says_search_covers_whole_doc(write_app):
    async with mounted(write_app) as pilot:
        shown = []
        with patch.object(write_app.query_one("#preview-pane"), 'write', side_effect=shown.append):
            write_app.handle_command('/help')
            await pilot.pause()
        assert "Search all notes in this doc" in shown[-1]


@pytest.mark.asyncio
async def test_preview_highlights_whole_hyphenated_tag(write_app):
    """F5: the highlighter uses the same pattern as indexing, so the whole tag is styled."""
    async with mounted(write_app) as pilot:
        write_app.notes_cache = [{"ts": "[10/24/26] (09:00)|", "text": "kickoff #project-alpha #done-",
                                  "doc_id": write_app.current_doc_id}]
        written = []
        with patch.object(write_app.query_one("#preview-pane"), 'write', side_effect=written.append):
            write_app.refresh_ui()
            await pilot.pause()
        assert "[bold #f9e2af]#project-alpha[/]" in written[-1]
        assert "[bold #f9e2af]#done[/]-" in written[-1]


# ---------------------------------------------------------------------------
# Status text is plain text, never markup (B7)
# ---------------------------------------------------------------------------

def _status(app):
    return str(app.query_one("#status-bar").render())


@pytest.mark.asyncio
async def test_status_with_closing_tag_does_not_crash(write_app):
    """B7: `/switch [/]` used to raise MarkupError out of the handler and crash the TUI."""
    async with mounted(write_app) as pilot:
        write_app.handle_command('/switch [/]')
        await pilot.pause()
        assert _status(write_app) == "Unknown alias '[/]'"


@pytest.mark.asyncio
async def test_status_shows_brackets_literally(write_app):
    async with mounted(write_app) as pilot:
        write_app.handle_command('/switch [b]')
        await pilot.pause()
        assert _status(write_app) == "Unknown alias '[b]'"   # used to be "Unknown alias ''"
        write_app.handle_command('/add [red]x doc_id_0000000000')
        await pilot.pause()
        assert _status(write_app) == "Added '[red]x'"   # bracketed aliases are valid
        write_app.handle_command('/remove [red]x')
        await pilot.pause()
        assert _status(write_app) == "Removed '[red]x'"


@pytest.mark.asyncio
async def test_show_error_is_plain_text(write_app):
    async with mounted(write_app) as pilot:
        write_app.show_error("boom [/] and [b]x[/b]")
        await pilot.pause()
        assert _status(write_app) == "boom [/] and [b]x[/b]"


@pytest.mark.asyncio
async def test_previously_escaped_messages_have_no_backslashes(write_app):
    async with mounted(write_app) as pilot:
        write_app.handle_command('/queue bogus')
        await pilot.pause()
        assert _status(write_app).startswith("Usage: /queue [list] | /queue drop <n>")
        assert "\\" not in _status(write_app)
        write_app.handle_command('/queue move 1 [x]')
        await pilot.pause()
        assert "\\" not in _status(write_app)


# ---------------------------------------------------------------------------
# "Today" / "Yesterday" date labels (B6, design decision #27)
# ---------------------------------------------------------------------------

def _freeze_now(monkeypatch, *ymd_hm):
    """Freeze mydocbot_app's clock so date labels can't flake across midnight."""
    from datetime import datetime as real_datetime

    class Frozen(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(*ymd_hm)
    monkeypatch.setattr('mydocbot_app.datetime', Frozen)


def _separator_labels(app):
    from mydocbot_app import DateSeparator
    return [str(sep.query_one(Label).render()).strip("─ ")
            for sep in app.query_one("#notes-list").children if isinstance(sep, DateSeparator)]


@pytest.mark.parametrize("ts,key", [
    ("[24/10/2026] [9.30]|", "10/24/26"),
    ("[5/3/2026] [9.05]|", "03/05/26"),     # single-digit day and month (DD/MM/YYYY)
    ("[31/12/2026] [23.59]|", "12/31/26"),
])
def test_read_only_date_key_is_mm_dd_yy(read_app, ts, key):
    """#27: the old read-only key was YY/MM/DD, so it never matched today's MM/DD/YY."""
    assert read_app._date_key(ts) == key


def test_write_date_key_is_mm_dd_yy(write_app):
    assert write_app._date_key("[10/24/26] (09:30)|") == "10/24/26"


@pytest.mark.parametrize("now,date_str,label", [
    ((2026, 10, 24, 10, 0), "10/24/26", "Today"),
    ((2026, 10, 24, 10, 0), "10/23/26", "Yesterday"),
    ((2026, 10, 24, 10, 0), "10/22/26", "10/22/26"),
    ((2027, 1, 1, 0, 5), "12/31/26", "Yesterday"),     # across a year boundary
    ((2027, 1, 1, 0, 5), "01/01/27", "Today"),
])
def test_format_date_header(monkeypatch, now, date_str, label):
    _freeze_now(monkeypatch, *now)
    assert MyDocBotApp._format_date_header(date_str) == label


@pytest.mark.asyncio
async def test_read_only_list_labels_today_and_yesterday(tmp_read_config_path, monkeypatch):
    """B6 end to end: read-format notes from today and yesterday get the right separators."""
    _freeze_now(monkeypatch, 2026, 10, 24, 10, 0)
    config.save_read_config({"default": "a", "aliases": {"a": "doc_r1"}})
    doc = ("24/10/2026\n[10.00]\ntoday's note\n"
           "23/10/2026\n[9.00]\nyesterday's note\n"
           "1/10/2026\n[8.00]\nolder note\n")
    with patch('mydocbot_app.google_docs.get_service', return_value=BlockingService(doc_text=doc)):
        app = ReadOnlyApp()
    async with mounted(app):
        assert _separator_labels(app) == ["Today", "Yesterday", "10/01/26"]
