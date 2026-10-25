from unittest.mock import MagicMock, patch

import pytest
from conftest import make_doc_response


class TestCmdList:
    def test_no_aliases(self, capsys):
        from core.commands import cmd_list
        config = {"aliases": {}}
        cmd_list(None, config, None)
        captured = capsys.readouterr()
        assert "No documents configured" in captured.out

    def test_lists_aliases(self, capsys):
        from core.commands import cmd_list
        config = {"aliases": {"log": "id1", "work": "id2"}}
        mock_service = MagicMock()
        mock_service.documents().get().execute.return_value = {"title": "Test Doc"}
        cmd_list(mock_service, config, "log")
        captured = capsys.readouterr()
        assert "log" in captured.out
        assert "work" in captured.out
        assert "active" in captured.out


class TestCmdAdd:
    def test_adds_alias(self, tmp_config_path, monkeypatch):
        from core.commands import cmd_add
        monkeypatch.setattr('core.config.CONFIG_PATH', tmp_config_path)
        config = {"default": "", "aliases": {}}
        cmd_add(config, ["newdoc", "doc_id_999"])
        assert "newdoc" in config["aliases"]
        assert config["aliases"]["newdoc"] == "doc_id_999"

    def test_duplicate_alias(self, capsys):
        from core.commands import cmd_add
        config = {"default": "", "aliases": {"existing": "valid_doc_id_123"}}
        cmd_add(config, ["existing", "another_valid_id_456"])
        captured = capsys.readouterr()
        assert "already exists" in captured.out
        assert config["aliases"]["existing"] == "valid_doc_id_123"

    def test_missing_args(self, capsys):
        from core.commands import cmd_add
        cmd_add({"aliases": {}}, ["only_alias"])
        captured = capsys.readouterr()
        assert "Usage" in captured.out


class TestCmdRemove:
    def test_removes_alias(self, tmp_config_path, monkeypatch):
        from core.commands import cmd_remove
        monkeypatch.setattr('core.config.CONFIG_PATH', tmp_config_path)
        config = {"default": "", "aliases": {"test": "id1"}}
        monkeypatch.setattr('builtins.input', lambda _: "y")
        result = cmd_remove(config, ["test"], None)
        assert "test" not in config["aliases"]
        assert result is True

    def test_removes_current_returns_true(self, tmp_config_path, monkeypatch):
        from core.commands import cmd_remove
        monkeypatch.setattr('core.config.CONFIG_PATH', tmp_config_path)
        config = {"default": "current", "aliases": {"current": "id1"}}
        monkeypatch.setattr('builtins.input', lambda _: "y")
        result = cmd_remove(config, ["current"], "current")
        assert result is True
        assert "current" not in config["aliases"]

    def test_not_found(self, capsys):
        from core.commands import cmd_remove
        result = cmd_remove({"aliases": {}}, ["unknown"], None)
        captured = capsys.readouterr()
        assert "not found" in captured.out
        assert result is False

    def test_no_args(self, capsys):
        from core.commands import cmd_remove
        result = cmd_remove({"aliases": {}}, [], None)
        captured = capsys.readouterr()
        assert "Usage" in captured.out
        assert result is False

    def test_canceled(self, monkeypatch, capsys):
        from core.commands import cmd_remove
        config = {"default": "", "aliases": {"test": "id1"}}
        monkeypatch.setattr('builtins.input', lambda _: "n")
        result = cmd_remove(config, ["test"], None)
        captured = capsys.readouterr()
        assert "Canceled" in captured.out
        assert result is False
        assert "test" in config["aliases"]


class TestCmdRename:
    def test_renames_alias(self, tmp_config_path, monkeypatch):
        from core.commands import cmd_rename
        monkeypatch.setattr('core.config.CONFIG_PATH', tmp_config_path)
        config = {"default": "", "aliases": {"old": "id1"}}
        cmd_rename(config, ["old", "new"])
        assert "old" not in config["aliases"]
        assert config["aliases"]["new"] == "id1"

    def test_renames_default(self, tmp_config_path, monkeypatch):
        from core.commands import cmd_rename
        monkeypatch.setattr('core.config.CONFIG_PATH', tmp_config_path)
        config = {"default": "old", "aliases": {"old": "id1"}}
        cmd_rename(config, ["old", "new"])
        assert config["default"] == "new"

    def test_missing_args(self, capsys):
        from core.commands import cmd_rename
        cmd_rename({"aliases": {}}, ["only_old"])
        captured = capsys.readouterr()
        assert "Usage" in captured.out


