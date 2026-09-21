"""Роутер идей (ideas): список идей, capture (создание заметки через Claude),
обновление статуса идеи и креативные идеи (KE proxy).
"""

import json
import logging

import requests
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from shared.vault_paths import VAULT_PATH

from .. import ke_client
from ..vault_cache import _cache
from ..vault_parsers import _calculate_readiness, _parse_tags, parse_note
from ..vault_scanner import (
    _VALID_IDEA_STATUSES,
    _domain_from_path,
    _find_idea_file,
    _scan_domain_folders,
    _update_frontmatter_field,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Ideas"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class CaptureRequest(BaseModel):
    type: str  # "idea" | "task" | "meeting"
    text: str


class CaptureResponse(BaseModel):
    filename: str
    path: str
    content: str


class IdeaStatusUpdateRequest(BaseModel):
    status: str


class IdeaStatusUpdateResponse(BaseModel):
    status: str
    new_status: str
    readiness: int
    updated: str
    filename: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/api/v1/ideas")
def get_ideas(domain: str | None = Query(default=None)):
    """Read all .md files from wiki/domains/*/ideas/, parse frontmatter + body,
    return sorted by date (newest first).

    Optional ?domain=<name> query parameter to filter by one domain.
    Each returned item includes a 'domain' field.
    """
    logger.info("GET /api/v1/ideas — start, domain=%s", domain)

    cache_key = f"ideas:{domain or '__all__'}"
    cached = _cache.get(cache_key)
    if cached is not None:
        logger.info("GET /api/v1/ideas -- returning cached (%d ideas)", len(cached))
        return cached

    files = _scan_domain_folders("ideas", domain_filter=domain)
    logger.info("GET /api/v1/ideas — found %d files", len(files))

    results = []
    for f in files:
        try:
            note = parse_note(f)
            idea_status = note.get("status", "Новая")
            results.append(
                {
                    "filename": note["filename"],
                    "date": note["date"],
                    "updated": note.get("updated", note["date"]),
                    "title": note["title"],
                    "tags": _parse_tags(note.get("tags", "")),
                    "status": idea_status,
                    "body": note["body"],
                    "domain": _domain_from_path(f),
                    "id": note.get("id", ""),
                    "readiness": _calculate_readiness(note["body"]),
                    "tier": note.get("tier", "active"),
                    "relevance": float(note.get("relevance", 1.0)),
                }
            )
        except Exception as exc:
            logger.error("GET /api/v1/ideas — failed to parse %s: %s", f.name, exc)
            continue
    results.sort(key=lambda x: x["date"], reverse=True)
    logger.info("GET /api/v1/ideas — returning %d notes", len(results))
    _cache.set(cache_key, results)
    return results


@router.post("/api/v1/capture", response_model=CaptureResponse)
def capture_note(req: CaptureRequest):
    """Create a note via Claude.

    Accepts type (idea/task/meeting) and text, processes through Claude,
    and saves to the vault via obsidian_writer.
    """
    logger.info("POST /api/v1/capture — start, type=%s, text_len=%d", req.type, len(req.text))

    if req.type not in ("idea", "task", "meeting"):
        logger.error("POST /api/v1/capture — invalid type: %s", req.type)
        raise HTTPException(status_code=400, detail=f"Invalid type: {req.type}. Must be one of: idea, task, meeting")

    try:
        if req.type == "idea":
            from app.claude_client import process_idea
            from app.handlers import _fallback_idea_data
            from app.obsidian_writer import write_idea

            logger.info("POST /api/v1/capture — processing idea via Claude")
            try:
                content = process_idea(req.text)
                logger.info("POST /api/v1/capture — Claude returned idea data with %d keys", len(content))
            except Exception as llm_err:
                logger.warning("POST /api/v1/capture — Claude API failed, saving raw idea: %s", llm_err)
                content = _fallback_idea_data(req.text)

            filepath = write_idea(content, req.text)
            logger.info("POST /api/v1/capture — saved idea to %s", filepath)
            _cache.invalidate()

        elif req.type in ("task", "meeting"):
            from app.claude_client import process_jira_ticket
            from app.handlers import _fallback_jira_content
            from app.obsidian_writer import write_jira_draft

            logger.info("POST /api/v1/capture — processing %s via Claude", req.type)
            jira_content: str
            try:
                jira_content = process_jira_ticket(req.text)
                logger.info("POST /api/v1/capture — Claude returned %d chars", len(jira_content))
            except Exception as llm_err:
                logger.warning("POST /api/v1/capture — Claude API failed, saving raw draft: %s", llm_err)
                jira_content = _fallback_jira_content(req.text)

            filepath = write_jira_draft(jira_content)
            logger.info("POST /api/v1/capture — saved draft to %s", filepath)
            _cache.invalidate()

        else:
            # Should not reach here due to the check above, but just in case
            raise HTTPException(status_code=400, detail=f"Unsupported type: {req.type}")

        # Compute relative path from VAULT root
        try:
            relative_path = str(filepath.relative_to(VAULT_PATH))
        except ValueError:
            relative_path = str(filepath)

        logger.info(
            "POST /api/v1/capture — success, filename=%s, path=%s",
            filepath.name,
            relative_path,
        )
        if req.type == "idea":
            response_content = json.dumps(content, ensure_ascii=False) if isinstance(content, dict) else str(content)
        else:
            response_content = jira_content
        return CaptureResponse(
            filename=filepath.name,
            path=relative_path,
            content=response_content,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("POST /api/v1/capture — error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.patch("/api/v1/ideas/{filename}/status")
def update_idea_status(filename: str, req: IdeaStatusUpdateRequest):
    """Update the status field in an idea file's frontmatter."""
    logger.info("PATCH /api/v1/ideas/%s/status — start, new_status=%s", filename, req.status)

    # Validate filename
    if not filename.endswith(".md"):
        logger.error("PATCH /api/v1/ideas/%s/status — invalid filename: must end with .md", filename)
        raise HTTPException(status_code=400, detail="Filename must end with .md")
    if "/" in filename or "\\" in filename or ".." in filename:
        logger.error("PATCH /api/v1/ideas/%s/status — invalid filename: path separators or traversal", filename)
        raise HTTPException(status_code=400, detail="Invalid filename")

    # Validate status
    if req.status not in _VALID_IDEA_STATUSES:
        logger.error("PATCH /api/v1/ideas/%s/status — invalid status: %s", filename, req.status)
        raise HTTPException(status_code=400, detail=f"Invalid status: {req.status}. Must be one of: {', '.join(sorted(_VALID_IDEA_STATUSES))}")

    # Find file
    file_path = _find_idea_file(filename)
    if not file_path:
        logger.error("PATCH /api/v1/ideas/%s/status — file not found", filename)
        raise HTTPException(status_code=404, detail="File not found")

    # Read file
    try:
        text = file_path.read_text(encoding="utf-8")
        logger.info("PATCH /api/v1/ideas/%s/status — read %d chars", filename, len(text))
    except Exception as exc:
        logger.error("PATCH /api/v1/ideas/%s/status — read error: %s", filename, exc)
        raise HTTPException(status_code=500, detail=f"Failed to read file: {exc}")

    # Update frontmatter
    from datetime import date
    today_str = date.today().isoformat()
    text = _update_frontmatter_field(text, "status", req.status)
    text = _update_frontmatter_field(text, "updated", today_str)

    # Write file back
    try:
        file_path.write_text(text, encoding="utf-8")
        _cache.invalidate()
        logger.info("PATCH /api/v1/ideas/%s/status — written successfully", filename)
    except Exception as exc:
        logger.error("PATCH /api/v1/ideas/%s/status — write error: %s", filename, exc)
        raise HTTPException(status_code=500, detail=f"Failed to write file: {exc}")

    # Calculate readiness from body
    note = parse_note(file_path)
    readiness = _calculate_readiness(note["body"])
    logger.info("PATCH /api/v1/ideas/%s/status — readiness=%d, done", filename, readiness)

    return IdeaStatusUpdateResponse(
        status="ok",
        new_status=req.status,
        readiness=readiness,
        updated=today_str,
        filename=filename,
    )


@router.get("/api/v1/ideas/creative")
def get_ideas_creative(count: int = Query(default=5, ge=1, le=50)):
    """Get creative ideas from knowledge engine."""
    logger.info("GET /api/v1/ideas/creative — start, count=%d", count)
    try:
        data = ke_client.get_creative(count)
        ideas = data.get("ideas", data) if isinstance(data, dict) else data
        logger.info("GET /api/v1/ideas/creative — success, count=%d", len(ideas))
        return ideas
    except requests.RequestException as exc:
        logger.error("GET /api/v1/ideas/creative — ke_client.get_creative failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"KE API error: {exc}")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("GET /api/v1/ideas/creative — error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
