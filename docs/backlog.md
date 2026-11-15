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

1. **A7:** config saves that don't overwrite another process's changes.
2. **F9:** multi-doc tag aggregation.

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
| D6 | **Reuse the lint result within a task** | open | low | S | lint.sh, .claude/skills/* | Lint runs 3–4 times per task (baseline, verify, log-change, review-handoff). Save a summary (pass/fail, test count, mypy file count) keyed by a hash of `git diff HEAD`; rerun only when it changed, and print only the summary or the failures. |
| D7 | **Run `/doc-audit` in a forked, cheaper-model context** | open | low | XS | .claude/skills/doc-audit/SKILL.md | It sweeps every doc and the code but only the findings matter. Try `context: fork` plus a `model:` setting in the frontmatter; test once before relying on it. |
| D8 | **Shorter `/log-change` entries** | open | low | S | .claude/skills/log-change/SKILL.md | CHANGELOG and `improvement-plan.md` describe each change twice. Let history entries link the task sheet for detail instead of repeating it; keep the "why". |
| D9 | **Brief's task-sheet list matches nearly every sheet** | open | low | XS | .claude/skills/task/orient.py `task_sheets()` | `orient.py D5 "log-change"` listed all 25 sheets, because every sheet's hand-off step names `/log-change`. Match only a sheet's title, Backlog line and Goal, or cap the list with a "N more" tail like the history matches. |
