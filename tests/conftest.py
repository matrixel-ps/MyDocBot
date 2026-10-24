import os
import tempfile

import pytest


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
    if os.path.exists(tmp_path):
        os.unlink(tmp_path)


@pytest.fixture
def tmp_read_config_path(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    tmp_path = tmp.name
    tmp.close()
    monkeypatch.setattr('core.config.READ_CONFIG_PATH', tmp_path)
    yield tmp_path
    if os.path.exists(tmp_path):
        os.unlink(tmp_path)


@pytest.fixture
def tmp_tags_index_path(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    tmp_path = tmp.name
    tmp.close()
    monkeypatch.setattr('core.parser.TAGS_INDEX_PATH', tmp_path)
    yield tmp_path
    if os.path.exists(tmp_path):
        os.unlink(tmp_path)


@pytest.fixture
def tmp_pending_path(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    tmp_path = tmp.name
    tmp.close()
    monkeypatch.setattr('core.parser.PENDING_PATH', tmp_path)
    yield tmp_path
    if os.path.exists(tmp_path):
        os.unlink(tmp_path)


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

        def get(self, documentId=None):
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

    def get(self, documentId=None):
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
