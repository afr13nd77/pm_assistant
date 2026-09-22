"""
calendar_client.py -- CalDAV client for Yandex Calendar with in-memory caching.

Provides meeting data for the TODAY page. Connects to Yandex Calendar via
CalDAV protocol, parses VEVENT components, determines meeting statuses,
and cross-references with vault meeting protocols.

Public API:
    is_enabled()         -> bool
    get_today_meetings() -> list[dict]
"""

import logging
import os
import re
import time as _time
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import caldav
import icalendar

from shared.vault_paths import wiki_meetings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------

_USERNAME = os.getenv("YANDEX_CALENDAR_USERNAME", "")
_PASSWORD = os.getenv("YANDEX_CALENDAR_APP_PASSWORD", "")
_TIMEZONE_NAME = os.getenv("YANDEX_CALENDAR_TIMEZONE", "Europe/Moscow")


def _get_credentials() -> tuple[str, str, str, str]:
    """Read CalDAV credentials: user-prefs (priority) -> env vars (fallback).

    Returns (username, password, timezone_name, caldav_url).
    """
    logger.info("_get_credentials -- reading user-prefs")
    try:
        from app.routers.user_prefs import _read_user_prefs
        prefs = _read_user_prefs()
        username = prefs.get("caldav_username", "")
        password = prefs.get("caldav_password", "")
        tz = prefs.get("caldav_timezone", "")
        url = prefs.get("caldav_url", "")
        if username and password:
            logger.info("_get_credentials -- using user-prefs credentials, username=%s", username)
            return (
                username,
                password,
                tz or _TIMEZONE_NAME,
                url or "https://caldav.yandex.ru/",
            )
    except Exception as exc:
        logger.error(f"_get_credentials -- failed to read user-prefs: {exc}")
    logger.info("_get_credentials -- falling back to env variables")
    return (_USERNAME, _PASSWORD, _TIMEZONE_NAME, "https://caldav.yandex.ru/")


# ---------------------------------------------------------------------------
# Public: is_enabled
# ---------------------------------------------------------------------------


def is_enabled() -> bool:
    """Return True if CalDAV credentials are configured (non-empty)."""
    username, password, _, _ = _get_credentials()
    return bool(username) and bool(password)


# ---------------------------------------------------------------------------
# In-memory TTL cache (separate from vault cache, TTL 600s)
# ---------------------------------------------------------------------------


class _CalendarCache:
    """Simple TTL cache for CalDAV results.

    Pattern copied from _VaultCache in vault_api.py with a longer TTL
    (600s) to respect Yandex CalDAV rate-limiting.
    """

    def __init__(self, ttl_seconds: float = 600.0):
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        ts, value = entry
        if (_time.time() - ts) > self._ttl:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (_time.time(), value)

    def invalidate(self, prefix: str = "") -> None:
        if not prefix:
            self._store.clear()
        else:
            keys_to_del = [k for k in self._store if k.startswith(prefix)]
            for k in keys_to_del:
                del self._store[k]


_calendar_cache = _CalendarCache(ttl_seconds=600.0)


# ---------------------------------------------------------------------------
# iCalendar text helpers
# ---------------------------------------------------------------------------


def _ical_unescape(s: str) -> str:
    """Unescape iCalendar TEXT property values (RFC 5545 sec 3.3.11)."""
    if not s:
        return ""
    return (
        s.replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\n", "\n")
        .replace("\\N", "\n")
    )


# ---------------------------------------------------------------------------
# VEVENT parsing
# ---------------------------------------------------------------------------


_URL_RE = re.compile(r'https?://\S+')


def _extract_conference_url(component: Any, location: str, description: str) -> str:
    """Extract conference URL from iCal event.

    Priority: URL property > location (if URL) > first URL in description.
    """
    url_prop = component.get("URL")
    if url_prop:
        url = str(url_prop).strip()
        if url.startswith("http"):
            logger.debug("_extract_conference_url -- from URL property: %s", url)
            return url

    if location and _URL_RE.match(location.strip()):
        logger.debug("_extract_conference_url -- from location: %s", location.strip())
        return location.strip()

    if description:
        match = _URL_RE.search(description)
        if match:
            logger.debug("_extract_conference_url -- from description: %s", match.group())
            return match.group()

    return ""


