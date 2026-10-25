import os
import re
import subprocess
import tempfile
import textwrap
from datetime import datetime, timedelta

from rich.markup import escape as md_escape
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Button, Label, ListItem, ListView, RichLog, Static, TextArea

from core import config, google_docs, notes, parser, validation
from core.commands import (
    QUEUE_USAGE,
    TAG_USAGE,
    export_to_markdown,
    parse_queue_args,
    queue_lines,
    queued_text,
    reindex_message,
    resolve_editor,
)

# Maximum number of notes kept in the in-memory session cache (per app instance),
# shared by both MyDocBotApp and ReadOnlyApp to avoid unbounded memory growth.
NOTES_CACHE_LIMIT = 500

CSS = """
Screen {
    background: #1e1e2e;
}

#header-bar {
    background: #313244;
    color: #cdd6f4;
    padding: 0 2;
    height: 3;
    dock: top;
}

#main-area {
    height: 1fr;
}

#notes-list {
    width: 40%;
    border: solid #45475a;
    background: #181825;
}

#notes-list Label {
    padding: 0 1;
}

#preview-pane {
    width: 60%;
    border: solid #45475a;
    background: #181825;
    padding: 1 2;
    overflow-y: auto;
}

#input-area {
    height: 6;
    background: #1e1e2e;
}

#input-bar {
    background: #1e1e2e;
    color: #cdd6f4;
    border: solid #45475a;
    height: 100%;
    width: 1fr;
}

#submit-btn {
    width: auto;
    height: 100%;
    background: #89b4fa;
    color: #1e1e2e;
    border: none;
    padding: 0 3;
    min-width: 12;
}

#submit-btn:hover {
    background: #b4d0fb;
}

#status-bar {
    background: #313244;
    color: #a6e3a1;
    height: 1;
    padding: 0 2;
    dock: bottom;
}

#input-bar:focus {
    border: solid #89b4fa;
}

#submit-btn:focus {
    background: #b4d0fb;
    border: solid #89b4fa;
}

.date-separator {
    height: 1;
    padding: 0 1;
}

.date-separator Label {
    padding: 0;
    color: #585b70;
}
"""


class NoteItem(ListItem):
    def __init__(self, timestamp, text, doc_id):
        preview = textwrap.shorten(text, width=80, placeholder="...").replace('\n', ' ')
        time_part = timestamp[12:17] if len(timestamp) >= 17 else timestamp
        tags = parser.extract_tags(text)
        tag_str = f"  [#a6e3a1]{' '.join(f'#{t}' for t in tags[:3])}[/]" if tags else ""
        label = Label(f"[{md_escape(time_part)}] {md_escape(preview)}{tag_str}")
        super().__init__(label)
        self.note_ts = timestamp
        self.note_text = text
        self.note_doc_id = doc_id
        self.tags = tags


class DateSeparator(ListItem):
    def __init__(self, label_text):
        label = Label(f"[bold #585b70]─── {label_text} ───[/]")
        super().__init__(label)
        self.classes = "date-separator"
        self._is_separator = True


class PreviewPane(RichLog):
    def _on_key(self, event):
        key = event.key
        if key == "up":
            self.scroll_up(animate=False)
        elif key == "down":
            self.scroll_down(animate=False)
        elif key == "pageup":
            self.scroll_page_up(animate=False)
        elif key == "pagedown":
            self.scroll_page_down(animate=False)
        elif key == "home":
            self.scroll_home(animate=False)
        elif key == "end":
            self.scroll_end(animate=False)
        else:
            super()._on_key(event)
            return
        event.stop()


