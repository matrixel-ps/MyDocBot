import os.path
import os
import argparse
import tempfile
import subprocess
import shutil
import shlex
from datetime import datetime
from core import config, google_docs, parser


def _resolve_editor():
    editor = os.environ.get('EDITOR')
    if editor:
        parts = shlex.split(editor)
        if shutil.which(parts[0]):
            return parts
    for candidate in ['vim', 'nano', 'vi']:
        path = shutil.which(candidate)
        if path:
            return [path]
    return None


def open_editor():
    editor_parts = _resolve_editor()
    if not editor_parts:
        print("No editor found. Set $EDITOR or install vim/nano.")
        return None

    tmp = tempfile.NamedTemporaryFile(
        mode='w+', suffix='.md', delete=False
    )
    tmp_path = tmp.name
    tmp.write("# Write your note here (lines starting with # are ignored)\n")
    tmp.close()

    try:
        ret = subprocess.call(editor_parts + [tmp_path])
        if ret != 0:
            print(f"Editor exited with code {ret}. Note discarded.")
            return None

        with open(tmp_path, 'r') as f:
            raw_lines = f.readlines()

        content_lines = []
        for line in raw_lines:
            stripped = line.strip()
            if stripped.startswith('#'):
                continue
            content_lines.append(line.rstrip('\n'))

        content = "\n".join(content_lines).strip()
        if not content:
            print("Empty note, canceled.")
            return None

        return content

    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def cmd_switch(service, svc_config, args, current_alias):
    if not args:
        print("Usage: /switch <alias>")
        return current_alias, None
    alias = args[0]
    doc_id = config.resolve_alias(svc_config, alias)
    if doc_id is None:
        print(f"Unknown alias '{alias}'. Use /list to see available docs.")
        return current_alias, None
    title = google_docs.fetch_doc_title(service, doc_id)
    display = f'"{title}"' if title else f'(id: {doc_id})'
    print(f"--- Switched to {display} ({alias}) ---")
    return alias, doc_id


def cmd_list(service, svc_config, current_alias):
    aliases = svc_config.get("aliases", {})
    if not aliases:
        print("No documents configured.")
        return
    print(f"{'Alias':<12} {'Doc ID / Title':<50}")
    print("-" * 62)
    for alias, doc_id in aliases.items():
        marker = "  (active)" if alias == current_alias else ""
        title = google_docs.fetch_doc_title(service, doc_id)
        display = f'"{title}"' if title else doc_id
        print(f"{alias:<12} {display:<50}{marker}")


def cmd_add(svc_config, args):
    if not args or len(args) < 2:
        print("Usage: /add <alias> <doc_id>")
        return
    alias, doc_id = args[0], args[1]
    aliases = svc_config.setdefault("aliases", {})
    if alias in aliases:
        print(f"Alias '{alias}' already exists. Use /remove first or pick another name.")
        return
    aliases[alias] = doc_id
    config.save_config(svc_config)
    print(f"--- Added alias '{alias}' ({doc_id}) ---")


def cmd_remove(svc_config, args, current_alias):
    if not args:
        print("Usage: /remove <alias>")
        return False
    alias = args[0]
    aliases = svc_config.get("aliases", {})
    if alias not in aliases:
        print(f"Alias '{alias}' not found.")
        return False
    confirm = input(f"Remove alias '{alias}' ({aliases[alias]})? [y/N] ")
    if confirm.lower() != 'y':
        print("Canceled.")
        return False
    aliases.pop(alias)
    default = svc_config.get("default")
    if alias == default:
        svc_config["default"] = next(iter(aliases)) if aliases else ""
    config.save_config(svc_config)
    print(f"--- Removed '{alias}' ---")
    return True


def cmd_rename(svc_config, args):
    if not args or len(args) < 2:
        print("Usage: /rename <old_alias> <new_alias>")
        return
    old, new = args[0], args[1]
    aliases = svc_config.get("aliases", {})
    if old not in aliases:
        print(f"Alias '{old}' not found.")
        return
    if new in aliases:
        print(f"Alias '{new}' already exists.")
        return
    aliases[new] = aliases.pop(old)
    if svc_config.get("default") == old:
        svc_config["default"] = new
    config.save_config(svc_config)
    print(f"--- Renamed '{old}' -> '{new}' ---")


def cmd_current(service, svc_config, current_alias):
    aliases = svc_config.get("aliases", {})
    if current_alias not in aliases:
        print("No active document.")
        return
    doc_id = aliases[current_alias]
    title = google_docs.fetch_doc_title(service, doc_id)
    print(f"Alias:    {current_alias}")
    print(f"Doc ID:   {doc_id}")
    print(f"Title:    {title if title else '(failed to fetch)'}")


def cmd_tag(service, svc_config, args, current_alias, current_doc_id):
    if not args:
        cmd_tag_list(svc_config, current_doc_id)
    elif args[0] == 'list':
        cmd_tag_list(svc_config, current_doc_id)
    elif args[0] == 'search' and len(args) >= 2:
        cmd_tag_search(svc_config, args[1], current_doc_id)
    elif args[0] == 'stats':
        cmd_tag_stats(svc_config, current_doc_id)
    else:
        print("Usage: /tag list | /tag search <tag> | /tag stats")


def cmd_tag_list(svc_config, current_doc_id):
    tags = parser.load_tags_index()
    if not tags:
        print("No tags indexed yet.")
        return
    print(f"{'Tag':<22} {'Notes':<6}")
    print("-" * 28)
    for tag, entries in sorted(tags.items()):
        count = len([e for e in entries if e["doc_id"] == current_doc_id])
        if count > 0:
            print(f"  #{tag:<18} {count}")


