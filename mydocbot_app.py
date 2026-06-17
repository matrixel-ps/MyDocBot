import re
import os
import tempfile
import subprocess
import shutil
import shlex
from datetime import datetime
from textual.app import App, ComposeResult
from textual.widgets import Header, Static, ListView, ListItem, Label, Input, TextArea, Button
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.reactive import reactive
from textual.message import Message
from textual.binding import Binding
from core import config, google_docs, parser

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
"""


class NoteItem(ListItem):
    def __init__(self, timestamp, text, doc_id):
        preview = text[:80].replace('\n', ' ')
        label = Label(f"[{timestamp}] {preview}")
        super().__init__(label)
        self.note_ts = timestamp
        self.note_text = text
        self.note_doc_id = doc_id
        self.tags = parser.extract_tags(text)


class MyDocBotApp(App):
    CSS = CSS

    BINDINGS = [
        Binding("ctrl+n", "focus_notes", "Notes"),
        Binding("ctrl+p", "focus_preview", "Preview"),
        Binding("ctrl+e", "focus_input", "Input"),
        Binding("escape", "focus_input", "Back"),
    ]

    MAX_CACHE = 500

    def __init__(self):
        super().__init__()
        self.svc_config = config.load_config()
        self.docs = google_docs.AsyncGoogleDocs()
        self.current_alias = None
        self.current_doc_id = None
        self.current_title = None
        self.notes_cache = []
        self.all_tags = {}
        self._last_selected_index = 0

    def _add_to_cache(self, ts, text, doc_id):
        self.notes_cache.insert(0, {"ts": ts, "text": text, "doc_id": doc_id})
        if len(self.notes_cache) > self.MAX_CACHE:
            self.notes_cache[:] = self.notes_cache[:self.MAX_CACHE]

    def compose(self) -> ComposeResult:
        yield Static("Connecting...", id="header-bar")
        with Horizontal(id="main-area"):
            yield ListView(id="notes-list")
            yield Static("Select a note to preview", id="preview-pane")
        with Horizontal(id="input-area"):
            yield TextArea(id="input-bar", text="", placeholder="Type a note... (click Submit)")
            yield Button("Submit", id="submit-btn", variant="primary")
        yield Static("Initializing...", id="status-bar")

    def on_mount(self):
        self.init_app()

    def init_app(self):
        try:
            aliases = self.svc_config.get("aliases", {})
            if not aliases:
                self.show_error("No docs configured. Use CLI --add first.")
                return

            default = self.svc_config.get("default", "")
            self.current_alias = default if default in aliases else next(iter(aliases))
            self.current_doc_id = aliases[self.current_alias]
            self.current_title = google_docs.fetch_doc_title(self.docs._service, self.current_doc_id)
            if not self.current_title:
                self.current_title = self.current_doc_id[:20] + "..."

            recent = google_docs.parse_entries(
                self.docs._service.documents().get(
                    documentId=self.current_doc_id
                ).execute(),
                count=2
            )
            for ts, body in recent:
                self._add_to_cache(ts, body, self.current_doc_id)

            self.all_tags = parser.load_tags_index()
        except Exception as e:
            self.show_error(f"Startup error: {e}")
            if not self.current_alias:
                self.current_alias = "?"
            if not self.current_doc_id:
                self.current_doc_id = "?"
            self.current_title = "(error)"

        self.refresh_ui()

    def refresh_ui(self):
        header = self.query_one("#header-bar")
        doc_display = f"[bold]{self.current_alias}[/] [italic]{self.current_title}[/]"
        status = "● Connected"
        header.update(f"[b]MyDocBot[/b]     {doc_display}     {status}")

        notes_list = self.query_one("#notes-list")
        notes_list.clear()
        doc_notes = [n for n in self.notes_cache if n["doc_id"] == self.current_doc_id]
        for n in doc_notes:
            item = NoteItem(n["ts"], n["text"], n["doc_id"])
            notes_list.append(item)
        if doc_notes:
            idx = min(self._last_selected_index, len(doc_notes) - 1)
            notes_list.index = idx
            self.show_note_preview(idx)

        self.update_status("Ready")

    def on_list_view_selected(self, event):
        notes_list = self.query_one("#notes-list")
        if notes_list.index is not None:
            self._last_selected_index = notes_list.index
            self.show_note_preview(notes_list.index)

    def show_note_preview(self, index):
        notes_list = self.query_one("#notes-list")
        children = list(notes_list.children)
        if not children or index >= len(children):
            return
        item = children[index]
        ts = item.note_ts
        text = item.note_text
        preview = self.query_one("#preview-pane")
        highlighted = re.sub(
            r'(#\w+)',
            r'[bold #f9e2af]\1[/]',
            text
        )
        preview.update(f"[#a6e3a1]{ts}[/]\n\n{highlighted}")

    def submit_note(self):
        input_bar = self.query_one("#input-bar")
        text = input_bar.text.strip()
        if not text:
            return

        if text.startswith('/'):
            input_bar.text = ""
            self.handle_command(text)
            return

        input_bar.text = ""
        timestamp = datetime.now().strftime("[%m/%d/%y] (%H:%M)|")
        entry = f"{timestamp} {text}"

        try:
            google_docs.prepend_text(self.docs._service, self.current_doc_id, entry)
        except Exception as e:
            self.update_status(f"Error: {e}")
            return

        parser.index_note(text, timestamp, self.current_doc_id, text)

        self._add_to_cache(timestamp, text, self.current_doc_id)

        tags = parser.extract_tags(text)
        tag_str = ' '.join(f'#{t}' for t in tags) if tags else '(no tags)'
        self.refresh_ui()
        self.update_status(f"Prepended  |  {tag_str}")

    def update_status(self, msg):
        status_bar = self.query_one("#status-bar")
        status_bar.update(msg)

    def show_error(self, msg):
        status_bar = self.query_one("#status-bar")
        status_bar.update(f"[#f38ba8]{msg}[/]")

    def on_button_pressed(self, event):
        if event.button.id == "submit-btn":
            self.submit_note()

    def action_focus_notes(self):
        self.query_one("#notes-list").focus()

    def action_focus_preview(self):
        self.query_one("#preview-pane").focus()

    def action_focus_input(self):
        self.query_one("#input-bar").focus()

    def key_press(self, event):
        if event.key == "tab":
            event.prevent_default()
            self.action_focus_notes()

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
        elif command == '/tag':
            self.cmd_tag(args)
        elif command == '/help':
            self.cmd_help()
        else:
            self.update_status(f"Unknown: {command}. Type /help")

    def cmd_switch(self, args):
        if not args:
            self.update_status("Usage: /switch <alias>")
            return
        alias = args[0]
        doc_id = config.resolve_alias(self.svc_config, alias)
        if not doc_id:
            self.update_status(f"Unknown alias '{alias}'")
            return
        title = google_docs.fetch_doc_title(self.docs._service, doc_id)
        self.current_alias = alias
        self.current_doc_id = doc_id
        self.current_title = title or doc_id[:20] + "..."
        recent = google_docs.parse_entries(
            self.docs._service.documents().get(documentId=doc_id).execute(),
            count=2
        )
        for ts, body in recent:
            self._add_to_cache(ts, body, doc_id)
        self._last_selected_index = 0
        self.refresh_ui()
        self.update_status(f"Switched to '{alias}' ({title or doc_id})")

    def cmd_list(self):
        aliases = self.svc_config.get("aliases", {})
        if not aliases:
            self.update_status("No documents configured.")
            return
        lines = []
        for alias, doc_id in aliases.items():
            marker = " ← active" if alias == self.current_alias else ""
            lines.append(f"  {alias:<12} {doc_id}{marker}")
        preview = self.query_one("#preview-pane")
        preview.update("[b]Configured Documents[/b]\n\n" + "\n".join(lines))

    def cmd_add(self, args):
        if not args or len(args) < 2:
            self.update_status("Usage: /add <alias> <doc_id>")
            return
        alias, doc_id = args[0], args[1]
        aliases = self.svc_config.setdefault("aliases", {})
        if alias in aliases:
            self.update_status(f"Alias '{alias}' already exists.")
            return
        aliases[alias] = doc_id
        config.save_config(self.svc_config)
        self.update_status(f"Added '{alias}'")

    def cmd_remove(self, args):
        if not args:
            self.update_status("Usage: /remove <alias>")
            return
        alias = args[0]
        aliases = self.svc_config.get("aliases", {})
        if alias not in aliases:
            self.update_status(f"Alias '{alias}' not found.")
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

    def cmd_current(self):
        preview = self.query_one("#preview-pane")
        preview.update(
            f"[b]Active Document[/b]\n\n"
            f"Alias:    {self.current_alias}\n"
            f"Title:    {self.current_title or '(unknown)'}\n"
            f"Doc ID:   {self.current_doc_id}"
        )

    def cmd_edit(self):
        editor_parts = self._resolve_editor()
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
            content_lines = [l.rstrip('\n') for l in raw_lines
                           if not l.strip().startswith('#')]
            content = "\n".join(content_lines).strip()
            if not content:
                self.update_status("Empty note")
                return
            timestamp = datetime.now().strftime("[%m/%d/%y] (%H:%M)|")
            entry = f"{timestamp} {content}"
            if google_docs.prepend_text(self.docs._service, self.current_doc_id, entry):
                parser.index_note(content, timestamp, self.current_doc_id, content)
                self._add_to_cache(timestamp, content, self.current_doc_id)
                self.refresh_ui()
                self.update_status("Prepended editor content")
            else:
                self.update_status("Failed to prepend note")
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
        title = google_docs.fetch_doc_title(self.docs._service, doc_id)
        self.current_alias = alias
        self.current_doc_id = doc_id
        self.current_title = title or doc_id[:20] + "..."
        self.refresh_ui()
        self.update_status(f"Switched to '{alias}'")

    def cmd_tag(self, args):
        if not args:
            self.cmd_tag_list()
        elif args[0] == 'list':
            self.cmd_tag_list()
        elif args[0] == 'search' and len(args) >= 2:
            self.cmd_tag_search(args[1])
        elif args[0] == 'stats':
            self.cmd_tag_stats()
        else:
            self.update_status("Usage: /tag list | /tag search <tag> | /tag stats")

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
        preview.update("[b]Tag Index[/b]\n\n" + "\n".join(lines))

    def cmd_tag_search(self, tag):
        tags = parser.load_tags_index()
        tag = tag.lower().lstrip('#')
        entries = tags.get(tag, [])
        doc_entries = [e for e in entries
                      if e["doc_id"] == self.current_doc_id]
        if not doc_entries:
            self.update_status(f"No notes with #{tag}")
            return
        lines = [f"[#f9e2af]#{tag}[/]   {len(doc_entries)} notes\n"]
        for e in doc_entries:
            lines.append(f"[#a6e3a1]{e['ts']}[/] {e['preview']}")
        preview = self.query_one("#preview-pane")
        preview.update("\n".join(lines))

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
        preview.update("\n".join(lines))

    def cmd_help(self):
        preview = self.query_one("#preview-pane")
        preview.update(
            "[b]Commands[/b]\n\n"
            "  /switch <alias>     Switch document\n"
            "  /list               List documents\n"
            "  /add <a> <id>       Add document\n"
            "  /remove <alias>     Remove document\n"
            "  /rename <o> <n>     Rename alias\n"
            "  /current            Show active doc\n"
            "  /edit               Open $EDITOR\n"
            "  /tag list           Show all tags\n"
            "  /tag search <tag>   Find notes by tag\n"
            "  /tag stats          Tag frequency chart\n"
            "  /help               This message\n\n"
            "[dim]Tab to Submit btn | Ctrl+N notes | Ctrl+P preview | Ctrl+E input[/]"
        )

    def _resolve_editor(self):
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
