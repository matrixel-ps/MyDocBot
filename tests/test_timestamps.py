"""Tests for core/timestamps.py, the one owner of the note timestamp format (A1)."""
import re
from datetime import date, datetime

import pytest

from core import timestamps as tsm


def test_format_parse_round_trip():
    now = datetime(2026, 10, 24, 9, 5)
    text = tsm.format_timestamp(now)
    assert text == "[10/24/26] (09:05)|"
    assert tsm.parse_timestamp(text) == now


def test_notes_and_core_still_export_format_helpers():
    import core
    from core import notes
    assert notes.format_timestamp is tsm.format_timestamp
    assert notes.TIMESTAMP_FORMAT == tsm.TIMESTAMP_FORMAT
    assert core.format_timestamp is tsm.format_timestamp


@pytest.mark.parametrize("bad", ["[13/40/26] (10:00)|", "[06/17/26} (10:00)|", "", "[06/17/26] (25:00)|", "06/17/26"])
def test_parse_timestamp_rejects(bad):
    with pytest.raises(ValueError):
        tsm.parse_timestamp(bad)


def test_parse_timestamp_ignores_trailing_text():
    assert tsm.parse_timestamp("[06/17/26] (14:30)| Meeting notes") == datetime(2026, 6, 17, 14, 30)


def test_date_key():
    assert tsm.date_key("[06/07/26] (14:30)|") == "06/07/26"


@pytest.mark.parametrize("flag,expected", [
    ("06/01/26", date(2026, 6, 1)),
    ("6/1/26", date(2026, 6, 1)),
    ("06/01/2026", date(2026, 6, 1)),   # A1: used to compare 2026 against 26
    ("12/31/2026", date(2026, 12, 31)),
])
def test_parse_date_flag(flag, expected):
    assert tsm.parse_date_flag(flag) == expected


@pytest.mark.parametrize("bad", ["not-a-date", "13/01/26", "06/01", ""])
def test_parse_date_flag_rejects(bad):
    with pytest.raises(ValueError):
        tsm.parse_date_flag(bad)


@pytest.mark.parametrize("text", [
    "[06/17/26] (14:30)|", "[06/17/26](14:30)|", "[06/17/26]   (14:30)|",
])
def test_header_pattern_matches_what_parse_entries_accepted(text):
    old = re.compile(r'(\[\d{2}/\d{2}/\d{2}\]\s*\(\d{2}:\d{2}\)\|)')
    assert re.match(tsm.HEADER_PATTERN, text).group(0) == old.match(text).group(1)
