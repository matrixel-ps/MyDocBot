# Changelog

All notable changes to MyDocBot are documented in this file.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Open work (bugs, planned features) is tracked in [`docs/backlog.md`](docs/backlog.md).

## [Unreleased]

### Changed
- **Offline queue:** a successful write in the TUI now retries queued notes
  for *all* documents, like the CLI and `/flush` already did. Retrying stops
  at the first failure for each document, so being offline costs one retry
  wait per document instead of one per queued note. In the TUI, notes written
  from the queue show up in the notes list right away.
- **Internal:** every way of writing a note (CLI, CLI `/edit`, TUI, TUI
  `/edit`) now goes through one function, `core.notes.submit_note()`.
- **Refactor:** Extracted a shared `BaseNotesApp` base class in
  `mydocbot_app.py` for `MyDocBotApp` and `ReadOnlyApp`, which previously
  duplicated ~230 lines of near-identical logic (notes cache management,
  date-grouped list rendering, preview pane rendering, and the `/switch`,
  `/list`, `/add`, `/current`, `/search`, `/refresh`, `/more` commands).
  `BaseNotesApp` uses a small hook interface (`_load_config`, `_save_config`,
  `_resolve_alias`, `_fetch_recent`, `_date_key`, `_resolve_initial_alias`)
  plus a handful of text/label class attributes (`HEADER_TITLE`,
  `EMPTY_NOTES_MSG`, `LIST_HEADER`, `NO_DOCS_MSG`, `NO_DOCS_LIST_MSG`,
  `ADD_SUCCESS_SUFFIX`) so each subclass only implements its genuine
  differences. `BINDINGS`, `compose()`, `handle_command()`'s command table,
  `/help` text, and write-only commands (`/edit`, `/remove`, `/rename`,
  `/export`, `/tag`, `/config`) intentionally stay per-subclass since they
  are not actually identical. File size: 1265 → 1036 lines. No public API
  changes; `tests/test_tui.py` passes unmodified.

### Fixed
- **Expired or revoked Google sign-in:** if the saved sign-in can't be
  refreshed (access revoked, or a token Google expired), MyDocBot now deletes
  `token.json` and opens the browser sign-in again instead of crashing. A
  corrupt `token.json` is handled the same way. Starting while offline now
  exits with a "couldn't reach Google" message and keeps your sign-in,
  instead of showing a traceback.
- **Offline notes out of order:** notes written while offline used to land
  *above* the newer note that triggered the retry. Queued notes are now
  written first, oldest first, so the doc stays in the order you wrote
  things. If a doc's queued notes still can't be written, new notes for it
  wait in the queue behind them instead of jumping ahead.
- **Tags on offline notes:** `#tags` in notes written while offline are now
  indexed once the note is written, so they show up in `/tag` and
  `/export <tag>`.
- **CLI `/edit` lost notes when offline:** a failed `/edit` write is now
  queued like any other note, instead of being silently dropped.
- **`/edit` skipped validation:** empty or oversized editor notes are now
  rejected like typed ones, in both the CLI and the TUI.
- **Read-Only TUI date grouping:** `ReadOnlyApp`'s "Today"/"Yesterday" date
  separators never actually matched, because the old
  `_readable_date_header()` built its comparison key in `YY/MM/DD` order
  while `_format_date_header()` compares against
  `datetime.now().strftime("%m/%d/%y")` (`MM/DD/YY` order) — so today's notes
  always fell through to a literal date instead of "Today". Discovered and
  fixed while extracting `BaseNotesApp._date_key()`; verified with a manual
  headless-TUI smoke test (today's note now correctly labeled "Today").
- **Critical:** `/config set history_size <n>` in the read/write TUI
  (`MyDocBotApp.cmd_config`) was unreachable dead code — an unconditional
  `return` after the `/config show` branch meant the `set` branch could
  never execute, and would have raised `UnboundLocalError` on `preview` if
  the guard were ever removed. The CLI equivalent (`core/commands.py`) was
  unaffected. Fixed by restructuring the `if/elif/else` to match the CLI
  version; added regression tests in `tests/test_tui.py`.
- **Rendering:** Timestamps and note text in both TUIs (`MyDocBotApp` and
  `ReadOnlyApp`) were displayed with literal, unrendered Rich markup codes
  (e.g. `[#a6e3a1]...[/]`) instead of being colorized, because `PreviewPane`
  (a `RichLog`) was instantiated without `markup=True` (Textual's default is
  `markup=False`). Fixed by enabling `markup=True` and escaping all
  dynamic/API-sourced content (timestamps, note bodies, doc titles, doc IDs,
  aliases, search keywords, tag names, error messages) via
  `rich.markup.escape()` before interpolating it into markup strings — this
  also prevents real note content containing `[...]` from being
  misinterpreted as (and silently swallowed by) Rich markup tags.

### Added
- `core/validation.validate_alias()` — rejects empty or whitespace-containing
  aliases (which would otherwise break the whitespace-split command parser)
  and aliases starting with `/`. Applied to `/add` and `/rename` in the CLI,
  the read/write TUI, and the read-only TUI, plus `main.py --add`.
- `core.google_docs` now caches successful `fetch_doc_title()` lookups
  in-process (keyed by `doc_id`) to avoid re-fetching the same document's
  title on every `/list`, `/switch`, and app startup. `/refresh` explicitly
  invalidates the cache for the current doc so renamed docs are picked up.
- `get_service()` now raises a friendly `SystemExit` message pointing to the
  README setup steps if `credentials.json` is missing, instead of an
  unhandled `FileNotFoundError` traceback.
- `token.json`, `docs_config.json`, and `read_config.json` are now written
  with owner-only (`0600`) file permissions (best-effort; no-op on platforms
  without POSIX permission bits).
- `tests/test_tui.py` — new Textual `run_test()`-based regression suite
  covering `MyDocBotApp`/`ReadOnlyApp` command handlers (`/config`, `/add`)
  with a mocked Google Docs service. This closes a major test coverage gap:
  previously none of `mydocbot_app.py` (~45% of the codebase) was tested.
- `.github/workflows/ci.yml` — GitHub Actions workflow running `lint.sh`
  (ruff + mypy + pytest) on push/PR to `main`/`dev`.
- This `CHANGELOG.md`.

### Changed
- `lint.sh` now includes `mydocbot_app.py` in the `mypy` invocation (it was
  previously excluded entirely) and no longer swallows mypy failures with
  `|| true` — mypy is now a real CI gate, not advisory-only.
- Consolidated previously-duplicated magic numbers into named constants:
  `NOTES_CACHE_LIMIT` (was `MAX_CACHE = 500` duplicated in both TUI classes),
  `validation.DEFAULT_HISTORY_SIZE` (was a bare `20` in `core/config.py`),
  and the `"1-500"` history-size range string in `/config` help text (now
  interpolates `validation.MIN_HISTORY_SIZE`/`MAX_HISTORY_SIZE` in all four
  places it previously appeared, so it can't drift out of sync).
- Added `pytest-asyncio` as a test dependency (required for the new
  Textual-TUI async tests) with `asyncio_mode = "auto"` configured in
  `pyproject.toml`.
- Added `rich>=13.0.0` as an explicit dependency in `requirements.txt` (it
  was previously only pulled in transitively via `textual`, but is now
  imported directly for markup escaping).

### Known Limitations (carried over, still accurate)
See README.md "Design Decisions & Known Limitations" for the full list,
including: single-threaded TUI (network calls block the UI), local-only tag
index (no historical backfill), `#tag` regex limited to word characters,
and independent read/write alias configs.

