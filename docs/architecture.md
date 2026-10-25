# MyDocBot — Architecture

How the code is put together, for anyone changing it. User-facing behavior is
in [`README.md`](../README.md). The reasoning behind each choice, with dates,
is in `docs/agent-notes/project-snapshot.md` ("Design Decisions") and
`docs/agent-notes/improvement-plan.md`.

## Data flow

```
User input (CLI / TUI / read-only TUI / Discord DM)
       │
       ▼
  Dispatch (main.py / mydocbot_app.py / discord_bot.py)
       │
       ├──▶ Command handlers ──▶ core/config.py      aliases, read + write configs
       │                       ▶ core/parser.py      tags, search, queue, date filters
       │                       ▶ core/google_docs.py API, retry, field masks, entry parsers
       │                       ▶ core/validation.py  input guards
       │
       └──▶ Note submission: core/notes.py submit_note(service, doc_id, text)
               ├── 1. validate_note(text)            reject empty / too long
               ├── 2. flush_pending_notes(service)   queued notes first, oldest first,
               │                                     stopping per doc at the first failure
               ├── 3. still queued for this doc?     queue behind them, don't try
               ├── 4. try_prepend(...)               None, or a WriteFailure
               └── 5. index_note(...) on success, queue_note(..., failure) otherwise
```

Every write is an `insertText` at index 1 (a prepend), so the doc reads
newest first. That's why queued notes must be written *before* a new one.

## Core modules (`core/`)

| Module | Responsibility | Key functions |
|---|---|---|
| `notes.py` | The one write path (CLI, `/edit`, TUI, one-shot, Discord) | `submit_note()` → `SubmitResult` |
| `google_docs.py` | Sign-in, API calls, retry, field masks, parsers | `get_service()`, `fetch_doc()`, `fetch_doc_title()`, `try_prepend()`, `prepend_text()`, `classify_write_error()`, `parse_entries()`, `parse_entries_readable()` |
| `parser.py` | Tags, offline queue, search, date filters, reindex | `extract_tags()`, `index_note()`, `reindex_doc()`, `queue_note()`, `flush_pending_notes()`, `search_entries()`, `filter_tag_entries_by_date()` |
| `timestamps.py` | The `[MM/DD/YY] (HH:MM)\|` format, in one place | `format_timestamp()`, `parse_timestamp()`, `date_key()`, `parse_date_flag()`, `HEADER_PATTERN` |
| `config.py` | Write and read-only alias configs | `load_config()`, `save_config()`, `resolve_alias()`, `get_history_size()`, `load_read_config()`, `save_read_config()` |
| `storage.py` | Atomic `0600` writes; corrupt-file quarantine; cross-process locking | `write_json()`, `write_text()`, `quarantine()`, `locked()` |
| `paths.py` | Where the data lives; first-run migration | `resolve_data_dir()`, `data_path()`, `prepare_data_dir()` |
| `validation.py` | Input guards | `validate_doc_id()`, `validate_alias()`, `validate_config()`, `validate_note()`, `validate_history_size()` |
| `discord_handler.py` | What the Discord bot does with a DM (no discord import) | `load_token()`, `load_discord_config()`, `load_allowed_users()`, `is_allowed()`, `split_alias()`, `write_note()` |
| `doc_watch.py` | Watch read-only docs: config, hash snapshots, diff, alert text (no discord import) | `parse_watch_config()`, `poll()` → `PollResult`, `snapshot()`, `diff()`, `format_changes()` |
| `commands.py` | CLI command handlers, plus text shared with the TUI | `dispatch()`, `cmd_*()`, `queued_text()`, `queue_lines()`, `reindex_message()`, `resolve_editor()`, `export_to_markdown()` |

