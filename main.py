import os.path
import os
import json
import argparse
import sys
from datetime import datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/documents']

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_PATH = os.path.join(BASE_DIR, 'credentials.json')
TOKEN_PATH = os.path.join(BASE_DIR, 'token.json')
CONFIG_PATH = os.path.join(BASE_DIR, 'docs_config.json')


def load_config():
    if not os.path.exists(CONFIG_PATH):
        config = {"default": "log", "aliases": {}}
        save_config(config)
        return config
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)


def save_config(config):
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=2)
        f.write('\n')


def resolve_alias(config, alias):
    aliases = config.get("aliases", {})
    if alias in aliases:
        return aliases[alias]
    return None


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


def cmd_switch(service, config, args, current_alias):
    if not args:
        print("Usage: /switch <alias>")
        return current_alias, None
    alias = args[0]
    doc_id = resolve_alias(config, alias)
    if doc_id is None:
        print(f"Unknown alias '{alias}'. Use /list to see available docs.")
        return current_alias, None
    title = fetch_doc_title(service, doc_id)
    display = f'"{title}"' if title else f'(id: {doc_id})'
    print(f"--- Switched to {display} ({alias}) ---")
    return alias, doc_id


def cmd_list(service, config, current_alias):
    aliases = config.get("aliases", {})
    if not aliases:
        print("No documents configured.")
        return
    print(f"{'Alias':<12} {'Doc ID / Title':<50}")
    print("-" * 62)
    for alias, doc_id in aliases.items():
        marker = "  (active)" if alias == current_alias else ""
        title = fetch_doc_title(service, doc_id)
        display = f'"{title}"' if title else doc_id
        print(f"{alias:<12} {display:<50}{marker}")


def cmd_add(config, args):
    if not args or len(args) < 2:
        print("Usage: /add <alias> <doc_id>")
        return
    alias, doc_id = args[0], args[1]
    aliases = config.setdefault("aliases", {})
    if alias in aliases:
        print(f"Alias '{alias}' already exists. Use /remove first or pick another name.")
        return
    aliases[alias] = doc_id
    save_config(config)
    print(f"--- Added alias '{alias}' ({doc_id}) ---")


def cmd_remove(config, args, current_alias):
    if not args:
        print("Usage: /remove <alias>")
        return None
    alias = args[0]
    aliases = config.get("aliases", {})
    if alias not in aliases:
        print(f"Alias '{alias}' not found.")
        return None
    confirm = input(f"Remove alias '{alias}' ({aliases[alias]})? [y/N] ")
    if confirm.lower() != 'y':
        print("Canceled.")
        return None
    doc_id = aliases.pop(alias)
    default = config.get("default")
    if alias == default:
        config["default"] = next(iter(aliases)) if aliases else ""
    if alias == current_alias:
        save_config(config)
        print(f"--- Removed '{alias}' ---")
        return True
    save_config(config)
    print(f"--- Removed '{alias}' ---")
    return None


def cmd_rename(config, args):
    if not args or len(args) < 2:
        print("Usage: /rename <old_alias> <new_alias>")
        return
    old, new = args[0], args[1]
    aliases = config.get("aliases", {})
    if old not in aliases:
        print(f"Alias '{old}' not found.")
        return
    if new in aliases:
        print(f"Alias '{new}' already exists.")
        return
    aliases[new] = aliases.pop(old)
    if config.get("default") == old:
        config["default"] = new
    save_config(config)
    print(f"--- Renamed '{old}' -> '{new}' ---")


def cmd_current(service, config, current_alias):
    aliases = config.get("aliases", {})
    if current_alias not in aliases:
        print("No active document.")
        return
    doc_id = aliases[current_alias]
    title = fetch_doc_title(service, doc_id)
    print(f"Alias:    {current_alias}")
    print(f"Doc ID:   {doc_id}")
    print(f"Title:    {title if title else '(failed to fetch)'}")


def cmd_help():
    print("Available commands:")
    print("  /switch <alias>   Switch to a different document")
    print("  /list             List all configured documents")
    print("  /add <a> <id>     Add a new document alias")
    print("  /remove <alias>   Remove a document alias")
    print("  /rename <o> <n>   Rename an alias")
    print("  /current          Show active document info")
    print("  /help             Show this message")
    print("  exit              Quit the application")


