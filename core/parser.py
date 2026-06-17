import os
import re
import json
import textwrap

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAGS_INDEX_PATH = os.path.join(BASE_DIR, 'tags_index.json')


def extract_tags(text):
    return re.findall(r'#(\w+)', text.lower())


def load_tags_index():
    if not os.path.exists(TAGS_INDEX_PATH):
        return {}
    with open(TAGS_INDEX_PATH, 'r') as f:
        content = f.read().strip()
        if not content:
            return {}
        return json.loads(content)


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


def filter_tag_entries_by_date(entries, since=None, until=None):
    if not since and not until:
        return entries
    since_tuple = _parse_date(since) if since else None
    until_tuple = _parse_date(until) if until else None
    result = []
    for e in entries:
        date_tuple = _parse_date(e["ts"][1:9])
        if since_tuple and date_tuple < since_tuple:
            continue
        if until_tuple and date_tuple > until_tuple:
            continue
        result.append(e)
    return result
