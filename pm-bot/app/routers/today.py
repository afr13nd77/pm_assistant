"""Эндпоинты страницы «Сегодня»: утренний дайджест, ежедневные новости,
встречи из CalDAV-календаря на сегодня.
"""

import logging
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from .. import calendar_client
from ..vault_cache import _cache, _caldav_executor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Today"])


# ---------------------------------------------------------------------------
# Today — Daily News helpers
# ---------------------------------------------------------------------------


def _news_neighbours(
    sorted_dates: list[str], current_date: str | None
) -> tuple[str | None, str | None]:
    """Return (prev_date, next_date) for *current_date* within a sorted list of date strings."""
    if not current_date or current_date not in sorted_dates:
        return (None, None)
    idx = sorted_dates.index(current_date)
    prev_d = sorted_dates[idx - 1] if idx > 0 else None
    next_d = sorted_dates[idx + 1] if idx < len(sorted_dates) - 1 else None
    return (prev_d, next_d)


# ---------------------------------------------------------------------------
# Today — Morning Digest
# ---------------------------------------------------------------------------


@router.get("/api/v1/today/digest")
async def get_today_digest(refresh: bool = False):
    """Утренний дайджест: парсинг последнего morning-digest файла из vault."""
    logger.info("GET /today/digest — start, refresh=%s", refresh)
    try:
        if refresh:
            _cache.invalidate("today:digest")

        cached = _cache.get("today:digest")
        if cached is not None:
            logger.info("GET /today/digest — returning cached")
            return cached

        from datetime import date

        from shared.vault_paths import wiki_morning_digests

        from ..today_parsers import find_latest_file, parse_digest

        digest_dir = wiki_morning_digests()
        today = date.today()

        file_path, is_today = find_latest_file(digest_dir, "morning-digest", today)

        if file_path is None:
            result: dict[str, Any] = {
                "date": None,
                "filename": None,
                "is_today": False,
                "focus": None,
                "sections": [],
                "full_markdown": None,
            }
            _cache.set("today:digest", result)
            logger.info("GET /today/digest — no digest files found")
            return result

        text = file_path.read_text(encoding="utf-8")
        parsed = parse_digest(text)

        # Extract date from filename (YYYY-MM-DD-morning-digest.md)
        file_date = file_path.stem[:10]  # "2026-07-22"

        result = {
            "date": file_date,
            "filename": file_path.name,
            "is_today": is_today,
            "focus": parsed["focus"],
            "sections": parsed["sections"],
            "full_markdown": parsed["full_markdown"],
        }

        _cache.set("today:digest", result)
        logger.info("GET /today/digest — success, date=%s, is_today=%s", file_date, is_today)
        return result
    except Exception as e:
        logger.error("GET /today/digest — error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to read morning digest")


# ---------------------------------------------------------------------------
# Today — Daily News
# ---------------------------------------------------------------------------


