# MyDocBot — Backlog

**This is the list of open work for the project.** README and CHANGELOG point
here instead of keeping their own lists. Finished work is recorded in
`CHANGELOG.md`, not here.

## How to use this file

- **Adding:** give the row the next unused ID in its category (`B` bugs, `P`
  privacy/hygiene, `F` features, `A` architecture, `D` docs/workflow). Never
  reuse an ID, even after its row is deleted, so references in old notes and
  commits stay unambiguous.
- **Status:** `open` → `in progress` → row deleted when done. Use `blocked`
  with a one-line reason in Notes when waiting on something.
- **Done:** delete the row; the `CHANGELOG.md` entry cites the ID.
- **Dropped:** delete the row and say why in the commit message.
- **Priority:** `high` / `med` / `low`. **Size:** XS < S < M < L. Both are
  estimates; adjust them freely.
- `file:line` references were accurate when the row was written and drift as
  code changes. Re-check before relying on them.

## Suggested order

1. **A7:** config saves that don't overwrite another process's changes.
2. **F9:** multi-doc tag aggregation.

## Bugs

| ID | Task | Status | Pri | Size | Location | Notes |
|---|---|---|---|---|---|---|
| B13 | **A `BrokenPipeError` on send fails all 3 retries** | open | low | S | core/google_docs.py `_api_call_with_retry` | Seen once in the bot's journal (2026-11-15 14:20, `Watch: can't read log — BrokenPipeError`). It is a `ConnectionError`, so it is retried, but httplib2 keeps the connection in its pool when `conn.request()` (the send) raises a `socket.error` other than ENETUNREACH/EADDRNOTAVAIL: only timeouts are popped from `Http.connections`. So every retry reuses the dead socket. Fix idea: before retrying a `ConnectionError`/`SSLError`, close the pooled connections (`service._http.http.connections`, via the google-auth `AuthorizedHttp` wrapper), with a test. Watch the journal first to see how often it happens after B12. |

## Privacy & repo hygiene

| ID | Task | Status | Pri | Size | Location | Notes |
|---|---|---|---|---|---|---|
| P5 | **Revisit the minimum Python before 2027-10** | open | low | XS | pyproject.toml, .github/workflows/ci.yml, README | google-api-core lists Python 3.11's end of life as 2027-10-24 and already warns about it on 3.11. Before then, raise the minimum to 3.12 (same 6 spots as P4; check `ruff check . --target-version py312`). |

## Features

| ID | Task | Status | Pri | Size | Location | Notes |
|---|---|---|---|---|---|---|
| F7 | **Configurable note formats per alias** | open | low | L | core/google_docs.py, core/config.py | Replace the two hard-coded parsers with a format setting per alias, so the read-only TUI can browse other doc layouts without new code. |
| F8 | **Tag autocomplete in TUI** | open | low | M | mydocbot_app.py | Suggest known tags from `tags_index.json` when the user types `#` in the read/write TUI input (`on_text_area_changed`). |
| F9 | **Multi-doc tag aggregation** | open | low | S | core/commands.py `cmd_tag_*`, mydocbot_app.py | An `--all` flag for `/tag` commands to aggregate across all configured docs, not just the active one. `/tag reindex` (F4) is per-doc too; `--all` there would loop over the aliases. |
| F12 | **`/undo` over Discord** | open | low | S | core/discord_handler.py, discord_bot.py | Let the allowlisted user undo their last bot-written note with a DM (e.g. `/undo`), using `undo.undo_last()`. Left out of F3. |

## Architecture & refactors

| ID | Task | Status | Pri | Size | Location | Notes |
|---|---|---|---|---|---|---|
| A7 | **Config saves overwrite changes made by another process** | open | low | S | core/commands.py, mydocbot_app.py `save_config` callers, main.py | The CLI and TUI load `docs_config.json` / `read_config.json` once at startup and later save that whole session copy, so an alias added in one process is lost when another saves. A6's lock doesn't help: there is no short load-modify-save to wrap. Fix by reloading under `storage.locked()` and applying just the one change (add/remove/rename alias, set default, history size). |

## Docs & agent workflow

| ID | Task | Status | Pri | Size | Location | Notes |
|---|---|---|---|---|---|---|
