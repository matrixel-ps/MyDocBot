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
from unittest.mock import patch

import pytest
from conftest import RecordingService

from core import config
from core import parser as prs
from mydocbot_app import MyDocBotApp, ReadOnlyApp


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
    async with write_app.run_test():
        write_app.cmd_config([])
        write_app.cmd_config(['show'])


@pytest.mark.asyncio
async def test_cmd_config_set_history_size_updates_config(write_app):
    async with write_app.run_test():
        write_app.cmd_config(['set', 'history_size', '50'])
        assert write_app.svc_config['history_size'] == 50
        assert write_app._history_size == 50
        # Persisted to disk, not just in-memory.
        reloaded = config.load_config()
        assert reloaded['history_size'] == 50


@pytest.mark.asyncio
async def test_cmd_config_set_invalid_history_size_is_rejected(write_app):
    async with write_app.run_test():
        before = write_app._history_size
        write_app.cmd_config(['set', 'history_size', '99999'])
        assert write_app._history_size == before


@pytest.mark.asyncio
async def test_cmd_config_unknown_key(write_app):
    async with write_app.run_test():
        # Should not raise; just reports an "unknown key" status message.
        write_app.cmd_config(['set', 'bogus', 'value'])


@pytest.mark.asyncio
async def test_cmd_config_usage_message_on_bad_args(write_app):
    async with write_app.run_test():
        write_app.cmd_config(['nonsense'])


@pytest.mark.asyncio
async def test_cmd_add_rejects_invalid_alias(write_app):
    async with write_app.run_test():
        before = dict(write_app.svc_config.get("aliases", {}))
        write_app.cmd_add(['bad alias', 'doc_id_0000000000'])
        assert write_app.svc_config.get("aliases", {}) == before


@pytest.mark.asyncio
async def test_cmd_add_accepts_valid_alias(write_app):
    async with write_app.run_test():
        write_app.cmd_add(['newdoc', 'doc_id_0000000000'])
        assert write_app.svc_config["aliases"]["newdoc"] == "doc_id_0000000000"


@pytest.mark.asyncio
async def test_read_only_app_mounts_and_lists(read_app):
    async with read_app.run_test():
        read_app.cmd_list()
        read_app.cmd_current()


@pytest.mark.asyncio
async def test_read_only_app_rejects_invalid_alias(read_app):
    async with read_app.run_test():
        before = dict(read_app.svc_config.get("aliases", {}))
        read_app.cmd_add(['bad alias', 'doc_id_0000000000'])
        assert read_app.svc_config.get("aliases", {}) == before


@pytest.mark.asyncio
async def test_submit_note_sends_and_caches(tmp_config_path, sample_config, tmp_tags_index_path, tmp_pending_path):
    service = RecordingService()
    app = _recording_app(sample_config, service)
    async with app.run_test():
        app.query_one("#input-bar").text = "tui note #work"
        app.submit_note()
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
    async with app.run_test():
        app.query_one("#input-bar").text = "offline tui note"
        app.submit_note()
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
    async with app.run_test():
        app.query_one("#input-bar").text = "new"
        app.submit_note()
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
    async with app.run_test():
        app.query_one("#input-bar").text = "x" * (51 * 1024)
        app.submit_note()
        assert service.calls == []
        assert app.query_one("#input-bar").text != ""
