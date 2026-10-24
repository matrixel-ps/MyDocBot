import json
import os
import re
import sys
import textwrap

from . import google_docs

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAGS_INDEX_PATH = os.path.join(BASE_DIR, 'tags_index.json')
PENDING_PATH = os.path.join(BASE_DIR, 'pending_queue.json')


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


def index_note(text, timestamp, doc_id, preview):
    tags = extract_tags(text)
    if not tags:
        return
    index = load_tags_index()
    for tag in tags:
        entry = {"ts": timestamp, "doc_id": doc_id, "preview": textwrap.shorten(preview, width=80, placeholder="...")}
        if entry not in index.setdefault(tag, []):
            index[tag].append(entry)
    save_tags_index(index)


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
