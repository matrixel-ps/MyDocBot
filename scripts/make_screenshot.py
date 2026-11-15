"""Regenerate the README screenshot: python scripts/make_screenshot.py

Renders the read/write TUI headlessly (Textual's run_test) against a fake Docs
service holding made-up notes, and saves it as an SVG. Nothing touches Google
or your real data: when run as a script, MYDOCBOT_HOME points at a throwaway
directory before any MyDocBot module is imported.
"""
import asyncio
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "docs" / "images" / "tui.svg"
SIZE = (110, 30)  # terminal columns x rows
# The list labels the newest days "Today" / "Yesterday"; pin "now" so the
# image is the same whenever it's regenerated.
NOW = datetime(2026, 11, 14, 18, 0)

DOC_TITLE = "Work Journal"
# Newest first, as MyDocBot keeps the doc. Fixed past dates, so the image only
# changes when the UI does.
NOTES = [
    ("[11/14/26] (16:45)|", "Shipped the watch alerts: edits now show as a word diff. #release #discord"),
    ("[11/14/26] (11:20)|", "Retro: keep the Friday demo, drop the Monday status mail. #team"),
    ("[11/14/26] (09:05)|", "Standup: finishing the README, then the license. #standup"),
    ("[11/13/26] (17:30)|", "Read chapter 5 of the replication book; leader election notes in the wiki. #reading"),
    ("[11/13/26] (14:10)|", "Call with the vendor: invoice fixed, renewal moves to January. #vendor"),
    ("[11/12/26] (10:00)|", "Idea: tag autocomplete in the TUI. #idea"),
]


def doc_text():
    return "".join(f"{ts} {body}\n\n" for ts, body in NOTES)


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


class FakeDocs:
    """Just enough of the Docs service for the TUI to load a doc."""

    def documents(self):
        return self

    def get(self, documentId=None, fields=None):
        return self

    def batchUpdate(self, documentId=None, body=None):
        raise RuntimeError("the screenshot app never writes")

    def execute(self):
        return {"title": DOC_TITLE,
                "body": {"content": [{"paragraph": {"elements": [{"textRun": {"content": doc_text()}}]}}]}}


async def _render(out_path):
    from core import config
    from mydocbot_app import MyDocBotApp

    config.save_config({"default": "journal", "aliases": {"journal": "example-doc-id"}})
    with patch("mydocbot_app.google_docs.get_service", return_value=FakeDocs()):
        app = MyDocBotApp()
    app.title = "MyDocBot"  # the screenshot's window title (default: the class name)
    with patch("mydocbot_app.datetime", _FrozenDatetime):
        async with app.run_test(size=SIZE) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.pause()  # let the list rebuild select the newest note (B14)
            app.save_screenshot(filename=out_path.name, path=str(out_path.parent))


def make_screenshot(out_path=DEFAULT_OUT):
    """Write the SVG to out_path. The caller must already have pointed the data
    paths somewhere safe (main() does; tests use their isolation fixture)."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(_render(out_path))
    return out_path


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    with tempfile.TemporaryDirectory() as home:
        os.environ["MYDOCBOT_HOME"] = home  # before the first MyDocBot import
        sys.path.insert(0, str(ROOT))
        print(f"Wrote {make_screenshot(out)}")


if __name__ == "__main__":
    main()
