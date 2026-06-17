import os
import asyncio
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

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


def fetch_doc_title(service, doc_id):
    try:
        doc = service.documents().get(documentId=doc_id).execute()
        return doc.get('title', '(untitled)')
    except Exception:
        return None


def prepend_text(service, doc_id, text):
    request_body = {
        'requests': [{
            'insertText': {
                'location': {'index': 1},
                'text': f"{text}\n\n"
            }
        }]
    }
    service.documents().batchUpdate(
        documentId=doc_id, body=request_body
    ).execute()


class AsyncGoogleDocs:
    def __init__(self):
        self._service = get_service()

    async def _run(self, fn):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, fn)

    async def prepend_text(self, doc_id, text):
        body = {
            'requests': [{
                'insertText': {
                    'location': {'index': 1},
                    'text': f"{text}\n\n"
                }
            }]
        }
        await self._run(
            lambda: self._service.documents().batchUpdate(
                documentId=doc_id, body=body
            ).execute()
        )

    async def fetch_doc_title(self, doc_id):
        doc = await self._run(
            lambda: self._service.documents().get(documentId=doc_id).execute()
        )
        return doc.get('title', '(untitled)')

    async def fetch_recent_notes(self, doc_id, count=2):
        doc = await self._run(
            lambda: self._service.documents().get(documentId=doc_id).execute()
        )
        return parse_entries(doc, count)


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
    import re
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
