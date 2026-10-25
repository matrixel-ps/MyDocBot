import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
from datetime import datetime

from . import config, google_docs, notes, parser, validation


def resolve_editor():
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
    editor_parts = resolve_editor()
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

        with open(tmp_path) as f:
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


def export_to_markdown(entries, filepath=None):
    if filepath is None:
        filepath = f"export_{datetime.now().strftime('%m%d%y_%H%M')}.md"
    path = os.path.join(os.getcwd(), filepath)
    with open(path, 'w') as f:
        f.write(f"# MyDocBot Export — {datetime.now().strftime('%m/%d/%y %H:%M')}\n\n")
        for e in entries:
            ts = e.get("ts", "")
            text = e.get("text", e.get("preview", ""))
            f.write(f"## {ts}\n\n{text}\n\n---\n\n")
    return path


def queued_text(result):
    """Why a submit_note() result was queued and what to do next; shared by the CLI and TUI."""
    failure = result.failure
    if result.queued_behind:
        why = failure.message if failure else "still pending"
        head = f"Queued behind {result.queued_behind} earlier note(s) for this doc ({why})"
    elif failure and failure.kind != "transient":
        head = f"Not sent: {failure.message}. Queued"
    else:
        head = "Queued note (offline)"
    if failure and failure.kind == "permanent":
        hint = "See /queue to move or drop it; /flush retries after you fix the doc"
    else:
        hint = "Use /flush to retry"
    return f"{head}. {parser.count_pending()} pending. {hint}."


QUEUE_USAGE = "Usage: /queue [list] | /queue drop <n> | /queue move <n> <alias>"


def _alias_for(svc_config, doc_id):
    for alias, alias_doc_id in svc_config.get("aliases", {}).items():
        if alias_doc_id == doc_id:
            return alias
    return doc_id


def queue_lines(svc_config):
    """Numbered lines for /queue list, oldest first; shared by the CLI and TUI."""
    lines = []
    for position, entry in enumerate(parser.load_pending_notes(), 1):
        preview = textwrap.shorten(entry["text"], width=60, placeholder="...")
        line = f"{position}. {entry['ts']} [{_alias_for(svc_config, entry['doc_id'])}] {preview}"
        failure = parser.entry_failure(entry)
        if failure:
            line += f" — {failure.message}"
        lines.append(line)
    return lines


def parse_queue_args(args):
    """Split /queue args into (action, position, alias); action is None when they don't parse."""
    action = args[0] if args else "list"
    if action == "list" and len(args) <= 1:
        return "list", None, None
    expected = {"drop": 2, "move": 3}.get(action)
    if expected is None or len(args) != expected or not args[1].isdigit():
        return None, None, None
    return action, int(args[1]), (args[2] if action == "move" else None)


def cmd_queue(svc_config, args):
    action, position, alias = parse_queue_args(args)
    if action == "list":
        lines = queue_lines(svc_config)
        if not lines:
            print("No pending notes.")
            return
        print(f"{len(lines)} pending (oldest first):")
        for line in lines:
            print(f"  {line}")
        return
    if action is None:
        print(QUEUE_USAGE)
        return
    queue = parser.load_pending_notes()
    if not 1 <= position <= len(queue):
        print(f"No queued note #{position} (there are {len(queue)}). See /queue.")
        return
    entry = queue[position - 1]
    if action == "drop":
        preview = textwrap.shorten(entry["text"], width=40, placeholder="...")
        confirm = input(f"Drop queued note #{position} ({entry['ts']} {preview})? It won't be sent. [y/N] ")
        if confirm.lower() != 'y':
            print("Canceled.")
            return
        parser.drop_pending(position)
        print(f"--- Dropped note #{position}. Its text was: ---")
        print(entry["text"])
        return
    aliases = svc_config.get("aliases", {})
    if alias not in aliases:
        print(f"Alias '{alias}' not found.")
        return
    parser.move_pending(position, aliases[alias])
    print(f"--- Note #{position} now goes to '{alias}', on the next note you write or /flush. ---")


def queued_message(result):
    """CLI message for a submit_note() result with status "queued"."""
    return f"--- {queued_text(result)} ---"


