import pytest
import json
import os
from unittest.mock import MagicMock
from io import StringIO
from datetime import datetime


class TestCmdList:
    def test_no_aliases(self, capsys):
        from main import cmd_list
        config = {"aliases": {}}
        cmd_list(None, config, None)
        captured = capsys.readouterr()
        assert "No documents configured" in captured.out

    def test_lists_aliases(self, capsys):
        from main import cmd_list
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
        import core.config as cfg
        from main import cmd_add
        monkeypatch.setattr('core.config.CONFIG_PATH', tmp_config_path)
        config = {"default": "", "aliases": {}}
        cmd_add(config, ["newdoc", "doc_id_999"])
        assert "newdoc" in config["aliases"]
        assert config["aliases"]["newdoc"] == "doc_id_999"

    def test_duplicate_alias(self, capsys):
        from main import cmd_add
        config = {"default": "", "aliases": {"existing": "id1"}}
        cmd_add(config, ["existing", "id2"])
        captured = capsys.readouterr()
        assert "already exists" in captured.out
        assert config["aliases"]["existing"] == "id1"

    def test_missing_args(self, capsys):
        from main import cmd_add
        cmd_add({"aliases": {}}, ["only_alias"])
        captured = capsys.readouterr()
        assert "Usage" in captured.out


class TestCmdRemove:
    def test_removes_alias(self, tmp_config_path, monkeypatch):
        import core.config as cfg
        from main import cmd_remove
        monkeypatch.setattr('core.config.CONFIG_PATH', tmp_config_path)
        config = {"default": "", "aliases": {"test": "id1"}}
        monkeypatch.setattr('builtins.input', lambda _: "y")
        result = cmd_remove(config, ["test"], None)
        assert "test" not in config["aliases"]

    def test_not_found(self, capsys):
        from main import cmd_remove
        result = cmd_remove({"aliases": {}}, ["unknown"], None)
        captured = capsys.readouterr()
        assert "not found" in captured.out


class TestCmdRename:
    def test_renames_alias(self, tmp_config_path, monkeypatch):
        import core.config as cfg
        from main import cmd_rename
        monkeypatch.setattr('core.config.CONFIG_PATH', tmp_config_path)
        config = {"default": "", "aliases": {"old": "id1"}}
        cmd_rename(config, ["old", "new"])
        assert "old" not in config["aliases"]
        assert config["aliases"]["new"] == "id1"

    def test_renames_default(self, tmp_config_path, monkeypatch):
        import core.config as cfg
        from main import cmd_rename
        monkeypatch.setattr('core.config.CONFIG_PATH', tmp_config_path)
        config = {"default": "old", "aliases": {"old": "id1"}}
        cmd_rename(config, ["old", "new"])
        assert config["default"] == "new"

    def test_missing_args(self, capsys):
        from main import cmd_rename
        cmd_rename({"aliases": {}}, ["only_old"])
        captured = capsys.readouterr()
        assert "Usage" in captured.out


class TestCmdCurrent:
    def test_shows_alias(self, capsys):
        from main import cmd_current
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
        from main import cmd_help
        cmd_help()
        captured = capsys.readouterr()
        assert "/switch" in captured.out
        assert "/list" in captured.out
        assert "/add" in captured.out
        assert "/remove" in captured.out
        assert "/rename" in captured.out
        assert "/current" in captured.out
        assert "/edit" in captured.out
        assert "/help" in captured.out
        assert "exit" in captured.out
