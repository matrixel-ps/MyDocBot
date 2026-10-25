"""Discord bot (F10): the message logic in core.discord_handler and the NoteBot
adapter in discord_bot.py. No network and no discord.py needed: messages are
plain fakes and the Google service is RecordingService."""
import asyncio
import json
import os
import sys
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from conftest import RecordingService

import core.config as cfg
import core.parser as prs
import discord_bot
from core import discord_handler as dh

OWNER = 111111111111111111
STRANGER = 222222222222222222


@pytest.fixture
def docs(tmp_config_path, tmp_pending_path, tmp_tags_index_path, sample_config):
    """A docs config (default "log" -> doc_id_123, "work" -> doc_id_456) and
    temp queue/index files, so real submit_note() calls stay in tmp."""
    cfg.save_config(sample_config)
    return sample_config


@pytest.fixture
def data_dir(_isolate_data_dir):
    _isolate_data_dir.mkdir(exist_ok=True)
    return _isolate_data_dir


class TestSplitAlias:
    @pytest.mark.parametrize("text,expected", [
        ("met with Sam #standup", (None, "met with Sam #standup")),
        ("  padded  ", (None, "padded")),
        ("-d work met with Sam", ("work", "met with Sam")),
        ("-d work line one\nline two", ("work", "line one\nline two")),
        ("-d work", ("work", "")),
        ("note with -d work inside", (None, "note with -d work inside")),
        ("-dwork no space", (None, "-dwork no space")),
    ])
    def test_cases(self, text, expected):
        assert dh.split_alias(text) == expected


class TestIsAllowed:
    def test_dm_from_allowed_user(self):
        assert dh.is_allowed(OWNER, True, {OWNER})

    def test_server_channel_message_is_ignored_even_from_owner(self):
        assert not dh.is_allowed(OWNER, False, {OWNER})

    def test_dm_from_stranger_is_ignored(self):
        assert not dh.is_allowed(STRANGER, True, {OWNER})


class TestLoadToken:
    def test_env_wins(self, data_dir):
        (data_dir / "discord_token").write_text("from-file")
        assert dh.load_token({dh.TOKEN_ENV: " from-env \n"}) == ("from-env", None)

    def test_file_when_env_unset(self, data_dir):
        path = data_dir / "discord_token"
        path.write_text("from-file\n")
        os.chmod(path, 0o600)
        assert dh.load_token({}) == ("from-file", None)

    def test_world_readable_file_warns(self, data_dir):
        path = data_dir / "discord_token"
        path.write_text("t")
        os.chmod(path, 0o644)
        token, warning = dh.load_token({})
        assert token == "t"
        assert warning and "chmod 600" in warning

    def test_missing(self, data_dir):
        with pytest.raises(dh.DiscordSetupError, match="No Discord bot token"):
            dh.load_token({})

    def test_empty_file(self, data_dir):
        (data_dir / "discord_token").write_text("\n")
        with pytest.raises(dh.DiscordSetupError, match="empty"):
            dh.load_token({})


class TestLoadAllowedUsers:
    def _write(self, data_dir, content):
        (data_dir / "discord_config.json").write_text(content)

    def test_strings_and_numbers_become_ints(self, data_dir):
        self._write(data_dir, json.dumps({"allowed_user_ids": [str(OWNER), 42]}))
        assert dh.load_allowed_users() == frozenset({OWNER, 42})

    def test_missing_file(self, data_dir):
        with pytest.raises(dh.DiscordSetupError, match="allowed_user_ids"):
            dh.load_allowed_users()

    @pytest.mark.parametrize("content", [
        '{"allowed_user_ids": []}',
        '{"allowed_users": ["1"]}',  # typo'd key must not look like a working setup
        '["1"]',
    ])
    def test_empty_or_wrong_shape_refuses(self, data_dir, content):
        self._write(data_dir, content)
        with pytest.raises(dh.DiscordSetupError, match="non-empty"):
            dh.load_allowed_users()

    def test_non_numeric_id(self, data_dir):
        self._write(data_dir, '{"allowed_user_ids": ["matias"]}')
        with pytest.raises(dh.DiscordSetupError, match="numeric"):
            dh.load_allowed_users()

    def test_invalid_json(self, data_dir):
        self._write(data_dir, "{nope")
        with pytest.raises(dh.DiscordSetupError, match="not valid JSON"):
            dh.load_allowed_users()


class TestWriteNote:
    def test_plain_message_goes_to_default_doc(self, docs):
        service = RecordingService()
        status, reply = dh.write_note(service, "met with Sam #standup")
        assert status == "sent"
        assert reply.startswith("Prepended to log on ")
        [(doc_id, text)] = service.calls
        assert doc_id == "doc_id_123" and text.endswith(" met with Sam #standup")
        assert "standup" in prs.load_tags_index()

    def test_alias_prefix_picks_the_doc(self, docs):
        service = RecordingService()
        status, reply = dh.write_note(service, "-d work shipped it")
        assert status == "sent" and reply.startswith("Prepended to work on ")
        assert service.calls[0][0] == "doc_id_456"
        assert service.calls[0][1].endswith(" shipped it")

    def test_unknown_alias_writes_nothing(self, docs):
        service = RecordingService()
        status, reply = dh.write_note(service, "-d nope hello")
        assert status == "error"
        assert reply == "Alias 'nope' not found. Available: log, work, personal"
        assert service.calls == [] and prs.count_pending() == 0

    def test_no_docs_configured(self, tmp_config_path):
        cfg.save_config({"default": "", "aliases": {}})
        status, reply = dh.write_note(RecordingService(), "hello")
        assert status == "error" and "mydocbot --add" in reply

    @pytest.mark.parametrize("text", ["   ", "-d work"])
    def test_empty_note_is_rejected(self, docs, text):
        service = RecordingService()
        assert dh.write_note(service, text) == ("rejected", "Note rejected: Note cannot be empty")
        assert service.calls == []

    def test_offline_note_is_queued_without_cli_only_hints(self, docs, monkeypatch):
        monkeypatch.setattr('core.google_docs.time.sleep', lambda s: None)
        status, reply = dh.write_note(RecordingService(failing={"doc_id_123"}), "offline thought")
        assert status == "queued"
        assert "1 pending" in reply and "retried with your next note" in reply
        assert "/flush" not in reply and "/queue" not in reply
        assert [e["text"] for e in prs.load_pending_notes()] == ["offline thought"]

    def test_aliases_added_elsewhere_are_seen_without_restart(self, docs):
        cfg.save_config({**docs, "aliases": {**docs["aliases"], "new": "doc_id_new"}})
        status, _ = dh.write_note(RecordingService(), "-d new hi")
        assert status == "sent"


