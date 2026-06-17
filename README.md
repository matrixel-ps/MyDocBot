# MyDocBot

A terminal-based note-taker that prepends timestamped notes to Google Docs.  
Dual interface: line-by-line CLI for quick entries, and a rich TUI for browsing and management.

---

## Architecture

### Data Flow

```
User Input (CLI/TUI)
       │
       ▼
  Dispatch Layer (main.py / mydocbot_app.py)
       │
       ├──▶ Command Handler     ──▶ core/config.py (aliases)
       │                          ▶ core/parser.py (tags)
       │                          ▶ core/google_docs.py (API)
       │
       └──▶ Note Submission
               │
               ├── 1. extract_tags(text) → tag index updated
               ├── 2. format_note() → timestamp + body
               └── 3. prepend_text(service, doc_id, note)
```

All writes go to Google Docs API. Tags are indexed locally in `tags_index.json` at submission time — no historical backfill.

### Core Modules (`core/`)

| Module | Responsibility | Key Functions |
|---|---|---|
| `config.py` | Document alias management | `load_config()`, `save_config()`, `resolve_alias()` |
| `google_docs.py` | Google Docs API wrappers | `get_service()`, `prepend_text()`, `parse_entries()`, `AsyncGoogleDocs` class |
| `parser.py` | Tag extraction & persistence | `extract_tags()`, `load_tags_index()`, `save_tags_index()`, `index_note()`, `search_tags()`, `get_tag_stats()` |

---

## Tech Stack

