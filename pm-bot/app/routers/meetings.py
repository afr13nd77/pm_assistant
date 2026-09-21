"""Эндпоинты встреч: список протоколов, содержимое конкретного протокола,
импорт транскриптов встреч из почты.
"""

import logging
from datetime import datetime, timedelta

import requests
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from shared.vault_paths import wiki_meetings

from .. import ke_client
from ..vault_cache import _cache
from ..vault_parsers import _extract_section, parse_note
from ..vault_scanner import _is_service_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Meetings"])


# ---------------------------------------------------------------------------
# GET /api/v1/meetings
# ---------------------------------------------------------------------------

@router.get("/api/v1/meetings")
def get_meetings(days: int = Query(default=14, ge=1, le=365)):
    """Read .md files from wiki/meetings/ for last N days.

    Returns notes with type, decisions, action_items, and blockers
    parsed from markdown sections.
    """
    logger.info("GET /api/v1/meetings — start, days=%d", days)

    cache_key = f"meetings:{days}"
    cached = _cache.get(cache_key)
    if cached is not None:
        logger.info("GET /api/v1/meetings — returning cached (%d meetings)", len(cached))
        return cached

    folder = wiki_meetings()

    if not folder.exists():
        logger.info(
            "GET /api/v1/meetings — meetings folder not found, returning empty list"
        )
        return []

    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    logger.info("GET /api/v1/meetings — cutoff date: %s", cutoff)

    try:
        files = sorted(
            (f for f in folder.glob("*.md") if not _is_service_file(f)),
            reverse=True,
        )
        logger.info("GET /api/v1/meetings — found %d total files", len(files))
    except Exception as exc:
        logger.error("GET /api/v1/meetings — error listing files: %s", exc)
        return []

    results = []
    for f in files:
        try:
            note = parse_note(f)
            note_date = note.get("date", "")
            if note_date < cutoff:
                continue

            body = note.get("body", "")

            # Extract decisions
            decisions_raw = _extract_section(body, "Решения")
            decisions = [
                line.strip().lstrip("- ").strip()
                for line in decisions_raw.splitlines()
                if line.strip() and line.strip() != "-"
            ] if decisions_raw else []

            # Extract action items (lines with - [ ])
            action_items_raw = _extract_section(body, "Action Items")
            action_items = [
                line.strip()
                for line in action_items_raw.splitlines()
                if "- [ ]" in line
            ] if action_items_raw else []

            # Extract blockers
            blockers = _extract_section(body, "Блокеры и риски")

            results.append(
                {
                    "filename": note["filename"],
                    "date": note_date,
                    "title": note["title"],
                    "type": note.get("type", ""),
                    "decisions": decisions,
                    "action_items": action_items,
                    "blockers": blockers if blockers else "",
                }
            )
        except Exception as exc:
            logger.error(
                "GET /api/v1/meetings — failed to parse %s: %s", f.name, exc
            )
            continue

    results.sort(key=lambda x: x["date"], reverse=True)
    logger.info("GET /api/v1/meetings — returning %d notes", len(results))
    _cache.set(cache_key, results)
    return results


# ---------------------------------------------------------------------------
# GET /api/v1/meetings/{filename}
# ---------------------------------------------------------------------------

@router.get("/api/v1/meetings/{filename}")
def get_meeting_by_filename(filename: str):
    """Return the full content of a specific meeting protocol file."""
    logger.info("GET /api/v1/meetings/%s — start", filename)

    # --- Security validation ---
    if not filename.endswith(".md"):
        logger.error("GET /api/v1/meetings/%s — rejected: filename does not end with .md", filename)
        raise HTTPException(status_code=400, detail="Filename must end with .md")

    if "/" in filename or "\\" in filename:
        logger.error("GET /api/v1/meetings/%s — rejected: path separators in filename", filename)
        raise HTTPException(status_code=400, detail="Filename must not contain path separators")

    folder = wiki_meetings()
    filepath = folder / filename

    if not filepath.exists():
        logger.info("GET /api/v1/meetings/%s — file not found", filename)
        raise HTTPException(status_code=404, detail="Meeting not found")

    try:
        content = filepath.read_text(encoding="utf-8")
        date = filepath.stem[:10] if len(filepath.stem) >= 10 else filepath.stem
        logger.info("GET /api/v1/meetings/%s — returning meeting (%d chars)", filename, len(content))
        return {"filename": filename, "content": content, "date": date}
    except Exception as exc:
        logger.error("GET /api/v1/meetings/%s — failed to read file: %s", filename, exc)
        raise HTTPException(status_code=500, detail="Failed to read meeting")


# ---------------------------------------------------------------------------
# Fetch Meetings (email import) endpoint
# ---------------------------------------------------------------------------

class FetchMeetingsRequest(BaseModel):
    notify: bool = False
    dry_run: bool = False


class FetchMeetingsResponse(BaseModel):
    status: str
    total_emails: int = 0
    already_processed: int = 0
    newly_processed: int = 0
    errors: int = 0
    details: list = []
    message: str = ""


@router.post("/api/v1/fetch-meetings", response_model=FetchMeetingsResponse)
def fetch_meetings_endpoint(req: FetchMeetingsRequest):
    """Fetch and process new meeting transcripts from email via knowledge-engine."""
    logger.info("POST /api/v1/fetch-meetings — start, notify=%s, dry_run=%s", req.notify, req.dry_run)
    try:
        data = ke_client.fetch_meetings(notify=req.notify, dry_run=req.dry_run)
        _cache.invalidate()
        logger.info("POST /api/v1/fetch-meetings — success: newly_processed=%s", data.get("newly_processed", 0))
        return FetchMeetingsResponse(**data)
    except requests.RequestException as exc:
        logger.error("POST /api/v1/fetch-meetings — ke_client error: %s", exc)
        raise HTTPException(status_code=502, detail=f"KE API error: {exc}")
    except Exception as exc:
        logger.error("POST /api/v1/fetch-meetings — error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