def cmd_export(service, svc_config, current_alias, current_doc_id, args):
    filepath = None
    tag = None
    parsed_args = []
    i = 0
    while i < len(args):
        if args[i] == '--file' and i + 1 < len(args):
            filepath = args[i + 1]
            i += 2
        else:
            parsed_args.append(args[i])
            i += 1

    if parsed_args:
        tag = parsed_args[0].lower().lstrip('#')

    if tag:
        tags = parser.load_tags_index()
        doc_entries = [e for e in tags.get(tag, []) if e["doc_id"] == current_doc_id]
        if not doc_entries:
            print(f"No entries for tag #{tag}")
            return
        entries = [{"ts": e["ts"], "text": e["preview"]} for e in doc_entries]
        try:
            path = export_to_markdown(entries, filepath)
            print(f"--- Exported {len(entries)} notes to {path} ---")
        except OSError as e:
            print(f"Export failed: {e}")
    else:
        if current_doc_id is None:
            print("No active document to export from.")
            return
        history_size = config.get_history_size(svc_config)
        try:
            api_entries = google_docs.parse_entries(google_docs.fetch_doc(service, current_doc_id),
                                                    count=history_size)
        except Exception as e:
            print(f"Error fetching notes for export: {e}", file=sys.stderr)
            return
        if not api_entries:
            print("No notes to export.")
            return
        entries = [{"ts": ts, "text": textwrap.shorten(body, width=500, placeholder="...")} for ts, body in api_entries]
        try:
            path = export_to_markdown(entries, filepath)
            print(f"--- Exported {len(entries)} notes to {path} ---")
        except OSError as e:
            print(f"Export failed: {e}")


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
    valid, msg = validation.validate_alias(alias)
    if not valid:
        print(f"Invalid alias: {msg}")
        return
    valid, msg = validation.validate_doc_id(doc_id)
    if not valid:
        print(f"Invalid doc_id: {msg}")
        return
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
    valid, msg = validation.validate_alias(new)
    if not valid:
        print(f"Invalid alias: {msg}")
        return
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
        rest, since, until = parser.parse_date_flags(args[1:])
        if rest:
            cmd_tag_search(svc_config, rest[0], current_doc_id, since, until)
        else:
            print("Usage: /tag search <tag> [--since MM/DD/YY] [--until MM/DD/YY]")
    elif args[0] == 'stats':
        cmd_tag_stats(svc_config, current_doc_id)
    elif args[0] == 'reindex':
        cmd_tag_reindex(service, current_alias, current_doc_id)
    else:
        print(TAG_USAGE)


TAG_USAGE = "Usage: /tag list | /tag search <tag> [--since] [--until] | /tag stats | /tag reindex"


def reindex_message(result, label):
    """One-line summary of a parser.reindex_doc() result, shared by the CLI and TUI."""
    if result.status == "no_notes":
        return f"No notes found in \"{label}\"; tag index left unchanged."
    return (f"Reindexed \"{label}\": {result.notes} notes, {result.tagged_notes} tagged, "
            f"{result.tags} tags (index entries for this doc: {result.entries_before} → {result.entries_after}).")


def cmd_tag_reindex(service, current_alias, current_doc_id):
    label = google_docs.fetch_doc_title(service, current_doc_id) or current_alias
    try:
        result = parser.reindex_doc(service, current_doc_id)
    except Exception as e:
        print(f"Reindex failed, tag index left unchanged: {e}")
        return
    print(reindex_message(result, label))


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


def cmd_tag_search(svc_config, tag, current_doc_id, since=None, until=None):
    tags = parser.load_tags_index()
    tag = tag.lower().lstrip('#')
    entries = tags.get(tag, [])
    doc_entries = [e for e in entries if e["doc_id"] == current_doc_id]
    doc_entries = parser.filter_tag_entries_by_date(doc_entries, since, until)
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


