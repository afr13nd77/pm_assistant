"""Unit tests for app.calendar_client module.

Covers: is_enabled, _ical_unescape, _tokenize, _assign_statuses,
_parse_event, _match_protocols, get_today_meetings, _CalendarCache.
"""

from __future__ import annotations

import importlib
import sys
import time as _time
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

# conftest.py stubs icalendar/caldav with MagicMock when they are not
# installed locally.  In our env they ARE installed, so we restore the
# real icalendar for _parse_event tests via monkeypatch (see fixture below).
try:
    _real_icalendar = importlib.import_module("icalendar.__init__")
except ImportError:
    # Fallback: load from the real package path
    _real_icalendar = None

# Force-load the real icalendar
_saved = sys.modules.get("icalendar")
if isinstance(_saved, MagicMock):
    sys.modules.pop("icalendar", None)
    # Remove submodules too
    for k in list(sys.modules):
        if k.startswith("icalendar"):
            sys.modules.pop(k, None)
    import icalendar as _real_icalendar  # noqa: E402

    # Restore stub so other tests don't break
    sys.modules["icalendar"] = _saved
else:
    import icalendar as _real_icalendar  # noqa: E402

from app.calendar_client import (  # noqa: E402, I001
    _CalendarCache,
    _assign_statuses,
    _ical_unescape,
    _match_protocols,
    _parse_event,
    _tokenize,
    get_today_meetings,
    is_enabled,
)

TZ = ZoneInfo("Europe/Moscow")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockEvent:
    """Minimal caldav event wrapper with `.data` attribute."""

    def __init__(self, data: str) -> None:
        self.data = data


def _make_ical(
    uid: str = "test-uid-001",
    summary: str = "Daily standup",
    dtstart: str = "20260722T093000Z",
    dtend: str = "20260722T100000Z",
    location: str = "",
    organizer: str = "",
    description: str = "",
    attendees: list[str] | None = None,
    all_day: bool = False,
    skip_dtstart: bool = False,
) -> str:
    """Build a minimal VCALENDAR string for testing."""
    lines = ["BEGIN:VCALENDAR", "BEGIN:VEVENT"]
    if not skip_dtstart:
        if all_day:
            lines.append(f"DTSTART;VALUE=DATE:{dtstart}")
        else:
            lines.append(f"DTSTART:{dtstart}")
    if dtend:
        if all_day:
            lines.append(f"DTEND;VALUE=DATE:{dtend}")
        else:
            lines.append(f"DTEND:{dtend}")
    lines.append(f"SUMMARY:{summary}")
    lines.append(f"UID:{uid}")
    if location:
        lines.append(f"LOCATION:{location}")
    if organizer:
        lines.append(f"ORGANIZER;CN={organizer}:mailto:org@example.com")
    if description:
        lines.append(f"DESCRIPTION:{description}")
    if attendees:
        for a in attendees:
            lines.append(f"ATTENDEE:mailto:{a}")
    lines.extend(["END:VEVENT", "END:VCALENDAR"])
    return "\n".join(lines)


# ===================================================================
# 1. TestIsEnabled
# ===================================================================


