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

from core import config
from mydocbot_app import MyDocBotApp, ReadOnlyApp


@pytest.fixture
def write_app(tmp_config_path, sample_config, mock_service, tmp_tags_index_path, tmp_pending_path):
    config.save_config(sample_config)
    with patch('mydocbot_app.google_docs.get_service', return_value=mock_service):
        app = MyDocBotApp()
        yield app


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
