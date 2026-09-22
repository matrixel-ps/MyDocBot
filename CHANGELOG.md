# Changelog

All notable changes to MyDocBot are documented in this file.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed
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

### Not Yet Done (see "Recommended Next Steps" in README.md)
- `/search` behaves differently between CLI (always fetches fresh from the
  API) and TUI (searches the in-memory session cache only) — not yet
  unified or clearly documented in `/help`.
- No file locking around the JSON config/index files if CLI and TUI are run
  concurrently against the same project directory.
- Tag/keyword command arguments typed by the user are not escaped before
  being shown in TUI status messages (low risk for a single-user personal
  tool, but noted for completeness).
