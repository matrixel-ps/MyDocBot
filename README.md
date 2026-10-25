# MyDocBot

A terminal-based note-taker that prepends timestamped notes to Google Docs.
Three interfaces: a line-by-line CLI for quick entries, a rich read/write TUI for browsing and management, and a read-only TUI for lightweight browsing of a differently-formatted doc.

See [`CHANGELOG.md`](CHANGELOG.md) for a running log of notable fixes and changes.

---

## Architecture

### Data Flow

```
User Input (CLI / TUI / Read-Only TUI)
       │
       ▼
  Dispatch Layer (main.py / mydocbot_app.py)
       │
       ├──▶ Command Handler     ──▶ core/config.py     (alias CRUD, read + write configs)
       │                          ▶ core/parser.py     (tags, search, queue, date filters)
       │                          ▶ core/google_docs.py (API + retry, two entry parsers)
       │                          ▶ core/validation.py  (input guards)
       │
       └──▶ Note Submission — core/notes.py: submit_note(service, doc_id, text)
               │
               ├── 1. validate_note(text)              → reject if empty / too long
               ├── 2. flush_pending_notes(service)     → write queued notes first, oldest first
               │                                          (stops per doc at the first failure)
               ├── 3. still queued for this doc?       → queue this note behind them
               ├── 4. prepend_text(service, id, entry) → bool (retries transient errors)
               └── 5. index_note(...) on success, queue_note(...) on failure
```

Writes go to Google Docs API. Tags are indexed locally in `tags_index.json`.
Failed writes are queued in `pending_queue.json` and retried, oldest first, before the next note is
written, so the doc keeps the order notes were written in.
The read-only mode never writes — it fetches and parses entries from a doc using a different
timestamp format (see `parse_entries_readable()` below).

### Core Modules (`core/`)

| Module | Responsibility | Key Functions |
|---|---|---|
| `config.py` | Document alias management (separate write + read-only configs) | `load_config()`, `save_config()`, `resolve_alias()`, `get_history_size()`, `load_read_config()`, `save_read_config()`, `resolve_read_alias()` |
| `google_docs.py` | Google Docs API wrappers | `get_service()`, `prepend_text()` → bool, `fetch_doc_title()`, `parse_entries()`, `parse_entries_readable()` |
| `parser.py` | Tags, search, offline queue, date filters | `extract_tags()`, `index_note()`, `search_cache()`, `queue_note()`, `count_pending()`, `flush_pending_notes()`, `parse_date_flags()`, `filter_tag_entries_by_date()` |
| `validation.py` | Input guards | `validate_doc_id()`, `validate_alias()`, `validate_config()`, `validate_note()`, `validate_history_size()` |
| `notes.py` | The single note write path (CLI + TUI) | `submit_note()` → `SubmitResult`, `format_timestamp()` |
| `paths.py` | Where personal data lives, first-run migration | `resolve_data_dir()`, `data_path()`, `prepare_data_dir()` |
| `commands.py` | CLI command handlers | `dispatch()`, all `cmd_*()` functions, `resolve_editor()`, `open_editor()`, `export_to_markdown()` |

---

## Tech Stack