class BaseNotesApp(App):
    """Shared foundation for MyDocBotApp (read/write) and ReadOnlyApp.

    Holds all state and behavior that is identical between the two Textual
    apps: notes cache management, date-grouped list rendering, preview pane
    rendering, and the handful of commands whose logic is the same in both
    modes (/switch, /list, /add, /current, /search, /refresh, /more).

    Subclasses plug in the handful of genuine differences via a small hook
    interface (config file, alias resolution, entry parsing, date-key
    extraction) plus a few text/label class attributes. Everything that is
    *not* identical between the two apps on purpose (BINDINGS, compose(),
    handle_command()'s command table, /help text, and write-only commands
    like /edit /remove /rename /export /tag /config) intentionally stays in
    the subclasses rather than being forced into hooks here.
    """

    CSS = CSS
    ENABLE_COMMAND_PALETTE = False
    MAX_CACHE = NOTES_CACHE_LIMIT

    # ---- text/label differences, overridden per subclass ----
    HEADER_TITLE = "MyDocBot"
    EMPTY_NOTES_MSG = "No notes yet."
    LIST_HEADER = "Documents"
    NO_DOCS_MSG = "No docs configured."
    NO_DOCS_LIST_MSG = "No docs configured."
    ADD_SUCCESS_SUFFIX = ""

    def __init__(self):
        super().__init__()
        self.svc_config = self._load_config()
        self._service = google_docs.get_service()
        self._history_size = config.get_history_size(self.svc_config)
        self.current_alias = None
        self.current_doc_id = None
        self.current_title = None
        self.notes_cache = []
        self.all_tags = {}
        self._last_selected_index = 0
        self._note_to_display = {}
        self._api_busy = None  # label of the Google call in flight, e.g. "saving note"

    # ---- hooks subclasses must implement ----
    def _load_config(self):
        raise NotImplementedError

    def _save_config(self, cfg):
        raise NotImplementedError

    def _resolve_alias(self, cfg, alias):
        raise NotImplementedError

    def _fetch_recent(self, doc_id, count):
        """Fetch up to `count` most-recent (ts, body) entries for doc_id."""
        raise NotImplementedError

    def _date_key(self, ts):
        """Return a canonical 'MM/DD/YY' string for grouping/labeling a note's
        timestamp, comparable against `_format_date_header`'s own
        `datetime.now().strftime("%m/%d/%y")` computation."""
        raise NotImplementedError

    def _resolve_initial_alias(self, aliases):
        default = self.svc_config.get("default", "")
        return default if default in aliases else next(iter(aliases))

    # ---- shared cache/date helpers ----
    def _add_to_cache(self, ts, text, doc_id):
        self.notes_cache.insert(0, {"ts": ts, "text": text, "doc_id": doc_id})
        if len(self.notes_cache) > self.MAX_CACHE:
            self.notes_cache[:] = self.notes_cache[:self.MAX_CACHE]

    @staticmethod
    def _format_date_header(date_str):
        today = datetime.now().strftime("%m/%d/%y")
        if date_str == today:
            return "Today"
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%m/%d/%y")
        if date_str == yesterday:
            return "Yesterday"
        month, day, year = date_str.split("/")
        return f"{month}/{day}/{year}"

    # ---- lifecycle ----
    def on_mount(self):
        preview = self.query_one("#preview-pane")
        preview.write("Select a note to preview")
        self.init_app()

    def init_app(self):
        """Draw the UI right away, then load the first doc's notes in the background."""
        aliases = self.svc_config.get("aliases", {})
        if not aliases:
            self.show_error(self.NO_DOCS_MSG)
            return
        self.current_alias = self._resolve_initial_alias(aliases)
        doc_id = self.current_doc_id = aliases[self.current_alias]
        self.current_title = doc_id[:20] + "..."
        self.all_tags = parser.load_tags_index()
        count = self._history_size

        def done(loaded):
            title, recent = loaded
            if title:
                self.current_title = title
            for ts, body in reversed(recent):
                self._add_to_cache(ts, body, doc_id)
            self.refresh_ui()

        def failed(e):
            self.current_title = "(error)"
            self.refresh_ui()
            self.show_error(f"Startup error: {e}")

        self.run_api("loading notes", lambda: self._fetch_title_and_recent(doc_id, count), done, failed)
        self.refresh_ui()

    def _fetch_title_and_recent(self, doc_id, count):
        """Worker-side: the doc's title and its `count` most recent entries."""
        return google_docs.fetch_doc_title(self._service, doc_id), self._fetch_recent(doc_id, count)

    # ---- background Google calls (A3) ----
    def run_api(self, label, work, on_done, on_error=None):
        """Run work() in a thread worker, then on_done(result) or on_error(exc) back
        on the UI thread. Returns True if the call started.

        work() may only call the Google API and core functions: no widgets and no
        app state, which change only in the callbacks. One call at a time: the
        Google client isn't thread-safe (an earlier @work version raced on
        _service), so a request while another runs is refused, not queued."""
        if self._refuse_if_busy():
            return False
        self._api_busy = label
        self._update_header()
        self.update_status(self._busy_text())
        on_error = on_error or (lambda e: self.show_error(f"{label[0].upper()}{label[1:]} failed: {e}"))

        def task():
            try:
                outcome = (on_done, work())
            except Exception as e:
                outcome = (on_error, e)
            try:
                self.call_from_thread(self._api_finished, *outcome)
            except RuntimeError:
                pass  # the app closed while the call was running; nothing left to update

        self.run_worker(task, thread=True, group="api", exit_on_error=False)
        return True

    def _api_finished(self, callback, value):
        self._api_busy = None
        self._update_header()
        self.update_status("Ready")
        callback(value)

    def _refuse_if_busy(self):
        """Show the busy message and return True while a Google call is in flight."""
        if not self._api_busy:
            return False
        self.update_status(f"Still {self._api_busy}… try again when it's done.")
        return True

    def _busy_text(self):
        label = self._api_busy or ""
        return f"⟳ {label[:1].upper()}{label[1:]}…"

    def _update_header(self):
        header = self.query_one("#header-bar")
        doc_display = f"[bold]{md_escape(self.current_alias or '')}[/] [italic]{md_escape(self.current_title or '')}[/]"
        status = "◌ Working…" if self._api_busy else "● Connected"
        header.update(f"[b]{self.HEADER_TITLE}[/b]     {doc_display}     {status}")

    def refresh_ui(self):
        self._update_header()

        notes_list = self.query_one("#notes-list")
        notes_list.clear()
        doc_notes = [n for n in self.notes_cache if n["doc_id"] == self.current_doc_id]
        idle_status = self._busy_text() if self._api_busy else "Ready"

        if not doc_notes:
            empty_msg = "Loading notes…" if self._api_busy == "loading notes" else self.EMPTY_NOTES_MSG
            notes_list.append(
                ListItem(Label(f"[#585b70]{empty_msg}[/]"))
            )
            self.update_status(idle_status)
            return

        current_date = None
        self._note_to_display = {}
        note_idx = 0
        display_idx = 0

        for n in doc_notes:
            date_key = self._date_key(n["ts"])
            if date_key != current_date:
                current_date = date_key
                notes_list.append(DateSeparator(self._format_date_header(date_key)))
                display_idx += 1
            item = NoteItem(n["ts"], n["text"], n["doc_id"])
            notes_list.append(item)
            self._note_to_display[note_idx] = display_idx
            note_idx += 1
            display_idx += 1

        target_note = min(self._last_selected_index, note_idx - 1)
        display_target = self._note_to_display.get(target_note, 0)
        notes_list.index = display_target
        self.show_note_preview(display_target)

        self.update_status(idle_status)

    def on_list_view_selected(self, event):
        notes_list = self.query_one("#notes-list")
        if notes_list.index is not None:
            children = list(notes_list.children)
            idx = notes_list.index
            if idx < len(children) and getattr(children[idx], '_is_separator', False):
                return
            note_idx = sum(1 for i in range(idx) if not getattr(children[i], '_is_separator', False))
            self._last_selected_index = note_idx
            self.show_note_preview(idx)

    def show_note_preview(self, display_index):
        notes_list = self.query_one("#notes-list")
        children = list(notes_list.children)
        if not children or display_index >= len(children):
            return
        item = children[display_index]
        while getattr(item, '_is_separator', False):
            display_index += 1
            if display_index >= len(children):
                return
            item = children[display_index]
        ts = item.note_ts
        text = item.note_text
        preview = self.query_one("#preview-pane")
        highlighted = re.sub(
            r'(#\w+)',
            r'[bold #f9e2af]\1[/]',
            md_escape(text)
        )
        preview.clear()
        preview.write(f"[#a6e3a1]{md_escape(ts)}[/]\n\n{highlighted}")
        preview.refresh()
        preview.scroll_home(animate=False)

    def update_status(self, msg):
        status_bar = self.query_one("#status-bar")
        status_bar.update(msg)

    def show_error(self, msg):
        status_bar = self.query_one("#status-bar")
        status_bar.update(f"[#f38ba8]{md_escape(str(msg))}[/]")

    def action_focus_notes(self):
        self.query_one("#notes-list").focus()

    def action_focus_preview(self):
        self.query_one("#preview-pane").focus()

    # ---- shared commands ----
    def cmd_switch(self, args):
        if not args:
            self.update_status("Usage: /switch <alias>")
            return
        alias = args[0]
        doc_id = self._resolve_alias(self.svc_config, alias)
        if not doc_id:
            self.update_status(f"Unknown alias '{alias}'")
            return
        count = self._history_size

        def done(loaded):
            title, recent = loaded
            self.current_alias = alias
            self.current_doc_id = doc_id
            self.current_title = title or doc_id[:20] + "..."
            self.notes_cache = [n for n in self.notes_cache if n["doc_id"] != doc_id]
            for ts, body in reversed(recent):
                self._add_to_cache(ts, body, doc_id)
            self._last_selected_index = 0
            self.refresh_ui()
            self.update_status(f"Switched to '{md_escape(alias)}' ({md_escape(title or doc_id)})")

        self.run_api("switching documents", lambda: self._fetch_title_and_recent(doc_id, count), done)

    def cmd_list(self):
        aliases = self.svc_config.get("aliases", {})
        if not aliases:
            self.update_status(self.NO_DOCS_LIST_MSG)
            return
        pairs = list(aliases.items())

        def done(titles):
            lines = []
            for (alias, doc_id), title in zip(pairs, titles):
                marker = " ← active" if alias == self.current_alias else ""
                display = f'"{md_escape(title)}"' if title else md_escape(doc_id)
                lines.append(f"  {md_escape(alias):<12} {display}{marker}")
            preview = self.query_one("#preview-pane")
            preview.clear()
            preview.write(f"[b]{self.LIST_HEADER}[/b]\n\n" + "\n".join(lines))
            preview.scroll_home(animate=False)

        self.run_api("listing documents",
                     lambda: [google_docs.fetch_doc_title(self._service, doc_id) for _, doc_id in pairs], done)

    def cmd_add(self, args):
        if not args or len(args) < 2:
            self.update_status("Usage: /add <alias> <doc_id>")
            return
        alias, doc_id = args[0], args[1]
        valid, msg = validation.validate_alias(alias)
        if not valid:
            self.update_status(f"Invalid alias: {msg}")
            return
        valid, msg = validation.validate_doc_id(doc_id)
        if not valid:
            self.update_status(f"Invalid doc_id: {msg}")
            return
        aliases = self.svc_config.setdefault("aliases", {})
        if alias in aliases:
            self.update_status(f"Alias '{alias}' already exists.")
            return
        aliases[alias] = doc_id
        self._save_config(self.svc_config)
        self.update_status(f"Added '{alias}'{self.ADD_SUCCESS_SUFFIX}")

    def cmd_current(self):
        preview = self.query_one("#preview-pane")
        preview.clear()
        preview.write(
            f"[b]Active Document[/b]\n\n"
            f"Alias:    {md_escape(self.current_alias or '')}\n"
            f"Title:    {md_escape(self.current_title or '(unknown)')}\n"
            f"Doc ID:   {md_escape(self.current_doc_id or '')}"
        )
        preview.scroll_home(animate=False)

    def cmd_search(self, args):
        if not args:
            self.update_status("Usage: /search <keyword>")
            return
        keyword = ' '.join(args)
        doc_id = self.current_doc_id

        def done(entries):
            self._show_search_results(keyword, parser.search_entries(entries, keyword))

        def fallback(e):
            # Can't fetch the doc: search what's loaded, and say it's partial.
            loaded = sum(1 for n in self.notes_cache if n["doc_id"] == doc_id)
            results = [(n["ts"], n["text"]) for n in parser.search_cache(self.notes_cache, doc_id, keyword)]
            self._show_search_results(
                keyword, results,
                note=f"Couldn't fetch the doc ({e}) — searched the {loaded} loaded notes only.")

        # Every note in the doc, like the CLI (B8), not just the loaded ones.
        self.run_api("searching", lambda: self._fetch_recent(doc_id, None), done, fallback)

    def _show_search_results(self, keyword, results, note=None):
        suffix = f"  {md_escape(note)}" if note else ""
        if not results:
            self.update_status(f"No notes matching '{md_escape(keyword)}'.{suffix}")
            return
        lines = [f"[b]Search: {md_escape(keyword)}[/]   {len(results)} notes\n"]
        for ts, body in results:
            preview_text = body.replace('\n', ' ')[:100]
            highlighted = re.sub(
                f'({re.escape(keyword)})', r'[bold #f9e2af]\1[/]',
                md_escape(preview_text), flags=re.IGNORECASE
            )
            lines.append(f"[#a6e3a1]{md_escape(ts)}[/] {highlighted}")
        preview = self.query_one("#preview-pane")
        preview.clear()
        preview.write("\n".join(lines))
        preview.scroll_home(animate=False)
        self.update_status(f"{len(results)} match(es) for '{md_escape(keyword)}'.{suffix}")

    def cmd_refresh(self):
        doc_id = self.current_doc_id
        count = self._history_size

        def work():
            google_docs.invalidate_title_cache(doc_id)
            return self._fetch_title_and_recent(doc_id, count)

        def done(loaded):
            title, recent = loaded
            if title:
                self.current_title = title
            existing = {(n["ts"], n["doc_id"]) for n in self.notes_cache}
            new_count = 0
            for ts, body in reversed(recent):
                if (ts, doc_id) not in existing:
                    self._add_to_cache(ts, body, doc_id)
                    new_count += 1
            self.refresh_ui()
            self.update_status(f"Loaded {new_count} new note(s)" if new_count else "No new notes")

        self.run_api("refreshing", work, done, lambda e: self.show_error(f"Refresh failed: {e}"))

    def cmd_more(self):
        doc_id = self.current_doc_id
        doc_notes_count = sum(1 for n in self.notes_cache if n["doc_id"] == doc_id)
        fetch_count = min(doc_notes_count + self._history_size, self.MAX_CACHE)

        if fetch_count <= doc_notes_count:
            self.update_status("All notes loaded (cache full or end of document)")
            return

        def done(recent):
            existing = {(n["ts"], n["doc_id"]) for n in self.notes_cache}
            new_entries = [(ts, body) for ts, body in recent if (ts, doc_id) not in existing]
            if not new_entries:
                self.update_status("No more notes to load")
                return
            for ts, body in new_entries:
                self.notes_cache.append({"ts": ts, "text": body, "doc_id": doc_id})
            if len(self.notes_cache) > self.MAX_CACHE:
                self.notes_cache[:] = self.notes_cache[:self.MAX_CACHE]
            self.refresh_ui()
            self.update_status(f"Loaded {len(new_entries)} more note(s)")

        self.run_api("loading older notes", lambda: self._fetch_recent(doc_id, fetch_count), done,
                     lambda e: self.show_error(f"Load more failed: {e}"))