class FakeMessage:
    def __init__(self, content, author_id=OWNER, dm=True, bot=False):
        self.content = content
        self.author = SimpleNamespace(id=author_id, bot=bot)
        self.guild = None if dm else SimpleNamespace(id=1)
        self.replies = []

    async def reply(self, text, mention_author=True):
        assert mention_author is False
        self.replies.append(text)


def _bot(log=None):
    return discord_bot.NoteBot(service=object(), allowed_users={OWNER},
                               log=(log.append if log is not None else lambda line: None))


class TestNoteBot:
    async def test_allowed_dm_is_written_off_the_event_loop_and_answered(self):
        loop_thread = threading.get_ident()
        seen = {}

        def fake_write(service, text):
            seen["thread"], seen["text"] = threading.get_ident(), text
            return "sent", "Prepended to log on [10/25/26] (14:31)|"

        log = []
        message = FakeMessage("hello")
        with patch('core.discord_handler.write_note', fake_write):
            await _bot(log).on_message(message)
        assert seen["text"] == "hello"
        assert seen["thread"] != loop_thread
        assert message.replies == ["Prepended to log on [10/25/26] (14:31)|"]
        assert log == [f"Note from {OWNER}: sent"]  # status only, never the note text

    async def test_stranger_dm_gets_no_reply_but_is_logged_with_their_id(self):
        log = []
        message = FakeMessage("hello", author_id=STRANGER)
        with patch('core.discord_handler.write_note') as write:
            await _bot(log).on_message(message)
        write.assert_not_called()
        assert message.replies == []
        assert log == [f"Ignored a DM from user {STRANGER} (not in allowed_user_ids)."]

    async def test_server_channel_message_is_silently_ignored(self):
        log = []
        message = FakeMessage("hello", dm=False)
        with patch('core.discord_handler.write_note') as write:
            await _bot(log).on_message(message)
        write.assert_not_called()
        assert message.replies == [] and log == []

    async def test_other_bots_are_not_logged(self):
        log = []
        await _bot(log).on_message(FakeMessage("hi", author_id=STRANGER, bot=True))
        assert log == []

    async def test_unexpected_error_still_gets_a_reply(self):
        message = FakeMessage("hello")
        with patch('core.discord_handler.write_note', side_effect=RuntimeError("boom")):
            await _bot().on_message(message)
        assert message.replies == ["Something went wrong; the note may not have been saved. Check the bot's log."]

    async def test_writes_run_one_at_a_time_in_arrival_order(self):
        active, peak, order = 0, 0, []
        guard = threading.Lock()

        def slow_write(service, text):
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
            threading.Event().wait(0.05)
            order.append(text)
            with guard:
                active -= 1
            return "sent", "ok"

        bot = _bot()
        with patch('core.discord_handler.write_note', slow_write):
            await asyncio.gather(*(bot.on_message(FakeMessage(f"n{i}")) for i in range(3)))
        assert peak == 1
        assert order == ["n0", "n1", "n2"]


class TestMain:
    def test_missing_setup_exits_1_before_needing_discord(self, monkeypatch, capsys):
        monkeypatch.delenv(dh.TOKEN_ENV, raising=False)
        assert discord_bot.main() == 1
        assert "No Discord bot token" in capsys.readouterr().err

    def test_missing_discord_py_exits_1(self, data_dir, monkeypatch, capsys):
        monkeypatch.setenv(dh.TOKEN_ENV, "t")
        (data_dir / "discord_config.json").write_text(json.dumps({"allowed_user_ids": [OWNER]}))
        monkeypatch.setitem(sys.modules, "discord", None)  # makes `import discord` raise ImportError
        with patch('discord_bot.google_docs.get_service') as get_service:
            assert discord_bot.main() == 1
        get_service.assert_not_called()
        assert "pip install -e '.[discord]'" in capsys.readouterr().err

    def test_watch_alias_typo_exits_1_at_startup(self, data_dir, tmp_read_config_path, monkeypatch, capsys):
        monkeypatch.setenv(dh.TOKEN_ENV, "t")
        cfg.save_read_config({"default": "standup", "aliases": {"standup": "doc_s"}})
        (data_dir / "discord_config.json").write_text(
            json.dumps({"allowed_user_ids": [OWNER], "watch": {"aliases": ["standpu"]}}))
        with patch('discord_bot.google_docs.get_service') as get_service:
            assert discord_bot.main() == 1
        get_service.assert_not_called()
        assert "not in read_config.json: standpu" in capsys.readouterr().err