def cmd_search(service, svc_config, current_doc_id, args):
    if not args:
        print("Usage: /search <keyword>")
        return
    if current_doc_id is None:
        print("No active document to search.")
        return
    keyword = ' '.join(args)
    try:
        # Every note in the doc, not just the newest history_size (B8).
        entries = google_docs.parse_entries(google_docs.fetch_doc(service, current_doc_id), count=None)
    except Exception as e:
        print(f"Error fetching notes for search: {e}", file=sys.stderr)
        return
    results = parser.search_entries(entries, keyword)
    if not results:
        print(f"No notes matching '{keyword}'")
        return
    print(f"Search: {keyword}   ({len(results)} result{'s' if len(results) != 1 else ''})\n")
    for ts, body in results:
        preview = body.replace('\n', ' ')[:120]
        print(f"  {ts} {preview}")


def cmd_config(svc_config, args):
    if not args or args[0] == 'show':
        history_size = config.get_history_size(svc_config)
        print("Config settings:")
        print(f"  history_size   {history_size}   "
              f"(notes loaded on startup / /switch; range "
              f"{validation.MIN_HISTORY_SIZE}-{validation.MAX_HISTORY_SIZE})")
        return
    if args[0] == 'set' and len(args) >= 3:
        key, value = args[1], args[2]
        if key == 'history_size':
            valid, msg = validation.validate_history_size(value)
            if not valid:
                print(f"Invalid value: {msg}")
                return
            svc_config["history_size"] = int(value)
            config.save_config(svc_config)
            print(f"--- history_size set to {value}. "
                  "Takes effect on next /switch or restart. ---")
        else:
            print(f"Unknown config key '{key}'. Available keys: history_size")
    else:
        print("Usage: /config show | /config set <key> <value>")
        print(f"       /config set history_size "
              f"<{validation.MIN_HISTORY_SIZE}-{validation.MAX_HISTORY_SIZE}>")


def cmd_help():
    print("Available commands:")
    print("  /edit                          Open $EDITOR to compose a multi-line note")
    print("  /switch <alias>                Switch to a different document")
    print("  /list                          List all configured documents")
    print("  /add <a> <id>                  Add a new document alias")
    print("  /remove <alias>                Remove a document alias")
    print("  /rename <o> <n>                Rename an alias")
    print("  /current                       Show active document info")
    print("  /flush                         Retry sending pending offline notes")
    print("  /queue [list]                  List queued notes and why they failed")
    print("  /queue drop <n>                Discard queued note n (asks first)")
    print("  /queue move <n> <alias>        Send queued note n to another alias")
    print("  /search <keyword>              Search all notes in this doc")
    print("  /export [<tag>] [--file <path>]  Export notes to Markdown file")
    print("  /tag list                      Show all indexed tags")
    print("  /tag search <t> [--since/--until]  Find notes by tag")
    print("  /tag stats                     Tag frequency chart")
    print("  /tag reindex                   Rebuild this doc's tags from the doc")
    print("  /config show                   Show config settings")
    print(f"  /config set history_size <n>   Set notes loaded on startup "
          f"({validation.MIN_HISTORY_SIZE}-{validation.MAX_HISTORY_SIZE})")
    print("  /help                          Show this message")
    print("  exit                           Quit the application")


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
                result = notes.submit_note(service, current_doc_id, content)
                if result.status == "rejected":
                    print(f"Note rejected: {result.reason}")
                elif result.status == "sent":
                    msg = f"--- Prepended editor content on {result.timestamp} ---"
                    if result.flushed:
                        msg += f" (flushed {len(result.flushed)} pending)"
                    print(msg)
                else:
                    print(queued_message(result))
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
    elif command == '/queue':
        cmd_queue(svc_config, args)
    elif command == '/flush':
        flushed = len(parser.flush_pending_notes(service, include_permanent=True))
        pending = parser.count_pending()
        if flushed:
            print(f"Flushed {flushed} pending notes.")
        if pending:
            print(f"{pending} notes still pending.")
        else:
            print("No pending notes.")
    elif command == '/tag':
        cmd_tag(service, svc_config, args, current_alias, current_doc_id)
    elif command == '/search':
        cmd_search(service, svc_config, current_doc_id, args)
    elif command == '/export':
        cmd_export(service, svc_config, current_alias, current_doc_id, args)
    elif command == '/config':
        cmd_config(svc_config, args)
    elif command == '/current':
        cmd_current(service, svc_config, current_alias)
    elif command == '/help':
        cmd_help()
    else:
        print(f"Unknown command: {command}. Type /help for available commands.")

    return current_alias, current_doc_id
