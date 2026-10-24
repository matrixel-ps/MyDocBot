from unittest.mock import MagicMock, patch

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
