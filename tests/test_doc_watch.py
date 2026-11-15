"""Watching read-only docs (F11): config, snapshots, diffs, messages, poll()
and the bot's watcher loop. The Google API is a fake keyed by doc ID; all
data paths are in tmp_path."""
import asyncio
import os
import ssl
import stat
from unittest.mock import patch

import pytest
from conftest import make_doc_response

import core.config as cfg
import discord_bot
from core import doc_watch as dw
from core.discord_handler import DiscordSetupError

READ_CONFIG = {"default": "standup", "aliases": {"standup": "doc_s", "other": "doc_o"}}


def readable(*entries):
    """Read-only format text, newest first: ("10/24/2026", "14.30", "body")."""
    return "\n\n".join(f"{date}\n[{time}]\n{body}" for date, time, body in entries) + "\n"


class DocsService:
    """Fake Docs service: docs[doc_id] is the text to return, or an exception to raise."""

    def __init__(self, **docs):
        self.docs = docs
        self.fetches = []
        self._doc_id = None

    def documents(self):
        return self

    def get(self, documentId=None, fields=None):
        self._doc_id = documentId
        return self

    def execute(self):
        self.fetches.append(self._doc_id)
        value = self.docs[self._doc_id]
        if isinstance(value, Exception):
            raise value
        return {"title": f"Title {self._doc_id}", **make_doc_response(value)}


@pytest.fixture
def read_config(tmp_read_config_path):
    cfg.save_read_config(READ_CONFIG)
    return READ_CONFIG


@pytest.fixture
def state_dir(_isolate_data_dir):
    _isolate_data_dir.mkdir(exist_ok=True)
    return _isolate_data_dir


@pytest.fixture(autouse=True)
def _no_retry_wait(monkeypatch):
    monkeypatch.setattr('core.google_docs.time.sleep', lambda s: None)


WATCH = dw.WatchConfig(("standup",))
E1 = ("10/23/2026", "09.00", "older entry")
E2 = ("10/24/2026", "14.30", "Deployed the new build")


class TestParseWatchConfig:
    def test_no_watch_block_means_nothing_watched(self):
        assert dw.parse_watch_config({"allowed_user_ids": [1]}, READ_CONFIG) is None

    def test_defaults_and_dedupe(self):
        watch = dw.parse_watch_config({"watch": {"aliases": ["standup", "standup", "other"]}}, READ_CONFIG)
        assert watch == dw.WatchConfig(("standup", "other"), 5.0)

    def test_custom_interval(self):
        watch = dw.parse_watch_config({"watch": {"aliases": ["other"], "interval_minutes": 15}}, READ_CONFIG)
        assert watch.interval_minutes == 15.0

    def test_unknown_alias_is_named(self):
        with pytest.raises(DiscordSetupError, match="not in read_config.json: nope"):
            dw.parse_watch_config({"watch": {"aliases": ["standup", "nope"]}}, READ_CONFIG)

    @pytest.mark.parametrize("watch", [[], {"aliases": []}, {"aliases": "standup"}, {"aliases": [1]}])
    def test_bad_shape(self, watch):
        with pytest.raises(DiscordSetupError):
            dw.parse_watch_config({"watch": watch}, READ_CONFIG)

    @pytest.mark.parametrize("interval", [0.5, 0, -1, "5", True, None])
    def test_bad_interval(self, interval):
        with pytest.raises(DiscordSetupError, match="interval_minutes"):
            dw.parse_watch_config({"watch": {"aliases": ["standup"], "interval_minutes": interval}}, READ_CONFIG)