class MyDocBotApp(BaseNotesApp):
    BINDINGS = [
        Binding("ctrl+n", "focus_notes", "Notes"),
        Binding("ctrl+p", "focus_preview", "Preview"),
        Binding("ctrl+e", "focus_input", "Input"),
        Binding("escape", "focus_input", "Back"),
        Binding("ctrl+s", "submit_note", "Submit"),
    ]

    HEADER_TITLE = "MyDocBot"
    EMPTY_NOTES_MSG = "No notes yet. Type something and submit!"
    LIST_HEADER = "Configured Documents"
    NO_DOCS_MSG = "No docs configured. Use CLI --add first."
    NO_DOCS_LIST_MSG = "No documents configured."
    ADD_SUCCESS_SUFFIX = ""

    def _load_config(self):
        return config.load_config()

    def _save_config(self, cfg):
        config.save_config(cfg)

    def _resolve_alias(self, cfg, alias):
        return config.resolve_alias(cfg, alias)

    def _fetch_recent(self, doc_id, count):
        return google_docs.parse_entries(
            google_docs.fetch_doc(self._service, doc_id),  # with retry (B10)
            count=count
        )

    def _date_key(self, ts):
        # Write timestamps look like "[MM/DD/YY] (HH:MM)|...", so chars 1-8 are
        # already the "MM/DD/YY" key expected by `_format_date_header`.
        return ts[1:9]

    def compose(self) -> ComposeResult:
        yield Static("Connecting...", id="header-bar")
        with Horizontal(id="main-area"):
            yield ListView(id="notes-list")
            yield PreviewPane(id="preview-pane", max_lines=None, highlight=False, wrap=True, markup=True)
        with Horizontal(id="input-area"):
            yield TextArea(id="input-bar", text="", placeholder="Type a note... (Ctrl+S to submit)")
            yield Button("Submit", id="submit-btn", variant="primary")
        yield Static("Initializing...", id="status-bar")

    def action_submit_note(self):
        self.submit_note()

    def submit_note(self):
        input_bar = self.query_one("#input-bar")
        text = input_bar.text.strip()
        if not text:
            return

        if text.startswith('/'):
            input_bar.text = ""
            self.handle_command(text)
            return

        # Validate here, on the UI thread, so a rejected note never starts a call.
        valid, reason = validation.validate_note(text)
        if not valid:
            self.update_status(f"Note rejected: {reason}")
            return

        tags = parser.extract_tags(text)
        tag_str = ' '.join(f'#{t}' for t in tags) if tags else '(no tags)'

        def done(result):
            input_bar.read_only = False
            if self._apply_submit_result(result, text, f"Prepended  |  {tag_str}"):
                input_bar.text = ""

        def failed(e):
            input_bar.read_only = False
            self.show_error(f"Submit failed, note kept in the input: {e}")

        # Read-only while the write runs, so the text can't change under it.
        if self._start_submit(text, done, failed):
            input_bar.read_only = True

    def _start_submit(self, text, on_done, on_error):
        doc_id = self.current_doc_id
        return self.run_api("saving note", lambda: notes.submit_note(self._service, doc_id, text), on_done, on_error)

    def _apply_submit_result(self, result, text, sent_status):
        """Update the cache and status for a submit_note() result. False if rejected."""
        if result.status == "rejected":
            self.update_status(f"Note rejected: {result.reason}")
            return False
        self._add_flushed_to_cache(result.flushed)
        if result.status == "sent":
            self._add_to_cache(result.timestamp, text, self.current_doc_id)
            status = sent_status
            if result.flushed:
                status += f" (flushed {len(result.flushed)})"
            self.refresh_ui()
            self.update_status(status)
        else:
            if result.flushed:
                self.refresh_ui()
            self.update_status(self._queued_status(result))
        return True

    def _add_flushed_to_cache(self, entries):
        """Add notes just written from the offline queue to the notes list.
        `entries` is oldest first and each was prepended in turn, so adding
        them in order (each goes to the top) matches the doc."""
        for entry in entries:
            if entry["doc_id"] == self.current_doc_id:
                self._add_to_cache(entry["ts"], entry["text"], entry["doc_id"])

    @staticmethod
    def _queued_status(result):
        return md_escape(queued_text(result))

    def on_button_pressed(self, event):
        if event.button.id == "submit-btn":
            self.submit_note()

    def action_focus_input(self):
        self.query_one("#input-bar").focus()

    def handle_command(self, cmd):
        parts = cmd.strip().split()
        command = parts[0].lower()
        args = parts[1:]

        if command == '/switch':
            self.cmd_switch(args)
        elif command == '/list':
            self.cmd_list()
        elif command == '/add':
            self.cmd_add(args)
        elif command == '/remove':
            self.cmd_remove(args)
        elif command == '/rename':
            self.cmd_rename(args)
        elif command == '/current':
            self.cmd_current()
        elif command == '/edit':
            self.cmd_edit()
        elif command == '/search':
            self.cmd_search(args)
        elif command == '/flush':
            self.cmd_flush()
        elif command == '/queue':
            self.cmd_queue(args)
        elif command == '/refresh':
            self.cmd_refresh()
        elif command == '/more':
            self.cmd_more()
        elif command == '/export':
            self.cmd_export(args)
        elif command == '/tag':
            self.cmd_tag(args)
        elif command == '/config':
            self.cmd_config(args)
        elif command == '/help':
            self.cmd_help()
        else:
            self.update_status(f"Unknown: {command}. Type /help")

    def cmd_flush(self):
        def done(sent):
            if sent:
                self._add_flushed_to_cache(sent)
                self.refresh_ui()
            pending = parser.count_pending()
            parts = []
            if sent:
                parts.append(f"Flushed {len(sent)}")
            if pending:
                parts.append(f"{pending} still pending")
            self.update_status(" | ".join(parts) if parts else "No pending notes.")

        self.run_api("flushing the queue",
                     lambda: parser.flush_pending_notes(self._service, include_permanent=True), done)

    def cmd_remove(self, args):
        if not args:
            self.update_status("Usage: /remove <alias>")
            return
        alias = args[0]
        aliases = self.svc_config.get("aliases", {})
        if alias not in aliases:
            self.update_status(f"Alias '{alias}' not found.")
            return
        # Removing the active alias switches docs (a Google call), so check
        # before changing anything rather than leave a half-done removal.
        if alias == self.current_alias and self._refuse_if_busy():
            return
        aliases.pop(alias)
        if self.svc_config.get("default") == alias:
            self.svc_config["default"] = next(iter(aliases)) if aliases else ""
        config.save_config(self.svc_config)
        if alias == self.current_alias:
            self.switch_to_any_doc()
        else:
            self.update_status(f"Removed '{alias}'")

    def cmd_rename(self, args):
        if not args or len(args) < 2:
            self.update_status("Usage: /rename <old> <new>")
            return
        old, new = args[0], args[1]
        valid, msg = validation.validate_alias(new)
        if not valid:
            self.update_status(f"Invalid alias: {msg}")
            return
        aliases = self.svc_config.get("aliases", {})
        if old not in aliases:
            self.update_status(f"Alias '{old}' not found.")
            return
        if new in aliases:
            self.update_status(f"Alias '{new}' already exists.")
            return
        aliases[new] = aliases.pop(old)
        if self.svc_config.get("default") == old:
            self.svc_config["default"] = new
        if self.current_alias == old:
            self.current_alias = new
        config.save_config(self.svc_config)
        self.update_status(f"Renamed '{old}' -> '{new}'")

    def cmd_edit(self):
        if self._refuse_if_busy():  # don't open the editor for a note we can't save yet
            return
        editor_parts = resolve_editor()
        if not editor_parts:
            self.update_status("No editor found. Set $EDITOR.")
            return
        tmp = tempfile.NamedTemporaryFile(
            mode='w+', suffix='.md', delete=False
        )
        tmp_path = tmp.name
        tmp.write("# Write your note here (# lines ignored)\n")
        tmp.close()
        try:
            with self.suspend():
                ret = subprocess.call(editor_parts + [tmp_path])
            if ret != 0:
                self.update_status(f"Editor exited with code {ret}")
                return
            with open(tmp_path) as f:
                raw_lines = f.readlines()
            content_lines = [line.rstrip('\n') for line in raw_lines
                           if not line.strip().startswith('#')]
            content = "\n".join(content_lines).strip()
            if not content:
                self.update_status("Empty note")
                return
            self._start_submit(
                content,
                lambda result: self._apply_submit_result(result, content, "Prepended editor content"),
                lambda e: self.show_error(f"Submit failed: {e}"))
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def switch_to_any_doc(self):
        aliases = self.svc_config.get("aliases", {})
        if not aliases:
            self.update_status("No docs remaining.")
            self.current_alias = None
            self.current_doc_id = None
            self.current_title = None
            self.refresh_ui()
            return
        alias = next(iter(aliases))
        doc_id = aliases[alias]

        def done(title):
            self.current_alias = alias
            self.current_doc_id = doc_id
            self.current_title = title or doc_id[:20] + "..."
            self.refresh_ui()
            self.update_status(f"Switched to '{md_escape(alias)}'")

        self.run_api("switching documents", lambda: google_docs.fetch_doc_title(self._service, doc_id), done)

    def cmd_export(self, args):
        filepath = None
        tag = None
        i = 0
        while i < len(args):
            if args[i] == '--file' and i + 1 < len(args):
                filepath = args[i + 1]
                i += 2
            else:
                if tag is None:
                    tag = args[i]
                i += 1

        if tag:
            tag = tag.lower().lstrip('#')
            tags = parser.load_tags_index()
            doc_entries = [e for e in tags.get(tag, []) if e["doc_id"] == self.current_doc_id]
            if not doc_entries:
                self.update_status(f"No entries for tag #{tag}")
                return
            entries = [{"ts": e["ts"], "text": e["preview"]} for e in doc_entries]
            try:
                path = export_to_markdown(entries, filepath)
                self.update_status(f"Exported {len(entries)} notes to {path}")
            except OSError as e:
                self.show_error(f"Export failed: {e}")
        else:
            doc_entries = [{"ts": n["ts"], "text": n["text"]}
                           for n in self.notes_cache if n["doc_id"] == self.current_doc_id]
            if not doc_entries:
                self.update_status("No notes in cache to export.")
                return
            try:
                path = export_to_markdown(doc_entries, filepath)
                self.update_status(f"Exported {len(doc_entries)} notes to {path}")
            except OSError as e:
                self.show_error(f"Export failed: {e}")

    def cmd_tag(self, args):
        if not args:
            self.cmd_tag_list()
        elif args[0] == 'list':
            self.cmd_tag_list()
        elif args[0] == 'search' and len(args) >= 2:
            rest, since, until = parser.parse_date_flags(args[1:])
            if rest:
                self.cmd_tag_search(rest[0], since, until)
            else:
                self.update_status("Usage: /tag search <tag> [--since MM/DD/YY] [--until MM/DD/YY]")
        elif args[0] == 'stats':
            self.cmd_tag_stats()
        elif args[0] == 'reindex':
            self.cmd_tag_reindex()
        else:
            self.update_status(TAG_USAGE)

    def _show_in_preview(self, text):
        preview = self.query_one("#preview-pane")
        preview.clear()
        preview.write(text)
        preview.scroll_home(animate=False)

    def cmd_queue(self, args):
        action, position, alias = parse_queue_args(args)
        if action == "list":
            lines = queue_lines(self.svc_config)
            if not lines:
                self.update_status("No pending notes.")
                return
            self._show_in_preview(f"[b]Queued notes[/b] ({len(lines)}, oldest first)\n\n"
                                  + "\n".join(md_escape(line) for line in lines))
            return
        if action is None:
            self.update_status(md_escape(QUEUE_USAGE))
            return
        if self._refuse_if_busy():  # a running call may be rewriting the queue file
            return
        queue = parser.load_pending_notes()
        if not 1 <= position <= len(queue):
            self.update_status(f"No queued note #{position} (there are {len(queue)}). See /queue.")
            return
        if action == "drop":
            # No y/N prompt in the TUI: show the full text so it can still be copied.
            entry = parser.drop_pending(position)
            self._show_in_preview(f"[b]Dropped queued note #{position}[/b] — it won't be sent:\n\n"
                                  f"[#a6e3a1]{md_escape(entry['ts'])}[/] {md_escape(entry['text'])}")
            self.update_status(f"Dropped note #{position}. {parser.count_pending()} pending.")
            return
        aliases = self.svc_config.get("aliases", {})
        if alias not in aliases:
            self.update_status(f"Alias '{md_escape(alias)}' not found.")
            return
        parser.move_pending(position, aliases[alias])
        self.update_status(f"Note #{position} now goes to '{md_escape(alias)}', on the next note you write or /flush.")

    def cmd_tag_reindex(self):
        doc_id = self.current_doc_id
        label = self.current_title or self.current_alias

        def done(result):
            self.all_tags = parser.load_tags_index()
            self.update_status(md_escape(reindex_message(result, label)))

        self.run_api("reindexing tags", lambda: parser.reindex_doc(self._service, doc_id), done,
                     lambda e: self.show_error(f"Reindex failed, tag index left unchanged: {e}"))

    def cmd_tag_list(self):
        tags = parser.load_tags_index()
        if not tags:
            self.update_status("No tags indexed yet.")
            return
        lines = []
        for tag, entries in sorted(tags.items()):
            doc_entries = [e for e in entries
                          if e["doc_id"] == self.current_doc_id]
            lines.append(f"  #{tag:<20} {len(doc_entries)} notes")
        preview = self.query_one("#preview-pane")
        preview.clear()
        preview.write("[b]Tag Index[/b]\n\n" + "\n".join(lines))
        preview.scroll_home(animate=False)

    def cmd_tag_search(self, tag, since=None, until=None):
        tags = parser.load_tags_index()
        tag = tag.lower().lstrip('#')
        entries = tags.get(tag, [])
        doc_entries = [e for e in entries
                      if e["doc_id"] == self.current_doc_id]
        doc_entries = parser.filter_tag_entries_by_date(doc_entries, since, until)
        if not doc_entries:
            self.update_status(f"No notes with #{tag}")
            return
        lines = [f"[#f9e2af]#{md_escape(tag)}[/]   {len(doc_entries)} notes\n"]
        for e in doc_entries:
            lines.append(f"[#a6e3a1]{md_escape(e['ts'])}[/] {md_escape(e['preview'])}")
        preview = self.query_one("#preview-pane")
        preview.clear()
        preview.write("\n".join(lines))
        preview.scroll_home(animate=False)

    def cmd_tag_stats(self):
        tags = parser.load_tags_index()
        if not tags:
            self.update_status("No tags indexed yet.")
            return
        doc_tags = {}
        for tag, entries in tags.items():
            count = len([e for e in entries
                        if e["doc_id"] == self.current_doc_id])
            if count > 0:
                doc_tags[tag] = count
        if not doc_tags:
            self.update_status("No tags for this document.")
            return
        max_count = max(doc_tags.values()) if doc_tags else 1
        lines = ["[b]Tag Frequency[/b]\n"]
        for tag, count in sorted(doc_tags.items(), key=lambda x: -x[1]):
            bar = '█' * int(count / max_count * 20) if max_count else ''
            lines.append(f"  #{tag:<20} {bar} {count}")
        preview = self.query_one("#preview-pane")
        preview.clear()
        preview.write("\n".join(lines))
        preview.scroll_home(animate=False)

    def cmd_config(self, args):
        if not args or args[0] == 'show':
            history_size = config.get_history_size(self.svc_config)
            preview = self.query_one("#preview-pane")
            preview.clear()
            preview.write(
                "[b]Config Settings[/b]\n\n"
                f"  history_size   {history_size}\n"
                f"  [dim](notes loaded on startup / /switch; range "
                f"{validation.MIN_HISTORY_SIZE}-{validation.MAX_HISTORY_SIZE})[/dim]\n\n"
                "  [dim]Use /config set history_size <n> to change.[/dim]"
            )
            preview.scroll_home(animate=False)
        elif args[0] == 'set' and len(args) >= 3:
            key, value = args[1], args[2]
            if key == 'history_size':
                valid, msg = validation.validate_history_size(value)
                if not valid:
                    self.update_status(f"Invalid: {msg}")
                    return
                self.svc_config["history_size"] = int(value)
                self._history_size = int(value)
                config.save_config(self.svc_config)
                self.update_status(
                    f"history_size set to {value}. Use /switch to reload notes."
                )
            else:
                self.update_status(f"Unknown key '{key}'. Available: history_size")
        else:
            self.update_status(
                f"Usage: /config show | /config set history_size "
                f"<{validation.MIN_HISTORY_SIZE}-{validation.MAX_HISTORY_SIZE}>"
            )

    def cmd_help(self):
        preview = self.query_one("#preview-pane")
        preview.clear()
        preview.write(
            "[b]Commands[/b]\n\n"
            "  /switch <alias>              Switch document\n"
            "  /list                        List documents\n"
            "  /add <a> <id>               Add document\n"
            "  /remove <alias>             Remove document\n"
            "  /rename <o> <n>             Rename alias\n"
            "  /current                    Show active doc\n"
            "  /edit                       Open $EDITOR\n"
            "  /flush                      Retry pending offline notes\n"
            "  /queue [list]               List queued notes and why they failed\n"
            "  /queue drop <n>             Discard queued note n\n"
            "  /queue move <n> <alias>     Send queued note n to another alias\n"
            "  /refresh                    Fetch latest notes from API\n"
            "  /more                       Load older notes beyond startup\n"
            "  /export [<tag>] [--file]     Export notes to Markdown file\n"
            "  /search <keyword>           Search all notes in this doc\n"
            "  /tag list                   Show all tags\n"
            "  /tag search <tag>           Find notes by tag\n"
            "  /tag stats                  Tag frequency chart\n"
            "  /tag reindex                Rebuild this doc's tags from the doc\n"
            "  /config show                Show config settings\n"
            "  /config set history_size    Set notes loaded on startup\n"
            "  /help                       This message\n\n"
            "[dim]Ctrl+S submit | Ctrl+N notes | Ctrl+P preview | Ctrl+E input | Tab cycle[/]"
        )
        preview.scroll_home(animate=False)