def cmd_tag_search(svc_config, tag, current_doc_id):
    tags = parser.load_tags_index()
    tag = tag.lower().lstrip('#')
    entries = tags.get(tag, [])
    doc_entries = [e for e in entries if e["doc_id"] == current_doc_id]
    if not doc_entries:
        print(f"No notes with #{tag}")
        return
    print(f"#{tag}  ({len(doc_entries)} notes)\n")
    for e in doc_entries:
        print(f"  {e['ts']} {e['preview']}")


def cmd_tag_stats(svc_config, current_doc_id):
    tags = parser.load_tags_index()
    if not tags:
        print("No tags indexed yet.")
        return
    doc_tags = {}
    for tag, entries in tags.items():
        count = len([e for e in entries if e["doc_id"] == current_doc_id])
        if count > 0:
            doc_tags[tag] = count
    if not doc_tags:
        print("No tags for this document.")
        return
    max_count = max(doc_tags.values()) if doc_tags else 1
    print(f"{'Tag':<22} {'Count':<6}  Bar")
    print("-" * 50)
    for tag, count in sorted(doc_tags.items(), key=lambda x: -x[1]):
        bar = '█' * int(count / max_count * 20) if max_count else ''
        print(f"  #{tag:<18} {count:<5} {bar}")


def cmd_help():
    print("Available commands:")
    print("  /edit             Open $EDITOR to compose a multi-line note")
    print("  /switch <alias>   Switch to a different document")
    print("  /list             List all configured documents")
    print("  /add <a> <id>     Add a new document alias")
    print("  /remove <alias>   Remove a document alias")
    print("  /rename <o> <n>   Rename an alias")
    print("  /current          Show active document info")
    print("  /tag list         Show all indexed tags")
    print("  /tag search <t>   Find notes by tag")
    print("  /tag stats        Tag frequency chart")
    print("  /help             Show this message")
    print("  exit              Quit the application")


def dispatch(service, svc_config, line, current_alias, current_doc_id):
    parts = line.strip().split()
    command = parts[0].lower()
    args = parts[1:]

    if command == '/switch':
        alias, doc_id = cmd_switch(service, svc_config, args, current_alias)
        if doc_id is not None:
            return alias, doc_id
    elif command == '/edit':
        if current_doc_id is None:
            print("No active document to save to.")
        else:
            content = open_editor()
            if content:
                timestamp = datetime.now().strftime("[%m/%d/%y] (%H:%M)|")
                entry_with_time = f"{timestamp} {content}"
                if google_docs.prepend_text(service, current_doc_id, entry_with_time):
                    parser.index_note(content, timestamp, current_doc_id, content)
                    print(f"--- Prepended editor content on {timestamp} ---")
    elif command == '/list':
        cmd_list(service, svc_config, current_alias)
    elif command == '/add':
        cmd_add(svc_config, args)
    elif command == '/remove':
        removed = cmd_remove(svc_config, args, current_alias)
        if removed and args and args[0] == current_alias:
            aliases = svc_config.get("aliases", {})
            default = svc_config.get("default", "")
            if aliases and default in aliases:
                title = google_docs.fetch_doc_title(service, aliases[default])
                display = f'"{title}"' if title else aliases[default]
                print(f"--- Switched to default alias '{default}' ({display}) ---")
                return default, aliases[default]
            elif aliases:
                new_alias = next(iter(aliases))
                title = google_docs.fetch_doc_title(service, aliases[new_alias])
                display = f'"{title}"' if title else aliases[new_alias]
                print(f"--- Switched to '{new_alias}' ({display}) ---")
                return new_alias, aliases[new_alias]
            else:
                print("No documents remaining. Add one with /add.")
                return None, None
    elif command == '/rename':
        cmd_rename(svc_config, args)
    elif command == '/tag':
        cmd_tag(service, svc_config, args, current_alias, current_doc_id)
    elif command == '/current':
        cmd_current(service, svc_config, current_alias)
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
    parser.add_argument('--tui', action='store_true',
                        help='Launch the rich TUI interface')
    args = parser.parse_args()

    if args.tui:
        from mydocbot_app import MyDocBotApp
        MyDocBotApp().run()
        return

    svc_config = config.load_config()
    aliases = svc_config.get("aliases", {})

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
        config.save_config(svc_config)
        print(f"Added alias '{alias}' ({doc_id}).")
        return

    service = google_docs.get_service()

    start_alias = args.doc or svc_config.get("default", "")
    if not start_alias or start_alias not in aliases:
        print(f"Alias '{start_alias}' not found. Available aliases:")
        for a in aliases:
            print(f"  {a}")
        return

    current_alias = start_alias
    current_doc_id = aliases[current_alias]
    current_title = google_docs.fetch_doc_title(service, current_doc_id)

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
                new_alias, new_doc_id = dispatch(service, svc_config, stripped, current_alias, current_doc_id)
                if new_alias is None and new_doc_id is None:
                    if not aliases:
                        print("No documents available. Use /add to add one.")
                        current_alias = None
                        current_doc_id = None
                        current_title = None
                elif new_alias != current_alias or new_doc_id != current_doc_id:
                    current_alias = new_alias
                    current_doc_id = new_doc_id
                    current_title = google_docs.fetch_doc_title(service, current_doc_id)
                    display = f'"{current_title}"' if current_title else current_doc_id
                    print(f"--- Now on {display} ({current_alias}) ---")
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
        if google_docs.prepend_text(service, current_doc_id, entry_with_time):
            parser.index_note(full_note, timestamp, current_doc_id, full_note)
            doc_label = current_title or current_doc_id[:20] + "..."
            print(f"--- Prepended to \"{doc_label}\" on {timestamp} ---")


if __name__ == '__main__':
    main()
