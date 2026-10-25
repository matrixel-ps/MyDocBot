"""What the Discord bot does with a direct message (F10), with no discord import.

discord_bot.py is the thin adapter around the discord.py client; everything it
decides goes through here, so it can be tested without a network or a client.
The bot only writes: a DM from an allowed user becomes a note through
notes.submit_note(), exactly like one-shot capture in the CLI.
"""
import json
import os
import re
import stat

from . import config, notes, parser
from .paths import data_path

DISCORD_CONFIG_PATH = data_path('discord_config.json')
DISCORD_TOKEN_PATH = data_path('discord_token')
TOKEN_ENV = 'MYDOCBOT_DISCORD_TOKEN'

# "-d <alias> <note>" sends the note to another doc, like `mydocbot -d work "note"`.
_ALIAS_PREFIX = re.compile(r'-d\s+(\S+)(?:\s+(.*))?\Z', re.DOTALL)


class DiscordSetupError(Exception):
    """Missing or invalid bot token or allowlist; the message says what to fix."""


def load_token(env=None):
    """The bot token from $MYDOCBOT_DISCORD_TOKEN, else the discord_token file
    in the data directory. Returns (token, warning-or-None)."""
    env = os.environ if env is None else env
    if env.get(TOKEN_ENV, '').strip():
        return env[TOKEN_ENV].strip(), None
    try:
        with open(DISCORD_TOKEN_PATH) as f:
            token = f.read().strip()
    except FileNotFoundError:
        raise DiscordSetupError(
            f"No Discord bot token. Set ${TOKEN_ENV}, or save it in {DISCORD_TOKEN_PATH} "
            "(chmod 600).") from None
    if not token:
        raise DiscordSetupError(f"{DISCORD_TOKEN_PATH} is empty.")
    warning = None
    if stat.S_IMODE(os.stat(DISCORD_TOKEN_PATH).st_mode) & 0o077:
        warning = (f"Warning: {DISCORD_TOKEN_PATH} is readable by other users; "
                   f"run: chmod 600 {DISCORD_TOKEN_PATH}")
    return token, warning


def load_allowed_users():
    """The Discord user IDs the bot acts on, from discord_config.json
    ({"allowed_user_ids": ["123…"]}). IDs may be strings or numbers. An empty
    or missing list is an error: the bot would otherwise ignore everyone, and a
    typo in the key must not look like a working setup."""
    try:
        with open(DISCORD_CONFIG_PATH) as f:
            data = json.load(f)
    except FileNotFoundError:
        raise DiscordSetupError(
            f"No {DISCORD_CONFIG_PATH}. Create it with your Discord user ID: "
            '{"allowed_user_ids": ["<your user id>"]}') from None
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise DiscordSetupError(f"{DISCORD_CONFIG_PATH} is not valid JSON: {e}") from None
    ids = data.get("allowed_user_ids") if isinstance(data, dict) else None
    if not isinstance(ids, list) or not ids:
        raise DiscordSetupError(f'{DISCORD_CONFIG_PATH} needs a non-empty "allowed_user_ids" list.')
    try:
        return frozenset(int(i) for i in ids)
    except (TypeError, ValueError):
        raise DiscordSetupError(
            f'"allowed_user_ids" in {DISCORD_CONFIG_PATH} must be numeric Discord user IDs.') from None


def is_allowed(author_id, is_dm, allowed_users):
    """Act only on direct messages from allowed users. Anything else (server
    channels, strangers, the bot's own messages) is ignored without a reply,
    so nobody else can tell the bot writes anywhere."""
    return is_dm and author_id in allowed_users


def split_alias(text):
    """(alias or None, note text). Only a leading "-d <alias>" is special."""
    stripped = text.strip()
    match = _ALIAS_PREFIX.match(stripped)
    if match:
        return match.group(1), match.group(2) or ""
    return None, stripped


def _queued_reply(result):
    """Like the CLI's queued text, without pointing at /flush or /queue, which
    Discord doesn't have: queued notes go out before the next note sent from
    anywhere."""
    failure = result.failure
    if result.queued_behind:
        why = failure.message if failure else "still pending"
        head = f"Queued behind {result.queued_behind} earlier note(s) for this doc ({why})"
    elif failure and failure.kind != "transient":
        head = f"Not sent: {failure.message}. Queued"
    else:
        head = "Queued (offline or Google unavailable)"
    return f"{head}. {parser.count_pending()} pending; they're retried with your next note."


def write_note(service, text):
    """Write one DM as a note. Returns (status, reply): status is
    submit_note()'s "sent" / "queued" / "rejected", or "error" for a config
    problem; reply is the text to send back. The docs config is reloaded every
    time, so aliases added in the CLI or TUI work at once."""
    alias, note = split_alias(text)
    svc_config = config.load_config()
    aliases = svc_config.get("aliases", {})
    if not aliases:
        return "error", "No documents configured. Add one with: mydocbot --add <alias> <doc_id>"
    alias = alias or svc_config.get("default", "")
    if alias not in aliases:
        return "error", f"Alias '{alias}' not found. Available: {', '.join(aliases)}"

    result = notes.submit_note(service, aliases[alias], note)
    if result.status == "rejected":
        return "rejected", f"Note rejected: {result.reason}"
    if result.status == "queued":
        return "queued", _queued_reply(result)
    reply = f"Prepended to {alias} on {result.timestamp}"
    if result.flushed:
        reply += f" (flushed {len(result.flushed)} pending)"
    return "sent", reply
