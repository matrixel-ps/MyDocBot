import os.path
import os
from datetime import datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/documents']

# Hardcoded ID of the Google Document
DOCUMENT_ID = 'YOUR_DOC_ID'

# Define paths relative to this script's location
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_PATH = os.path.join(BASE_DIR, 'credentials.json')
TOKEN_PATH = os.path.join(BASE_DIR, 'token.json')


def get_service():
    creds = None
    # Use TOKEN_PATH instead of just 'token.json'
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Use the absolute path CREDENTIALS_PATH here
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)

        # Save the token to the absolute path
        with open(TOKEN_PATH, 'w') as token:
            token.write(creds.to_json())

    return build('docs', 'v1', credentials=creds)


def prepend_text(service, text):
    requests = [{'insertText': {'location': {'index': 1}, 'text': f"{text}\n\n"}}]
    service.documents().batchUpdate(documentId=DOCUMENT_ID, body={'requests': requests}).execute()


def main():
    service = get_service()
    print("--- MyDocBot is active. Type your notes below (Type 'exit' to quit) ---")
    print("Press 'enter' on an empty line to save.")

    while True:
        lines = []
        while True:
            line = input("> ")

            if line.lower() == 'exit' and not lines:
                return
            if line == "":
                break
            lines.append(line)
        if lines:
            full_note = "\n".join(lines)
            timestamp = datetime.now().strftime("[%m/%d/%y] (%H:%M)|")
            entry_with_time = f"{timestamp} {full_note}"
            prepend_text(service, entry_with_time)
            print(f"--- Prepended to MyDocBot Log on {timestamp} ---")


if __name__ == '__main__':
    main()