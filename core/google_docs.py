import os
import re
import sys
import time

from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .paths import data_path

SCOPES = ['https://www.googleapis.com/auth/documents']

CREDENTIALS_PATH = data_path('credentials.json')
TOKEN_PATH = data_path('token.json')

# In-process cache of doc_id -> title, to avoid re-fetching the same doc's
# title on every /list, /switch, or startup call within a single session.
# Only successful lookups are cached; failures (None) are always retried.
_TITLE_CACHE: dict[str, str] = {}


def invalidate_title_cache(doc_id=None):
    """Drop a single cached title (or all of them if doc_id is None)."""
    if doc_id is None:
        _TITLE_CACHE.clear()
    else:
        _TITLE_CACHE.pop(doc_id, None)


def _discard_token(reason):
    """Delete an unusable token.json so the browser sign-in runs again."""
    print(f"Saved Google sign-in {reason}; you'll need to sign in again.", file=sys.stderr)
    try:
        os.unlink(TOKEN_PATH)
    except FileNotFoundError:
        pass


def _load_saved_creds():
    if not os.path.exists(TOKEN_PATH):
        return None
    try:
        return Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    except ValueError:
        _discard_token("is unreadable")
        return None


def _refresh(creds):
    """Refresh creds in place. Returns False if the token was rejected and discarded.

    An offline refresh (TransportError) exits instead, keeping token.json:
    the token is still good once the network is back.
    """
    try:
        creds.refresh(Request())
        return True
    except RefreshError:
        _discard_token("has expired or been revoked")
        return False
    except TransportError as e:
        raise SystemExit(
            f"Error: Couldn't reach Google to refresh your sign-in ({e}).\n"
            "Check your internet connection and try again."
        ) from None


def get_service():
    creds = _load_saved_creds()

    if not creds or not creds.valid:
        refreshed = creds and creds.expired and creds.refresh_token and _refresh(creds)
        if not refreshed:
            if not os.path.exists(CREDENTIALS_PATH):
                raise SystemExit(
                    f"Error: '{CREDENTIALS_PATH}' not found.\n"
                    "Download OAuth 2.0 credentials (Desktop app) from the Google Cloud "
                    "Console and save them at that path. "
                    "See README.md 'Setup' section for details."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, 'w') as token:
            token.write(creds.to_json())
        try:
            os.chmod(TOKEN_PATH, 0o600)
        except OSError:
            pass  # best-effort on platforms without POSIX permission support

    return build('docs', 'v1', credentials=creds)


def _api_call_with_retry(fn, max_retries=3):
    for attempt in range(max_retries):
        try:
            return fn()
        except HttpError as e:
            if e.resp.status in (429, 500, 502, 503, 504) and attempt < max_retries - 1:
                time.sleep(1 * (2 ** attempt))
                continue
            raise
        except (ConnectionError, TimeoutError):
            if attempt < max_retries - 1:
                time.sleep(1 * (2 ** attempt))
                continue
            raise


def fetch_doc(service, doc_id):
    """The full document body, with retry. Raises on failure."""
    return _api_call_with_retry(
        lambda: service.documents().get(documentId=doc_id).execute()
    )


def fetch_doc_title(service, doc_id, use_cache=True):
    if use_cache and doc_id in _TITLE_CACHE:
        return _TITLE_CACHE[doc_id]
    try:
        doc = fetch_doc(service, doc_id)
        title = doc.get('title', '(untitled)')
        _TITLE_CACHE[doc_id] = title
        return title
    except Exception:
        return None


def prepend_text(service, doc_id, text):
    try:
        request_body = {
            'requests': [{
                'insertText': {
                    'location': {'index': 1},
                    'text': f"{text}\n\n"
                }
            }]
        }
        _api_call_with_retry(
            lambda: service.documents().batchUpdate(
                documentId=doc_id, body=request_body
            ).execute()
        )
        return True
    except Exception as e:
        print(f"Error: Failed to prepend note — {e}", file=sys.stderr)
        return False


def parse_entries_readable(doc, count=2):
    content = doc.get('body', {}).get('content', [])
    full_text = []
    for elem in content:
        para = elem.get('paragraph')
        if not para:
            continue
        for el in para.get('elements', []):
            run = el.get('textRun')
            if run:
                full_text.append(run.get('content', ''))
    text = ''.join(full_text).replace('\r\n', '\n').replace('\r', '\n')

    parts = re.split(
        r'(?=^\d{1,2}/\d{1,2}/\d{4}\n\[\d{1,2}\.\d{1,2}\]$)',
        text.strip(),
        flags=re.MULTILINE
    )
    entries = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        lines = part.split('\n')
        if len(lines) < 2:
            continue
        date_line = lines[0].strip()
        time_line = lines[1].strip()
        body = '\n'.join(lines[2:]).strip()

        date_match = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})$', date_line)
        if not date_match:
            continue
        time_match = re.match(r'^\[(\d{1,2})\.(\d{1,2})\]', time_line)
        if not time_match:
            continue

        ts = f"[{date_line}] [{time_match.group(1)}.{time_match.group(2)}]|"
        entries.append((ts, body))

    return entries[:count]


def parse_entries(doc, count=2):
    content = doc.get('body', {}).get('content', [])
    full_text = []
    for elem in content:
        para = elem.get('paragraph')
        if not para:
            continue
        for el in para.get('elements', []):
            run = el.get('textRun')
            if run:
                full_text.append(run.get('content', ''))
    text = ''.join(full_text)
    # Only a full "[MM/DD/YY] (HH:MM)|" header at the start of a line begins a
    # new entry, so a date written inside a note body doesn't split it (B5).
    parts = re.split(r'^(?=\[\d{2}/\d{2}/\d{2}\]\s*\(\d{2}:\d{2}\)\|)', text, flags=re.MULTILINE)
    entries = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        m = re.match(r'(\[\d{2}/\d{2}/\d{2}\]\s*\(\d{2}:\d{2}\)\|)', part)
        if m:
            ts = m.group(1)
            body = part[len(ts):].strip()
            entries.append((ts, body))
    return entries[:count]
