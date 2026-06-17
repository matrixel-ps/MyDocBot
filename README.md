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
       │                          ▶ core/parser.py (tags, search)
       │                          ▶ core/google_docs.py (API)
       │
       └──▶ Note Submission
               │
               ├── 1. extract_tags(text) → tag index updated
               ├── 2. format_note() → timestamp + body
               └── 3. prepend_text(service, doc_id, note) → bool
```

All writes go to Google Docs API. Tags are indexed locally in `tags_index.json` at submission time — no historical backfill.

### Core Modules (`core/`)

| Module | Responsibility | Key Functions |
|---|---|---|
| `config.py` | Document alias management | `load_config()`, `save_config()`, `resolve_alias()` |
| `google_docs.py` | Google Docs API wrappers | `get_service()`, `prepend_text()` → bool, `parse_entries()`, `AsyncGoogleDocs` |
| `parser.py` | Tag extraction, search, persistence | `extract_tags()`, `load_tags_index()`, `index_note()`, `search_cache()` |

---

## Tech Stack

- **Language:** Python 3.10+
- **CLI:** Standard library (`argparse`, `input` REPL, `subprocess` for editor)
- **TUI:** [Textual](https://textual.textualize.io/) 0.41+ — async widget framework
- **Storage:** Google Docs API (`google-api-python-client`, `google-auth-oauthlib`, OAuth 2.0)
- **Config:** Local JSON files — `docs_config.json` (aliases) and `tags_index.json` (tag index)
- **Testing:** pytest 7.4+ with monkeypatched Google API — **66 tests, 0 network needed**

---

## Features

### CLI Mode (`python main.py`)

- **Line-by-line input:** Type notes one line at a time; a blank line submits.
- **Slash-commands:** All commands start with `/`.
- **`/edit`:** Launches `$EDITOR` (falls back: `$VISUAL` → `$EDITOR` → `nano`). Lines starting with `#` are stripped as draft comments.
- **`/switch <alias>`:** Changes the active document for the session.
- **`/add`, `/remove`, `/rename`:** Mutates `docs_config.json` in place. `/remove` prompts for confirmation and auto-switches if the current alias was removed.
- **Tag commands:** `/tag list`, `/tag search <tag>`, `/tag stats` — all operate on local `tags_index.json` only.
- **Error resilience:** Network failures print to stderr and continue the session.
- **Config corruption resilience:** Corrupt `docs_config.json` is detected, a warning is printed, and a fresh config is created.

### TUI Mode (`python main.py --tui`)

- **Compose layout (dock-based):** 5 visual areas:
  - **Header dock (top):** Shows app name, current alias, doc title, connection indicator.
  - **NotesList dock (left, 40%):** Date-grouped list of notes with time-only stamps and `#tag` badges.
  - **Preview dock (right, 60%):** Full note text with highlighted `#tags`. Auto-scrolls to top on each selection.
  - **Input dock (bottom):** Multi-line `TextArea` + **Submit** button.
  - **Status bar (very bottom):** Shows ready state or error messages.
- **Date grouping:** Notes organized under `─── Today ───`, `─── Yesterday ───`, or `─── MM/DD/YY ───` headers.
- **Tag badges in list:** Up to 3 `#tag` names shown after each preview snippet (green).
- **Keyboard shortcuts:**
  - `Ctrl+S` — Submit note
  - `Ctrl+N` — Focus notes list
  - `Ctrl+P` — Focus preview pane
  - `Ctrl+E` — Focus input area
  - `Escape` — Back to input
  - `Tab` — Cycle focus: notes → input → submit → notes
- **Full-text search:** `/search <keyword>` filters session cache and shows results with keyword highlighting.
- **Submit button** is the primary submission mechanism (reliable on all terminals).
- **Sync API calls:** Google API calls run on the main thread (no threading races).
- **Notes cache:** Newest-first, capped at 500 entries.
- **`/edit`:** Uses Textual's `self.suspend()` for clean terminal handoff — editor opens in the foreground, TUI resumes on exit.
- **Dark theme:** Catppuccin-inspired. Background `#1e1e2e`, accents in `#89b4fa` (blue), `#a6e3a1` (green), `#f38ba8` (red warning), `#585b70` (dimmed separators).