class TestDiff:
    def entries(self, *raw):
        return [(f"[{d}] [{t}]|", b) for d, t, b in raw]

    def test_new_edited_removed_carry_old_text(self):
        old = dw.snapshot(self.entries(E2, E1), "x")
        e3 = ("10/25/2026", "08.00", "brand new")
        changes = dw.diff(old, self.entries(e3, ("10/24/2026", "14.30", "Deployed v2")))
        assert [(c.kind, c.ts, c.body, c.old) for c in changes] == [
            ("new", "[10/25/2026] [08.00]|", "brand new", None),
            ("edited", "[10/24/2026] [14.30]|", "Deployed v2", "Deployed the new build"),
            ("removed", "[10/23/2026] [09.00]|", None, "older entry"),
        ]

    def test_whitespace_only_edit_is_not_a_change(self):
        old = dw.snapshot(self.entries(E2), "x")
        assert dw.diff(old, self.entries(("10/24/2026", "14.30", "Deployed  the\nnew build "))) == []

    def test_same_timestamp_twice_are_separate_entries(self):
        twins = self.entries(("10/24/2026", "14.30", "a"), ("10/24/2026", "14.30", "b"))
        old = dw.snapshot(twins[:1], "x")
        [change] = dw.diff(old, twins)
        assert (change.kind, change.body) == ("new", "b")

    def test_snapshot_keeps_entry_text(self):
        snap = dw.snapshot(self.entries(E2), "x")
        assert snap["entries"] == {"[10/24/2026] [14.30]|": {"text": "Deployed the new build"}}
        assert not dw.has_legacy_entries(snap)

    def test_legacy_hash_only_snapshot_still_compares(self):
        legacy = {"text_hash": "x", "entries": {
            "[10/24/2026] [14.30]|": dw._hash("Deployed the new build"),
            "[10/23/2026] [09.00]|": dw._hash("older entry")}}
        assert dw.has_legacy_entries(legacy)
        assert dw.diff(legacy, self.entries(E2, E1)) == []  # no flood of "edited"
        changes = dw.diff(legacy, self.entries(("10/24/2026", "14.30", "Deployed v2")))
        assert [(c.kind, c.old) for c in changes] == [("edited", None), ("removed", None)]


class TestWordDiff:
    def test_replaced_and_added_words(self):
        assert dw.word_diff("Call the dentist on Tuesday", "Call the dentist on Thursday at 3pm") == (
            "Call the dentist on ~~Tuesday~~ **Thursday at 3pm**")

    def test_deleted_words(self):
        assert dw.word_diff("buy milk and eggs today", "buy milk today") == "buy milk ~~and eggs~~ today"
        assert dw.word_diff("buy milk today", "buy milk") == "buy milk ~~today~~"

    def test_new_line_breaks_kept_and_markers_dont_span_them(self):
        assert dw.word_diff("one\ntwo", "one\nnew line\nand more\ntwo") == (
            "one\n**new line**\n**and more**\ntwo")

    def test_markdown_in_notes_is_escaped(self):
        assert dw.word_diff("a *b*", "a *b* c_d") == "a \\*b\\* **c\\_d**"


