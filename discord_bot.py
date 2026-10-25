"""mydocbot-discord: DM a private Discord bot to write a note (F10), and get
a DM when a watched read-only doc changes (F11).

Thin adapter around discord.py; the decisions live in core.discord_handler
and core.doc_watch.
discord.py is an optional extra (pip install -e .[discord]), so it is only
imported in main(); NoteBot works with any object shaped like a message.
"""
import asyncio
import sys

from core import config, discord_handler, doc_watch, google_docs, paths


class NoteBot:
    """Turns allowed DMs into notes and runs the doc watcher, one Google call
    at a time.

    submit_note() and doc_watch.poll() block (Google calls, retry waits), so
    they run in a worker thread to keep the gateway connection alive. The
    Google client (httplib2) isn't thread-safe, so an asyncio lock lets only
    one of them run at a time; later work waits its turn in arrival order."""

    def __init__(self, service, allowed_users, log=print):
        self.service = service
        self.allowed_users = allowed_users
        self.log = log
        self._google_lock = asyncio.Lock()
        self.watcher_task = None  # kept so the task isn't garbage-collected

    async def on_message(self, message):
        is_dm = message.guild is None
        author_id = message.author.id
        if not discord_handler.is_allowed(author_id, is_dm, self.allowed_users):
            if is_dm and not getattr(message.author, "bot", False):
                # Logged (never answered) so the owner can find their own ID.
                self.log(f"Ignored a DM from user {author_id} (not in allowed_user_ids).")
            return
        async with self._google_lock:
            try:
                status, reply = await asyncio.to_thread(discord_handler.write_note, self.service, message.content)
            except Exception as e:  # keep the bot alive and tell the sender
                status = f"error ({type(e).__name__}: {e})"
                reply = "Something went wrong; the note may not have been saved. Check the bot's log."
        self.log(f"Note from {author_id}: {status}")  # never the note text
        await message.reply(reply, mention_author=False)

    async def run_watcher(self, watch, notify, sleep=asyncio.sleep):
        """Poll the watched docs forever, every watch.interval_minutes, and
        pass each change message to notify(). A failed poll or DM is logged and
        the loop carries on; doc_watch keeps per-doc errors from becoming
        changes."""
        while True:
            try:
                async with self._google_lock:
                    result = await asyncio.to_thread(doc_watch.poll, self.service, watch)
            except Exception as e:
                self.log(f"Watch: poll failed ({type(e).__name__}: {e})")
                result = doc_watch.PollResult()
            for line in result.logs:
                self.log(line)
            for message in result.messages:
                try:
                    await notify(message)
                except Exception as e:
                    self.log(f"Watch: couldn't send a DM ({type(e).__name__}: {e})")
            await sleep(watch.interval_minutes * 60)


def main():
    paths.prepare_data_dir()
    try:
        token, warning = discord_handler.load_token()
        discord_config = discord_handler.load_discord_config()
        allowed = discord_handler.load_allowed_users(discord_config)
        watch = doc_watch.parse_watch_config(discord_config, config.load_read_config())
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

    async def notify(text):
        for user_id in allowed:
            user = client.get_user(user_id) or await client.fetch_user(user_id)
            await user.send(text)

    async def start_watcher():
        await client.wait_until_ready()
        await bot.run_watcher(watch, notify)

    async def setup_hook():
        # Runs once per process, unlike on_ready, which repeats on reconnect.
        if watch:
            bot.watcher_task = asyncio.create_task(start_watcher())

    client.setup_hook = setup_hook

    @client.event
    async def on_ready():
        watching = (f"; watching {', '.join(watch.aliases)} every {watch.interval_minutes:g} min"
                    if watch else "")
        print(f"MyDocBot Discord bot online as {client.user}; "
              f"accepting DMs from {len(allowed)} user(s){watching}.", flush=True)

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