class TestCmdCurrent:
    def test_shows_alias(self, capsys):
        from core.commands import cmd_current
        mock_service = MagicMock()
        mock_service.documents().get().execute.return_value = {"title": "My Log"}
        config = {"aliases": {"log": "doc_1"}}
        cmd_current(mock_service, config, "log")
        captured = capsys.readouterr()
        assert "log" in captured.out
        assert "My Log" in captured.out
        assert "doc_1" in captured.out


class TestCmdHelp:
    def test_lists_commands(self, capsys):
        from core.commands import cmd_help
        cmd_help()
        captured = capsys.readouterr()
        assert "/switch" in captured.out
        assert "/list" in captured.out
        assert "/add" in captured.out
        assert "/remove" in captured.out
        assert "/rename" in captured.out
        assert "/current" in captured.out
        assert "/edit" in captured.out
        assert "/tag" in captured.out
        assert "/help" in captured.out
        assert "exit" in captured.out


class TestCmdTag:
    def test_list_empty(self, capsys, tmp_tags_index_path, monkeypatch):
        import core.parser as prs
        from core.commands import cmd_tag_list
        monkeypatch.setattr('core.parser.TAGS_INDEX_PATH', tmp_tags_index_path)
        prs.save_tags_index({})
        cmd_tag_list({"aliases": {}}, "doc_1")
        captured = capsys.readouterr()
        assert "No tags indexed" in captured.out

    def test_list_shows_tags(self, capsys, tmp_tags_index_path, monkeypatch):
        import core.parser as prs
        from core.commands import cmd_tag_list
        monkeypatch.setattr('core.parser.TAGS_INDEX_PATH', tmp_tags_index_path)
        prs.save_tags_index({"bug": [{"ts": "t1", "doc_id": "doc_1", "preview": "fix"}]})
        cmd_tag_list({"aliases": {}}, "doc_1")
        captured = capsys.readouterr()
        assert "#bug" in captured.out

    def test_search_found(self, capsys, tmp_tags_index_path, monkeypatch):
        import core.parser as prs
        from core.commands import cmd_tag_search
        monkeypatch.setattr('core.parser.TAGS_INDEX_PATH', tmp_tags_index_path)
        prs.save_tags_index({"meeting": [{"ts": "t1", "doc_id": "doc_1", "preview": "notes"}]})
        cmd_tag_search({"aliases": {}}, "meeting", "doc_1")
        captured = capsys.readouterr()
        assert "#meeting" in captured.out

    def test_search_not_found(self, capsys, tmp_tags_index_path, monkeypatch):
        import core.parser as prs
        from core.commands import cmd_tag_search
        monkeypatch.setattr('core.parser.TAGS_INDEX_PATH', tmp_tags_index_path)
        prs.save_tags_index({})
        cmd_tag_search({"aliases": {}}, "nonexistent", "doc_1")
        captured = capsys.readouterr()
        assert "No notes" in captured.out

    def test_stats(self, capsys, tmp_tags_index_path, monkeypatch):
        import core.parser as prs
        from core.commands import cmd_tag_stats
        monkeypatch.setattr('core.parser.TAGS_INDEX_PATH', tmp_tags_index_path)
        prs.save_tags_index({"bug": [{"ts": "t1", "doc_id": "doc_1", "preview": "fix"}]})
        cmd_tag_stats({"aliases": {}}, "doc_1")
        captured = capsys.readouterr()
        assert "#bug" in captured.out
        assert "█" in captured.out


