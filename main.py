import argparse
import sys

from core import config, google_docs, notes, parser, paths, validation
from core.commands import dispatch, queued_message

# One-shot exit codes. 2 is left to argparse for usage errors; 3 lets a script
# or hotkey tell "queued offline" apart from "sent".
EXIT_SENT = 0
EXIT_ERROR = 1
EXIT_QUEUED = 3


def _stdin_note():
    """Note text piped on stdin, or None when stdin is a terminal."""
    if sys.stdin is None or sys.stdin.isatty():
        return None
    return sys.stdin.read()


def one_shot(svc_config, alias, text):
    """Write a single note to `alias` (or the default doc) and return an exit code."""
    aliases = svc_config.get("aliases", {})
    alias = alias or svc_config.get("default", "")
    if not aliases:
        print("No documents configured. Add one with --add <alias> <doc_id>.", file=sys.stderr)
        return EXIT_ERROR
    if alias not in aliases:
        print(f"Alias '{alias}' not found. Available: {', '.join(aliases)}", file=sys.stderr)
        return EXIT_ERROR
    service = google_docs.get_service()
    result = notes.submit_note(service, aliases[alias], text)
    if result.status == "rejected":
        print(f"Note rejected: {result.reason}", file=sys.stderr)
        return EXIT_ERROR
    if result.status == "queued":
        print(queued_message(result), file=sys.stderr)
        return EXIT_QUEUED
    msg = f"--- Prepended to {alias} on {result.timestamp} ---"
    if result.flushed:
        msg += f" (flushed {len(result.flushed)} pending)"
    print(msg)
    return EXIT_SENT


def main():
    arg_parser = argparse.ArgumentParser(description="MyDocBot - terminal note-taker for Google Docs")
    arg_parser.add_argument('--doc', '-d', type=str, default=None,
                            help='Document alias to start on (or to write a one-shot note to)')
    arg_parser.add_argument('--list', '-l', action='store_true',
                            help='List configured aliases and exit')
    arg_parser.add_argument('--add', nargs=2, metavar=('ALIAS', 'DOC_ID'),
                            help='Add a document alias and exit')
    arg_parser.add_argument('--tui', action='store_true',
                            help='Launch the rich TUI interface')
    arg_parser.add_argument('--read', '-r', nargs='?', const='', default=None,
                            help='Launch read-only TUI (optional: start alias)')
    arg_parser.add_argument('note', nargs='*',
                            help='Write this note and exit, without the REPL. '
                                 'A note piped on stdin works the same way.')
    args = arg_parser.parse_args()
    modes = args.read is not None or args.tui or args.list or args.add

    if args.note and modes:
        arg_parser.error("a note can't be combined with --tui, --read, --list, or --add")

    paths.prepare_data_dir()

    if not modes:
        text = " ".join(args.note) if args.note else _stdin_note()
        if text is not None:
            return one_shot(config.load_config(), args.doc, text.rstrip("\n"))

    if args.read is not None:
        from mydocbot_app import ReadOnlyApp
        ReadOnlyApp(start_alias=args.read or None).run()
        return

    if args.tui:
        from mydocbot_app import MyDocBotApp
        MyDocBotApp().run()
        return

    svc_config = config.load_config()
    aliases = svc_config.get("aliases", {})

    if args.list:
        if not aliases:
            print("No documents configured.")
        else:
            for alias, doc_id in aliases.items():
                print(f"  {alias:<12} {doc_id}")
        return

    if args.add:
        alias, doc_id = args.add
        valid, vmsg = validation.validate_alias(alias)
        if not valid:
            print(f"Invalid alias: {vmsg}")
            return
        valid, vmsg = validation.validate_doc_id(doc_id)
        if not valid:
            print(f"Invalid doc_id: {vmsg}")
            return
        if alias in aliases:
            print(f"Alias '{alias}' already exists.")
            return
        aliases[alias] = doc_id
        config.save_config(svc_config)
        print(f"Added alias '{alias}' ({doc_id}).")
        return

    if not aliases:
        print("No documents configured. Add one with:")
        print("  python main.py --add <alias> <doc_id>")
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
        pending = parser.count_pending()
        pending_tag = f" [{pending} pending]" if pending else ""
        prompt = f"[{current_alias}] {display_title}{pending_tag} > "

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
        result = notes.submit_note(service, current_doc_id, full_note)
        if result.status == "rejected":
            print(f"Note rejected: {result.reason}")
        elif result.status == "sent":
            doc_label = current_title or current_doc_id[:20] + "..."
            msg = f"--- Prepended to \"{doc_label}\" on {result.timestamp} ---"
            if result.flushed:
                msg += f" (flushed {len(result.flushed)} pending)"
            print(msg)
        else:
            print(queued_message(result))


if __name__ == '__main__':
    raise SystemExit(main())
