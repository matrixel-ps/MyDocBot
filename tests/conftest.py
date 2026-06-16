import pytest
import json
import os
import tempfile


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
def tmp_tags_index_path(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    tmp_path = tmp.name
    tmp.close()
    monkeypatch.setattr('core.parser.TAGS_INDEX_PATH', tmp_path)
    yield tmp_path
    if os.path.exists(tmp_path):
        os.unlink(tmp_path)


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
