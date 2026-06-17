import shutil

from core.commands import _resolve_editor


class TestResolveEditor:
    def test_uses_editor_env(self, monkeypatch):
        monkeypatch.setenv('EDITOR', 'vim')
        monkeypatch.setattr('shutil.which', lambda cmd: f'/usr/bin/{cmd}' if cmd == 'vim' else None)
        result = _resolve_editor()
        assert result == ['vim']

    def test_uses_editor_with_args(self, monkeypatch):
        monkeypatch.setenv('EDITOR', 'code --wait')
        monkeypatch.setattr('shutil.which', lambda cmd: '/usr/bin/code' if cmd == 'code' else None)
        result = _resolve_editor()
        assert result == ['code', '--wait']

    def test_falls_back_to_available_editor(self, monkeypatch):
        monkeypatch.delenv('EDITOR', raising=False)
        result = _resolve_editor()
        assert result is None or shutil.which(result[0]) is not None

    def test_returns_none_when_no_editor(self, monkeypatch):
        monkeypatch.delenv('EDITOR', raising=False)
        monkeypatch.setattr('shutil.which', lambda cmd: None)
        result = _resolve_editor()
        assert result is None
