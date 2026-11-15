"""Watch read-only docs and report new, edited and removed entries (F11).

The Discord bot runs poll() every few minutes; this module has no discord
import. The Docs API can't push changes to a desktop app, and revisionId is
only filled in for editors, so each poll fetches the doc (title + text only)
and compares its entries with the last snapshot.

watch_state.json maps a doc ID to each entry's text, keyed by its timestamp,
so an edit can be shown as a word diff and a removal with what was removed.
State written before that held only a hash per entry; it is still compared,
and is replaced by text on the next poll. The first poll of a doc is a silent
baseline, and an error never replaces a snapshot or sends a change.
"""
import difflib
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field

from . import config, google_docs, storage
from .discord_handler import DiscordSetupError
from .paths import data_path

WATCH_STATE_PATH = data_path('watch_state.json')

DEFAULT_INTERVAL_MINUTES = 5
MIN_INTERVAL_MINUTES = 1
# A doc that fails this many polls in a row gets one alert (and one when it recovers).
FAILURE_ALERT_AFTER = 3
# Discord rejects longer messages; format_changes() splits across several.
DISCORD_MESSAGE_LIMIT = 2000
# Error text in the log and in alerts is cut to this.
ERROR_CHARS = 200
DOC_URL = "https://docs.google.com/document/d/{}"
# A long entry fills the rest of a message only if at least this much room is left.
MIN_SPLIT_ROOM = 80


@dataclass(frozen=True)
class WatchConfig:
    aliases: tuple[str, ...]
    interval_minutes: float = DEFAULT_INTERVAL_MINUTES


def parse_watch_config(data, read_config):
    """The "watch" block of discord_config.json, or None when there is none.
    Every alias must exist in read_config.json now; a typo is a startup error
    rather than a doc that is silently never watched."""
    watch = data.get("watch")
    if watch is None:
        return None
    if not isinstance(watch, dict):
        raise DiscordSetupError('"watch" must be an object: {"aliases": [...], "interval_minutes": 5}')
    aliases = watch.get("aliases")
    if not isinstance(aliases, list) or not aliases or not all(isinstance(a, str) for a in aliases):
        raise DiscordSetupError('"watch" needs a non-empty "aliases" list of read-only aliases.')
    known = read_config.get("aliases", {})
    unknown = [a for a in aliases if a not in known]
    if unknown:
        raise DiscordSetupError(
            f"Watched alias(es) not in read_config.json: {', '.join(unknown)}. "
            "Add them with /add in mydocbot --read.")
    interval = watch.get("interval_minutes", DEFAULT_INTERVAL_MINUTES)
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or interval < MIN_INTERVAL_MINUTES:
        raise DiscordSetupError(f'"interval_minutes" must be a number, at least {MIN_INTERVAL_MINUTES}.')
    return WatchConfig(tuple(dict.fromkeys(aliases)), float(interval))


def _hash(text):
    """Whitespace-insensitive, so re-wrapping or trailing spaces aren't a change."""
    return hashlib.sha256(" ".join(text.split()).encode()).hexdigest()[:16]


def _keyed(entries):
    """[(key, ts, body)] in doc order. Two entries with the same timestamp get
    "#2", "#3"… so neither hides the other."""
    seen = {}
    keyed = []
    for ts, body in entries:
        seen[ts] = seen.get(ts, 0) + 1
        key = ts if seen[ts] == 1 else f"{ts}#{seen[ts]}"
        keyed.append((key, ts, body))
    return keyed


def snapshot(entries, text):
    return {"text_hash": _hash(text), "entries": {key: {"text": body} for key, _, body in _keyed(entries)}}


def has_legacy_entries(old):
    """True for a snapshot written before entry text was kept (a hash string per entry)."""
    return any(isinstance(v, str) for v in old.get("entries", {}).values())


def _old_text(value):
    """The stored text of a snapshot entry, or None for a legacy hash-only one."""
    return value.get("text") if isinstance(value, dict) else None


def _same(value, body):
    old = _old_text(value)
    if old is None:
        return value == _hash(body)
    return " ".join(old.split()) == " ".join(body.split())


@dataclass
class Change:
    kind: str  # "new", "edited" or "removed"
    ts: str
    body: str | None = None  # the current text; None for "removed"
    old: str | None = None   # the previous text (edited, removed); None if only a hash was kept


