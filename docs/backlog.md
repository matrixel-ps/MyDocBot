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

1. **A1:** timestamp parsing helper (XS).
2. **A4:** merge duplicated text-extraction code (XS).
3. **D3:** add a coverage report (XS).

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

## Architecture & refactors

| ID | Task | Status | Pri | Size | Location | Notes |
|---|---|---|---|---|---|---|
| A1 | **Timestamp parsing helper** | open | low | XS | core/parser.py `filter_tag_entries_by_date()`, mydocbot_app.py `MyDocBotApp._date_key()`, core/google_docs.py `parse_entries()` | The *formatting* half is done: `core.notes.format_timestamp()` / `TIMESTAMP_FORMAT` (2026-10-23, with A2). Parsing still slices `ts[1:9]` and re-states the format in regexes. Add `parse_timestamp()` next to `format_timestamp()`. |
| A4 | **Merge duplicated text-extraction code** | open | low | XS | core/google_docs.py | `parse_entries()` and `parse_entries_readable()` share their first 12 lines word for word; extract `_doc_text(doc)`. |
| A5 | **True pagination for `/more`** | open | low | M | mydocbot_app.py `cmd_more()`, core/google_docs.py | `/more` re-downloads and re-parses the whole doc to show a few older notes: `O(doc size)` per call as the doc grows. |
| A6 | **File locking for concurrent CLI + TUI use** | open | low | M | core/config.py, core/parser.py | No locking around `docs_config.json`, `read_config.json`, `tags_index.json`, `pending_queue.json` when the CLI and a TUI run against the same directory at once. Atomic write-then-rename is a cheaper first step. |

## Docs & agent workflow

| ID | Task | Status | Pri | Size | Location | Notes |
|---|---|---|---|---|---|---|
| D1 | **Shorten the README** | open | low | S | README.md | Still long and history-heavy in places (e.g. "Design Decisions & Known Limitations"). Keep the user-facing parts; leave history to CHANGELOG and the agent notes. |
| D3 | **Add a coverage report** | open | low | XS | lint.sh / pyproject.toml, dev requirements | `pytest --cov` to show which parts of `mydocbot_app.py` are still untested. |