- **Language:** Python 3.10+
- **CLI:** Standard library (`argparse`, `input` REPL, `subprocess` for editor)
- **TUI:** [Textual](https://textual.textualize.io/) 0.41+ — async widget framework
- **Storage:** Google Docs API (`google-api-python-client`, `google-auth-oauthlib`, OAuth 2.0)
- **Config:** Local JSON files — `docs_config.json` (aliases) and `tags_index.json` (tag index)
- **Testing:** pytest 7.4+ with monkeypatched Google API

---

## Features

### CLI Mode (`python main.py`)

- **Line-by-line input:** Type notes one line at a time; a blank line submits. The `get_multiline_input()` function accumulates lines until empty input.
- **Slash-commands:** All commands start with `/`. Dispatch happens in `main.py` via a command string comparison block.
- **`/edit`:** Launches `$EDITOR` with a temp `.md` file. After the editor exits, lines starting with `#` are stripped (treated as scratch/draft lines), then the remaining content is submitted as a single note.
- **`/switch <alias>`:** Changes the active document for the session by calling `resolve_alias()`.
- **`/add`, `/remove`, `/rename`:** Mutates `docs_config.json` in place. `/remove` prompts for confirmation.
- **Tag commands:** `/tag list`, `/tag search <tag>`, `/tag stats` — all operate on the local `tags_index.json` only. No Google API calls.

### TUI Mode (`python main.py --tui`)

- **Compose layout (dock-based):** 5 visual areas:
  - **Header dock (top):** Shows app name, current alias, doc title, and a connection indicator.
  - **NotesList dock (left):** Scrollable list of `NoteItem` widgets (custom `ListItem` subclass). Each shows timestamp, preview snippet, and tag highlights (in `#ffaaff` purple). On startup, fetches the last 2 notes via `parse_entries()`.
  - **Preview dock (right):** Full note text displayed in a read-only rich text widget. Updates when a note is selected.
  - **Input dock (bottom + status bar):** Multi-line `TextArea` + a **Submit** button. Status bar shows context-sensitive hints.
  - **Status bar (very bottom):** Shows ready state or error messages.
- **Submit button** is the primary submission mechanism. The `on_button_pressed` handler:
  1. Gets input text
  2. Checks for leading `/` (command dispatch)
  3. Calls `extract_tags()`, `index_note()`, `prepend_text()`
  4. Calls `update_notes()` to refresh the list
  5. Clears the input
- **Sync API calls:** Google API calls run on the main thread, blocking briefly.
- **Event handling:** `Ctrl+E` focuses input, `Ctrl+N` focuses notes list, `Ctrl+P` focuses preview pane.
- **Dark theme:** Catppuccin-inspired palette. Background `#1e1e2e`, accents in `#89b4fa` (blue), `#a6e3a1` (green), `#f38ba8` (red warning).

### Cross-Cutting Features

- **`#tag` auto-detection:** Uses `re.findall(r'#(\w+)', text.lower())` — only word characters, no hyphens (`#project-x` → tag `project`).
- **Tag persistence:** After every note submission, `index_note()` appends to `tags_index.json` with a timestamp, doc_id, and a preview (first 80 chars of the note body).
- **OAuth flow:** Runs synchronously. `get_service()` picks up an existing `token.json` or launches the browser-based OAuth consent flow via `google-auth-oauthlib`.

---

## Setup

### 1. Google Cloud Project & OAuth

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project, enable the **Google Docs API**
3. Create OAuth 2.0 credentials (Desktop application type)
4. Download `credentials.json` and place it in the project root

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Add a document alias

```bash
python main.py --add log <google_doc_id>
```

Replace `<google_doc_id>` with the ID from the URL:
`https://docs.google.com/document/d/THIS_IS_THE_ID/edit`

### 4. Run

```bash
# CLI mode (default)
python main.py

# TUI mode
python main.py --tui

# Start with specific alias
python main.py --doc work

# List all aliases
python main.py --list
```

On first run, the OAuth flow opens your browser for Google account authorization.

---

## CLI Usage

### Starting

```
python main.py                   # default doc alias
python main.py --doc work        # specific alias
python main.py --list            # list all aliases
python main.py --add log <id>    # register a Google Doc
```

### Inside a Session

- Type text, press Enter for next line, **blank line submits**.
- Type `exit` or `Ctrl+C` to quit.
- Type `/help` for the command menu.

### Command Reference

| Command | Description |
|---|---|
| `/switch <alias>` | Switch active document mid-session |
| `/list` | Show all configured aliases |
| `/add <alias> <doc_id>` | Register a new Google Doc |
| `/remove <alias>` | Remove an alias (asks confirmation) |
| `/rename <old> <new>` | Rename an alias |
| `/current` | Show active alias + Doc ID |
| `/edit` | Open `$EDITOR` for multi-line note |
| `/tag list` | All indexed tags + note counts |
| `/tag search <tag>` | Notes matching a tag (local index) |
| `/tag stats` | Tag frequency bar chart |
| `/help` | Show command list |
| `exit` | Quit |

---

## TUI Layout

```
┌──────────────────────────────────────────────────────────────┐
│  Header Bar                                                  │
│  MyDocBot          [log] MyDocBot Log           ● Connected  │
├─────────────────────────────┬────────────────────────────────┤
│  Notes List                 │  Preview Pane                  │
│  ── Today ──────────        │  Full note text with           │
│  [06/16] Meeting notes      │  highlighted #tags and         │
│  [06/16] Bug fix #bug      │  timestamp styling             │
│                             │                                │
│  ── Yesterday ──────        │                                │
│  [06/15] Research spike     │                                │
│                             │                                │
├─────────────────────────────┴────────────────────────────────┤
│  Input: Type your note here...               [ Submit ]     │
├──────────────────────────────────────────────────────────────┤
│  Status: Ready                                       Ctrl+E  │
└──────────────────────────────────────────────────────────────┘
```

### Widget Tree (Textual)

```
MyDocBotApp (App)
├── Header (docked top)
├── HorizontalScroll (docked, fills remaining)
│   ├── NotesList (dock left, 40% width)
│   └── PreviewPane (dock right, 60% width)
├── InputBar (docked bottom)
│   ├── TextArea (multiline, grows)
│   └── SubmitButton (static width)
└── StatusBar (docked bottom, fixed height)
```

---

## Configuration Files

### `docs_config.json`
```json
{
  "default": "log",
  "aliases": {
    "log": "YOUR_DOC_ID",
    "work": "another_doc_id_here"
  }
}
```

### `tags_index.json` (auto-generated)
```json
{
  "meeting": [
    {
      "ts": "[06/16/26] (14:30)",
      "doc_id": "YOUR_DOC_ID",
      "preview": "Met with team to discuss sprint planning and roadmap prio..."
    }
  ]
}
```

### Auto-created files

| File | Origin | Purpose |
|---|---|---|
| `credentials.json` | Downloaded from Google Cloud | OAuth client config |
| `token.json` | Generated on first auth | Cached OAuth refresh token |
| `docs_config.json` | Created on first `--add` | Document alias registry |
| `tags_index.json` | Auto-populated as notes are written | Local tag search index |

---

## Note Format

Each note is prepended to the Google Doc as:

```
[MM/DD/YY] (HH:MM)
Note body here — multiple lines are preserved.

#tags are included in the body as-is.
```

The timestamp is generated via `datetime.now().strftime("[%m/%d/%y] (%H:%M)")`.

---

## Project Structure

```
.
├── main.py                  # Entry point — argparse, CLI REPL, command dispatch
├── mydocbot_app.py          # Textual TUI app (MyDocBotApp, NoteItem, 5 handlers)
├── core/
│   ├── __init__.py          # Re-exports for other modules
│   ├── config.py            # load_config/save_config/resolve_alias/add_alias/remove_alias/rename_alias
│   ├── google_docs.py       # get_service (OAuth), prepend_text (sync), parse_entries,
│   │                        # AsyncGoogleDocs class for TUI with @work wrappers
│   └── parser.py            # extract_tags, load/save_tags_index, index_note, search_tags,
│                            # get_tag_stats, format_note
├── tests/
│   ├── __init__.py
│   ├── conftest.py          # Shared fixtures: mock service, temp config, temp tag index
│   ├── test_config.py       # 8 tests — alias CRUD, resolve, error cases
│   ├── test_parser.py       # 15 tests — extraction edge cases, index save/load/search/stats
│   ├── test_commands.py     # 12 tests — CLI /switch, /add, /remove, /rename, /edit, /tag*
│   └── test_editor.py       # 4 tests — EDITOR env var resolution, fallback, missing binary
├── docs_config.json          # Local config (you modify)
├── tags_index.json           # Auto-generated tag DB
├── credentials.json          # Google OAuth (you provide)
├── token.json                # Auto-generated OAuth token (gitignore this)
└── requirements.txt          # textual>=0.41.0, pytest>=7.4.0, google-auth-oauthlib, google-api-python-client
```

---

## Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_parser.py -v

# Run by keyword
python -m pytest tests/ -k "tag_search"
```

All 37 tests use monkeypatched Google API (`unittest.mock.patch`) and `tmp_path` fixtures from pytest — no network, no OAuth, no real Google Docs needed.

### Test Coverage

| Module | Tests | What's covered |
|---|---|---|
| `test_config.py` | 8 | Load valid/missing/malformed config, save, add/remove/rename aliases, resolve |
| `test_parser.py` | 15 | Tag extraction (simple, multi, edge chars, case folding), index load/save, search with 0/1/many results, stats, format_note timestamp |
| `test_commands.py` | 12 | All CLI command functions: switch, list, add, remove, rename, edit, tag list/search/stats, help, exit, invalid tag |
| `test_editor.py` | 4 | EDITOR var present, unset var (fallback to nano), non-existent binary (error), prefixed binary path |

---

## Design Decisions & Known Limitations

- **No async Google API in TUI:** `@work(thread=True)` was removed because it silently failed to execute. The sync call blocks the UI briefly (200-500ms typical), which is acceptable for a personal note-taking tool.
- **Submit button instead of keyboard shortcut:** `Ctrl+Enter` was unreliable across terminals (xterm, kitty, ghostty, tmux) and OS. The Submit button always works.
- **`NoteItem` inherits from `ListItem`** with a custom CSS class for styling. Tags are rendered with inline purple color via Rich markup (`[#ffaaff]#tag[/]`).
- **Local-only tag index:** Tags are only indexed from the moment the feature was deployed. No historical notes are fetched from Google Docs for retroactive indexing.
- **`#tag` regex limitation:** `#(\w+)` matches word characters only. `#project-alpha` becomes tag `project`. Use `#project_alpha` for compound tags.
- **OAuth token file:** `token.json` is created in the project root. It should be added to `.gitignore` to avoid committing refresh tokens.
- **Google Doc format:** The doc must have the first line as a blank line for the append-at-top approach to work cleanly. `prepend_text()` prepends the formatted note + two newlines at the very start of the document body.

---

## Editor Support (`/edit`)

The `/edit` command follows a specific flow:

1. Creates a temp file with `.md` extension under `/tmp/`
2. Writes a comment header showing instructions (lines start with `#`)
3. Launches `$EDITOR` — falls back: `$VISUAL` → `$EDITOR` → `nano`
4. Waits for the editor to exit
5. Reads the file back, strips `#` comment lines
6. Submits remaining content as a single note
7. Cleans up temp file

---

## Quickstart Checklist

- [ ] Enable Google Docs API in Cloud Console
- [ ] Download `credentials.json` to project root
- [ ] `pip install -r requirements.txt`
- [ ] `python main.py --add mynotes <doc_id>`
- [ ] `python main.py` (first run triggers OAuth)
- [ ] Type some notes, try `/edit`, add `#tags`
- [ ] Try `python main.py --tui` for the TUI