class TestCmdSearch:
    """Tests for CLI /search command (fetches from API at search time)."""

    def _make_service_with(self, text):
        svc = MagicMock()
        svc.documents().get().execute.return_value = make_doc_response(text)
        return svc

    def test_search_found(self, capsys):
        from core.commands import cmd_search
        note_text = "[06/18/26] (10:00)| sprint review meeting notes"
        svc = self._make_service_with(note_text)
        cmd_search(svc, {"default": "log", "aliases": {}}, "doc_1", ["sprint"])
        out = capsys.readouterr().out
        assert "sprint" in out
        assert "1 result" in out

    def test_search_not_found(self, capsys):
        from core.commands import cmd_search
        note_text = "[06/18/26] (10:00)| completely unrelated content"
        svc = self._make_service_with(note_text)
        cmd_search(svc, {"default": "log", "aliases": {}}, "doc_1", ["xyz_missing"])
        out = capsys.readouterr().out
        assert "No notes matching" in out

    def test_search_no_args_prints_usage(self, capsys):
        from core.commands import cmd_search
        cmd_search(MagicMock(), {}, "doc_1", [])
        assert "Usage" in capsys.readouterr().out

    def test_search_api_error_prints_to_stderr(self, capsys):
        from core.commands import cmd_search
        svc = MagicMock()
        svc.documents().get().execute.side_effect = Exception("network down")
        cmd_search(svc, {}, "doc_1", ["anything"])
        assert "Error" in capsys.readouterr().err

    def test_search_case_insensitive(self, capsys):
        from core.commands import cmd_search
        note_text = "[06/18/26] (10:00)| Sprint Review"
        svc = self._make_service_with(note_text)
        cmd_search(svc, {}, "doc_1", ["sprint"])
        assert "1 result" in capsys.readouterr().out

    def test_search_multi_word_keyword(self, capsys):
        from core.commands import cmd_search
        note_text = "[06/18/26] (10:00)| sprint review completed successfully"
        svc = self._make_service_with(note_text)
        cmd_search(svc, {}, "doc_1", ["sprint", "review"])
        out = capsys.readouterr().out
        assert "1 result" in out

    def test_search_respects_history_size(self, capsys):
        """history_size from svc_config is passed to parse_entries as count."""
        from core.commands import cmd_search
        svc = MagicMock()
        svc.documents().get().execute.return_value = {"body": {"content": []}}
        with patch('core.commands.google_docs.parse_entries') as mock_parse:
            mock_parse.return_value = []
            cmd_search(svc, {"history_size": 75}, "doc_1", ["anything"])
            # parse_entries(doc, count=75) — count is a keyword arg
            mock_parse.assert_called_once()
            assert mock_parse.call_args[1].get('count') == 75

    def test_search_no_doc_id(self, capsys):
        from core.commands import cmd_search
        cmd_search(MagicMock(), {}, None, ["something"])
        assert "No active document" in capsys.readouterr().out


class TestCmdConfig:
    """Tests for /config show and /config set history_size."""

    def test_show_default(self, capsys):
        from core.commands import cmd_config
        cmd_config({"default": "log", "aliases": {}}, ["show"])
        out = capsys.readouterr().out
        assert "history_size" in out
        assert "20" in out

    def test_show_custom_value(self, capsys):
        from core.commands import cmd_config
        cmd_config({"default": "log", "aliases": {}, "history_size": 75}, ["show"])
        assert "75" in capsys.readouterr().out

    def test_show_no_args_same_as_show(self, capsys):
        from core.commands import cmd_config
        cmd_config({"default": "log", "aliases": {}}, [])
        assert "history_size" in capsys.readouterr().out

    def test_set_valid_saves_config(self, tmp_config_path, monkeypatch, capsys):
        from core.commands import cmd_config
        monkeypatch.setattr('core.config.CONFIG_PATH', tmp_config_path)
        cfg = {"default": "log", "aliases": {}}
        cmd_config(cfg, ["set", "history_size", "50"])
        assert cfg["history_size"] == 50
        assert "50" in capsys.readouterr().out

    def test_set_invalid_value_not_saved(self, capsys):
        from core.commands import cmd_config
        cfg = {"default": "log", "aliases": {}}
        cmd_config(cfg, ["set", "history_size", "0"])
        assert "history_size" not in cfg
        assert "Invalid" in capsys.readouterr().out

    def test_set_too_high_not_saved(self, capsys):
        from core.commands import cmd_config
        cfg = {"default": "log", "aliases": {}}
        cmd_config(cfg, ["set", "history_size", "999"])
        assert "history_size" not in cfg
        assert "Invalid" in capsys.readouterr().out

    def test_set_unknown_key(self, capsys):
        from core.commands import cmd_config
        cfg = {"default": "log", "aliases": {}}
        cmd_config(cfg, ["set", "bad_key", "10"])
        assert "Unknown" in capsys.readouterr().out

    def test_set_missing_value_shows_usage(self, capsys):
        from core.commands import cmd_config
        cmd_config({}, ["set", "history_size"])
        assert "Usage" in capsys.readouterr().out


