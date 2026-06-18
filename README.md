# MyDocBot

A terminal-based note-taker that prepends timestamped notes to Google Docs.
Dual interface: a line-by-line CLI for quick entries and a rich TUI for browsing and management.

---

## Architecture

### Data Flow

```
User Input (CLI / TUI)
       │
       ▼
  Dispatch Layer (main.py / mydocbot_app.py)
       │
       ├──▶ Command Handler     ──▶ core/config.py     (alias CRUD)
       │                          ▶ core/parser.py     (tags, search, queue)
       │                          ▶ core/google_docs.py (API + retry)
       │                          ▶ core/validation.py  (input guards)
       │
       └──▶ Note Submission
               │
               ├── 1. validate_note(text)           → reject if empty / too long
               ├── 2. prepend_text(service, id, entry) → bool (retries transient errors)
               ├── 3. index_note(text, ts, doc_id)  → tags_index.json updated
               └── 4. flush_pending_notes(service)  → drain offline queue on success
```

Writes go to Google Docs API. Tags are indexed locally in `tags_index.json`.
Failed writes are queued in `pending_queue.json` and retried automatically on the next success.

### Core Modules (`core/`)

| Module | Responsibility | Key Functions |
|---|---|---|
| `config.py` | Document alias management | `load_config()`, `save_config()`, `resolve_alias()` |
| `google_docs.py` | Google Docs API wrappers | `get_service()`, `prepend_text()` → bool, `fetch_doc_title()`, `parse_entries()` |
| `parser.py` | Tags, search, offline queue | `extract_tags()`, `index_note()`, `search_cache()`, `queue_note()`, `flush_pending_notes()`, `filter_tag_entries_by_date()` |
| `validation.py` | Input guards | `validate_doc_id()`, `validate_config()`, `validate_note()` |
| `commands.py` | CLI command handlers | `dispatch()`, all `cmd_*()` functions, `resolve_editor()` |

---

## Tech Stack