- **Language:** Python 3.10+ (developed against 3.14)
- **CLI:** Standard library (`argparse`, `input` REPL, `subprocess` for editor)
- **TUI:** [Textual](https://textual.textualize.io/) 0.41+ — async widget framework (two apps: read/write and read-only)
- **Storage:** Google Docs API (`google-api-python-client`, `google-auth-oauthlib`, OAuth 2.0)
- **Config:** Local JSON files — `docs_config.json` (write-mode aliases), `read_config.json` (read-only aliases), and `tags_index.json` (tag index)
- **Testing:** pytest 7.4+ with monkeypatched Google API — **305 tests, 0 network needed** (includes a headless Textual `run_test()` suite for both TUI apps)
- **Lint/Types:** ruff (0 errors) + mypy — both are real CI gates via `lint.sh` (mypy covers `mydocbot_app.py` too, not just `core/`)
- **CI:** GitHub Actions (`.github/workflows/ci.yml`) runs `lint.sh` on every push/PR to `main`/`dev`

---

## Features

### CLI Mode (`python main.py`)

- **Line-by-line input:** Type notes one line at a time; a blank line submits.
- **Slash-commands:** All commands start with `/`.
- **`/edit`:** Launches `$EDITOR` (falls back: `$EDITOR` → `vim` → `nano` → `vi`). Lines starting with `#` are stripped as draft comments.
- **`/switch <alias>`:** Changes the active document for the session.
- **`/add`, `/remove`, `/rename`:** Mutates `docs_config.json` in place. `/remove` prompts for confirmation and auto-switches if the current alias was removed. Alias names are validated (`validate_alias()`): no whitespace, no leading `/`.
- **`/search <keyword>`:** Fetches recent notes from the API (up to `history_size`) and filters by keyword.
- **`/export [<tag>] [--file <path>]`:** Exports notes to a local Markdown file — either the notes tagged with `<tag>` (from the local tag index) or the most recent notes fetched from the API if no tag is given.
- **`/config show` / `/config set history_size <n>`:** View or change how many notes are loaded on startup/switch (range 1–500, default 20).
- **Tag commands:** `/tag list`, `/tag search <tag>`, `/tag stats` — all operate on local `tags_index.json` only. `/tag search` supports `--since` / `--until` date filters. `/tag reindex` rebuilds the current doc's tag entries from the whole doc (picks up older notes, notes typed directly in Google Docs, and edits/deletions); other docs' entries are kept and the previous index is saved as `tags_index.json.bak`.
- **Offline queue:** Failed submissions are saved to `pending_queue.json`. Before each new note is written, queued notes for all docs are retried, oldest first, so the doc stays in order; if a doc's queued notes still fail, new notes for it are queued behind them. Tags in queued notes are indexed once they're written. Use `/flush` to retry manually. Pending count is shown in the prompt.
- **Why a note was queued:** the message says what went wrong — offline, a sign-in that needs a restart, or a problem that won't fix itself (document not found, no edit permission). Notes that failed for one of those last reasons are kept but not retried automatically before every note; `/queue` lists every queued note with its last error, `/queue drop <n>` discards one (after asking), `/queue move <n> <alias>` sends one to another alias (e.g. after fixing a wrong doc ID), and `/flush` retries everything.
- **Input validation:** Empty notes, oversized notes (>50 KB), and malformed doc IDs are rejected before any API call.
- **Error resilience:** Network failures are caught — session continues, note is queued. Corrupt `docs_config.json` falls back to a fresh empty config with a stderr warning.

### Read/Write TUI Mode (`python main.py --tui`)

- **Compose layout (dock-based):** 5 visual areas:
  - **Header (top):** App name, current alias, doc title, connection indicator.
  - **NotesList (left, 40%):** Date-grouped list with time-only stamps and `#tag` badges (up to 3).
  - **PreviewPane (right, 60%):** Full note text with highlighted `#tags`. Vertically scrollable for long entries; auto-scrolls to top on selection.
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
- **`/refresh`:** Re-fetches the latest notes from the API for the current document.
- **`/more`:** Loads older notes beyond the initial startup batch into the cache/list.
- **`/export [<tag>] [--file <path>]`:** Same export behavior as the CLI, run from inside the TUI.
- **`/config show` / `/config set history_size <n>`:** Same config command as the CLI.
- **Offline queue:** Same queue mechanics as CLI — `/flush` and `/queue` available (a dropped note's full text is shown in the preview pane so it can still be copied), pending count shown in status bar. Notes written from the queue appear in the notes list right away.
- **Notes cache:** Newest-first, capped at 500 entries. Loaded from Google Docs on startup and after each doc switch (`history_size` most recent entries, default 20).
- **Dark theme:** Catppuccin-inspired. Background `#1e1e2e`, accents `#89b4fa` (blue), `#a6e3a1` (green), `#f38ba8` (red warning), `#585b70` (dimmed separators).

### Read-Only TUI Mode (`python main.py --read [alias]`)

- A separate, lighter-weight Textual app (`ReadOnlyApp`) for browsing notes without ever writing to the doc.
- Uses its own alias registry, `read_config.json`, independent from `docs_config.json`.
- Parses a **different timestamp format** than write mode:
  ```
  DD/MM/YYYY
  [HH.MM]
  Note body...
  ```
  via `google_docs.parse_entries_readable()` (vs. `parse_entries()` for write-mode's `[MM/DD/YY] (HH:MM)|` format).
- **Commands:** `/switch <alias>`, `/list`, `/add <alias> <doc_id>` (adds to the read-only config), `/current`, `/search <keyword>`, `/refresh`, `/more`, `/help`.
- **Keyboard shortcuts:**
  - `Ctrl+S` — Run typed command
  - `Ctrl+N` — Focus notes list
  - `Ctrl+P` — Focus preview pane
  - `Ctrl+E` — Focus command input
  - `Escape` — Back to command input
  - `Tab` — Cycle focus
- No submit/edit/tag/export/config/flush commands — this mode is browse-only.

### Cross-Cutting Features

- **`#tag` auto-detection:** `re.findall(r'#(\w+)', text.lower())` — word characters only. Use `#project_alpha` for compound tags.
- **Tag persistence:** After every submission, `index_note()` appends to `tags_index.json`. Duplicates (same ts + doc_id + preview) are suppressed.
- **API retry:** `prepend_text()` (and other API calls via `_api_call_with_retry()`) retry up to 3 times on HTTP 429/5xx and connection errors, with 1 s / 2 s / 4 s exponential backoff. Non-transient errors (403, 404) are not retried.
- **OAuth flow:** Picks up existing `token.json` or launches browser consent via `google-auth-oauthlib`. If `credentials.json` is missing, `get_service()` exits with a friendly setup message instead of a raw traceback. If the saved token can't be refreshed (revoked or expired) or is unreadable, it is deleted and the browser sign-in runs again; if Google can't be reached at startup, it exits with a connection message and keeps `token.json`.
- **Config resilience:** Corrupt `docs_config.json`, `read_config.json`, `tags_index.json`, and `pending_queue.json` all fall back gracefully with a stderr warning instead of crashing.
- **Doc title caching:** `fetch_doc_title()` caches successful lookups in-process (keyed by `doc_id`), so `/list`, `/switch`, and startup don't repeatedly re-fetch the same title. `/refresh` invalidates the cache for the current doc so external renames are picked up.
- **File permissions:** `token.json`, `docs_config.json`, and `read_config.json` are written with owner-only (`0600`) permissions (best-effort).

---

## Setup

### 1. Google Cloud Project & OAuth

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project, enable the **Google Docs API**
3. Create OAuth 2.0 credentials (Desktop application type)
4. Download it as `credentials.json` into the data directory (see below)

### 2. Install

```bash
pipx install -e .            # global `mydocbot` command (or: uv tool install -e .)
# or, inside a virtualenv:
pip install -e .             # `mydocbot` while the venv is active
pip install -r requirements.txt   # also installs the test tools
```

`python main.py` still works from the repo, with the same flags.

### Data directory

All personal files (`credentials.json`, `token.json`, `docs_config.json`,
`read_config.json`, `tags_index.json`, `pending_queue.json`) live in one
directory, the first that applies:

1. `$MYDOCBOT_HOME`
2. `$XDG_CONFIG_HOME/mydocbot`
3. `~/.config/mydocbot`

It is created `0700` on first run. **Upgrading from an older version:** if
that directory doesn't exist yet, the first run copies those files from the
repo root (their old location) and lists what it copied. The originals are
left in place; delete them once everything works. Migration only ever
happens when the directory is first created.
The repo root is found from the installed code, so migration needs an
editable install (`-e`) or `python main.py`; otherwise copy the files by hand.

### 3. Add a document alias

```bash
mydocbot --add log <google_doc_id>
```

Doc ID from URL: `https://docs.google.com/document/d/THIS_IS_THE_ID/edit`

Or copy `docs_config.example.json` to `docs_config.json` in the data
directory and replace `YOUR_GOOGLE_DOC_ID`.

### 4. Run

```bash
mydocbot                    # CLI mode (default)
mydocbot --tui              # Read/write TUI mode
mydocbot --read             # Read-only TUI mode (uses read_config.json default)
mydocbot --read log2        # Read-only TUI mode, starting on a specific alias
mydocbot --doc work         # Start CLI with specific alias
mydocbot --list             # List all configured (write-mode) aliases
```

### Quick capture (one note, no REPL)

```bash
mydocbot "met with Sam #standup"       # write to the default doc and exit
mydocbot -d work "call the vendor"     # write to another alias
echo "built from a script" | mydocbot -d work   # note read from stdin
git log -1 --format=%s | mydocbot      # anything piped in becomes the note
```

It goes through the same path as the REPL: validation, offline queueing,
`#tag` indexing, and writing any queued notes first. Success prints one line
to stdout; errors go to stderr. Exit codes: `0` sent, `1` rejected or
config error (e.g. unknown alias), `2` usage error, `3` queued offline.
Piping text into `mydocbot` now always means "write this note"; to drive
the REPL from a script, use a pseudo-terminal or the one-shot form instead.

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
| `/flush` | Retry all queued offline notes (including ones that failed permanently) |
| `/queue [list]` | List queued notes, oldest first, with the reason each one failed |
| `/queue drop <n>` | Discard queued note `n` (asks first; prints its text) |
| `/queue move <n> <alias>` | Send queued note `n` to another alias instead |
| `/search <keyword>` | Full-text search over notes fetched from the API |
| `/export [<tag>] [--file <path>]` | Export notes (by tag, or most recent) to a local Markdown file |
| `/tag list` | All indexed tags + note counts for current doc |
| `/tag search <tag> [--since MM/DD/YY] [--until MM/DD/YY]` | Notes matching a tag |
| `/tag stats` | Tag frequency bar chart |
| `/tag reindex` | Rebuild the current doc's tags from the doc itself (backup kept as `tags_index.json.bak`) |
| `/config show` | Show current config settings (e.g. `history_size`) |
| `/config set history_size <1-500>` | Set how many notes are loaded on startup/switch |
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

### Widget Tree (Read/Write TUI)

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
│   └── PreviewPane (dock right, 60%) — RichLog, vertically scrollable
├── InputBar (docked bottom)
│   ├── TextArea (multiline, placeholder hints Ctrl+S)
│   └── SubmitButton
└── StatusBar (docked bottom)
```

The **Read-Only TUI** (`ReadOnlyApp`) uses the same NotesList / PreviewPane / StatusBar layout but
replaces the multi-line `InputBar` with a single-line command input (no Submit button, no editing) —
all interaction is via `/`-commands run with `Ctrl+S`.

---

## Configuration Files

### `docs_config.json` (write mode)
```json
{
  "default": "log",
  "aliases": {
    "log": "YOUR_GOOGLE_DOC_ID"
  },
  "history_size": 20
}
```
`history_size` is optional and defaults to 20 (range 1–500) — set via `/config set history_size <n>`.

### `read_config.json` (read-only mode)
```json
{
  "default": "",
  "aliases": {}
}
```
Independent from `docs_config.json` — managed separately via `/add` inside `--read` mode.

### `tags_index.json` (auto-generated)
```json
{
  "meeting": [
    {
      "ts": "[06/18/26] (14:30)|",
      "doc_id": "YOUR_GOOGLE_DOC_ID",
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
    "doc_id": "YOUR_GOOGLE_DOC_ID",
    "ts": "[06/18/26] (14:31)|"
  }
]
```

### File origins

All of these live in the [data directory](#data-directory), not the repo.

| File | Origin | Purpose |
|---|---|---|
| `credentials.json` | Downloaded from Google Cloud | OAuth client config |
| `token.json` | Generated on first auth | Cached OAuth refresh token |
| `docs_config.json` | Created on first `--add` (or copied from `docs_config.example.json`) | Write-mode document alias registry |
| `read_config.json` | Created on first `--read`/`--add` in read-only mode | Read-only document alias registry |
| `tags_index.json` | Auto-populated on each submit | Local tag search index |
| `pending_queue.json` | Auto-created on network failure | Offline note buffer |

---

## Note Format

Write mode (what MyDocBot itself produces):
```
[MM/DD/YY] (HH:MM)| Note body here — multiple lines preserved.

#tags are included in the body as-is.
```

Read-only mode expects a different, pre-existing format in the target doc:
```
DD/MM/YYYY
[HH.MM]
Note body here — multiple lines preserved.
```

---

## Project Structure

```
.
├── main.py                  (199 lines) CLI entry (`mydocbot`), argparse, one-shot capture, REPL loop, --read/--tui dispatch
├── mydocbot_app.py          (1206 lines) Textual TUIs — BaseNotesApp (shared) + MyDocBotApp
│                            (read/write) + ReadOnlyApp, both extending BaseNotesApp
├── core/
│   ├── __init__.py          Re-exports with __all__
│   ├── commands.py          All CLI cmd_*(), dispatch(), resolve_editor(), export
│   ├── config.py            Alias CRUD for write + read-only configs, history_size, 0600 perms
│   ├── google_docs.py       OAuth, prepend_text→bool, retry, parse_entries(+readable), title cache
│   ├── notes.py             submit_note() — the single write path (validate, flush, prepend, index, queue)
│   ├── parser.py            Tags, search_cache, offline queue, date filters
│   ├── paths.py             Data directory ($MYDOCBOT_HOME / XDG / ~/.config/mydocbot), first-run migration
│   └── validation.py        validate_doc_id, validate_alias, validate_config, validate_note, validate_history_size
├── tests/
│   ├── conftest.py           Fixtures: autouse data-dir isolation, config/read-config/tags/pending paths, mock_service, doc builder
│   ├── test_main.py          main() REPL loop, --add flag, pending count display, one-shot capture
│   ├── test_paths.py         Data-dir resolution and one-time migration
│   ├── test_notes.py         submit_note(): sent/queued/rejected, offline-queue order
│   ├── test_google_docs.py   get_service() sign-in: refresh, revoked/corrupt token, offline
│   ├── test_config.py        Config CRUD + corrupt JSON fallback (write & read)
│   ├── test_parser.py        Tags, parse_entries, retry, search, corrupt JSON, malformed ts
│   ├── test_commands.py      CLI cmd_* functions, cmd_search, cmd_config, cmd_export
│   ├── test_dispatch.py      dispatch /remove auto-switch paths
│   ├── test_editor.py        resolve_editor() fallback chain
│   ├── test_validation.py    doc_id, alias, config, note, history_size validators
│   └── test_tui.py           Headless Textual run_test() suite for MyDocBotApp/ReadOnlyApp
├── docs_config.example.json  Example write-mode config with a placeholder doc ID
├── .github/workflows/ci.yml  GitHub Actions: lint.sh on push/PR to main/dev
├── pyproject.toml            Package metadata + `mydocbot` entry point; ruff, mypy, pytest-asyncio config
├── lint.sh                   CI gate: ruff → mypy → pytest (all must pass)
├── CHANGELOG.md               Notable changes, most-recent-first
└── requirements.txt          textual, rich, pytest, pytest-asyncio, google-api packages
```

---

## Testing

```bash
python -m pytest tests/ -v                        # All 305 tests
python -m pytest tests/test_parser.py -v          # Parser + queue + date-filter tests
python -m pytest tests/test_tui.py -v             # Headless Textual TUI tests
python -m pytest tests/ -k "corrupt"              # Corrupt-JSON resilience tests
python -m pytest tests/test_main.py -v            # CLI REPL loop tests
bash lint.sh                                      # ruff + mypy + pytest — all three must pass
```

| File | Coverage |
|---|---|
| `test_main.py` | REPL submit/queue/flush, `--add` flag validation, pending count in prompt, one-shot capture (args, stdin, `-d`, exit codes) |
| `test_paths.py` | Data-dir precedence, `0700` creation, one-time copy-only migration (never into an existing dir) |
| `test_config.py` | Load, save, resolve, corrupt JSON fallback + warning (write & read-only config) |
| `test_notes.py` | `submit_note()`: sent / queued / rejected, queued notes written first and in order, queue-behind, all-docs flush |
| `test_google_docs.py` | `get_service()`: valid/refreshed token, revoked or corrupt token re-runs sign-in, offline startup exits and keeps the token |
| `test_parser.py` | Tag CRUD, parse_entries, prepend_text retry, search_cache, date filters, corrupt JSON, malformed timestamps |
| `test_commands.py` | All CLI commands: switch, list, add, remove, rename, current, tag, search, export, config, help |
| `test_dispatch.py` | Dispatch `/remove` auto-switch to default/first/none |
| `test_editor.py` | `resolve_editor()` env var, fallback chain, missing binary |
| `test_validation.py` | `validate_doc_id`, `validate_alias`, `validate_config`, `validate_note`, `validate_history_size` |
| `test_tui.py` | `MyDocBotApp`/`ReadOnlyApp` mounted headlessly via Textual's `run_test()`; covers `/config` (incl. the fixed dead-code bug), `/add` alias validation, read-only mount/list/current |

All tests use monkeypatched Google API and temp files — no network, no OAuth. Current total: **305 passed**.
`test_tui.py` requires `pytest-asyncio` (configured with `asyncio_mode = "auto"` in `pyproject.toml`).

---

## Design Decisions & Known Limitations

- **Submit via `Ctrl+S` or button:** `Ctrl+Enter` was unreliable across terminals. The Submit button is the always-reliable fallback.
- **Google calls run in the background (TUI):** loading, submitting, `/switch`, `/list`, `/refresh`, `/more`, `/flush`, and `/tag reindex` run in a worker thread, so the window stays usable — you can browse and preview notes, scroll, and use `/help`, `/search`, `/tag list`, or `/queue list` meanwhile. The status bar shows what's running (`⟳ Saving note…`) and the header shows `◌ Working…`. Only one Google call runs at a time (the Google client isn't thread-safe); starting another, or editing the queue with `/queue drop`/`move`, while one runs is refused with "Still … try again when it's done." The note being saved stays in the input (read-only) until the write finishes. Quitting during a call waits for it to finish. The CLI still blocks while it waits.
- **Date grouping via separator items:** `DateSeparator` items carry a `_is_separator` flag; note index mapping is maintained in `_note_to_display`.
- **Local tag index:** Notes are indexed as you write them. Older notes, notes typed directly in Google Docs, and later edits aren't picked up until you run `/tag reindex`, which re-reads the whole doc (one full-document API call).
- **Entry boundaries:** A new note starts only at a full `[MM/DD/YY] (HH:MM)|` header at the start of a line, so a date written inside a note body (e.g. `due [07/01/26]`) doesn't split the note.
- **`#tag` regex:** `#(\w+)` matches word characters only — `#project-alpha` → tag `project`. Use underscores: `#project_alpha`.
- **Notes cache:** 500-entry cap, newest-first. Loaded from the API on startup (`history_size` most recent, default 20) and on each `/switch`; `/refresh` re-fetches, `/more` loads older entries.
- **Offline queue:** `pending_queue.json` is deleted when empty. The queue is flushed (all docs, oldest first) *before* each new note, because every write is a prepend at the top of the doc. Flushing stops per doc at the first failure, to keep order and to avoid one retry wait per queued note. Use `/flush` to retry manually.
- **Write failures are classified:** HTTP 400/403/404 are *permanent* (the automatic flush skips that doc until `/flush`, since retrying can't help until you fix something); 401 and an expired/revoked sign-in are *auth* (restart to sign in again; retried automatically); everything else, including unknown errors, is *transient*. The reason is stored with each queued note (`"error"` in `pending_queue.json`). A note moved with `/queue move` keeps its original timestamp, so it can land above newer notes in the target doc.
- **API retry:** Transient errors (429, 500/502/503/504, `ConnectionError`, `TimeoutError`) are retried up to 3 times with 1 s / 2 s / 4 s backoff. Non-transient errors (403, 404) are not retried.
- **`resolve_editor()` shared:** Both CLI and TUI call the same `resolve_editor()` from `core/commands.py`. Editor fallback order: `$EDITOR` → `vim` → `nano` → `vi`.
- **Independent read/write configs:** `docs_config.json` and `read_config.json` are separate registries so the same alias name can point to different docs (or exist in only one mode) without conflict.
- **Read-only mode has no write path:** `ReadOnlyApp` never calls `prepend_text()` — it only fetches and displays, using its own timestamp format parser (`parse_entries_readable()`).
- **OAuth token file:** `token.json` lives in the data directory (outside the repo) and is written with `0600` permissions.
- **Alias validation:** `validate_alias()` rejects whitespace and leading `/` in alias names, since aliases are matched via whitespace-split command parsing (`line.strip().split()`); an alias with a space would otherwise silently break `/switch`, `/remove`, etc.
- **Doc title cache:** `fetch_doc_title()` caches successful results in-process per `doc_id` to avoid redundant API round-trips across `/list`, `/switch`, and startup; `/refresh` explicitly invalidates the current doc's cached title.
- **Shared constants:** `NOTES_CACHE_LIMIT` (500), `validation.DEFAULT_HISTORY_SIZE` (20), and `validation.MIN_HISTORY_SIZE`/`MAX_HISTORY_SIZE` (1/500) are defined once and referenced everywhere the value is needed (help text, validation, cache trimming) instead of being duplicated as magic numbers.
- **`lint.sh` is a real gate:** `mypy` now runs against `mydocbot_app.py` in addition to `core/`, and its exit code is no longer swallowed with `|| true` — a type error anywhere in the app now fails CI.

---

## Editor Support (`/edit`)

1. Creates a temp `.md` file in `/tmp/`
2. Writes a `#` comment header as scratch guidance
3. Launches editor via `resolve_editor()`: `$EDITOR` → `vim` → `nano` → `vi`
4. Waits for editor to exit (TUI suspends cleanly via `self.suspend()`)
5. Reads file, strips all lines starting with `#`
6. Submits content as a single note (validated before API call)
7. Cleans up temp file

`/edit` is available in CLI mode and the read/write TUI; it is **not** available in the read-only TUI.

---

## Open Work

Known bugs, planned features, and improvement ideas are tracked in one place:
[`docs/backlog.md`](docs/backlog.md). Notable fixes and changes already made are in
[`CHANGELOG.md`](CHANGELOG.md).

---

## Quickstart

- [ ] Enable Google Docs API in Cloud Console
- [ ] `pipx install -e .` (or `pip install -e .` in a venv)
- [ ] Download `credentials.json` into `~/.config/mydocbot/` (or `$MYDOCBOT_HOME`)
- [ ] `mydocbot --add mynotes <doc_id>`
- [ ] `mydocbot` (first run triggers OAuth browser flow)
- [ ] `mydocbot "a quick note #tag"` to write one note and exit
- [ ] `mydocbot --tui` for the date-grouped read/write TUI
- [ ] `mydocbot --read` for the browse-only TUI (needs its own alias via `/add` once inside)
