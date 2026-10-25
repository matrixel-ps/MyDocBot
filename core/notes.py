from dataclasses import dataclass, field

from . import google_docs, parser, validation
from .timestamps import TIMESTAMP_FORMAT, format_timestamp  # noqa: F401  re-exported; defined in timestamps (A1)


@dataclass
class SubmitResult:
    """Outcome of submit_note(). `status` is "sent", "queued", or "rejected".
    `flushed` holds the previously queued entries written before this note,
    oldest first; `queued_behind` is how many notes for the same doc were
    still queued ahead of this one (0 unless it was queued without trying).
    `failure` says why a queued note wasn't written: this note's own failed
    write, or, when queued behind, the stored failure of the oldest note
    holding the doc up (None if that note never recorded one)."""
    status: str
    timestamp: str | None = None
    reason: str | None = None
    flushed: list[dict] = field(default_factory=list)
    queued_behind: int = 0
    failure: google_docs.WriteFailure | None = None


def submit_note(service, doc_id, text, now=None):
    """Validate, timestamp, and prepend a note, keeping the doc in the order
    notes were written. Shared by every write path (CLI REPL, CLI /edit, TUI
    submit, TUI /edit) so they can't drift.

    The offline queue is flushed *first*: every write goes to the top of the
    doc, so older queued notes must land before this one. If notes for this
    doc are still queued afterwards, its last write just failed, so this note
    is queued behind them without trying (keeps the order, and skips another
    retry wait). Otherwise it's prepended and its tags indexed, or queued if
    the write fails."""
    valid, msg = validation.validate_note(text)
    if not valid:
        return SubmitResult("rejected", reason=msg)

    timestamp = format_timestamp(now)
    flushed = parser.flush_pending_notes(service)

    behind = parser.count_pending(doc_id)
    if behind:
        parser.queue_note(text, doc_id, timestamp)
        return SubmitResult("queued", timestamp, flushed=flushed, queued_behind=behind,
                            failure=parser.first_pending_failure(doc_id))

    failure = google_docs.try_prepend(service, doc_id, f"{timestamp} {text}")
    if failure is None:
        parser.index_note(text, timestamp, doc_id, text)
        return SubmitResult("sent", timestamp, flushed=flushed)

    parser.queue_note(text, doc_id, timestamp, failure)
    return SubmitResult("queued", timestamp, flushed=flushed, failure=failure)