- **Language:** Python 3.10+
- **CLI:** Standard library (`argparse`, `input` REPL, `subprocess` for editor)
- **TUI:** [Textual](https://textual.textualize.io/) 0.41+ — async widget framework
- **Storage:** Google Docs API (`google-api-python-client`, `google-auth-oauthlib`, OAuth 2.0)
- **Config:** Local JSON files — `docs_config.json` (aliases) and `tags_index.json` (tag index)
- **Testing:** pytest 7.4+ with monkeypatched Google API — **131 tests, 0 network needed**
- **Lint/Types:** ruff (0 errors) + mypy

---

## Features

### CLI Mode (`python main.py`)

- **Line-by-line input:** Type notes one line at a time; a blank line submits.
- **Slash-commands:** All commands start with `/`.
- **`/edit`:** Launches `$EDITOR` (falls back: `$EDITOR` → `vim` → `nano` → `vi`). Lines starting with `#` are stripped as draft comments.
- **`/switch <alias>`:** Changes the active document for the session.
- **`/add`, `/remove`, `/rename`:** Mutates `docs_config.json` in place. `/remove` prompts for confirmation and auto-switches if the current alias was removed.
- **Tag commands:** `/tag list`, `/tag search <tag>`, `/tag stats` — all operate on local `tags_index.json` only. `/tag search` supports `--since` / `--until` date filters.
- **Offline queue:** Failed submissions are saved to `pending_queue.json`. The queue is automatically flushed on the next successful write. Use `/flush` to retry manually. Pending count is shown in the prompt.
- **Input validation:** Empty notes, oversized notes (>50 KB), and malformed doc IDs are rejected before any API call.
- **Error resilience:** Network failures are caught — session continues, note is queued. Corrupt `docs_config.json` falls back to a fresh empty config with a stderr warning.

### TUI Mode (`python main.py --tui`)

- **Compose layout (dock-based):** 5 visual areas:
  - **Header (top):** App name, current alias, doc title, connection indicator.
  - **NotesList (left, 40%):** Date-grouped list with time-only stamps and `#tag` badges (up to 3).
  - **PreviewPane (right, 60%):** Full note text with highlighted `#tags`. Auto-scrolls to top on selection.
  - **InputBar (bottom):** Multi-line `TextArea` + **Submit** button.
  - **StatusBar (very bottom):** Ready state, error messages, pending offline count.
- **Date grouping:** Notes organized under `─── Today ───`, `─── Yesterday ───`, or `─── MM/DD/YY ───` headers.
- **Keyboard shortcuts:**
  - `Ctrl+S` — Submit note
  - `Ctrl+N` — Focus notes list
  - `Ctrl+P` — Focus preview pane
  - `Ctrl+E` — Focus input area
  - `Escape` — Back to input
  - `Tab` — Cycle focus: notes → input → submit → notes
- **Full-text search:** `/search <keyword>` filters session cache and shows results with keyword highlighting.
- **`/edit`:** Uses Textual's `self.suspend()` for clean terminal handoff — editor opens in the foreground, TUI resumes on exit.
- **Offline queue:** Same queue mechanics as CLI — `/flush` available, pending count shown in status bar.
- **Notes cache:** Newest-first, capped at 500 entries. Loaded from Google Docs on startup and after each doc switch (20 most recent entries).
- **Dark theme:** Catppuccin-inspired. Background `#1e1e2e`, accents `#89b4fa` (blue), `#a6e3a1` (green), `#f38ba8` (red warning), `#585b70` (dimmed separators).

### Cross-Cutting Features

- **`#tag` auto-detection:** `re.findall(r'#(\w+)', text.lower())` — word characters only. Use `#project_alpha` for compound tags.
- **Tag persistence:** After every submission, `index_note()` appends to `tags_index.json`. Duplicates (same ts + doc_id + preview) are suppressed.
- **API retry:** `prepend_text()` retries up to 3 times on HTTP 429/5xx and connection errors, with 1 s / 2 s / 4 s exponential backoff. Non-transient errors (403, 404) are not retried.
- **OAuth flow:** Picks up existing `token.json` or launches browser consent via `google-auth-oauthlib`.
- **Config resilience:** Corrupt `docs_config.json`, `tags_index.json`, and `pending_queue.json` all fall back gracefully with a stderr warning instead of crashing.

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
| `/list` | Show all configured aliases and their titles |
| `/add <alias> <doc_id>` | Register a new Google Doc (validates doc_id format) |
| `/remove <alias>` | Remove an alias (confirms, auto-switches away) |
| `/rename <old> <new>` | Rename an alias |
| `/current` | Show active alias, title, and Doc ID |
| `/edit` | Open `$EDITOR` for multi-line note |
| `/flush` | Retry all queued offline notes |
| `/tag list` | All indexed tags + note counts for current doc |
| `/tag search <tag> [--since MM/DD/YY] [--until MM/DD/YY]` | Notes matching a tag |
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
│  ─── Today ───              │  [06/18/26] (14:30)|           │
│  [14:30] Meeting #project   │  Met with team about the       │
│  [13:00] Bug fix #bug       │  sprint. #project #meeting     │
│  ─── Yesterday ───          │                                │
│  [10:15] Research spike     │                                │
├─────────────────────────────┴────────────────────────────────┤
│  Type a note... (Ctrl+S to submit)              [ Submit ]   │
├──────────────────────────────────────────────────────────────┤
│  Ready                                                       │
└──────────────────────────────────────────────────────────────┘
```

### Widget Tree

```
MyDocBotApp (App)
├── Header (docked top)
├── Horizontal (docked, fills remaining)
│   ├── NotesList (dock left, 40%) — ListView
│   │   ├── DateSeparator (─── Today ───)
│   │   ├── NoteItem  [14:30] Meeting #project
│   │   ├── NoteItem  [13:00] Bug fix #bug
│   │   ├── DateSeparator (─── Yesterday ───)
│   │   └── NoteItem  [10:15] Research spike
│   └── PreviewPane (dock right, 60%) — Static
├── InputBar (docked bottom)
│   ├── TextArea (multiline, placeholder hints Ctrl+S)
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
      "ts": "[06/18/26] (14:30)|",
      "doc_id": "YOUR_DOC_ID",
      "preview": "Met with team to discuss sprint..."
    }
  ]
}
```

### `pending_queue.json` (auto-generated when offline)
```json
[
  {
    "text": "offline note text",
    "doc_id": "YOUR_DOC_ID",
    "ts": "[06/18/26] (14:31)|"
  }
]
```

### File origins

| File | Origin | Purpose |
|---|---|---|
| `credentials.json` | Downloaded from Google Cloud | OAuth client config |
| `token.json` | Generated on first auth | Cached OAuth refresh token |
| `docs_config.json` | Created on first `--add` | Document alias registry |
| `tags_index.json` | Auto-populated on each submit | Local tag search index |
| `pending_queue.json` | Auto-created on network failure | Offline note buffer |

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
├── main.py                  (142 lines) CLI entry, arg_parser, REPL loop
├── mydocbot_app.py          (657 lines) Textual TUI — widgets, 10+ cmd handlers
├── core/
│   ├── __init__.py          (19 lines)  Re-exports with __all__
│   ├── commands.py          (310 lines) All CLI cmd_*(), dispatch(), resolve_editor()
│   ├── config.py            (42 lines)  Alias CRUD, corrupt-config fallback
│   ├── google_docs.py       (108 lines) OAuth, prepend_text→bool, retry, parse_entries
│   ├── parser.py            (152 lines) Tags, search_cache, offline queue, date filters
│   └── validation.py        (31 lines)  validate_doc_id, validate_config, validate_note
├── tests/
│   ├── conftest.py           Fixtures: config/tags/pending paths, mock_service, doc builder
│   ├── test_main.py         (14 tests)  main() REPL loop and --add flag
│   ├── test_config.py       (10 tests)  Config CRUD + corrupt JSON fallback
│   ├── test_parser.py       (64 tests)  Tags, parse_entries, retry, search, corrupt JSON, malformed ts
│   ├── test_commands.py     (20 tests)  CLI cmd_* functions
│   ├── test_dispatch.py     ( 6 tests)  dispatch /remove auto-switch paths
│   ├── test_editor.py       ( 4 tests)  resolve_editor() fallback chain
│   └── test_validation.py   (13 tests)  doc_id, config, note validators
├── docs_config.json          Alias config
├── tags_index.json           Auto-generated tag index
├── pending_queue.json        Auto-generated offline queue (present only when notes are queued)
├── credentials.json          Google OAuth credentials (you provide)
├── token.json                Auto-generated OAuth token (gitignored)
├── pyproject.toml            ruff + mypy config
├── lint.sh                   CI: ruff → mypy → pytest
└── requirements.txt          textual, pytest, google-api packages
```