def _parse_event(event: Any, tz: ZoneInfo) -> dict | None:
    """Parse a single caldav event object into a meeting dict.

    Returns None if parsing fails.
    """
    try:
        cal = icalendar.Calendar.from_ical(event.data)
    except Exception as exc:
        logger.error(f"_parse_event -- failed to parse iCal data: {exc}")
        return None

    for component in cal.walk():
        if component.name != "VEVENT":
            continue

        try:
            # --- title ---
            summary_raw = str(component.get("SUMMARY", ""))
            title = _ical_unescape(summary_raw)

            # --- uid ---
            uid = str(component.get("UID", ""))

            # --- start / end / all-day detection ---
            dtstart = component.get("DTSTART")
            dtend = component.get("DTEND")

            if dtstart is None:
                logger.error("_parse_event -- DTSTART missing, skipping event")
                return None

            dtstart_val = dtstart.dt
            is_all_day = False

            if isinstance(dtstart_val, date) and not isinstance(dtstart_val, datetime):
                # All-day event: date objects (no time component)
                is_all_day = True
                start_str = "00:00"
                start_dt = datetime.combine(dtstart_val, datetime.min.time(), tzinfo=tz)
                if dtend is not None:
                    dtend_val = dtend.dt
                    end_dt = datetime.combine(dtend_val, datetime.min.time(), tzinfo=tz)
                else:
                    end_dt = start_dt
                end_str = "23:59" if is_all_day else end_dt.astimezone(tz).strftime("%H:%M")
            else:
                # Timed event
                if dtstart_val.tzinfo is None:
                    dtstart_val = dtstart_val.replace(tzinfo=tz)
                start_dt = dtstart_val.astimezone(tz)
                start_str = start_dt.strftime("%H:%M")

                if dtend is not None:
                    dtend_val = dtend.dt
                    if isinstance(dtend_val, date) and not isinstance(dtend_val, datetime):
                        end_dt = datetime.combine(dtend_val, datetime.min.time(), tzinfo=tz)
                    else:
                        if dtend_val.tzinfo is None:
                            dtend_val = dtend_val.replace(tzinfo=tz)
                        end_dt = dtend_val.astimezone(tz)
                else:
                    end_dt = start_dt
                end_str = end_dt.astimezone(tz).strftime("%H:%M")

            duration_minutes = int((end_dt - start_dt).total_seconds() // 60)
            if duration_minutes < 0:
                duration_minutes = 0

            # --- location ---
            location_raw = str(component.get("LOCATION", "") or "")
            location = _ical_unescape(location_raw)

            # --- organizer ---
            organizer_prop = component.get("ORGANIZER")
            organizer = ""
            if organizer_prop is not None:
                cn = organizer_prop.params.get("CN", "")
                if cn:
                    organizer = str(cn)
                else:
                    # Fallback: extract email from mailto:
                    org_str = str(organizer_prop)
                    if org_str.lower().startswith("mailto:"):
                        organizer = org_str[7:]
                    else:
                        organizer = org_str

            # --- attendees_count ---
            attendees = component.get("ATTENDEE")
            if attendees is None:
                attendees_count = 0
            elif isinstance(attendees, list):
                attendees_count = len(attendees)
            else:
                attendees_count = 1

            # --- description ---
            desc_raw = str(component.get("DESCRIPTION", "") or "")
            description = _ical_unescape(desc_raw)
            if len(description) > 2000:
                description = description[:2000]

            # --- conference URL ---
            conference_url = _extract_conference_url(
                component, location, description,
            )

            return {
                "uid": uid,
                "title": title,
                "start": start_str,
                "end": end_str,
                "duration_minutes": duration_minutes,
                "location": location,
                "organizer": organizer,
                "attendees_count": attendees_count,
                "description": description,
                "conference_url": conference_url,
                "is_all_day": is_all_day,
                "status": "upcoming",  # will be assigned by _assign_statuses
                "has_protocol": False,  # will be assigned by _match_protocols
                "protocol_filename": None,
            }
        except Exception as exc:
            logger.error(f"_parse_event -- error extracting fields: {exc}")
            return None

    # No VEVENT component found
    logger.error("_parse_event -- no VEVENT component in event data")
    return None


# ---------------------------------------------------------------------------
# Status assignment
# ---------------------------------------------------------------------------


def _assign_statuses(meetings: list[dict], tz: ZoneInfo) -> None:
    """Assign status to each meeting based on current time.

    Statuses: done, in_progress, next, upcoming.
    Meetings must be sorted by start time before calling this function.
    """
    now = datetime.now(tz).strftime("%H:%M")
    first_future_found = False

    for m in meetings:
        if m["end"] <= now:
            m["status"] = "done"
        elif m["start"] <= now <= m["end"]:
            m["status"] = "in_progress"
        elif not first_future_found:
            m["status"] = "next"
            first_future_found = True
        else:
            m["status"] = "upcoming"


# ---------------------------------------------------------------------------
# Protocol matching
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> set[str]:
    """Split text into lowercase tokens longer than 3 characters."""
    words = re.findall(r"[a-zA-ZЀ-ӿ]+", text.lower())
    return {w for w in words if len(w) > 3}


def _match_protocols(meetings: list[dict], today: date) -> None:
    """Cross-reference meetings with wiki/meetings/ protocol files.

    For each meeting, check if a protocol file exists for today with
    a fuzzy title match (token overlap score >= 0.3).
    """
    logger.info("_match_protocols -- scanning wiki/meetings/ for protocols")
    try:
        meetings_dir = wiki_meetings()
    except Exception as exc:
        logger.error(f"_match_protocols -- failed to access wiki/meetings/: {exc}")
        return

    today_iso = today.isoformat()  # YYYY-MM-DD

    # Collect today's protocol files
    today_files: list[Path] = []
    try:
        if meetings_dir.exists():
            for f in meetings_dir.iterdir():
                if f.is_file() and f.name.startswith(today_iso) and f.suffix == ".md":
                    today_files.append(f)
    except Exception as exc:
        logger.error(f"_match_protocols -- error scanning meetings directory: {exc}")
        return

    logger.info(f"_match_protocols -- found {len(today_files)} protocol files for {today_iso}")

    if not today_files:
        return

    for m in meetings:
        title_tokens = _tokenize(m["title"])
        if not title_tokens:
            continue

        for protocol_file in today_files:
            file_tokens = _tokenize(protocol_file.stem)
            if not file_tokens:
                continue

            intersection = title_tokens & file_tokens
            score = len(intersection) / len(title_tokens)

            if score >= 0.3:
                m["has_protocol"] = True
                m["protocol_filename"] = protocol_file.name
                logger.info(
                    f"_match_protocols -- matched '{m['title']}' -> "
                    f"'{protocol_file.name}' (score={score:.2f})"
                )
                break  # first match is enough


# ---------------------------------------------------------------------------
# Public: get_today_meetings
# ---------------------------------------------------------------------------


def get_today_meetings() -> list[dict]:
    """Fetch today's meetings from Yandex Calendar via CalDAV.

    Synchronous function (designed for asyncio.run_in_executor in FastAPI).
    Returns a list of meeting dicts sorted by start time.
    On any error returns an empty list (graceful degradation).
    """
    logger.info("get_today_meetings -- start")

    if not is_enabled():
        logger.info("get_today_meetings -- CalDAV disabled (no credentials)")
        return []

    cached = _calendar_cache.get("meetings")
    if cached is not None:
        logger.info(f"get_today_meetings -- returning cached ({len(cached)} meetings)")
        return cached

    username, password, tz_name, caldav_url = _get_credentials()

    try:
        logger.info("get_today_meetings -- connecting to CalDAV server")
        client = caldav.DAVClient(  # type: ignore[operator]
            url=caldav_url,
            username=username,
            password=password,
        )
        principal = client.principal()
        logger.info("get_today_meetings -- authenticated successfully")

        calendars = principal.calendars()
        logger.info(f"get_today_meetings -- found {len(calendars)} calendars")

        tz = ZoneInfo(tz_name)
        today = datetime.now(tz).date()
        start = datetime.combine(today, datetime.min.time(), tzinfo=tz)
        end = datetime.combine(today, datetime.max.time(), tzinfo=tz)

        events: list[Any] = []
        for cal in calendars:
            try:
                cal_name = getattr(cal, "name", "<unknown>")
                cal_events = cal.date_search(start=start, end=end, expand=True)
                logger.info(
                    f"get_today_meetings -- calendar '{cal_name}': "
                    f"{len(cal_events)} events"
                )
                events.extend(cal_events)
            except Exception as exc:
                cal_name = getattr(cal, "name", "<unknown>")
                logger.error(
                    f"get_today_meetings -- error fetching calendar '{cal_name}': {exc}"
                )

        meetings: list[dict] = []
        for event in events:
            parsed = _parse_event(event, tz)
            if parsed:
                meetings.append(parsed)

        meetings.sort(key=lambda m: m["start"])
        _assign_statuses(meetings, tz)
        _match_protocols(meetings, today)

        _calendar_cache.set("meetings", meetings)
        logger.info(f"get_today_meetings -- success, {len(meetings)} meetings")
        return meetings

    except Exception as exc:
        logger.error(f"get_today_meetings -- CalDAV error: {exc}")
        return []
