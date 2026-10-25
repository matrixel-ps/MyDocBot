"""The note timestamp format, `[MM/DD/YY] (HH:MM)|`, in one place (A1).

Imports nothing from core, so any core module (google_docs included) can use
it without an import cycle.
"""
import re
from datetime import datetime

TIMESTAMP_FORMAT = "[%m/%d/%y] (%H:%M)|"

# A header as written by format_timestamp(). parse_entries() also accepts any
# whitespace between "]" and "(", as it always has.
HEADER_PATTERN = r'\[(\d{2})/(\d{2})/(\d{2})\]\s*\((\d{2}):(\d{2})\)\|'
_HEADER_RE = re.compile(HEADER_PATTERN)


def format_timestamp(now=None):
    return (now or datetime.now()).strftime(TIMESTAMP_FORMAT)


def parse_timestamp(ts):
    """The datetime at the start of ts. Raises ValueError if it isn't a valid header."""
    m = _HEADER_RE.match(ts or "")
    if not m:
        raise ValueError(f"not a note timestamp: {ts!r}")
    month, day, year, hour, minute = m.groups()
    return datetime.strptime(f"{month}/{day}/{year} {hour}:{minute}", "%m/%d/%y %H:%M")


def date_key(ts):
    """"MM/DD/YY" for grouping notes by day."""
    return parse_timestamp(ts).strftime("%m/%d/%y")


def parse_date_flag(text):
    """A --since/--until date: MM/DD/YY or MM/DD/YYYY, zero padding optional."""
    for fmt in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"not a date (expected MM/DD/YY): {text!r}")