`main.py` parses arguments, prepares the data dir, and runs one-shot
capture, the REPL, or a TUI. `mydocbot_app.py` holds both Textual apps.
`discord_bot.py` (`mydocbot-discord`, optional `discord` extra) is a thin
discord.py client: `NoteBot.on_message()` checks the allowlist, runs
`discord_handler.write_note()` in a worker thread (one at a time, since
httplib2 isn't thread-safe) and replies. discord.py is imported only in
`main()`, so the tests need neither it nor a network.
With a `watch` block, `setup_hook` starts `NoteBot.run_watcher()` once per
process (`on_ready` repeats on reconnect). Every `interval_minutes` it runs
`doc_watch.poll()` in a thread under the same lock as note writes, then DMs
each allowed user. `poll()` re-resolves the aliases from `read_config.json`,
fetches each doc (`fetch_doc`, title + text) and parses it with
`parse_entries_readable()`. A new doc ID becomes a silent baseline; a changed
text hash is diffed by entry. A doc that suddenly parses to zero entries
keeps its snapshot, like `/tag reindex`. There is no cheaper change check: the
Docs API fills in `revisionId` only for editors, and Drive's `modifiedTime`
would need another OAuth scope.

## The TUIs

```
BaseNotesApp (App)          shared: cache, date-grouped list, preview, run_api(),
│                           /switch /list /add /current /search /refresh /more
├── MyDocBotApp             read/write: submit, /edit, /flush, /queue, /tag, /export, /config
└── ReadOnlyApp             browse-only, its own config and timestamp format

Layout (both): header · notes ListView (24 cols, date + time per note via the
  `_note_label()` hook) | WrappingPreview (1fr; VerticalScroll + Static, re-wraps
  on resize, no sideways scroll) · input bar · status bar
```

- **Notes list:** `DateSeparator` items carry `_is_separator = True`;
  `_note_to_display` maps note positions to list rows across the
  separators.
- **Subclass hooks:**
  - `_load_config`, `_save_config`, `_resolve_alias`;
  - `_parse(doc, count)` (which parser to use);
  - `_date_key(ts)` (the "MM/DD/YY" key for grouping);
  - `_resolve_initial_alias`;
  - a few label constants.

  `BINDINGS`, `compose()`, the command table and `/help` stay per app on
  purpose.
- **Background Google calls:** every API call goes through
  `run_api(label, work, on_done, on_error)`.
  - `work()` runs in a Textual thread worker and touches no widgets or app
    state; the callbacks run back on the UI thread via `call_from_thread`.
  - **One call at a time:** the Google client (`httplib2`) isn't
    thread-safe, so `_api_busy` refuses a second call. Commands that would
    edit a file a worker may be writing (`/queue drop|move`) check it too.
- **Session cache:** `_doc_entries[doc_id]` keeps every entry from the
  last whole-doc fetch, and `/more` pages through it; the app's own writes
  clear it.
- **Status bar:** shows plain text (`rich.text.Text`), never markup,
  because messages contain user input.

## Data file formats

All files live in the data directory (see README). They are written by
`storage.write_json()`: atomically, `0600`, indent 2.

`tags_index.json` holds, per tag, one entry per note:

```json
{"meeting": [{"ts": "[06/18/26] (14:30)|", "doc_id": "…", "preview": "Met with team to discuss sprint..."}]}
```

`pending_queue.json` holds queued notes, oldest first. `error` is the last
failure (`kind` is `transient`, `auth` or `permanent`):

```json
[{"text": "offline note", "doc_id": "…", "ts": "[06/18/26] (14:31)|",
  "error": {"kind": "transient", "message": "offline or Google unavailable"}}]
```

It is deleted when empty. `read_config.json` has the same shape as
`docs_config.json` (`default`, `aliases`, optional `history_size`).

`discord_config.json` lists the Discord user IDs the bot obeys (strings or
numbers; it must not be empty). The bot token is in `discord_token` (plain
text, `0600`) or `$MYDOCBOT_DISCORD_TOKEN`:

```json
{"allowed_user_ids": ["111111111111111111"],
 "watch": {"aliases": ["standup"], "interval_minutes": 5}}
```

`watch_state.json` is written only by the watcher. It maps a doc ID to a
16-hex-character sha256 of the whitespace-collapsed text and of each entry's
body, keyed by timestamp (`#2`, `#3` for repeats), plus a failure count. It
never holds note text. Corrupt → quarantined, and the docs are re-baselined.

```json
{"doc_s": {"text_hash": "…", "entries": {"[10/24/2026] [14.30]|": "…"}, "failures": 0}}
```

**Locking (A6):** every load-modify-save of `pending_queue.json` and
`tags_index.json` runs under `storage.locked()`: an `fcntl.flock` on
`<file>.lock` (never deleted) plus a per-file reentrant thread lock. A flush
also takes `pending_queue.json.flush.lock` without waiting; if another flush
holds it, it returns at once. The queue lock isn't held during Google calls;
`_save_flush_result()` reapplies the flush to the queue as it is then. The
configs are not locked (backlog A7).

## Design notes

- **Submit is `Ctrl+S` or the button:** `Ctrl+Enter` was unreliable across
  terminals.
- **Aliases** reject whitespace and a leading `/`, because commands are
  split on whitespace (`line.strip().split()`).
- **The read and write configs are independent,** so the same alias name
  can point at different docs in each mode.
- **The read-only app never writes:** it has no path to `try_prepend()`.
- **Constants are defined once:** `NOTES_CACHE_LIMIT` (in
  `mydocbot_app.py`) and `validation.DEFAULT_HISTORY_SIZE` /
  `MIN_HISTORY_SIZE` / `MAX_HISTORY_SIZE` are referenced everywhere
  instead of literals.
- **Field masks:** the Docs API can't fetch part of a document, so loads
  ask only for `title` and the text runs (`google_docs.CONTENT_FIELDS`),
  and title lookups only for `title`.
- **Theme:** Catppuccin-inspired colours, in the `CSS` string at the top of
  `mydocbot_app.py`: background `#1e1e2e`, accents `#89b4fa` / `#a6e3a1`,
  errors `#f38ba8`, separators `#585b70`.
- **`/edit`:** writes a temp `.md` file with a `#` hint line and opens the
  editor (the TUI uses `self.suspend()`). It drops `#` lines, submits the
  rest through `submit_note()`, and deletes the file.

## Tests

`bash lint.sh` (ruff → mypy → pytest) is the gate; CI runs it on Python 3.11
and 3.14. `bash coverage.sh` is a report only. All tests mock the Google API,
and `tests/conftest.py` points every data path into a temp folder, so no test
touches real files. TUI tests use Textual's headless `run_test()` through
`mounted()` / `settle()` in `tests/test_tui.py`; see the `testing` skill.

| File | Covers |
|---|---|
| `test_main.py` | REPL submit / queue / flush, `--add`, prompt, one-shot capture and exit codes |
| `test_notes.py` | `submit_note()`: sent / queued / rejected, flush-first order, queue-behind |
| `test_google_docs.py` | Sign-in recovery, write-failure classification, `try_prepend`, field masks |
| `test_parser.py` | Tags, `parse_entries`, retry, search, date filters, reindex, queue errors and editing |
| `test_timestamps.py` | Timestamp format / parse, date keys and flags |
| `test_config.py` | Config load / save / resolve, corrupt fallback |
| `test_storage.py` | Atomic writes: readers never see a truncated file; `0600` |
| `test_locking.py` | `storage.locked()`; concurrent processes/threads lose no queue or tag update; flush exclusivity and reconcile |
| `test_discord.py` | Discord bot: alias prefix, allowlist, token/allowlist loading, `write_note`, `NoteBot` with fake messages, `main()` exit codes |
| `test_doc_watch.py` | Doc watcher: config, diff, message limits, `poll()` (baseline, changes, errors and recovery, retargets, state file), `run_watcher` loop |
| `test_corrupt_backup.py` | Corrupt files moved to timestamped backups; unreadable files left alone |
| `test_paths.py` | Data-dir resolution and one-time migration |
| `test_commands.py` | CLI commands, including `/queue`, `/search`, `/tag reindex`, `/export` |
| `test_dispatch.py` | `/remove` auto-switch paths |
| `test_editor.py` | `resolve_editor()` fallback chain |
| `test_validation.py` | Input validators |
| `test_orient.py` | The `/task` orientation brief (`.claude/skills/task/orient.py`) on fixture docs |
| `test_tui.py` | Both TUIs headless: commands, background calls (with `BlockingService`), status escaping, date labels, list date/time labels and preview wrapping (both apps), `/more` cache |