### Cross-Cutting Features

- **`#tag` auto-detection:** `re.findall(r'#(\w+)', text.lower())` — word characters only. Use `#project_alpha` for compound tags.
- **Tag persistence:** After every submission, `index_note()` appends to `tags_index.json`.
- **OAuth flow:** Runs synchronously. Picks up existing `token.json` or launches browser consent via `google-auth-oauthlib`.

---

## Setup

### 1. Google Cloud Project & OAuth

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project, enable the **Google Docs API**
3. Create OAuth 2.0 credentials (Desktop application type)
4. Download `credentials.json` to project root

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Add a document alias

```bash
python main.py --add log <google_doc_id>
```

Doc ID from URL: `https://docs.google.com/document/d/THIS_IS_THE_ID/edit`

### 4. Run

```bash
python main.py              # CLI mode (default)
python main.py --tui        # TUI mode
python main.py --doc work   # Start with specific alias
python main.py --list       # List all aliases
```

---

## CLI Usage

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
| `/remove <alias>` | Remove an alias (asks confirmation, auto-switches) |
| `/rename <old> <new>` | Rename an alias |
| `/current` | Show active alias + Doc ID |
| `/edit` | Open `$EDITOR` for multi-line note |
| `/tag list` | All indexed tags + note counts |
| `/tag search <tag>` | Notes matching a tag (local index) |
| `/tag stats` | Tag frequency bar chart |
| `/search <keyword>` | Full-text search (TUI only, session cache) |
| `/help` | Show command list |
| `exit` | Quit |

---

## TUI Layout

```
┌──────────────────────────────────────────────────────────────┐
│  MyDocBot          [log] "My Doc"               ● Connected  │
├─────────────────────────────┬────────────────────────────────┤
│  Notes List                 │  Preview Pane                  │
│  ─── Today ───              │  [06/17/26] (14:30)|          │
│  [14:30] Meeting #project   │  Met with team about the      │
│  [13:00] Bug fix #bug      │  sprint. #project #meeting    │
│  ─── Yesterday ───          │                                │
│  [10:15] Research spike     │                                │
├─────────────────────────────┴────────────────────────────────┤
│  Type a note... (Ctrl+S to submit)           [ Submit ]     │
├──────────────────────────────────────────────────────────────┤
│  Ready                                              Ctrl+E  │
└──────────────────────────────────────────────────────────────┘
```

### Widget Tree

```
MyDocBotApp (App)
├── Header (docked top)
├── HorizontalScroll (docked, fills remaining)
│   ├── NotesList (dock left, 40%) — ListView
│   │   ├── DateSeparator (─── Today ───)
│   │   ├── NoteItem  [14:30] Meeting #project
│   │   ├── NoteItem  [13:00] Bug fix #bug
│   │   ├── DateSeparator (─── Yesterday ───)
│   │   └── NoteItem  [10:15] Research spike
│   └── PreviewPane (dock right, 60%) — Static
├── InputBar (docked bottom)
│   ├── TextArea (multiline)
│   └── SubmitButton
└── StatusBar (docked bottom)
```

---

## Configuration Files

### `docs_config.json`
```json
{
  "default": "log",
  "aliases": {
    "log": "YOUR_DOC_ID"
  }
}
```

### `tags_index.json` (auto-generated)
```json
{
  "meeting": [
    {
      "ts": "[06/17/26] (14:30)|",
      "doc_id": "YOUR_DOC_ID",
      "preview": "Met with team to discuss sprint..."
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
| `tags_index.json` | Auto-populated | Local tag search index |

---

## Note Format

```
[MM/DD/YY] (HH:MM)| Note body here — multiple lines preserved.