class TestFormatChanges:
    def test_full_text_diff_removed_text_and_link(self):
        changes = [dw.Change("new", "[10/24/2026] [14.30]|", "Deployed\nsecond line"),
                   dw.Change("edited", "[10/24/2026] [10.00]|", "meet at 3", "meet at 2"),
                   dw.Change("removed", "[10/23/2026] [09.00]|", old="gone now")]
        assert dw.format_changes("standup", "Team Log", changes, "doc_s") == [
            '📄 standup ("Team Log"): 1 new, 1 edited, 1 removed\n'
            "<https://docs.google.com/document/d/doc_s>\n\n"
            "🆕 10/24/2026 [14.30]\n> Deployed\n> second line\n\n"
            "✏️ edited 10/24/2026 [10.00]\n> meet at ~~2~~ **3**\n\n"
            "🗑️ removed 10/23/2026 [09.00]\n> gone now"]

    def test_without_stored_text(self):
        changes = [dw.Change("edited", "[10/24/2026] [10.00]|", "meet at 3"),
                   dw.Change("removed", "[10/23/2026] [09.00]|")]
        assert dw.format_changes("standup", None, changes) == [
            "📄 standup: 1 edited, 1 removed\n\n"
            "✏️ edited 10/24/2026 [10.00] (previous text wasn't stored)\n> meet at 3\n\n"
            "🗑️ removed 10/23/2026 [09.00]"]

    def test_every_change_listed(self):
        changes = [dw.Change("new", f"[10/{d:02}/2026] [10.00]|", f"note {d}") for d in range(1, 9)]
        [message] = dw.format_changes("standup", None, changes)
        assert message.count("🆕") == 8 and "more" not in message

    def test_long_output_is_split_not_cut(self):
        bodies = [" ".join(f"w{n}-{i}" for i in range(400)) for n in range(4)]  # ~2.5k chars each
        changes = [dw.Change("new", "[10/24/2026] [14.30]|", b) for b in bodies]
        messages = dw.format_changes("standup", "T", changes, "doc_s")
        assert len(messages) > 4
        assert all(len(m) <= dw.DISCORD_MESSAGE_LIMIT for m in messages)
        text = " ".join(messages).replace("> ", " ")
        words = text.split()
        for n in range(4):  # nothing lost, order kept
            expected = [f"w{n}-{i}" for i in range(400)]
            got = [w for w in words if w.startswith(f"w{n}-")]
            assert got == expected
        assert all(line.startswith("> ") for m in messages for line in m.split("\n") if line.startswith("w"))
        assert not any(line.startswith("w") for m in messages for line in m.split("\n"))

    def test_word_longer_than_a_message_is_split(self):
        changes = [dw.Change("new", "[10/24/2026] [14.30]|", "x" * 5000)]
        messages = dw.format_changes("standup", None, changes, limit=500)
        assert all(len(m) <= 500 for m in messages)
        assert "".join(messages).count("x") == 5000