@router.get("/api/v1/today/news")
async def get_today_news(
    refresh: bool = False,
    date: str = Query(default=None, description="Дата в формате YYYY-MM-DD"),
):
    """Ежедневные новости: парсинг daily-news файла из vault (конкретная дата или последний)."""
    logger.info(f"GET /today/news — start, refresh={refresh}, date={date}")
    try:
        from datetime import date as date_type

        from shared.vault_paths import wiki_daily_news

        from ..today_parsers import find_latest_file, parse_news

        # Validate date parameter format
        date_param = date  # rename to avoid shadowing
        if date_param is not None:
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_param):
                logger.warning(f"GET /today/news — invalid date format: {date_param}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid date format: '{date_param}'. Expected YYYY-MM-DD.",
                )

        # Cache key depends on date parameter
        cache_key = f"today:news:{date_param}" if date_param else "today:news"

        if refresh:
            _cache.invalidate(cache_key)
            logger.info(f"GET /today/news — cache invalidated for key={cache_key}")

        cached = _cache.get(cache_key)
        if cached is not None:
            logger.info(f"GET /today/news — returning cached, key={cache_key}")
            return cached

        news_dir = wiki_daily_news()
        today = date_type.today()

        # --- Collect all available news dates for prev/next navigation ---
        all_dates: list[str] = []
        if news_dir.is_dir():
            for f in news_dir.iterdir():
                if f.is_file() and f.name.endswith("-news.md"):
                    d = f.stem[:10]
                    if re.match(r"^\d{4}-\d{2}-\d{2}$", d):
                        all_dates.append(d)
        all_dates.sort()
        logger.info(f"GET /today/news — found {len(all_dates)} news files in vault")

        # --- Resolve the target file ---
        file_path: Path | None = None
        is_today = False

        if date_param:
            # Direct lookup by date
            target = news_dir / f"{date_param}-news.md"
            if target.is_file():
                file_path = target
                logger.info(f"GET /today/news — found file for date={date_param}")
            else:
                logger.info(f"GET /today/news — no file for date={date_param}")
            is_today = date_param == str(today)
        else:
            # Original behaviour: find latest file
            file_path, is_today = find_latest_file(news_dir, "news", today)

        # --- Build response ---
        if file_path is None:
            file_date = date_param  # preserve requested date (or None)
            prev_date, next_date = _news_neighbours(all_dates, file_date)
            result: dict[str, Any] = {
                "date": file_date,
                "filename": None,
                "is_today": is_today if date_param else False,
                "prev_date": prev_date,
                "next_date": next_date,
                "categories": {"competitors": [], "ai_llm": []},
            }
            _cache.set(cache_key, result)
            logger.info(f"GET /today/news — no news file, date={file_date}")
            return result

        text = file_path.read_text(encoding="utf-8")
        parsed = parse_news(text)

        # Extract date from filename (YYYY-MM-DD-news.md)
        file_date = file_path.stem[:10]  # "2026-07-21"
        prev_date, next_date = _news_neighbours(all_dates, file_date)

        result = {
            "date": file_date,
            "filename": file_path.name,
            "is_today": is_today,
            "prev_date": prev_date,
            "next_date": next_date,
            "categories": parsed["categories"],
        }

        _cache.set(cache_key, result)
        logger.info(
            f"GET /today/news — success, date={file_date}, is_today={is_today}, "
            f"prev={prev_date}, next={next_date}"
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GET /today/news — error: {e}")
        raise HTTPException(status_code=500, detail="Failed to read daily news")


# ---------------------------------------------------------------------------
# GET /api/v1/today/meetings — CalDAV meetings for today
# ---------------------------------------------------------------------------


@router.get("/api/v1/today/meetings")
async def get_today_meetings(refresh: bool = False):
    """Return today's meetings from CalDAV calendar (graceful degradation)."""
    logger.info(f"GET /today/meetings — start, refresh={refresh}")
    try:
        import asyncio
        from datetime import date

        today = date.today().isoformat()

        if not calendar_client.is_enabled():
            result = {
                "date": today,
                "count": 0,
                "source": "disabled",
                "meetings": [],
            }
            logger.info("GET /today/meetings — CalDAV disabled")
            return result

        if refresh:
            calendar_client._calendar_cache.invalidate()

        try:
            # Run synchronous CalDAV in executor
            loop = asyncio.get_event_loop()
            meetings = await loop.run_in_executor(
                _caldav_executor,
                calendar_client.get_today_meetings,
            )

            result = {
                "date": today,
                "count": len(meetings),
                "source": "caldav",
                "meetings": meetings,
            }
            logger.info(f"GET /today/meetings — success, count={len(meetings)}")
            return result
        except Exception as caldav_err:
            logger.error(f"GET /today/meetings — CalDAV error: {caldav_err}")
            return {
                "date": today,
                "count": 0,
                "source": "error",
                "meetings": [],
            }
    except Exception as e:
        logger.error(f"GET /today/meetings — error: {e}")
        return {
            "date": date.today().isoformat() if "date" in dir() else None,
            "count": 0,
            "source": "error",
            "meetings": [],
        }
