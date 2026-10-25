"""mydocbot-discord: DM a private Discord bot to write a note (F10).

Thin adapter around discord.py; the decisions live in core.discord_handler.
discord.py is an optional extra (pip install -e .[discord]), so it is only
imported in main(); NoteBot works with any object shaped like a message.
"""
import asyncio
import sys

from core import discord_handler, google_docs, paths


class NoteBot:
    """Turns allowed DMs into notes, one write at a time.

    submit_note() blocks (Google calls, retry waits), so it runs in a worker
    thread to keep the gateway connection alive. The Google client (httplib2)
    isn't thread-safe, so an asyncio lock lets only one write run at a time;
    later messages wait their turn in arrival order."""

    def __init__(self, service, allowed_users, log=print):
        self.service = service
        self.allowed_users = allowed_users
        self.log = log
        self._write_lock = asyncio.Lock()

    async def on_message(self, message):
        is_dm = message.guild is None
        author_id = message.author.id
        if not discord_handler.is_allowed(author_id, is_dm, self.allowed_users):
            if is_dm and not getattr(message.author, "bot", False):
                # Logged (never answered) so the owner can find their own ID.
                self.log(f"Ignored a DM from user {author_id} (not in allowed_user_ids).")
            return
        async with self._write_lock:
            try:
                status, reply = await asyncio.to_thread(discord_handler.write_note, self.service, message.content)
            except Exception as e:  # keep the bot alive and tell the sender
                status = f"error ({type(e).__name__}: {e})"
                reply = "Something went wrong; the note may not have been saved. Check the bot's log."
        self.log(f"Note from {author_id}: {status}")  # never the note text
        await message.reply(reply, mention_author=False)


def main():
    paths.prepare_data_dir()
    try:
        token, warning = discord_handler.load_token()
        allowed = discord_handler.load_allowed_users()
    except discord_handler.DiscordSetupError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    if warning:
        print(warning, file=sys.stderr)

    try:
        import discord
    except ImportError:
        print("discord.py isn't installed. Install the extra: pip install -e '.[discord]'", file=sys.stderr)
        return 1

    service = google_docs.get_service()
    bot = NoteBot(service, allowed, log=lambda line: print(line, flush=True))

    # Default intents include DMs. Message content of DMs to the bot arrives
    # without the privileged Message Content intent, so none is requested.
    client = discord.Client(intents=discord.Intents.default())

    @client.event
    async def on_ready():
        print(f"MyDocBot Discord bot online as {client.user}; "
              f"accepting DMs from {len(allowed)} user(s).", flush=True)

    @client.event
    async def on_message(message):
        if message.author == client.user:
            return
        await bot.on_message(message)

    try:
        client.run(token)  # discord.py logs connection events to stderr
    except discord.LoginFailure:
        print("Error: Discord rejected the bot token. Reset it in the Developer Portal "
              "and update it.", file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