#tags are included in the body as-is.
```

---

## Project Structure

```
.
├── main.py                  (344 lines) CLI entry, argparse, 12 cmd handlers, dispatch
├── mydocbot_app.py          (636 lines) Textual TUI: DateSeparator, NoteItem, MyDocBotApp,
│                                        9 cmd handlers, Submit + Ctrl+S, date grouping
├── core/
│   ├── __init__.py          (3 lines)  Re-exports
│   ├── config.py            (34 lines) Alias CRUD, JSONDecodeError handling
│   ├── google_docs.py       (122 lines) OAuth, prepend_text→bool, parse_entries, AsyncGoogleDocs
│   └── parser.py            (43 lines) Tag extraction, index CRUD, search_cache
├── tests/
│   ├── conftest.py          (66 lines) Fixtures: sample_config, tmp_paths, mock_service, doc builder
│   ├── test_config.py       (72 lines) 11 tests — CRUD + corrupt JSON handling
│   ├── test_parser.py       (206 lines) 32 tests — tags, parse_entries, prepend_text, search_cache
│   ├── test_commands.py     (151 lines) 16 tests — all CLI dispatch commands
│   ├── test_dispatch.py     (78 lines)  6 tests — dispatch /remove auto-switch paths
│   └── test_editor.py       (30 lines)  4 tests — EDITOR resolution
├── docs_config.json          Alias config
├── tags_index.json           Auto-generated tag DB
├── credentials.json          Google OAuth (you provide)
├── token.json                Auto-generated OAuth token (gitignore)
└── requirements.txt          textual>=0.41.0, pytest>=7.4.0, google packages
```

---

## Testing

```bash
python -m pytest tests/ -v                    # All 66 tests
python -m pytest tests/test_parser.py -v      # Parser tests
python -m pytest tests/ -k "search"           # Search-related tests
```

| Module | Tests | What's covered |
|---|---|---|
| `test_config.py` | 11 | Load, save, resolve, corrupt JSON fallback + warning |
| `test_parser.py` | 32 | Tag extraction, index CRUD, parse_entries, prepend_text errors, search_cache |
| `test_commands.py` | 16 | All CLI commands: switch, list, add, remove (bool), rename, current, help |
| `test_dispatch.py` | 6 | Dispatch /remove auto-switch to default/first/none |
| `test_editor.py` | 4 | EDITOR env var, fallback, missing binary |

All tests use monkeypatched Google API and temp files — no network, no OAuth.

---

## Design Decisions & Known Limitations

- **Submit button + Ctrl+S:** `Ctrl+Enter` was unreliable across terminals. The Submit button always works; `Ctrl+S` is a convenience that may not fire on terminals that intercept it (XOFF).
- **Single-threaded TUI:** `@work(thread=True)` was removed because it silently swallowed execution. Sync Google API calls block the UI briefly (200-500ms), acceptable for a personal tool.
- **Date grouping via ListItem separators:** `DateSeparator` items with `_is_separator` flag; index mapping via `_note_to_display` dict.
- **Local-only tag index:** No historical note backfill from Google Docs.
- **`#tag` regex:** `#(\w+)` matches word characters only — `#project-alpha` → tag `project`.
- **Notes cache:** Newest-first order, capped at 500 entries, evicts oldest.
- **`/edit` uses `self.suspend()`:** Clean terminal handoff via Textual's suspend/resume API.
- **OAuth token file:** `token.json` lives in project root — add to `.gitignore`.

---

## Editor Support (`/edit`)

1. Creates temp `.md` file in `/tmp/`
2. Writes `#` comment header as scratch buffer
3. Launches editor: `$VISUAL` → `$EDITOR` → `nano`
4. Waits for editor to exit
5. Reads file, strips `#` comment lines
6. Submits content as a single note
7. Cleans up temp file

---

## Quickstart

- [ ] Enable Google Docs API in Cloud Console
- [ ] Download `credentials.json` to project root
- [ ] `pip install -r requirements.txt`
- [ ] `python main.py --add mynotes <doc_id>`
- [ ] `python main.py` (first run triggers OAuth)
- [ ] `python main.py --tui` for date-grouped TUI
