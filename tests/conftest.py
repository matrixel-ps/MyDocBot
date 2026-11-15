import glob
import os
import tempfile

import pytest


def _remove_with_backups(path):
    """Delete a temp data file, any <path>.corrupt-* backups made from it (B11),
    and its lock files (<path>.lock, <path>.flush.lock; A6)."""
    for p in [path, *glob.glob(f"{path}.corrupt-*"), *glob.glob(f"{path}*.lock")]:
        if os.path.exists(p):
            os.unlink(p)


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path, monkeypatch):
    """Point every personal data path into tmp_path, so no test can read or write
    the real ~/.config/mydocbot or the old repo-root files. The tmp_*_path
    fixtures below override individual paths on top of this."""
    data_dir = tmp_path / 'mydocbot-data'
    monkeypatch.setattr('core.paths.DATA_DIR', str(data_dir))
    monkeypatch.setattr('core.paths.LEGACY_DIR', str(tmp_path / 'legacy'))
    monkeypatch.setattr('core.config.CONFIG_PATH', str(data_dir / 'docs_config.json'))
    monkeypatch.setattr('core.config.READ_CONFIG_PATH', str(data_dir / 'read_config.json'))
    monkeypatch.setattr('core.parser.TAGS_INDEX_PATH', str(data_dir / 'tags_index.json'))
    monkeypatch.setattr('core.parser.PENDING_PATH', str(data_dir / 'pending_queue.json'))
    monkeypatch.setattr('core.google_docs.TOKEN_PATH', str(data_dir / 'token.json'))
    monkeypatch.setattr('core.google_docs.CREDENTIALS_PATH', str(data_dir / 'credentials.json'))
    monkeypatch.setattr('core.discord_handler.DISCORD_CONFIG_PATH', str(data_dir / 'discord_config.json'))
    monkeypatch.setattr('core.discord_handler.DISCORD_TOKEN_PATH', str(data_dir / 'discord_token'))
    monkeypatch.setattr('core.doc_watch.WATCH_STATE_PATH', str(data_dir / 'watch_state.json'))
    # tmp_path, not data_dir: every sent note writes it, and data_dir must stay
    # uncreated for the paths tests (first-run creation and migration).
    monkeypatch.setattr('core.undo.LAST_WRITE_PATH', str(tmp_path / 'last_write.json'))
    return data_dir


@pytest.fixture
def sample_config():
    return {
        "default": "log",
        "aliases": {
            "log": "doc_id_123",
            "work": "doc_id_456",
            "personal": "doc_id_789",
        }
    }


@pytest.fixture
def tmp_config_path(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    tmp_path = tmp.name
    tmp.close()
    monkeypatch.setattr('core.config.CONFIG_PATH', tmp_path)
    yield tmp_path
    _remove_with_backups(tmp_path)


@pytest.fixture
def tmp_read_config_path(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    tmp_path = tmp.name
    tmp.close()
    monkeypatch.setattr('core.config.READ_CONFIG_PATH', tmp_path)
    yield tmp_path
    _remove_with_backups(tmp_path)


@pytest.fixture
def tmp_tags_index_path(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    tmp_path = tmp.name
    tmp.close()
    monkeypatch.setattr('core.parser.TAGS_INDEX_PATH', tmp_path)
    yield tmp_path
    _remove_with_backups(tmp_path)


@pytest.fixture
def tmp_pending_path(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    tmp_path = tmp.name
    tmp.close()
    monkeypatch.setattr('core.parser.PENDING_PATH', tmp_path)
    yield tmp_path
    _remove_with_backups(tmp_path)


def make_doc_response(text: str) -> dict:
    """Wrap plain text into a Google Doc API body.content structure."""
    return {
        "body": {
            "content": [
                {"paragraph": {"elements": [{"textRun": {"content": text}}]}}
            ]
        }
    }


@pytest.fixture
def mock_service(monkeypatch):
    class MockService:
        def documents(self):
            return self

        def get(self, documentId=None, fields=None):
            return self

        def batchUpdate(self, documentId=None, body=None):
            return self

        def execute(self):
            return {}
    return MockService()


class RecordingService:
    """Mock Docs service that records each successful batchUpdate as
    (doc_id, text), in call order, and raises ConnectionError for any doc_id
    in `failing` (so prepend_text() returns False). documents().get() returns
    an empty doc."""

    def __init__(self, failing=()) -> None:
        self.calls: list[tuple[str, str]] = []
        self.failing = set(failing)
        self._pending: tuple[str, str] | None = None

    def documents(self):
        return self

    def get(self, documentId=None, fields=None):
        self._pending = None
        return self

    def batchUpdate(self, documentId=None, body=None):
        assert body is not None
        text = body['requests'][0]['insertText']['text']
        self._pending = (documentId or "", text.rstrip('\n'))
        return self

    def execute(self):
        if self._pending is None:
            return {}
        doc_id, text = self._pending
        self._pending = None
        if doc_id in self.failing:
            raise ConnectionError("offline")
        self.calls.append((doc_id, text))
        return {}
