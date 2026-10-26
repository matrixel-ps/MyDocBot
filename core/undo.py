"""`/undo` of the last note MyDocBot wrote to a doc (F3).

submit_note() records each sent note in last_write.json, one record per doc:
the exact string it inserted at the top. undo_last() removes that string, but
only while the doc still starts with it (google_docs.try_undo), then drops the
note's tag entries and the record. One level: after an undo, or once the top no
longer matches, there is nothing left to undo for that doc.

The record lives in the data directory, not in memory, so one-shot capture
(`mydocbot "note"`, then `mydocbot --undo`) and a TUI note undone from the CLI
both work.
"""
import json
import os
import sys
from dataclasses import dataclass

from . import google_docs, parser, storage
from .paths import data_path

LAST_WRITE_PATH = data_path('last_write.json')


def load_last_writes():
    """{doc_id: {"ts", "text", "written"}}; {} if missing. A corrupt file is moved
    aside like the other data files (B11): losing it only loses the undo."""
    if not os.path.exists(LAST_WRITE_PATH):
        return {}
    try:
        with open(LAST_WRITE_PATH) as f:
            content = f.read().strip()
        data = json.loads(content) if content else {}
        if not isinstance(data, dict):
            raise ValueError("not a JSON object")
        return data
    except (ValueError, UnicodeDecodeError) as e:  # JSONDecodeError is a ValueError
        backup = storage.quarantine(LAST_WRITE_PATH)
        print(f"Warning: Corrupt undo record at {LAST_WRITE_PATH} — {e}. Moved it to {backup}; "
              "/undo has nothing to undo until the next note.", file=sys.stderr)
        return {}
    except OSError as e:
        print(f"Warning: Can't read undo record at {LAST_WRITE_PATH} — {e}.", file=sys.stderr)
        return {}


def _save(records):
    if records:
        storage.write_json(LAST_WRITE_PATH, records)  # atomic, 0600 (A6)
    elif os.path.exists(LAST_WRITE_PATH):
        os.unlink(LAST_WRITE_PATH)


def record_write(doc_id, timestamp, text, written):
    """Remember the note just prepended to doc_id; replaces that doc's previous record."""
    with storage.locked(LAST_WRITE_PATH):
        records = load_last_writes()
        records[doc_id] = {"ts": timestamp, "text": text, "written": written}
        _save(records)


def last_write(doc_id):
    return load_last_writes().get(doc_id)


def _clear(doc_id, record):
    """Drop doc_id's record, unless another process has replaced it meanwhile."""
    with storage.locked(LAST_WRITE_PATH):
        records = load_last_writes()
        if records.get(doc_id) == record:
            del records[doc_id]
            _save(records)


@dataclass
class UndoResult:
    """Outcome of undo_last(). status is one of:
    "undone": the note was removed from the doc (and its tags from the index);
    "nothing": no note to undo for this doc;
    "queued": notes for this doc are waiting in the offline queue, so the top of
      the doc isn't the newest submit (use /queue drop);
    "changed": the doc no longer starts with the note, so nothing was deleted and
      the record is dropped;
    "failed": the fetch or delete failed (see failure); the record is kept to retry."""
    status: str
    record: dict | None = None
    failure: google_docs.WriteFailure | None = None


def check_undo(doc_id):
    """What undo_last() would act on, without calling Google: an UndoResult with
    status "ready" (and the record), "nothing", or "queued". The CLI uses it to show
    the note before asking."""
    record = last_write(doc_id)
    if record is None:
        return UndoResult("nothing")
    if parser.count_pending(doc_id):
        return UndoResult("queued", record)
    return UndoResult("ready", record)


def undo_last(service, doc_id):
    """Remove the last note written to doc_id, if it's still at the top. See UndoResult."""
    check = check_undo(doc_id)
    if check.status != "ready":
        return check
    record = check.record
    assert record is not None
    outcome = google_docs.try_undo(service, doc_id, record["written"])
    if outcome == "undone":
        parser.unindex_note(record["text"], record["ts"], doc_id, record["text"])
        _clear(doc_id, record)
        return UndoResult("undone", record)
    if outcome == "changed":
        _clear(doc_id, record)
        return UndoResult("changed", record)
    return UndoResult("failed", record, failure=outcome)


def undo_message(result):
    """One-line text for an UndoResult, shared by the CLI and TUI (no markup)."""
    record = result.record or {}
    if result.status == "undone":
        return f"Removed the note from {record.get('ts', '')} from the doc."
    if result.status == "nothing":
        return "Nothing to undo for this doc."
    if result.status == "queued":
        return ("Notes for this doc are still queued, so the top of the doc isn't your last note. "
                "See /queue, and /queue drop <n> to discard one.")
    if result.status == "changed":
        return ("The doc no longer starts with your last note (edited, or another note is on top), "
                "so nothing was deleted.")
    message = result.failure.message if result.failure else "unknown error"
    return f"Undo failed: {message}. Nothing was deleted; try /undo again."