class TestIsEnabled:
    """Tests for is_enabled()."""

    def test_enabled_with_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Both username and password non-empty -> True."""
        monkeypatch.setattr("app.calendar_client._USERNAME", "user@yandex.ru")
        monkeypatch.setattr("app.calendar_client._PASSWORD", "app-password-123")
        assert is_enabled() is True

    def test_disabled_empty_username(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty username -> False."""
        monkeypatch.setattr("app.calendar_client._USERNAME", "")
        monkeypatch.setattr("app.calendar_client._PASSWORD", "app-password-123")
        assert is_enabled() is False

    def test_disabled_empty_password(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty password -> False."""
        monkeypatch.setattr("app.calendar_client._USERNAME", "user@yandex.ru")
        monkeypatch.setattr("app.calendar_client._PASSWORD", "")
        assert is_enabled() is False


# ===================================================================
# 2. TestIcalUnescape
# ===================================================================


class TestIcalUnescape:
    """Tests for _ical_unescape()."""

    def test_unescape_comma(self) -> None:
        assert _ical_unescape("hello\\,world") == "hello,world"

    def test_unescape_semicolon(self) -> None:
        assert _ical_unescape("hello\\;world") == "hello;world"

    def test_unescape_newline(self) -> None:
        assert _ical_unescape("line1\\nline2") == "line1\nline2"

    def test_unescape_newline_uppercase(self) -> None:
        assert _ical_unescape("line1\\Nline2") == "line1\nline2"

    def test_unescape_empty(self) -> None:
        assert _ical_unescape("") == ""

    def test_unescape_no_escapes(self) -> None:
        assert _ical_unescape("plain text") == "plain text"


# ===================================================================
# 3. TestTokenize
# ===================================================================


class TestTokenize:
    """Tests for _tokenize()."""

    def test_basic_tokenize(self) -> None:
        result = _tokenize("Daily standup meeting")
        assert result == {"daily", "standup", "meeting"}

    def test_short_words_filtered(self) -> None:
        """Words with <= 3 chars are excluded."""
        result = _tokenize("The big red fox")
        # "the" (3), "big" (3), "red" (3) -> filtered; "fox" (3) -> also filtered
        # len > 3, so 3-char words are excluded too
        assert "the" not in result
        assert "big" not in result
        assert "red" not in result
        # "fox" has exactly 3 chars -> also excluded (> 3, not >= 3)
        assert result == set()

    def test_short_words_filtered_with_long(self) -> None:
        """Mix of short and long words."""
        result = _tokenize("The very big meeting")
        assert result == {"very", "meeting"}

    def test_cyrillic(self) -> None:
        result = _tokenize("Планирование релиза")
        assert result == {"планирование", "релиза"}

    def test_empty_string(self) -> None:
        result = _tokenize("")
        assert result == set()


# ===================================================================
# 4. TestAssignStatuses
# ===================================================================


class TestAssignStatuses:
    """Tests for _assign_statuses()."""

    def _make_meeting(self, start: str, end: str) -> dict:
        return {
            "start": start,
            "end": end,
            "status": "upcoming",
            "title": "Test",
        }

    def test_done(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Meeting with end < now -> status='done'."""
        meetings = [self._make_meeting("08:00", "09:00")]
        with patch("app.calendar_client.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.strftime.return_value = "10:00"
            mock_dt.now.return_value = mock_now
            _assign_statuses(meetings, TZ)
        assert meetings[0]["status"] == "done"

    def test_in_progress(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """start <= now <= end -> status='in_progress'."""
        meetings = [self._make_meeting("09:00", "11:00")]
        with patch("app.calendar_client.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.strftime.return_value = "10:00"
            mock_dt.now.return_value = mock_now
            _assign_statuses(meetings, TZ)
        assert meetings[0]["status"] == "in_progress"

    def test_next(self) -> None:
        """First future meeting -> status='next'."""
        meetings = [self._make_meeting("14:00", "15:00")]
        with patch("app.calendar_client.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.strftime.return_value = "10:00"
            mock_dt.now.return_value = mock_now
            _assign_statuses(meetings, TZ)
        assert meetings[0]["status"] == "next"

    def test_upcoming(self) -> None:
        """Second+ future meeting -> status='upcoming'."""
        meetings = [
            self._make_meeting("14:00", "15:00"),
            self._make_meeting("16:00", "17:00"),
        ]
        with patch("app.calendar_client.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.strftime.return_value = "10:00"
            mock_dt.now.return_value = mock_now
            _assign_statuses(meetings, TZ)
        assert meetings[0]["status"] == "next"
        assert meetings[1]["status"] == "upcoming"

    def test_mixed(self) -> None:
        """4 meetings covering all statuses: done, in_progress, next, upcoming."""
        meetings = [
            self._make_meeting("07:00", "08:00"),  # done
            self._make_meeting("09:00", "11:00"),  # in_progress
            self._make_meeting("14:00", "15:00"),  # next
            self._make_meeting("16:00", "17:00"),  # upcoming
        ]
        with patch("app.calendar_client.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.strftime.return_value = "10:00"
            mock_dt.now.return_value = mock_now
            _assign_statuses(meetings, TZ)
        assert meetings[0]["status"] == "done"
        assert meetings[1]["status"] == "in_progress"
        assert meetings[2]["status"] == "next"
        assert meetings[3]["status"] == "upcoming"


# ===================================================================
# 5. TestParseEvent
# ===================================================================


class TestParseEvent:
    """Tests for _parse_event().

    Uses autouse fixture to replace the MagicMock icalendar stub
    with the real icalendar module inside app.calendar_client.
    """

    @pytest.fixture(autouse=True)
    def _use_real_icalendar(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("app.calendar_client.icalendar", _real_icalendar)

    def test_regular_event(self) -> None:
        """Valid VEVENT with all fields -> returns complete dict."""
        ical = _make_ical(
            uid="uid-42",
            summary="Daily standup",
            dtstart="20260722T093000Z",
            dtend="20260722T100000Z",
            location="Room 42",
            organizer="John Doe",
            description="Team sync",
            attendees=["alice@example.com", "bob@example.com"],
        )
        event = MockEvent(ical)
        result = _parse_event(event, TZ)

        assert result is not None
        assert result["uid"] == "uid-42"
        assert result["title"] == "Daily standup"
        assert result["duration_minutes"] == 30
        assert result["location"] == "Room 42"
        assert result["organizer"] == "John Doe"
        assert result["attendees_count"] == 2
        assert result["description"] == "Team sync"
        assert result["is_all_day"] is False
        # start/end are time strings in Moscow timezone (UTC+3)
        assert result["start"] == "12:30"  # 09:30 UTC = 12:30 Moscow
        assert result["end"] == "13:00"  # 10:00 UTC = 13:00 Moscow

    def test_all_day_event(self) -> None:
        """All-day event (date, not datetime) -> is_all_day=True, 00:00-23:59."""
        ical = _make_ical(
            uid="uid-allday",
            summary="Conference",
            dtstart="20260722",
            dtend="20260723",
            all_day=True,
        )
        event = MockEvent(ical)
        result = _parse_event(event, TZ)

        assert result is not None
        assert result["is_all_day"] is True
        assert result["start"] == "00:00"
        assert result["end"] == "23:59"

    def test_missing_dtstart(self) -> None:
        """Event without DTSTART -> returns None."""
        ical = _make_ical(skip_dtstart=True)
        event = MockEvent(ical)
        result = _parse_event(event, TZ)

        assert result is None

    def test_no_attendees(self) -> None:
        """Event with no ATTENDEE -> attendees_count=0."""
        ical = _make_ical(attendees=None)
        event = MockEvent(ical)
        result = _parse_event(event, TZ)

        assert result is not None
        assert result["attendees_count"] == 0

    def test_invalid_ical_data(self) -> None:
        """Broken iCal data -> returns None."""
        event = MockEvent("NOT VALID ICAL DATA")
        result = _parse_event(event, TZ)
        assert result is None

    def test_description_truncated(self) -> None:
        """Description longer than 2000 chars is truncated."""
        long_desc = "A" * 3000
        ical = _make_ical(description=long_desc)
        event = MockEvent(ical)
        result = _parse_event(event, TZ)

        assert result is not None
        assert len(result["description"]) == 2000


# ===================================================================
# 6. TestMatchProtocols
# ===================================================================


class TestMatchProtocols:
    """Tests for _match_protocols()."""

    def test_match_found(self, tmp_path: Path) -> None:
        """Protocol file with matching date and title tokens -> has_protocol=True."""
        today = date(2026, 7, 22)
        protocol_file = tmp_path / "2026-07-22-supplier-daily.md"
        protocol_file.write_text("# Supplier Daily Protocol", encoding="utf-8")

        meetings = [
            {
                "title": "Supplier Daily Meeting",
                "has_protocol": False,
                "protocol_filename": None,
            }
        ]

        with patch("app.calendar_client.wiki_meetings", return_value=tmp_path):
            _match_protocols(meetings, today)

        assert meetings[0]["has_protocol"] is True
        assert meetings[0]["protocol_filename"] == "2026-07-22-supplier-daily.md"

    def test_no_match(self, tmp_path: Path) -> None:
        """Empty directory -> has_protocol=False."""
        today = date(2026, 7, 22)
        meetings = [
            {
                "title": "Supplier Daily Meeting",
                "has_protocol": False,
                "protocol_filename": None,
            }
        ]

        with patch("app.calendar_client.wiki_meetings", return_value=tmp_path):
            _match_protocols(meetings, today)

        assert meetings[0]["has_protocol"] is False
        assert meetings[0]["protocol_filename"] is None

    def test_partial_match(self, tmp_path: Path) -> None:
        """Token overlap score >= 0.3 -> match found."""
        today = date(2026, 7, 22)
        # Title: "Weekly supplier review session" -> tokens: weekly, supplier, review, session (4)
        # File stem: "2026-07-22-supplier-notes" -> tokens: supplier, notes (2)
        # intersection: {supplier} -> score = 1/4 = 0.25 ... need higher
        # Let's make a better example:
        # Title: "Supplier daily" -> tokens: supplier, daily (2)
        # File: "2026-07-22-daily-notes.md" -> tokens: daily, notes (2)
        # intersection: {daily} -> score = 1/2 = 0.5 >= 0.3 -> match
        protocol_file = tmp_path / "2026-07-22-daily-notes.md"
        protocol_file.write_text("# Notes", encoding="utf-8")

        meetings = [
            {
                "title": "Supplier daily",
                "has_protocol": False,
                "protocol_filename": None,
            }
        ]

        with patch("app.calendar_client.wiki_meetings", return_value=tmp_path):
            _match_protocols(meetings, today)

        assert meetings[0]["has_protocol"] is True

    def test_wrong_date_no_match(self, tmp_path: Path) -> None:
        """Protocol file exists but for different date -> no match."""
        today = date(2026, 7, 22)
        protocol_file = tmp_path / "2026-07-21-supplier-daily.md"
        protocol_file.write_text("# Old protocol", encoding="utf-8")

        meetings = [
            {
                "title": "Supplier Daily Meeting",
                "has_protocol": False,
                "protocol_filename": None,
            }
        ]

        with patch("app.calendar_client.wiki_meetings", return_value=tmp_path):
            _match_protocols(meetings, today)

        assert meetings[0]["has_protocol"] is False


# ===================================================================
# 7. TestGetTodayMeetings
# ===================================================================


class TestGetTodayMeetings:
    """Tests for get_today_meetings()."""

    def test_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When credentials are empty -> returns empty list."""
        monkeypatch.setattr("app.calendar_client._USERNAME", "")
        monkeypatch.setattr("app.calendar_client._PASSWORD", "")
        result = get_today_meetings()
        assert result == []

    def test_caldav_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CalDAV connection error -> returns empty list (graceful degradation)."""
        monkeypatch.setattr("app.calendar_client._USERNAME", "user@yandex.ru")
        monkeypatch.setattr("app.calendar_client._PASSWORD", "password")
        # Invalidate cache so we actually try to connect
        from app.calendar_client import _calendar_cache

        _calendar_cache.invalidate()

        with patch("app.calendar_client.caldav.DAVClient") as mock_client:
            mock_client.return_value.principal.side_effect = Exception(
                "Connection refused"
            )
            result = get_today_meetings()

        assert result == []

    def test_cache_hit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Second call returns cached data, no CalDAV call."""
        monkeypatch.setattr("app.calendar_client._USERNAME", "user@yandex.ru")
        monkeypatch.setattr("app.calendar_client._PASSWORD", "password")

        from app.calendar_client import _calendar_cache

        cached_meetings = [{"title": "Cached meeting", "start": "10:00"}]
        _calendar_cache.set("meetings", cached_meetings)

        # Should NOT touch CalDAV at all
        with patch("app.calendar_client.caldav.DAVClient") as mock_client:
            result = get_today_meetings()
            mock_client.assert_not_called()

        assert result == cached_meetings

        # Cleanup
        _calendar_cache.invalidate()

    def test_successful_fetch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Successful CalDAV fetch returns parsed meetings."""
        monkeypatch.setattr("app.calendar_client._USERNAME", "user@yandex.ru")
        monkeypatch.setattr("app.calendar_client._PASSWORD", "password")
        monkeypatch.setattr("app.calendar_client._TIMEZONE_NAME", "Europe/Moscow")
        # Restore real icalendar so _parse_event works inside get_today_meetings
        monkeypatch.setattr("app.calendar_client.icalendar", _real_icalendar)

        from app.calendar_client import _calendar_cache

        _calendar_cache.invalidate()

        ical_data = _make_ical(
            uid="uid-fetch",
            summary="Standup",
            dtstart="20260722T060000Z",
            dtend="20260722T063000Z",
        )

        mock_event = MockEvent(ical_data)
        mock_calendar = MagicMock()
        mock_calendar.name = "Work"
        mock_calendar.date_search.return_value = [mock_event]

        with (
            patch("app.calendar_client.caldav.DAVClient") as mock_client,
            patch("app.calendar_client.wiki_meetings") as mock_wiki,
        ):
            # Setup CalDAV mock chain
            mock_principal = MagicMock()
            mock_principal.calendars.return_value = [mock_calendar]
            mock_client.return_value.principal.return_value = mock_principal

            # wiki_meetings for _match_protocols
            mock_wiki_path = MagicMock()
            mock_wiki_path.exists.return_value = True
            mock_wiki_path.iterdir.return_value = []
            mock_wiki.return_value = mock_wiki_path

            result = get_today_meetings()

        assert len(result) == 1
        assert result[0]["uid"] == "uid-fetch"
        assert result[0]["title"] == "Standup"

        # Cleanup
        _calendar_cache.invalidate()


# ===================================================================
# 8. TestCalendarCache
# ===================================================================


class TestCalendarCache:
    """Tests for _CalendarCache."""

    def test_set_and_get(self) -> None:
        """set -> get returns the stored value."""
        cache = _CalendarCache(ttl_seconds=60.0)
        cache.set("key1", {"data": 42})
        assert cache.get("key1") == {"data": 42}

    def test_get_missing_key(self) -> None:
        """get on non-existent key -> None."""
        cache = _CalendarCache(ttl_seconds=60.0)
        assert cache.get("no-such-key") is None

    def test_expired(self) -> None:
        """After TTL expires, get returns None."""
        cache = _CalendarCache(ttl_seconds=0.01)
        cache.set("key1", "value")
        _time.sleep(0.03)
        assert cache.get("key1") is None

    def test_invalidate(self) -> None:
        """invalidate() clears all entries."""
        cache = _CalendarCache(ttl_seconds=60.0)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.invalidate()
        assert cache.get("key1") is None
        assert cache.get("key2") is None

    def test_invalidate_with_prefix(self) -> None:
        """invalidate(prefix) removes only matching keys."""
        cache = _CalendarCache(ttl_seconds=60.0)
        cache.set("meetings:today", "data1")
        cache.set("meetings:tomorrow", "data2")
        cache.set("other:key", "data3")
        cache.invalidate("meetings:")
        assert cache.get("meetings:today") is None
        assert cache.get("meetings:tomorrow") is None
        assert cache.get("other:key") == "data3"

    def test_overwrite(self) -> None:
        """Setting same key again overwrites the value and resets TTL."""
        cache = _CalendarCache(ttl_seconds=60.0)
        cache.set("key1", "old")
        cache.set("key1", "new")
        assert cache.get("key1") == "new"
