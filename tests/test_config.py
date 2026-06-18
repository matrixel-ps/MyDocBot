import json
import os

import core.config as cfg


class TestLoadConfig:
    def test_creates_default_when_missing(self, tmp_config_path):
        if os.path.exists(tmp_config_path):
            os.unlink(tmp_config_path)
        result = cfg.load_config()
        assert result["default"] == "log"
        assert result["aliases"] == {}
        assert os.path.exists(tmp_config_path)

    def test_loads_existing(self, tmp_config_path, sample_config):
        with open(tmp_config_path, 'w') as f:
            json.dump(sample_config, f)
        result = cfg.load_config()
        assert result == sample_config


class TestSaveConfig:
    def test_writes_config(self, tmp_config_path):
        data = {"default": "test", "aliases": {"a": "id1"}}
        cfg.save_config(data)
        with open(tmp_config_path) as f:
            loaded = json.load(f)
        assert loaded == data

    def test_round_trip(self, tmp_config_path, sample_config):
        cfg.save_config(sample_config)
        loaded = cfg.load_config()
        assert loaded == sample_config


class TestResolveAlias:
    def test_found(self, sample_config):
        assert cfg.resolve_alias(sample_config, "log") == "doc_id_123"
        assert cfg.resolve_alias(sample_config, "work") == "doc_id_456"
        assert cfg.resolve_alias(sample_config, "personal") == "doc_id_789"

    def test_not_found(self, sample_config):
        assert cfg.resolve_alias(sample_config, "nonexistent") is None

    def test_empty_aliases(self):
        config = {"default": "", "aliases": {}}
        assert cfg.resolve_alias(config, "anything") is None


class TestLoadConfigErrors:
    def test_corrupt_json_returns_fallback(self, tmp_config_path):
        with open(tmp_config_path, 'w') as f:
            f.write("{invalid json here")
        result = cfg.load_config()
        assert result == {"default": "", "aliases": {}}

    def test_corrupt_json_overwrites_with_valid(self, tmp_config_path):
        with open(tmp_config_path, 'w') as f:
            f.write("{broken")
        cfg.load_config()
        with open(tmp_config_path) as f:
            loaded = json.load(f)
        assert loaded == {"default": "", "aliases": {}}

    def test_corrupt_json_prints_warning(self, tmp_config_path, capsys):
        with open(tmp_config_path, 'w') as f:
            f.write("{garbage}")
        cfg.load_config()
        captured = capsys.readouterr()
        assert "Warning:" in captured.err
        assert "Corrupt config" in captured.err


class TestGetHistorySize:
    def test_default_when_missing(self):
        config = {"default": "log", "aliases": {}}
        assert cfg.get_history_size(config) == 20

    def test_returns_custom_value(self):
        config = {"default": "log", "aliases": {}, "history_size": 75}
        assert cfg.get_history_size(config) == 75

    def test_coerces_string_to_int(self):
        config = {"default": "log", "aliases": {}, "history_size": "50"}
        assert cfg.get_history_size(config) == 50

    def test_returns_default_on_bad_value(self):
        config = {"default": "log", "aliases": {}, "history_size": "bad"}
        assert cfg.get_history_size(config) == 20