def diff(old, entries):
    """Changes from the snapshot `old` to `entries`, new and edited in doc
    order, then removed. Whitespace-only edits aren't changes."""
    old_entries = old.get("entries", {})
    changes = []
    current = set()
    for key, ts, body in _keyed(entries):
        current.add(key)
        if key not in old_entries:
            changes.append(Change("new", ts, body))
        elif not _same(old_entries[key], body):
            changes.append(Change("edited", ts, body, _old_text(old_entries[key])))
    for key, value in old_entries.items():
        if key not in current:
            changes.append(Change("removed", key.split("#")[0], old=_old_text(value)))
    return changes


def _when(ts):
    """'[10/24/2026] [14.30]|' -> '10/24/2026 [14.30]'."""
    date, _, time = ts.rstrip("|").partition("] ")
    return f"{date.lstrip('[')} {time}".strip()


_MARKDOWN = re.compile(r"([\\*_~`|])")


def _escape(text):
    """Note text shown literally, not as Discord markdown."""
    return _MARKDOWN.sub(r"\\\1", text)


def _quote(text):
    return "\n".join(f"> {line}" for line in text.split("\n"))


def _mark(text, marker):
    """Wrap each line of `text` separately, so markdown never spans a line break
    (or a message split)."""
    return "\n".join(f"{marker}{line.strip()}{marker}" if line.strip() else line for line in text.split("\n"))


def word_diff(old, new):
    """The new text with removed words as ~~strikethrough~~ and added words in
    **bold**. Words are compared ignoring whitespace; the new text's line
    breaks are kept."""
    old_words = old.split()
    new_tokens = re.findall(r"(\S+)(\s*)", new.strip())
    new_words = [w for w, _ in new_tokens]

    def new_text(j1, j2):
        return "".join(_escape(w) + ws for w, ws in new_tokens[j1:j2])

    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old_words, new_words, autojunk=False).get_opcodes():
        if tag == "equal":
            out.append(new_text(j1, j2))
            continue
        if tag in ("delete", "replace"):
            if out and not out[-1][-1:].isspace():
                out.append(" ")
            out.append(_mark(_escape(" ".join(old_words[i1:i2])), "~~") + " ")
        if tag in ("insert", "replace"):
            added = new_text(j1, j2)
            trailing = new_tokens[j2 - 1][1]
            out.append(_mark(added[:len(added) - len(trailing)], "**") + trailing)
    return "".join(out).rstrip()


_LABELS = {"new": "🆕", "edited": "✏️ edited", "removed": "🗑️ removed"}


def _change_block(change):
    head = f"{_LABELS[change.kind]} {_when(change.ts)}"
    if change.kind == "new":
        text = _escape(change.body or "")
    elif change.kind == "edited" and change.old is not None:
        text = word_diff(change.old, change.body or "")
    elif change.kind == "edited":
        head += " (previous text wasn't stored)"
        text = _escape(change.body or "")
    elif change.old is not None:
        text = _escape(change.old)
    else:
        return head
    return f"{head}\n{_quote(text)}" if text.strip() else head


def _cut(line, room, prefix):
    """Where to cut `line` to fit `room` chars: the last space that fits (not
    inside the "> " quote prefix), else exactly at `room`."""
    cut = line.rfind(" ", len(prefix) + 1, room + 1)
    return cut if cut > 0 else room


def _pack(blocks, limit):
    """Join blocks with blank lines into as few messages as fit under `limit`.
    A block that fits in one message is never split; a longer one fills the
    current message and carries on in the next, split on line breaks, then
    spaces, then anywhere. A quoted line stays quoted on every piece."""
    messages = []
    current = ""
    for block in blocks:
        if current and len(current) + 2 + len(block) <= limit:
            current += "\n\n" + block
            continue
        if len(block) <= limit:
            if current:
                messages.append(current)
            current = block
            continue
        for i, line in enumerate(block.split("\n")):
            sep = ("\n\n" if i == 0 else "\n") if current else ""
            prefix = "> " if line.startswith("> ") else ""
            while True:
                room = limit - len(current) - len(sep)
                if len(line) <= room:
                    current += sep + line
                    break
                if room >= MIN_SPLIT_ROOM or not current:
                    cut = _cut(line, room, prefix)
                    current += sep + line[:cut]
                    line = prefix + line[cut:].lstrip(" ")
                messages.append(current)
                current, sep = "", ""
    if current:
        messages.append(current)
    return messages


