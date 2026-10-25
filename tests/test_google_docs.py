"""Tests for get_service() sign-in handling (B4).

Credentials, the OAuth flow and build() are all patched, and TOKEN_PATH /
CREDENTIALS_PATH point into tmp_path, so no real OAuth runs and the real
token.json is never read or written.
"""
import os
from unittest.mock import MagicMock, patch

import pytest
from google.auth.exceptions import RefreshError, TransportError

from core import google_docs

OLD_TOKEN = '{"old": true}'
NEW_TOKEN = '{"new": true}'


@pytest.fixture
def auth_paths(tmp_path, monkeypatch):
    token = tmp_path / 'token.json'
    creds_file = tmp_path / 'credentials.json'
    creds_file.write_text('{}')
    monkeypatch.setattr('core.google_docs.TOKEN_PATH', str(token))
    monkeypatch.setattr('core.google_docs.CREDENTIALS_PATH', str(creds_file))
    return token, creds_file


def _creds(valid=False, expired=True, refresh_error=None):
    creds = MagicMock()
    creds.valid = valid
    creds.expired = expired
    creds.refresh_token = 'refresh'
    creds.to_json.return_value = NEW_TOKEN
    if refresh_error:
        creds.refresh.side_effect = refresh_error
    return creds


def _get_service(saved_creds=None, load_error=None):
    """Call get_service() with Google auth patched; return (result, flow_mock, build_mock)."""
    flow = MagicMock()
    flow.run_local_server.return_value = _creds(valid=True, expired=False)
    load = MagicMock(return_value=saved_creds, side_effect=load_error)
    with patch.object(google_docs.Credentials, 'from_authorized_user_file', load), \
            patch.object(google_docs.InstalledAppFlow, 'from_client_secrets_file', return_value=flow), \
            patch.object(google_docs, 'build', return_value='service') as build:
        return google_docs.get_service(), flow, build


class TestGetService:
    def test_valid_token_skips_refresh_and_flow(self, auth_paths):
        token, _ = auth_paths
        token.write_text(OLD_TOKEN)
        creds = _creds(valid=True, expired=False)
        result, flow, build = _get_service(creds)
        assert result == 'service'
        creds.refresh.assert_not_called()
        flow.run_local_server.assert_not_called()
        assert token.read_text() == OLD_TOKEN

    def test_expired_token_refreshes_and_saves(self, auth_paths):
        token, _ = auth_paths
        token.write_text(OLD_TOKEN)
        creds = _creds()
        result, flow, _ = _get_service(creds)
        assert result == 'service'
        creds.refresh.assert_called_once()
        flow.run_local_server.assert_not_called()
        assert token.read_text() == NEW_TOKEN

    def test_revoked_token_reruns_sign_in(self, auth_paths, capsys):
        token, _ = auth_paths
        token.write_text(OLD_TOKEN)
        creds = _creds(refresh_error=RefreshError('invalid_grant'))
        result, flow, _ = _get_service(creds)
        assert result == 'service'
        flow.run_local_server.assert_called_once()
        assert token.read_text() == NEW_TOKEN
        assert 'sign in again' in capsys.readouterr().err

    def test_revoked_token_without_credentials_file(self, auth_paths):
        token, creds_file = auth_paths
        token.write_text(OLD_TOKEN)
        creds_file.unlink()
        creds = _creds(refresh_error=RefreshError('invalid_grant'))
        with pytest.raises(SystemExit, match='not found'):
            _get_service(creds)
        assert not os.path.exists(token)

    def test_offline_refresh_exits_and_keeps_token(self, auth_paths):
        token, _ = auth_paths
        token.write_text(OLD_TOKEN)
        creds = _creds(refresh_error=TransportError('no network'))
        with pytest.raises(SystemExit, match="Couldn't reach Google"):
            _get_service(creds)
        assert token.read_text() == OLD_TOKEN

    def test_corrupt_token_reruns_sign_in(self, auth_paths, capsys):
        token, _ = auth_paths
        token.write_text('not json')
        result, flow, _ = _get_service(load_error=ValueError('bad json'))
        assert result == 'service'
        flow.run_local_server.assert_called_once()
        assert token.read_text() == NEW_TOKEN
        assert 'sign in again' in capsys.readouterr().err

    def test_no_token_runs_sign_in(self, auth_paths):
        token, _ = auth_paths
        result, flow, _ = _get_service()
        assert result == 'service'
        flow.run_local_server.assert_called_once()
        assert token.read_text() == NEW_TOKEN


# ---------------------------------------------------------------------------
# Write-failure classification (F6)
# ---------------------------------------------------------------------------

def _http(status):
    from googleapiclient.errors import HttpError
    return HttpError(MagicMock(status=status, reason='x'), b'{}')


class TestClassifyWriteError:
    @pytest.mark.parametrize("status,needle", [
        (404, "not found"), (403, "permission"), (400, "rejected"),
    ])
    def test_permanent_http(self, status, needle):
        failure = google_docs.classify_write_error(_http(status))
        assert failure.kind == "permanent"
        assert needle in failure.message

    def test_401_is_auth(self):
        assert google_docs.classify_write_error(_http(401)).kind == "auth"

    def test_refresh_error_is_auth(self):
        failure = google_docs.classify_write_error(RefreshError("invalid_grant"))
        assert failure.kind == "auth"
        assert "restart" in failure.message

    @pytest.mark.parametrize("error", [
        _http(429), _http(503), ConnectionError("down"), TimeoutError("slow"),
        TransportError("no net"), RuntimeError("something odd"),
    ])
    def test_transient(self, error):
        assert google_docs.classify_write_error(error).kind == "transient"

    def test_httplib2_network_error_is_transient(self):
        import httplib2
        failure = google_docs.classify_write_error(httplib2.ServerNotFoundError("no dns"))
        assert failure.kind == "transient"
        assert "offline" in failure.message


class TestTryPrepend:
    def _service(self, error=None):
        service = MagicMock()
        if error:
            service.documents.return_value.batchUpdate.return_value.execute.side_effect = error
        return service

    def test_success_returns_none(self):
        assert google_docs.try_prepend(self._service(), "doc", "text") is None

    def test_failure_returns_classified(self, capsys):
        failure = google_docs.try_prepend(self._service(_http(404)), "doc", "text")
        assert failure == google_docs.WriteFailure("permanent", failure.message)
        assert "not found" in capsys.readouterr().err

    def test_prepend_text_still_bool(self):
        assert google_docs.prepend_text(self._service(), "doc", "t") is True
        assert google_docs.prepend_text(self._service(_http(403)), "doc", "t") is False
