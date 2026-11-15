"""The README screenshot generator (scripts/make_screenshot.py) still runs.

It renders the read/write TUI headlessly against a fake Docs service; the
autouse isolation fixture keeps its config write in tmp_path."""
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "make_screenshot.py"


def _load():
    spec = importlib.util.spec_from_file_location("make_screenshot", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_writes_an_svg_of_the_tui_with_the_made_up_notes(tmp_path, _isolate_data_dir):
    _isolate_data_dir.mkdir()  # the isolated data dir starts uncreated
    shot = _load()
    out = shot.make_screenshot(tmp_path / "tui.svg")
    svg = out.read_text()
    assert svg.startswith("<svg")
    assert "Work&#160;Journal" in svg  # Textual writes spaces as &#160;
    assert "Today" in svg and "Yesterday" in svg  # "now" is pinned, so the labels don't drift


def test_fake_service_never_writes():
    shot = _load()
    try:
        shot.FakeDocs().batchUpdate(documentId="x", body={})
    except RuntimeError:
        return
    raise AssertionError("FakeDocs.batchUpdate should refuse")