def format_changes(alias, title, changes, doc_id=None, limit=DISCORD_MESSAGE_LIMIT):
    """Discord messages for one doc's changes: a header (counts and a doc
    link), then every change in full, split across messages under `limit`."""
    counts = [f"{n} {kind}" for kind in ("new", "edited", "removed")
              if (n := sum(c.kind == kind for c in changes))]
    name = f'{alias} ("{title}")' if title else alias
    header = f"📄 {name}: {', '.join(counts)}"
    if doc_id:
        header += f"\n<{DOC_URL.format(doc_id)}>"  # <> stops Discord's link preview
    return _pack([header] + [_change_block(c) for c in changes], limit)


def load_state():
    if not os.path.exists(WATCH_STATE_PATH):
        return {}
    try:
        with open(WATCH_STATE_PATH) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        backup = storage.quarantine(WATCH_STATE_PATH)
        print(f"Warning: Corrupt watch state at {WATCH_STATE_PATH} — {e}. Moved it to {backup}; "
              "watched docs start from a new baseline.", file=sys.stderr)
        return {}


def save_state(state):
    storage.write_json(WATCH_STATE_PATH, state)  # atomic, 0600


@dataclass
class PollResult:
    messages: list[str] = field(default_factory=list)  # to DM the owner
    logs: list[str] = field(default_factory=list)      # for the bot's log only


def _short_error(e):
    text = f"{type(e).__name__}: {e}"
    return text if len(text) <= ERROR_CHARS else text[:ERROR_CHARS - 1] + "…"


def _check_doc(service, alias, doc_id, entry, result):
    """Poll one doc, updating its state `entry` in place."""
    try:
        doc = google_docs.fetch_doc(service, doc_id)
    except Exception as e:
        entry["failures"] = entry.get("failures", 0) + 1
        if entry["failures"] == 1:
            result.logs.append(f"Watch: can't read {alias} — {_short_error(e)}")
        if entry["failures"] == FAILURE_ALERT_AFTER:
            result.messages.append(
                f"⚠️ Can't read {alias} ({FAILURE_ALERT_AFTER} checks in a row): {_short_error(e)}")
        return
    if entry.get("failures", 0) >= FAILURE_ALERT_AFTER:
        result.messages.append(f"✅ {alias} is readable again.")
    entry["failures"] = 0

    text = google_docs.doc_text(doc)
    entries = google_docs.parse_entries_readable(doc, count=None)
    if "entries" not in entry:
        entry.update(snapshot(entries, text))
        result.logs.append(f"Watch: baseline for {alias} ({len(entries)} entries).")
        return
    if entry["text_hash"] == _hash(text):
        if has_legacy_entries(entry):  # state from before text was kept: store it now, silently
            entry.update(snapshot(entries, text))
            result.logs.append(f"Watch: stored entry text for {alias}.")
        return
    if not entries and entry["entries"]:
        # Like /tag reindex: a doc that suddenly parses to nothing is more
        # likely a format change or a bad response than every entry deleted.
        result.logs.append(f"Watch: {alias} parsed to no entries; keeping the last snapshot.")
        return
    changes = diff(entry, entries)
    entry.update(snapshot(entries, text))
    if changes:
        result.messages.extend(format_changes(alias, doc.get("title"), changes, doc_id))


def poll(service, watch):
    """Check every watched doc once. Read-only: nothing here writes to a doc.

    Aliases are resolved from read_config.json on each poll, so /add or a
    retarget in mydocbot --read applies without a restart; a retargeted alias
    has a new doc ID and so starts from a new baseline. State for docs no
    longer watched is dropped."""
    result = PollResult()
    read_aliases = config.load_read_config().get("aliases", {})
    with storage.locked(WATCH_STATE_PATH):
        state = load_state()
        new_state = {}
        for alias in watch.aliases:
            doc_id = read_aliases.get(alias)
            if not doc_id:
                result.logs.append(f"Watch: {alias} is no longer in read_config.json; skipped.")
                continue
            entry = new_state.setdefault(doc_id, dict(state.get(doc_id, {})))
            _check_doc(service, alias, doc_id, entry, result)
        if new_state != state:
            save_state(new_state)
    return result
