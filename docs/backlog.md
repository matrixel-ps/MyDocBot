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

1. **F6:** permanent vs. transient write failures, and a `/queue` command.
2. **A3:** keep the TUI responsive during network calls (reindex and offline
   submits can block for seconds).
3. **B8:** make `/search` mean the same thing in the CLI and TUI.

## Bugs

| ID | Task | Status | Pri | Size | Location | Notes |
|---|---|---|---|---|---|---|
| B6 | **No regression test for read-only "Today" label** | open | low | XS | tests/test_tui.py | Flagged in design decision #27: add a targeted test for `_date_key()` / `_format_date_header()`. |
| B7 | **User input not escaped in TUI status messages** | open | low | XS | mydocbot_app.py `update_status()` callers, e.g. :370, :763, :822 | Aliases, tags, and validation messages are interpolated into Rich markup unescaped (`show_error()` already escapes). Input containing `[...]` can be swallowed or mis-styled. Carried over from CHANGELOG "Not Yet Done". |
| B8 | **`/search` means different things in CLI and TUI** | open | med | S | core/commands.py `cmd_search()`, mydocbot_app.py `BaseNotesApp.cmd_search()` | The CLI fetches fresh from the API; both TUIs search only the session cache. Unify, or at least say so in `/help`. |

## Privacy & repo hygiene

| ID | Task | Status | Pri | Size | Location | Notes |
|---|---|---|---|---|---|---|
| P2 | **Split runtime vs. dev dependencies, pin lint tools** | open | med | S | requirements.txt, .github/workflows/ci.yml | pytest sits next to runtime packages, and CI installs unpinned ruff/mypy (local pins: `ruff==0.15.18`, `mypy==2.1.0`). Add `requirements-dev.txt` or pyproject optional-deps. |
| P3 | **CI Python version doesn't match local** | open | low | XS | .github/workflows/ci.yml | CI runs 3.11, local is 3.14, and the stated minimum is 3.10. Use a 3.10 + 3.14 matrix. |

## Features

| ID | Task | Status | Pri | Size | Location | Notes |
|---|---|---|---|---|---|---|
| F3 | **`/undo` last note** | open | low | M | core/google_docs.py, commands, TUI | Remove the range MyDocBot just wrote at the top of the doc, but only if the top entry still matches what was written. |
| F5 | **Hyphenated tags** | open | low | XS | core/parser.py `extract_tags()` | Allow `#project-alpha` with a regex like `#([\w-]+)` (strip a trailing `-`). Today it silently becomes `#project`. Update design decision #9 and the README. |
| F6 | **Permanent vs. transient write failures; `/queue` command** | open | med | M | core/google_docs.py `prepend_text()`, core/parser.py, commands, TUI | A bad `doc_id` or revoked permission (403/404) is queued like an offline failure and retried forever with no explanation. Don't retry permanent errors, store the last error with each queued entry, and add `/queue` to list or drop entries. Since 2026-10-23 a doc whose queued note keeps failing also keeps its *new* notes queued behind it (by design, to keep order), so this matters more. A sign-in revoked *mid-session* also lands here: the token refresh fails inside the write, `prepend_text()` catches the `RefreshError`, and the note is queued with no hint to restart (startup is handled since B4, 2026-10-24). |
| F7 | **Configurable note formats per alias** | open | low | L | core/google_docs.py, core/config.py | Replace the two hard-coded parsers with a format setting per alias, so the read-only TUI can browse other doc layouts without new code. |
| F8 | **Tag autocomplete in TUI** | open | low | M | mydocbot_app.py | Suggest known tags from `tags_index.json` when the user types `#` in the read/write TUI input (`on_text_area_changed`). |
| F9 | **Multi-doc tag aggregation** | open | low | S | core/commands.py `cmd_tag_*`, mydocbot_app.py | An `--all` flag for `/tag` commands to aggregate across all configured docs, not just the active one. `/tag reindex` (F4) is per-doc too; `--all` there would loop over the aliases. |

## Architecture & refactors

| ID | Task | Status | Pri | Size | Location | Notes |
|---|---|---|---|---|---|---|
| A1 | **Timestamp parsing helper** | open | low | XS | core/parser.py `filter_tag_entries_by_date()`, mydocbot_app.py `MyDocBotApp._date_key()`, core/google_docs.py `parse_entries()` | The *formatting* half is done: `core.notes.format_timestamp()` / `TIMESTAMP_FORMAT` (2026-10-23, with A2). Parsing still slices `ts[1:9]` and re-states the format in regexes. Add `parse_timestamp()` next to `format_timestamp()`. |
| A3 | **Keep the TUI responsive during network calls** | open | med | M | mydocbot_app.py | Run API calls in Textual workers with a loading indicator. With retry backoff a call can block ~7 s, not the 200–500 ms assumed in design decision #3. Since 2026-10-23 a submit flushes the queue first, so offline it blocks ~7 s per doc that has queued notes (it stops at the first failure per doc). |
| A4 | **Merge duplicated text-extraction code** | open | low | XS | core/google_docs.py | `parse_entries()` and `parse_entries_readable()` share their first 12 lines word for word; extract `_doc_text(doc)`. |
| A5 | **True pagination for `/more`** | open | low | M | mydocbot_app.py `cmd_more()`, core/google_docs.py | `/more` re-downloads and re-parses the whole doc to show a few older notes: `O(doc size)` per call as the doc grows. |
| A6 | **File locking for concurrent CLI + TUI use** | open | low | M | core/config.py, core/parser.py | No locking around `docs_config.json`, `read_config.json`, `tags_index.json`, `pending_queue.json` when the CLI and a TUI run against the same directory at once. Atomic write-then-rename is a cheaper first step. |

## Docs & agent workflow

| ID | Task | Status | Pri | Size | Location | Notes |
|---|---|---|---|---|---|---|
| D1 | **Shorten the README** | open | low | S | README.md | Still long and history-heavy in places (e.g. "Design Decisions & Known Limitations"). Keep the user-facing parts; leave history to CHANGELOG and the agent notes. |
| D2 | **Stop hard-coding numbers that drift** | open | med | S | AGENTS.md, README.md, project-snapshot.md, `/doc-audit` skill | The test count and "N commits ahead" figures appear in ~8 places; AGENTS.md is already wrong ("5 commits ahead", "uncommitted changes" when the tree is clean). Drop them or have `/doc-audit` check them. |
| D3 | **Add a coverage report** | open | low | XS | lint.sh / pyproject.toml, dev requirements | `pytest --cov` to show which parts of `mydocbot_app.py` are still untested. |