class ReadOnlyApp(BaseNotesApp):
    BINDINGS = [
        Binding("ctrl+n", "focus_notes", "Notes"),
        Binding("ctrl+p", "focus_preview", "Preview"),
        Binding("ctrl+e", "focus_cmd", "Command"),
        Binding("escape", "focus_cmd", "Back"),
        Binding("ctrl+s", "run_command", "Run"),
    ]

    HEADER_TITLE = "MyDocBot — Read-Only"
    EMPTY_NOTES_MSG = "No notes yet."
    LIST_HEADER = "Read-Only Documents"
    NO_DOCS_MSG = "No read-only docs configured. Use CLI --add or create read_config.json."
    NO_DOCS_LIST_MSG = "No read-only docs configured."
    ADD_SUCCESS_SUFFIX = " to read-only config"

    def __init__(self, start_alias=None):
        self.start_alias = start_alias
        super().__init__()

    def _load_config(self):
        return config.load_read_config()

    def _save_config(self, cfg):
        config.save_read_config(cfg)

    def _resolve_alias(self, cfg, alias):
        return config.resolve_read_alias(cfg, alias)

    def _fetch_recent(self, doc_id, count):
        return google_docs.parse_entries_readable(
            google_docs.fetch_doc(self._service, doc_id),  # with retry (B10)
            count=count
        )

    def _date_key(self, ts):
        # Read timestamps look like "[DD/MM/YYYY] [H.M]|...". Rebuild the
        # "MM/DD/YY" key expected by `_format_date_header` so Today/Yesterday
        # detection actually lines up with `datetime.now().strftime("%m/%d/%y")`.
        date_str = ts.split("]")[0][1:]
        day, month, year = date_str.split("/")
        return f"{int(month):02d}/{int(day):02d}/{int(year) % 100:02d}"

    def _resolve_initial_alias(self, aliases):
        if self.start_alias and self.start_alias in aliases:
            return self.start_alias
        return super()._resolve_initial_alias(aliases)

    def compose(self) -> ComposeResult:
        yield Static("Connecting...", id="header-bar")
        with Horizontal(id="main-area"):
            yield ListView(id="notes-list")
            yield PreviewPane(id="preview-pane", max_lines=None, highlight=False, wrap=True, markup=True)
        with Horizontal(id="input-area"):
            yield TextArea(id="cmd-bar", text="", placeholder="Type /command... (Ctrl+S to run)")
            yield Button("Run", id="submit-btn", variant="primary")
        yield Static("Initializing...", id="status-bar")

    def action_run_command(self):
        self.run_command()

    def run_command(self):
        cmd_bar = self.query_one("#cmd-bar")
        text = cmd_bar.text.strip()
        if not text:
            return
        cmd_bar.text = ""
        if text.startswith('/'):
            self.handle_command(text)
        else:
            self.update_status("Read-only mode. Type /command or /help.")

    def on_button_pressed(self, event):
        if event.button.id == "submit-btn":
            self.run_command()

    def action_focus_cmd(self):
        self.query_one("#cmd-bar").focus()

    def handle_command(self, cmd):
        parts = cmd.strip().split()
        command = parts[0].lower()
        args = parts[1:]

        if command == '/switch':
            self.cmd_switch(args)
        elif command == '/list':
            self.cmd_list()
        elif command == '/add':
            self.cmd_add(args)
        elif command == '/current':
            self.cmd_current()
        elif command == '/search':
            self.cmd_search(args)
        elif command == '/refresh':
            self.cmd_refresh()
        elif command == '/more':
            self.cmd_more()
        elif command == '/help':
            self.cmd_help()
        else:
            self.update_status(f"Unknown: {command}. Type /help")

    def cmd_help(self):
        preview = self.query_one("#preview-pane")
        preview.clear()
        preview.write(
            "[b]Read-Only Commands[/b]\n\n"
            "  /switch <alias>              Switch document\n"
            "  /list                        List documents\n"
            "  /add <a> <id>               Add document to read-only config\n"
            "  /current                     Show active doc\n"
            "  /search <keyword>            Search all notes in this doc\n"
            "  /refresh                     Fetch latest notes from API\n"
            "  /more                        Load older notes beyond startup\n"
            "  /help                        This message\n\n"
            "[dim]Ctrl+S run | Ctrl+N notes | Ctrl+P preview | Ctrl+E command | Tab cycle[/]"
        )
        preview.scroll_home(animate=False)
