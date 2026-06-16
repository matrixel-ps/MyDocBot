import os
import re
import json

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
        entry = {"ts": timestamp, "doc_id": doc_id, "preview": preview[:80]}
        index.setdefault(tag, []).append(entry)
    save_tags_index(index)