def dispatch(service, config, line, current_alias, current_doc_id):
    parts = line.strip().split()
    command = parts[0].lower()
    args = parts[1:]

    if command == '/switch':
        alias, doc_id = cmd_switch(service, config, args, current_alias)
        if doc_id is not None:
            return alias, doc_id
    elif command == '/list':
        cmd_list(service, config, current_alias)
    elif command == '/add':
        cmd_add(config, args)
    elif command == '/remove':
        result = cmd_remove(config, args, current_alias)
        if result is True:
            aliases = config.get("aliases", {})
            default = config.get("default", "")
            if aliases and default in aliases:
                title = fetch_doc_title(service, aliases[default])
                display = f'"{title}"' if title else aliases[default]
                print(f"--- Switched to default alias '{default}' ({display}) ---")
                return default, aliases[default]
            elif aliases:
                new_alias = next(iter(aliases))
                title = fetch_doc_title(service, aliases[new_alias])
                display = f'"{title}"' if title else aliases[new_alias]
                print(f"--- Switched to '{new_alias}' ({display}) ---")
                return new_alias, aliases[new_alias]
            else:
                print("No documents remaining. Add one with /add.")
                return None, None
    elif command == '/rename':
        cmd_rename(config, args)
    elif command == '/current':
        cmd_current(service, config, current_alias)
    elif command == '/help':
        cmd_help()
    else:
        print(f"Unknown command: {command}. Type /help for available commands.")

    return current_alias, current_doc_id


def main():
    parser = argparse.ArgumentParser(description="MyDocBot - terminal note-taker for Google Docs")
    parser.add_argument('--doc', '-d', type=str, default=None,
                        help='Start with the given document alias')
    parser.add_argument('--list', '-l', action='store_true',
                        help='List configured aliases and exit')
    parser.add_argument('--add', nargs=2, metavar=('ALIAS', 'DOC_ID'),
                        help='Add a document alias and exit')
    args = parser.parse_args()

    config = load_config()
    aliases = config.get("aliases", {})

    if not aliases:
        print("No documents configured. Add one with:")
        print("  python main.py --add <alias> <doc_id>")
        return

    if args.list:
        for alias, doc_id in aliases.items():
            print(f"  {alias:<12} {doc_id}")
        return

    if args.add:
        alias, doc_id = args.add
        if alias in aliases:
            print(f"Alias '{alias}' already exists.")
            return
        aliases[alias] = doc_id
        save_config(config)
        print(f"Added alias '{alias}' ({doc_id}).")
        return

    service = get_service()

    start_alias = args.doc or config.get("default", "")
    if not start_alias or start_alias not in aliases:
        print(f"Alias '{start_alias}' not found. Available aliases:")
        for a in aliases:
            print(f"  {a}")
        return

    current_alias = start_alias
    current_doc_id = aliases[current_alias]
    current_title = fetch_doc_title(service, current_doc_id)

    if current_title:
        print(f"--- MyDocBot is active on \"{current_title}\" ---")
    else:
        print(f"--- MyDocBot is active on doc {current_doc_id} ---")
    print("Type '/help' for commands, 'exit' to quit.")
    print("Press 'enter' on an empty line to save.")

    while True:
        display_title = current_title or current_doc_id[:20] + "..."
        prompt = f"[{current_alias}] {display_title} > "

        lines = []
        while True:
            try:
                raw = input(prompt if not lines else "> ")
            except (EOFError, KeyboardInterrupt):
                print()
                return

            stripped = raw.strip()

            if stripped.lower() == 'exit' and not lines:
                return

            if stripped.startswith('/') and not lines:
                result = dispatch(service, config, stripped, current_alias, current_doc_id)
                if result and result[0] is not None:
                    new_alias, new_doc_id = result
                    if new_alias != current_alias or new_doc_id != current_doc_id:
                        current_alias = new_alias
                        current_doc_id = new_doc_id
                        current_title = fetch_doc_title(service, current_doc_id)
                        display = f'"{current_title}"' if current_title else current_doc_id
                        print(f"--- Now on {display} ({current_alias}) ---")
                    else:
                        pass
                elif result is None or result == (None, None):
                    if not aliases:
                        print("No documents available. Use /add to add one.")
                        current_alias = None
                        current_doc_id = None
                        current_title = None
                break

            if stripped == "" and not lines:
                continue

            if stripped == "":
                break

            lines.append(raw)

        if not lines or current_doc_id is None:
            continue

        full_note = "\n".join(lines)
        timestamp = datetime.now().strftime("[%m/%d/%y] (%H:%M)|")
        entry_with_time = f"{timestamp} {full_note}"
        prepend_text(service, current_doc_id, entry_with_time)
        doc_label = current_title or current_doc_id[:20] + "..."
        print(f"--- Prepended to \"{doc_label}\" on {timestamp} ---")


if __name__ == '__main__':
    main()
