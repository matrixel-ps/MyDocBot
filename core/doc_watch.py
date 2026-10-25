"""Watch read-only docs and report new, edited and removed entries (F11).

The Discord bot runs poll() every few minutes; this module has no discord
import. The Docs API can't push changes to a desktop app, and revisionId is
only filled in for editors, so each poll fetches the doc (title + text only)
and compares its entries with the last snapshot.

Snapshots hold hashes, never note text: watch_state.json maps a doc ID to a
hash per entry, keyed by its timestamp. The first poll of a doc is a silent
baseline, and an error never replaces a snapshot or sends a change.
"""
import hashlib
import json
import os
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
# Discord rejects longer messages; previews and the entry count keep well under it.
DISCORD_MESSAGE_LIMIT = 2000
PREVIEW_CHARS = 200
MAX_LISTED = 5


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
    return {"text_hash": _hash(text), "entries": {key: _hash(body) for key, _, body in _keyed(entries)}}


@dataclass
class Change:
    kind: str  # "new", "edited" or "removed"
    ts: str
    body: str | None = None  # the current text; None for "removed" (only its hash was kept)


def diff(old, entries):
    """Changes from the snapshot `old` to `entries`, new and edited in doc
    order, then removed."""
    old_entries = old.get("entries", {})
    changes = []
    current = set()
    for key, ts, body in _keyed(entries):
        current.add(key)
        if key not in old_entries:
            changes.append(Change("new", ts, body))
        elif old_entries[key] != _hash(body):
            changes.append(Change("edited", ts, body))
    for key in old_entries:
        if key not in current:
            changes.append(Change("removed", key.split("#")[0]))
    return changes


def _when(ts):
    """'[10/24/2026] [14.30]|' -> '10/24/2026 [14.30]'."""
    date, _, time = ts.rstrip("|").partition("] ")
    return f"{date.lstrip('[')} {time}".strip()


def _preview(body):
    flat = " ".join(body.split())
    return flat if len(flat) <= PREVIEW_CHARS else flat[:PREVIEW_CHARS - 1] + "…"


_LABELS = {"new": "🆕", "edited": "✏️ edited", "removed": "🗑️ removed"}


def format_changes(alias, title, changes):
    """One Discord message for one doc's changes, under the length limit."""
    counts = [f"{n} {kind}" for kind in ("new", "edited", "removed")
              if (n := sum(c.kind == kind for c in changes))]
    name = f'{alias} ("{title}")' if title else alias
    lines = [f"📄 {name}: {', '.join(counts)}"]
    for change in changes[:MAX_LISTED]:
        line = f"{_LABELS[change.kind]} {_when(change.ts)}"
        if change.body is not None:
            line += f" — {_preview(change.body)}"
        lines.append(line)
    if len(changes) > MAX_LISTED:
        lines.append(f"…and {len(changes) - MAX_LISTED} more")
    message = "\n".join(lines)
    return message if len(message) <= DISCORD_MESSAGE_LIMIT else message[:DISCORD_MESSAGE_LIMIT - 1] + "…"


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
    return text if len(text) <= PREVIEW_CHARS else text[:PREVIEW_CHARS - 1] + "…"


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
        return
    if not entries and entry["entries"]:
        # Like /tag reindex: a doc that suddenly parses to nothing is more
        # likely a format change or a bad response than every entry deleted.
        result.logs.append(f"Watch: {alias} parsed to no entries; keeping the last snapshot.")
        return
    changes = diff(entry, entries)
    entry.update(snapshot(entries, text))
    if changes:
        result.messages.append(format_changes(alias, doc.get("title"), changes))


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