class TestDispatchEdit:
    """CLI /edit goes through core.notes.submit_note() (A2)."""

    def test_edit_queues_note_when_write_fails(self, tmp_pending_path, tmp_tags_index_path, monkeypatch, capsys):
        from conftest import RecordingService

        from core import parser as prs
        from core.commands import dispatch
        monkeypatch.setattr('core.google_docs.time.sleep', lambda s: None)
        service = RecordingService(failing={"doc_1"})
        with patch('core.commands.open_editor', return_value="from editor #work"):
            dispatch(service, {"aliases": {"log": "doc_1"}}, "/edit", "log", "doc_1")
        queued = prs.load_pending_notes()
        assert [q["text"] for q in queued] == ["from editor #work"]
        assert "Queued" in capsys.readouterr().out

    def test_edit_sends_and_indexes(self, tmp_pending_path, tmp_tags_index_path):
        from conftest import RecordingService

        from core import parser as prs
        from core.commands import dispatch
        service = RecordingService()
        with patch('core.commands.open_editor', return_value="from editor #work"):
            dispatch(service, {"aliases": {"log": "doc_1"}}, "/edit", "log", "doc_1")
        assert len(service.calls) == 1
        assert service.calls[0][1].endswith(" from editor #work")
        assert "work" in prs.load_tags_index()


class TestTagReindex:
    """F4: /tag reindex in the CLI."""

    def _reindex(self, result=None, error=None, title="My Log"):
        from core.commands import cmd_tag
        with patch('core.commands.google_docs.fetch_doc_title', return_value=title), \
                patch('core.commands.parser.reindex_doc', return_value=result, side_effect=error) as reindex:
            cmd_tag('service', {"aliases": {}}, ['reindex'], 'log', 'doc_1')
        return reindex

    def test_prints_summary(self, capsys):
        from core.parser import ReindexResult
        reindex = self._reindex(ReindexResult("reindexed", 412, 57, 23, 31, 88))
        reindex.assert_called_once_with('service', 'doc_1')
        out = capsys.readouterr().out
        assert 'Reindexed "My Log": 412 notes, 57 tagged, 23 tags' in out
        assert "31 → 88" in out

    def test_falls_back_to_alias_label(self, capsys):
        from core.parser import ReindexResult
        self._reindex(ReindexResult("reindexed", 1, 0, 0, 0, 0), title=None)
        assert 'Reindexed "log"' in capsys.readouterr().out

    def test_no_notes_message(self, capsys):
        from core.parser import ReindexResult
        self._reindex(ReindexResult("no_notes", entries_before=4, entries_after=4))
        assert "No notes found" in capsys.readouterr().out

    def test_failure_message(self, capsys):
        self._reindex(error=ConnectionError("offline"))
        out = capsys.readouterr().out
        assert "Reindex failed" in out and "offline" in out

    def test_usage_mentions_reindex(self, capsys):
        from core.commands import cmd_tag
        cmd_tag('service', {"aliases": {}}, ['bogus'], 'log', 'doc_1')
        assert "/tag reindex" in capsys.readouterr().out

    def test_help_mentions_reindex(self, capsys):
        from core.commands import cmd_help
        cmd_help()
        assert "/tag reindex" in capsys.readouterr().out


class TestQueuedText:
    """F6: queued messages say why and what to do."""

    def _result(self, failure=None, behind=0):
        from core.notes import SubmitResult
        return SubmitResult("queued", "t", failure=failure, queued_behind=behind)

    def _text(self, result, pending=2):
        from core.commands import queued_text
        with patch('core.commands.parser.count_pending', return_value=pending):
            return queued_text(result)

    def test_transient(self):
        from core.google_docs import WriteFailure
        text = self._text(self._result(WriteFailure("transient", "offline or Google unavailable")))
        assert text == "Queued note (offline). 2 pending. Use /flush to retry."

    def test_permanent_names_reason_and_queue(self):
        from core.google_docs import WriteFailure
        text = self._text(self._result(WriteFailure("permanent", "document not found (404)")))
        assert text.startswith("Not sent: document not found (404). Queued. 2 pending.")
        assert "/queue" in text

    def test_auth(self):
        from core.google_docs import WriteFailure
        text = self._text(self._result(WriteFailure("auth", "restart MyDocBot to sign in again")))
        assert "Not sent: restart MyDocBot" in text and "/flush" in text

    def test_queued_behind_names_blocking_error(self):
        from core.google_docs import WriteFailure
        text = self._text(self._result(WriteFailure("permanent", "no permission (403)"), behind=3))
        assert text.startswith("Queued behind 3 earlier note(s) for this doc (no permission (403))")

    def test_queued_behind_without_stored_error(self):
        assert "(still pending)" in self._text(self._result(behind=1))

    def test_cli_message_wraps(self):
        from core.commands import queued_message
        with patch('core.commands.parser.count_pending', return_value=1):
            assert queued_message(self._result()).startswith("--- Queued note (offline).")


