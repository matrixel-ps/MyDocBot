# MyDocBot — Backlog

**This is the only list of open work for the project.** README, CHANGELOG, and
the agent notes point here instead of keeping their own lists. Finished work is
recorded in `CHANGELOG.md` (user-facing) and `docs/agent-notes/improvement-plan.md`
(dated history), not here.

## How to use this file

- **Adding:** give the row the next unused ID in its category (`B` bugs, `P`
  privacy/hygiene, `F` features, `A` architecture, `D` docs/workflow). Never
  reuse an ID, even after its row is deleted, so references in old task
  sheets and history entries stay unambiguous.
- **Status:** `open` → `in progress` (with a link to its `docs/tasks/<slug>.md`
  sheet, created by `/task <ID>`) → row deleted when done. Use `blocked` with a
  one-line reason in Notes when waiting on something.
- **Done:** delete the row. `/log-change` records the work, citing the ID, in
  `improvement-plan.md` and `CHANGELOG.md`.
- **Dropped:** delete the row and note the ID and reason in the next
  `improvement-plan.md` entry.
- **Priority:** `high` / `med` / `low`. **Size:** XS < S < M < L. Both are
  estimates; adjust them freely.
- `file:line` references were accurate when the row was written and drift as
  code changes. Re-check before relying on them.

## Suggested order

1. **A6 + F10:** file locking, then the Discord bot (in progress together).
2. **F3:** `/undo` last note.
3. **F9:** multi-doc tag aggregation.

## Bugs

| ID | Task | Status | Pri | Size | Location | Notes |
|---|---|---|---|---|---|---|

## Privacy & repo hygiene

| ID | Task | Status | Pri | Size | Location | Notes |
|---|---|---|---|---|---|---|
| P5 | **Revisit the minimum Python before 2027-10** | open | low | XS | pyproject.toml, .github/workflows/ci.yml, README | google-api-core lists Python 3.11's end of life as 2027-10-24 and already warns about it on 3.11. Before then, raise the minimum to 3.12 (same 6 spots as P4; check `ruff check . --target-version py312`). |

## Features

| ID | Task | Status | Pri | Size | Location | Notes |
|---|---|---|---|---|---|---|
| F3 | **`/undo` last note** | open | low | M | core/google_docs.py, commands, TUI | Remove the range MyDocBot just wrote at the top of the doc, but only if the top entry still matches what was written. |
| F7 | **Configurable note formats per alias** | open | low | L | core/google_docs.py, core/config.py | Replace the two hard-coded parsers with a format setting per alias, so the read-only TUI can browse other doc layouts without new code. |
| F8 | **Tag autocomplete in TUI** | open | low | M | mydocbot_app.py | Suggest known tags from `tags_index.json` when the user types `#` in the read/write TUI input (`on_text_area_changed`). |
| F9 | **Multi-doc tag aggregation** | open | low | S | core/commands.py `cmd_tag_*`, mydocbot_app.py | An `--all` flag for `/tag` commands to aggregate across all configured docs, not just the active one. `/tag reindex` (F4) is per-doc too; `--all` there would loop over the aliases. |
| F10 | **Discord bot: send a note by DM** | in progress ([sheet](tasks/discord-bot.md)) | med | L | new core/discord_handler.py + adapter, pyproject.toml | DM a private bot and the message is written with `submit_note()`; `-d <alias>` picks the doc; only allowlisted Discord user IDs are acted on; short text reply. `discord.py` as an optional extra with a `mydocbot-discord` command, run always-on under `systemd --user`. Needs A6 first. |

## Architecture & refactors

| ID | Task | Status | Pri | Size | Location | Notes |
|---|---|---|---|---|---|---|
| A7 | **Config saves overwrite changes made by another process** | open | low | S | core/commands.py, mydocbot_app.py `save_config` callers, main.py | The CLI and TUI load `docs_config.json` / `read_config.json` once at startup and later save that whole session copy, so an alias added in one process is lost when another saves. A6's lock doesn't help: there is no short load-modify-save to wrap. Fix by reloading under `storage.locked()` and applying just the one change (add/remove/rename alias, set default, history size). |
| A6 | **File locking for concurrent CLI + TUI use** | in progress ([sheet](tasks/discord-bot.md)) | low | M | core/storage.py, core/config.py, core/parser.py | Atomic writes are done (2026-10-24): a reader never sees an empty or partial file. What's left: two processes doing read-modify-write on the same file at the same instant (e.g. both `queue_note()`) can still lose one update. Fix with an advisory lock (`fcntl.flock` on a lock file in the data dir) around load-modify-save; POSIX-only. |

## Docs & agent workflow

| ID | Task | Status | Pri | Size | Location | Notes |
|---|---|---|---|---|---|---|