---

## Testing

```bash
python -m pytest tests/ -v                        # All 131 tests
python -m pytest tests/test_parser.py -v          # Parser + queue + date-filter tests
python -m pytest tests/ -k "corrupt"              # Corrupt-JSON resilience tests
python -m pytest tests/test_main.py -v            # CLI REPL loop tests
bash lint.sh                                      # ruff + mypy + pytest (full CI)
```

| File | Tests | Coverage |
|---|---|---|
| `test_main.py` | 14 | REPL submit/queue/flush, `--add` flag validation, pending count in prompt |
| `test_config.py` | 10 | Load, save, resolve, corrupt JSON fallback + warning |
| `test_parser.py` | 64 | Tag CRUD, parse_entries, prepend_text retry, search_cache, date filters, corrupt JSON, malformed timestamps |
| `test_commands.py` | 20 | All CLI commands: switch, list, add, remove, rename, current, tag, help |
| `test_dispatch.py` | 6 | Dispatch `/remove` auto-switch to default/first/none |
| `test_editor.py` | 4 | `resolve_editor()` env var, fallback chain, missing binary |
| `test_validation.py` | 13 | `validate_doc_id`, `validate_config`, `validate_note` |

All tests use monkeypatched Google API and temp files — no network, no OAuth.

---

## Design Decisions & Known Limitations

- **Submit via `Ctrl+S` or button:** `Ctrl+Enter` was unreliable across terminals. The Submit button is the always-reliable fallback.
- **Single-threaded TUI:** `@work(thread=True)` was removed; Google API calls block the UI briefly (200–500 ms), acceptable for a personal tool.
- **Date grouping via separator items:** `DateSeparator` items carry a `_is_separator` flag; note index mapping is maintained in `_note_to_display`.
- **Local-only tag index:** No historical backfill from Google Docs — only notes submitted in this install are indexed.
- **`#tag` regex:** `#(\w+)` matches word characters only — `#project-alpha` → tag `project`. Use underscores: `#project_alpha`.
- **Notes cache:** 500-entry cap, newest-first. Loaded from the API on startup (20 most recent) and on each `/switch`.
- **Offline queue:** `pending_queue.json` is deleted when empty. Queue is flushed automatically after each successful submit; use `/flush` to retry manually.
- **API retry:** Transient errors (429, 500/502/503/504, `ConnectionError`, `TimeoutError`) are retried up to 3 times with 1 s / 2 s / 4 s backoff. Non-transient errors (403, 404) are not retried.
- **`resolve_editor()` shared:** Both CLI and TUI call the same `resolve_editor()` from `core/commands.py`. Editor fallback order: `$EDITOR` → `vim` → `nano` → `vi`.
- **OAuth token file:** `token.json` lives in the project root — ensure it's in `.gitignore`.

---

## Editor Support (`/edit`)

1. Creates a temp `.md` file in `/tmp/`
2. Writes a `#` comment header as scratch guidance
3. Launches editor via `resolve_editor()`: `$EDITOR` → `vim` → `nano` → `vi`
4. Waits for editor to exit (TUI suspends cleanly via `self.suspend()`)
5. Reads file, strips all lines starting with `#`
6. Submits content as a single note (validated before API call)
7. Cleans up temp file

---

## Quickstart

- [ ] Enable Google Docs API in Cloud Console
- [ ] Download `credentials.json` to project root
- [ ] `pip install -r requirements.txt`
- [ ] `python main.py --add mynotes <doc_id>`
- [ ] `python main.py` (first run triggers OAuth browser flow)
- [ ] `python main.py --tui` for the date-grouped TUI