class TestPoll:
    def test_first_poll_is_a_silent_baseline(self, read_config, state_dir):
        result = dw.poll(DocsService(doc_s=readable(E2, E1)), WATCH)
        assert result.messages == []
        assert result.logs == ["Watch: baseline for standup (2 entries)."]
        assert set(dw.load_state()["doc_s"]["entries"]) == {"[10/24/2026] [14.30]|", "[10/23/2026] [09.00]|"}

    def test_new_entry_sends_one_message(self, read_config, state_dir):
        service = DocsService(doc_s=readable(E1))
        dw.poll(service, WATCH)
        service.docs["doc_s"] = readable(E2, E1)
        result = dw.poll(service, WATCH)
        assert result.messages == ['📄 standup ("Title doc_s"): 1 new\n'
                                   "<https://docs.google.com/document/d/doc_s>\n\n"
                                   "🆕 10/24/2026 [14.30]\n> Deployed the new build"]

    def test_no_change_and_formatting_only_change_are_quiet(self, read_config, state_dir):
        service = DocsService(doc_s=readable(E2, E1))
        dw.poll(service, WATCH)
        assert dw.poll(service, WATCH).messages == []
        service.docs["doc_s"] = "Team log header\n\n" + readable(E2, E1)  # text changed, no entry did
        assert dw.poll(service, WATCH).messages == []
        assert dw.poll(service, WATCH).messages == []  # snapshot was updated

    def test_edit_and_removal(self, read_config, state_dir):
        service = DocsService(doc_s=readable(E2, E1))
        dw.poll(service, WATCH)
        service.docs["doc_s"] = readable(("10/24/2026", "14.30", "Deployed v2"))
        [message] = dw.poll(service, WATCH).messages
        assert "1 edited, 1 removed" in message
        assert "✏️ edited 10/24/2026 [14.30]\n> Deployed ~~the new build~~ **v2**" in message
        assert "🗑️ removed 10/23/2026 [09.00]\n> older entry" in message

    def test_long_change_sends_several_messages(self, read_config, state_dir):
        service = DocsService(doc_s=readable(E1))
        dw.poll(service, WATCH)
        service.docs["doc_s"] = readable(("10/24/2026", "14.30", "word " * 1000), E1)
        messages = dw.poll(service, WATCH).messages
        assert len(messages) == 3 and all(len(m) <= dw.DISCORD_MESSAGE_LIMIT for m in messages)

    def test_legacy_state_gets_text_silently_then_diffs(self, read_config, state_dir):
        service = DocsService(doc_s=readable(E2, E1))
        dw.poll(service, WATCH)
        state = dw.load_state()
        state["doc_s"]["entries"] = {k: dw._hash(v["text"]) for k, v in state["doc_s"]["entries"].items()}
        dw.save_state(state)  # as written before entry text was kept
        result = dw.poll(service, WATCH)
        assert result.messages == [] and result.logs == ["Watch: stored entry text for standup."]
        assert not dw.has_legacy_entries(dw.load_state()["doc_s"])
        service.docs["doc_s"] = readable(("10/24/2026", "14.30", "Deployed v2"), E1)
        [message] = dw.poll(service, WATCH).messages
        assert "~~the new build~~ **v2**" in message

    def test_doc_that_parses_to_nothing_keeps_the_snapshot(self, read_config, state_dir):
        service = DocsService(doc_s=readable(E2, E1))
        dw.poll(service, WATCH)
        before = dw.load_state()
        service.docs["doc_s"] = "something in a different format\n"
        result = dw.poll(service, WATCH)
        assert result.messages == [] and "parsed to no entries" in result.logs[0]
        assert dw.load_state() == before

    def test_errors_keep_snapshot_alert_once_then_recover(self, read_config, state_dir):
        service = DocsService(doc_s=readable(E1))
        dw.poll(service, WATCH)
        service.docs["doc_s"] = ConnectionError("offline")
        results = [dw.poll(service, WATCH) for _ in range(dw.FAILURE_ALERT_AFTER + 1)]
        assert results[0].messages == [] and results[0].logs == ["Watch: can't read standup — ConnectionError: offline"]
        assert all(r.logs == [] for r in results[1:])  # logged once, not every poll
        assert [m for r in results for m in r.messages] == [
            f"⚠️ Can't read standup ({dw.FAILURE_ALERT_AFTER} checks in a row): ConnectionError: offline"]
        service.docs["doc_s"] = readable(E2, E1)  # back, with a new entry written meanwhile
        messages = dw.poll(service, WATCH).messages
        assert messages[0] == "✅ standup is readable again."
        assert "1 new" in messages[1]

    def test_error_before_first_baseline_doesnt_count_as_baseline(self, read_config, state_dir):
        service = DocsService(doc_s=ConnectionError("offline"))
        dw.poll(service, WATCH)
        service.docs["doc_s"] = readable(E2, E1)
        result = dw.poll(service, WATCH)
        assert result.messages == [] and "baseline" in result.logs[0]

    def test_stale_connection_ssl_error_is_retried_not_a_failure(self, read_config, state_dir):
        """B12: the bot's idle connection is closed by Google between polls; the
        first read of the next poll raises ssl.SSLError and is retried."""
        service = DocsService(doc_s=readable(E1))
        dw.poll(service, WATCH)
        eof = ssl.SSLError(1, "[SSL: UNEXPECTED_EOF_WHILE_READING] unexpected eof while reading")
        new_text = readable(E2, E1)

        def execute():
            service.fetches.append(service._doc_id)
            if len(service.fetches) == 2:
                raise eof
            return {"title": "T", **make_doc_response(new_text)}
        service.execute = execute
        result = dw.poll(service, WATCH)
        assert result.logs == [] and dw.load_state()["doc_s"].get("failures") == 0
        assert len(result.messages) == 1 and "1 new" in result.messages[0]

    def test_one_failing_doc_doesnt_stop_the_others(self, read_config, state_dir):
        watch = dw.WatchConfig(("standup", "other"))
        service = DocsService(doc_s=ConnectionError("down"), doc_o=readable(E1))
        dw.poll(service, watch)
        service.docs["doc_o"] = readable(E2, E1)
        assert any("1 new" in m for m in dw.poll(service, watch).messages)

    def test_retargeted_alias_starts_a_new_baseline_and_drops_old_state(self, read_config, state_dir):
        service = DocsService(doc_s=readable(E1), doc_new=readable(E2, E1))
        dw.poll(service, WATCH)
        cfg.save_read_config({**READ_CONFIG, "aliases": {**READ_CONFIG["aliases"], "standup": "doc_new"}})
        result = dw.poll(service, WATCH)
        assert result.messages == [] and "baseline" in result.logs[0]
        assert set(dw.load_state()) == {"doc_new"}

    def test_alias_removed_from_read_config_is_skipped(self, read_config, state_dir):
        cfg.save_read_config({"default": "other", "aliases": {"other": "doc_o"}})
        service = DocsService()
        result = dw.poll(service, WATCH)
        assert service.fetches == []
        assert result.logs == ["Watch: standup is no longer in read_config.json; skipped."]

    def test_state_file_is_owner_only(self, read_config, state_dir):
        dw.poll(DocsService(doc_s=readable(E1)), WATCH)
        assert stat.S_IMODE(os.stat(dw.WATCH_STATE_PATH).st_mode) == 0o600

    def test_never_writes_to_a_doc(self, read_config, state_dir):
        service = DocsService(doc_s=readable(E1))
        service.batchUpdate = None  # any write attempt would fail loudly
        dw.poll(service, WATCH)
        service.docs["doc_s"] = readable(E2, E1)
        dw.poll(service, WATCH)

    def test_corrupt_state_is_moved_aside_and_rebaselined(self, read_config, state_dir, capsys):
        with open(dw.WATCH_STATE_PATH, "w") as f:
            f.write("{nope")
        result = dw.poll(DocsService(doc_s=readable(E1)), WATCH)
        assert result.messages == [] and "baseline" in result.logs[0]
        assert "Corrupt watch state" in capsys.readouterr().err


