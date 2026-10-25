"""Tests for the data directory location and one-time migration (F2)."""
import os
import stat

from core import paths


class TestResolveDataDir:
    def test_mydocbot_home_wins(self, tmp_path):
        env = {'MYDOCBOT_HOME': str(tmp_path / 'mine'), 'XDG_CONFIG_HOME': str(tmp_path / 'xdg')}
        assert paths.resolve_data_dir(env) == str(tmp_path / 'mine')

    def test_xdg_config_home(self, tmp_path):
        env = {'XDG_CONFIG_HOME': str(tmp_path / 'xdg')}
        assert paths.resolve_data_dir(env) == str(tmp_path / 'xdg' / 'mydocbot')

    def test_default_is_dot_config(self, monkeypatch, tmp_path):
        monkeypatch.setenv('HOME', str(tmp_path))
        assert paths.resolve_data_dir({}) == str(tmp_path / '.config' / 'mydocbot')

    def test_empty_values_ignored(self, monkeypatch, tmp_path):
        monkeypatch.setenv('HOME', str(tmp_path))
        env = {'MYDOCBOT_HOME': '', 'XDG_CONFIG_HOME': ''}
        assert paths.resolve_data_dir(env) == str(tmp_path / '.config' / 'mydocbot')

    def test_tilde_expanded(self, monkeypatch, tmp_path):
        monkeypatch.setenv('HOME', str(tmp_path))
        assert paths.resolve_data_dir({'MYDOCBOT_HOME': '~/notes'}) == str(tmp_path / 'notes')


class TestPrepareDataDir:
    def _legacy(self, tmp_path, **files):
        legacy = tmp_path / 'repo'
        legacy.mkdir()
        for name, content in files.items():
            (legacy / name).write_text(content)
        return legacy

    def test_creates_dir_owner_only(self, tmp_path):
        data = tmp_path / 'data'
        paths.prepare_data_dir(str(data), str(self._legacy(tmp_path)))
        assert stat.S_IMODE(os.stat(data).st_mode) == 0o700

    def test_copies_existing_files_and_keeps_originals(self, tmp_path, capsys):
        legacy = self._legacy(tmp_path, **{'docs_config.json': '{"a": 1}', 'token.json': 'tok'})
        data = tmp_path / 'data'
        copied = paths.prepare_data_dir(str(data), str(legacy))
        assert sorted(copied) == ['docs_config.json', 'token.json']
        assert (data / 'docs_config.json').read_text() == '{"a": 1}'
        assert (data / 'token.json').read_text() == 'tok'
        assert stat.S_IMODE(os.stat(data / 'token.json').st_mode) == 0o600
        assert (legacy / 'docs_config.json').exists()
        assert (legacy / 'token.json').exists()
        err = capsys.readouterr().err
        assert str(data) in err and 'docs_config.json' in err

    def test_ignores_other_files(self, tmp_path):
        legacy = self._legacy(tmp_path, **{'docs_config.example.json': '{}', 'notes.txt': 'x'})
        data = tmp_path / 'data'
        assert paths.prepare_data_dir(str(data), str(legacy)) == []
        assert os.listdir(data) == []

    def test_existing_dir_is_never_migrated_into(self, tmp_path, capsys):
        legacy = self._legacy(tmp_path, **{'pending_queue.json': '[stale]', 'docs_config.json': 'old'})
        data = tmp_path / 'data'
        data.mkdir()
        (data / 'docs_config.json').write_text('new')
        assert paths.prepare_data_dir(str(data), str(legacy)) == []
        assert (data / 'docs_config.json').read_text() == 'new'
        assert not (data / 'pending_queue.json').exists()
        assert capsys.readouterr().err == ''

    def test_second_run_does_nothing(self, tmp_path, capsys):
        legacy = self._legacy(tmp_path, **{'pending_queue.json': '[1]'})
        data = tmp_path / 'data'
        paths.prepare_data_dir(str(data), str(legacy))
        (data / 'pending_queue.json').unlink()  # queue emptied and deleted by the app
        capsys.readouterr()
        assert paths.prepare_data_dir(str(data), str(legacy)) == []
        assert not (data / 'pending_queue.json').exists()
        assert capsys.readouterr().err == ''

    def test_data_dir_same_as_legacy(self, tmp_path):
        data = tmp_path / 'same'
        assert paths.prepare_data_dir(str(data), str(data)) == []

    def test_defaults_use_module_paths(self, _isolate_data_dir):
        assert paths.prepare_data_dir() == []
        assert os.path.isdir(_isolate_data_dir)