class TestCmdQueue:
    CONFIG = {"aliases": {"log": "doc_a", "work": "doc_b"}}

    @pytest.fixture(autouse=True)
    def _queue(self, tmp_path, monkeypatch):
        import core.parser as prs
        monkeypatch.setattr(prs, 'PENDING_PATH', str(tmp_path / 'pending_queue.json'))
        prs.save_pending_notes([
            {"text": "stuck note", "doc_id": "doc_old", "ts": "[10/24/26] (09:00)|",
             "error": {"kind": "permanent", "message": "document not found (404)"}},
            {"text": "offline note", "doc_id": "doc_a", "ts": "[10/24/26] (09:05)|"},
        ])
        self.prs = prs

    def _run(self, args, answer=None):
        from core.commands import cmd_queue
        with patch('builtins.input', return_value=answer) as ask:
            cmd_queue(self.CONFIG, args)
        return ask

    def test_list(self, capsys):
        self._run([])
        out = capsys.readouterr().out
        assert "2 pending (oldest first)" in out
        assert "1. [10/24/26] (09:00)| [doc_old] stuck note — document not found (404)" in out
        assert "2. [10/24/26] (09:05)| [log] offline note" in out

    def test_list_empty(self, capsys):
        self.prs.save_pending_notes([])
        self._run(['list'])
        assert "No pending notes." in capsys.readouterr().out

    def test_drop_confirmed(self, capsys):
        ask = self._run(['drop', '1'], answer='y')
        assert "[y/N]" in ask.call_args.args[0]
        assert [e["text"] for e in self.prs.load_pending_notes()] == ["offline note"]
        out = capsys.readouterr().out
        assert "Dropped note #1" in out and "stuck note" in out

    def test_drop_canceled(self, capsys):
        self._run(['drop', '1'], answer='n')
        assert len(self.prs.load_pending_notes()) == 2
        assert "Canceled." in capsys.readouterr().out

    def test_drop_out_of_range(self, capsys):
        ask = self._run(['drop', '5'])
        ask.assert_not_called()
        assert "No queued note #5 (there are 2)" in capsys.readouterr().out

    def test_move(self, capsys):
        self._run(['move', '1', 'work'])
        entry = self.prs.load_pending_notes()[0]
        assert entry["doc_id"] == "doc_b" and "error" not in entry
        assert "now goes to 'work'" in capsys.readouterr().out

    def test_move_unknown_alias(self, capsys):
        self._run(['move', '1', 'nope'])
        assert self.prs.load_pending_notes()[0]["doc_id"] == "doc_old"
        assert "Alias 'nope' not found." in capsys.readouterr().out

    @pytest.mark.parametrize("args", [['drop'], ['drop', 'x'], ['move', '1'], ['bogus'], ['list', 'extra']])
    def test_usage(self, args, capsys):
        self._run(args)
        assert "Usage: /queue" in capsys.readouterr().out

    def test_dispatch_routes_queue(self, capsys):
        from core.commands import dispatch
        dispatch('service', self.CONFIG, '/queue', 'log', 'doc_a')
        assert "2 pending" in capsys.readouterr().out

    def test_help_lists_queue(self, capsys):
        from core.commands import cmd_help
        cmd_help()
        out = capsys.readouterr().out
        assert "/queue drop <n>" in out and "/queue move <n> <alias>" in out

    def test_flush_includes_permanent(self):
        from core.commands import dispatch
        with patch('core.commands.parser.flush_pending_notes', return_value=[]) as flush:
            dispatch('service', self.CONFIG, '/flush', 'log', 'doc_a')
        flush.assert_called_once_with('service', include_permanent=True)
