import os
import re
import sys
import time

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ['https://www.googleapis.com/auth/documents']

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CREDENTIALS_PATH = os.path.join(BASE_DIR, 'credentials.json')
TOKEN_PATH = os.path.join(BASE_DIR, 'token.json')


def get_service():
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, 'w') as token:
            token.write(creds.to_json())

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


def fetch_doc_title(service, doc_id):
    try:
        doc = _api_call_with_retry(
            lambda: service.documents().get(documentId=doc_id).execute()
        )
        return doc.get('title', '(untitled)')
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
    parts = re.split(r'(?=\[\d{2}/\d{2}/\d{2}\])', text)
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