class StopLoop(Exception):
    pass


class TestRunWatcher:
    async def test_polls_sends_and_sleeps_the_interval(self):
        bot = discord_bot.NoteBot(service=object(), allowed_users={1}, log=lambda line: None)
        sent, sleeps = [], []
        results = iter([dw.PollResult(messages=["a", "b"], logs=[]), dw.PollResult()])

        async def notify(text):
            sent.append(text)

        async def sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) == 2:
                raise StopLoop

        with patch('core.doc_watch.poll', lambda service, watch: next(results)):
            with pytest.raises(StopLoop):
                await bot.run_watcher(dw.WatchConfig(("standup",), 5), notify, sleep=sleep)
        assert sent == ["a", "b"]
        assert sleeps == [300, 300]

    async def test_failed_poll_or_dm_is_logged_and_the_loop_continues(self):
        log = []
        bot = discord_bot.NoteBot(service=object(), allowed_users={1}, log=log.append)
        calls = iter([RuntimeError("boom"), dw.PollResult(messages=["m"], logs=["Watch: x"])])

        def poll(service, watch):
            value = next(calls)
            if isinstance(value, Exception):
                raise value
            return value

        async def notify(text):
            raise OSError("dm closed")

        async def sleep(seconds):
            if len(log) >= 3:
                raise StopLoop

        with patch('core.doc_watch.poll', poll):
            with pytest.raises(StopLoop):
                await bot.run_watcher(dw.WatchConfig(("standup",), 1), notify, sleep=sleep)
        assert log == ["Watch: poll failed (RuntimeError: boom)", "Watch: x",
                       "Watch: couldn't send a DM (OSError: dm closed)"]

    async def test_poll_waits_for_a_note_write_in_progress(self):
        bot = discord_bot.NoteBot(service=object(), allowed_users={1}, log=lambda line: None)
        order = []

        def poll(service, watch):
            order.append("poll")
            return dw.PollResult()

        async def sleep(seconds):
            raise StopLoop

        async def notify(text):
            pass

        with patch('core.doc_watch.poll', poll):
            async with bot._google_lock:  # a note write in progress
                task = asyncio.create_task(bot.run_watcher(dw.WatchConfig(("standup",)), notify, sleep=sleep))
                await asyncio.sleep(0.05)
                order.append("write done")
            with pytest.raises(StopLoop):
                await task
        assert order == ["write done", "poll"]
