import json
import os
import re
import shutil
import sys
import textwrap
from dataclasses import dataclass

from . import google_docs
from .paths import data_path

TAGS_INDEX_PATH = data_path('tags_index.json')
PENDING_PATH = data_path('pending_queue.json')


def extract_tags(text):
    return re.findall(r'#(\w+)', text.lower())


def load_tags_index():
    if not os.path.exists(TAGS_INDEX_PATH):
        return {}
    try:
        with open(TAGS_INDEX_PATH) as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: Corrupt tags index at {TAGS_INDEX_PATH} — {e}. Starting fresh.", file=sys.stderr)
        return {}


def save_tags_index(index):
    with open(TAGS_INDEX_PATH, 'w') as f:
        json.dump(index, f, indent=2)
        f.write('\n')


def _add_note_tags(index, text, timestamp, doc_id, preview):
    """Add one entry per #tag in text to index (in place), skipping exact duplicates."""
    for tag in extract_tags(text):
        entry = {"ts": timestamp, "doc_id": doc_id, "preview": textwrap.shorten(preview, width=80, placeholder="...")}
        if entry not in index.setdefault(tag, []):
            index[tag].append(entry)


def index_note(text, timestamp, doc_id, preview):
    if not extract_tags(text):
        return
    index = load_tags_index()
    _add_note_tags(index, text, timestamp, doc_id, preview)
    save_tags_index(index)


def _count_doc_entries(index, doc_id):
    return sum(1 for entries in index.values() for e in entries if e["doc_id"] == doc_id)


@dataclass
class ReindexResult:
    status: str  # "reindexed" or "no_notes" (doc parsed to zero notes; index left unchanged)
    notes: int = 0
    tagged_notes: int = 0
    tags: int = 0
    entries_before: int = 0
    entries_after: int = 0


def reindex_doc(service, doc_id):
    """Rebuild doc_id's tag entries from the doc's full text; other docs' entries are kept.

    Replaces rather than merges, so notes deleted or edited in Google Docs are
    reflected. The previous index is copied to tags_index.json.bak first. A
    fetch error propagates before anything is touched. If the doc parses to
    zero notes the index is left alone, so an unexpected format or empty
    response can't wipe this doc's tags.
    """
    doc = google_docs.fetch_doc(service, doc_id)
    entries = google_docs.parse_entries(doc, count=None)
    index = load_tags_index()
    before = _count_doc_entries(index, doc_id)
    if not entries:
        return ReindexResult("no_notes", entries_before=before, entries_after=before)

    if os.path.exists(TAGS_INDEX_PATH):
        shutil.copy2(TAGS_INDEX_PATH, TAGS_INDEX_PATH + '.bak')
    index = {tag: [e for e in tag_entries if e["doc_id"] != doc_id] for tag, tag_entries in index.items()}
    tagged = 0
    for timestamp, body in reversed(entries):  # the doc is newest first; the index is oldest first
        if extract_tags(body):
            tagged += 1
            _add_note_tags(index, body, timestamp, doc_id, body)
    index = {tag: tag_entries for tag, tag_entries in index.items() if tag_entries}
    save_tags_index(index)
    doc_tags = sum(1 for tag_entries in index.values() if any(e["doc_id"] == doc_id for e in tag_entries))
    return ReindexResult("reindexed", len(entries), tagged, doc_tags, before, _count_doc_entries(index, doc_id))


def search_cache(cache, doc_id, keyword):
    return [n for n in cache
            if n["doc_id"] == doc_id
            and keyword.lower() in n["text"].lower()]


def _parse_date(date_str):
    month, day, year = date_str.split("/")
    return (int(year), int(month), int(day))


def parse_date_flags(args):
    rest = []
    since = None
    until = None
    i = 0
    while i < len(args):
        if args[i] == '--since' and i + 1 < len(args):
            since = args[i + 1]
            i += 2
        elif args[i] == '--until' and i + 1 < len(args):
            until = args[i + 1]
            i += 2
        else:
            rest.append(args[i])
            i += 1
    return rest, since, until


def load_pending_notes():
    if not os.path.exists(PENDING_PATH):
        return []
    try:
        with open(PENDING_PATH) as f:
            content = f.read().strip()
            if not content:
                return []
            return json.loads(content)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: Corrupt pending queue at {PENDING_PATH} — {e}. Discarding.", file=sys.stderr)
        return []


def save_pending_notes(queue):
    if queue:
        with open(PENDING_PATH, 'w') as f:
            json.dump(queue, f, indent=2)
            f.write('\n')
    elif os.path.exists(PENDING_PATH):
        os.unlink(PENDING_PATH)


def queue_note(text, doc_id, timestamp):
    queue = load_pending_notes()
    queue.append({"text": text, "doc_id": doc_id, "ts": timestamp})
    save_pending_notes(queue)


def count_pending(doc_id=None):
    queue = load_pending_notes()
    if doc_id is None:
        return len(queue)
    return sum(1 for entry in queue if entry["doc_id"] == doc_id)


def flush_pending_notes(service):
    """Write queued notes for every doc, oldest first, and return the entries
    that were written. Within a doc, stop at the first failure: every write
    goes to the top of the doc, so writing a later note while an earlier one
    is still queued would put them out of order, and while offline each extra
    attempt costs another full retry cycle."""
    queue = load_pending_notes()
    if not queue:
        return []
    remaining = []
    sent = []
    blocked = set()
    for entry in queue:
        if entry["doc_id"] in blocked:
            remaining.append(entry)
            continue
        timestamp = entry["ts"]
        entry_text = f"{timestamp} {entry['text']}"
        if google_docs.prepend_text(service, entry["doc_id"], entry_text):
            # Index at flush time, not queue time: only notes that actually
            # reached the doc are in tags_index.json.
            index_note(entry["text"], timestamp, entry["doc_id"], entry["text"])
            sent.append(entry)
        else:
            blocked.add(entry["doc_id"])
            remaining.append(entry)
    save_pending_notes(remaining)
    return sent


def filter_tag_entries_by_date(entries, since=None, until=None):
    if not since and not until:
        return entries
    try:
        since_tuple = _parse_date(since) if since else None
        until_tuple = _parse_date(until) if until else None
    except (ValueError, IndexError):
        print("Warning: invalid date filter (expected MM/DD/YY)", file=sys.stderr)
        return entries
    result = []
    for e in entries:
        try:
            date_tuple = _parse_date(e["ts"][1:9])
        except (ValueError, IndexError):
            print(f"Warning: skipping entry with malformed timestamp: {e.get('ts', '')!r}", file=sys.stderr)
            continue
        if since_tuple and date_tuple < since_tuple:
            continue
        if until_tuple and date_tuple > until_tuple:
            continue
        result.append(e)
    return result
