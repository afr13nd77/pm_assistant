"""Artifact endpoints: единичный GET и PATCH field/body для любого артефакта vault."""

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from shared.vault_paths import VAULT_PATH

from ..vault_cache import _cache
from ..vault_parsers import _calculate_readiness, _parse_tags, parse_note
from ..vault_scanner import _domain_from_path, _find_artifact_file, _update_frontmatter_field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Artifacts"])


# ---------------------------------------------------------------------------
# Artifact field / body update
# ---------------------------------------------------------------------------

_ALLOWED_FIELD_KEYS = {"status", "domain", "tags", "priority", "tier"}


class ArtifactFieldUpdateRequest(BaseModel):
    key: str
    value: str


class ArtifactFieldUpdateResponse(BaseModel):
    status: str
    filename: str
    key: str
    value: str
    readiness: int
    updated: str


@router.patch("/api/v1/artifact/{filename}/field")
def update_artifact_field(filename: str, req: ArtifactFieldUpdateRequest):
    """Update a single frontmatter field in any vault artifact."""
    logger.info("PATCH /api/v1/artifact/%s/field — start, key=%s value=%s", filename, req.key, req.value)

    # Validate filename
    if not filename.endswith(".md"):
        logger.error("PATCH artifact/%s/field — invalid filename: must end with .md", filename)
        raise HTTPException(status_code=400, detail="Filename must end with .md")
    if "/" in filename or "\\" in filename or ".." in filename:
        logger.error("PATCH artifact/%s/field — invalid filename: path separators or traversal", filename)
        raise HTTPException(status_code=400, detail="Invalid filename")

    # Validate key
    if req.key not in _ALLOWED_FIELD_KEYS:
        logger.error("PATCH artifact/%s/field — invalid key: %s", filename, req.key)
        raise HTTPException(status_code=400, detail=f"Invalid key: {req.key}. Allowed: {', '.join(sorted(_ALLOWED_FIELD_KEYS))}")

    # Find file
    try:
        file_path = _find_artifact_file(filename)
    except Exception as exc:
        logger.error("PATCH artifact/%s/field — find error: %s", filename, exc)
        raise HTTPException(status_code=500, detail=f"Search error: {exc}")
    if not file_path:
        logger.error("PATCH artifact/%s/field — file not found", filename)
        raise HTTPException(status_code=404, detail="File not found")

    # Read file
    try:
        text = file_path.read_text(encoding="utf-8")
        logger.info("PATCH artifact/%s/field — read %d chars", filename, len(text))
    except Exception as exc:
        logger.error("PATCH artifact/%s/field — read error: %s", filename, exc)
        raise HTTPException(status_code=500, detail=f"Failed to read file: {exc}")

    # Update frontmatter
    from datetime import date
    today_str = date.today().isoformat()
    text = _update_frontmatter_field(text, req.key, req.value)
    text = _update_frontmatter_field(text, "updated", today_str)

    # Write file
    try:
        file_path.write_text(text, encoding="utf-8")
        _cache.invalidate()
        logger.info("PATCH artifact/%s/field — written successfully", filename)
    except Exception as exc:
        logger.error("PATCH artifact/%s/field — write error: %s", filename, exc)
        raise HTTPException(status_code=500, detail=f"Failed to write file: {exc}")

    # Calculate readiness (for ideas)
    readiness = 0
    try:
        note = parse_note(file_path)
        readiness = _calculate_readiness(note.get("body", ""))
    except Exception:
        pass
    logger.info("PATCH artifact/%s/field — done, readiness=%d", filename, readiness)

    return ArtifactFieldUpdateResponse(
        status="ok",
        filename=filename,
        key=req.key,
        value=req.value,
        readiness=readiness,
        updated=today_str,
    )


class ArtifactBodyUpdateRequest(BaseModel):
    body: str = Field(..., max_length=50000)


class ArtifactBodyUpdateResponse(BaseModel):
    status: str
    filename: str
    readiness: int
    updated: str


@router.patch("/api/v1/artifact/{filename}/body")
def update_artifact_body(filename: str, req: ArtifactBodyUpdateRequest):
    """Update the markdown body of any vault artifact (preserves frontmatter)."""
    logger.info("PATCH /api/v1/artifact/%s/body — start, body_length=%d", filename, len(req.body))

    # Validate filename
    if not filename.endswith(".md"):
        logger.error("PATCH artifact/%s/body — invalid filename", filename)
        raise HTTPException(status_code=400, detail="Filename must end with .md")
    if "/" in filename or "\\" in filename or ".." in filename:
        logger.error("PATCH artifact/%s/body — invalid filename: traversal", filename)
        raise HTTPException(status_code=400, detail="Invalid filename")

    # Find file
    try:
        file_path = _find_artifact_file(filename)
    except Exception as exc:
        logger.error("PATCH artifact/%s/body — find error: %s", filename, exc)
        raise HTTPException(status_code=500, detail=f"Search error: {exc}")
    if not file_path:
        logger.error("PATCH artifact/%s/body — file not found", filename)
        raise HTTPException(status_code=404, detail="File not found")

    # Read file
    try:
        text = file_path.read_text(encoding="utf-8")
        logger.info("PATCH artifact/%s/body — read %d chars", filename, len(text))
    except Exception as exc:
        logger.error("PATCH artifact/%s/body — read error: %s", filename, exc)
        raise HTTPException(status_code=500, detail=f"Failed to read file: {exc}")

    # Replace body (preserve frontmatter)
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            text = parts[0] + "---" + parts[1] + "---\n" + req.body
        else:
            text = req.body
    else:
        text = req.body

    # Update 'updated' field in frontmatter
    from datetime import date
    today_str = date.today().isoformat()
    text = _update_frontmatter_field(text, "updated", today_str)

    # Write file
    try:
        file_path.write_text(text, encoding="utf-8")
        _cache.invalidate()
        logger.info("PATCH artifact/%s/body — written successfully", filename)
    except Exception as exc:
        logger.error("PATCH artifact/%s/body — write error: %s", filename, exc)
        raise HTTPException(status_code=500, detail=f"Failed to write file: {exc}")

    # Calculate readiness
    readiness = 0
    try:
        note = parse_note(file_path)
        readiness = _calculate_readiness(note.get("body", ""))
    except Exception:
        pass
    logger.info("PATCH artifact/%s/body — done, readiness=%d", filename, readiness)

    return ArtifactBodyUpdateResponse(
        status="ok",
        filename=filename,
        readiness=readiness,
        updated=today_str,
    )


# ---------------------------------------------------------------------------
# Single Artifact endpoint
# ---------------------------------------------------------------------------

@router.get("/api/v1/artifact")
async def get_artifact(path: str = Query(..., min_length=3, max_length=500)):
    """Return a single vault artifact by its relative filepath.

    The path must start with 'wiki/', must not contain '..' (path traversal),
    and must point to an existing .md file.
    """
    logger.info("GET /api/v1/artifact — start, path=%r", path)

    # --- Security: path traversal ---
    if ".." in path:
        logger.error("GET /api/v1/artifact — rejected: path traversal attempt, path=%r", path)
        raise HTTPException(status_code=400, detail="Path must not contain '..'")

    # --- Security: must start with wiki/ ---
    if not path.startswith("wiki/"):
        logger.error("GET /api/v1/artifact — rejected: path does not start with 'wiki/', path=%r", path)
        raise HTTPException(status_code=400, detail="Path must start with 'wiki/'")

    # --- Security: only .md files ---
    if not path.endswith(".md"):
        logger.error("GET /api/v1/artifact — rejected: path does not end with '.md', path=%r", path)
        raise HTTPException(status_code=404, detail="Only .md files are supported")

    full_path = VAULT_PATH / path

    if not full_path.exists() or not full_path.is_file():
        logger.error("GET /api/v1/artifact — file not found: %s", full_path)
        raise HTTPException(status_code=404, detail="Artifact not found")

    try:
        note = parse_note(full_path)
    except Exception as exc:
        logger.error("GET /api/v1/artifact — failed to parse %s: %s", full_path, exc)
        raise HTTPException(status_code=500, detail=f"Failed to parse artifact: {exc}")

    raw_tags = note.get("tags", "")
    tags = _parse_tags(raw_tags) if isinstance(raw_tags, str) else raw_tags if isinstance(raw_tags, list) else []

    result = {
        "filename": note.get("filename", full_path.name),
        "title": note.get("title", full_path.stem),
        "date": note.get("date", ""),
        "body": note.get("body", ""),
        "domain": _domain_from_path(full_path),
        "tags": tags,
        "status": note.get("status", ""),
        "id": note.get("id", ""),
        "tier": note.get("tier", ""),
        "relevance": note.get("relevance", ""),
    }

    logger.info(
        "GET /api/v1/artifact — success, filename=%s, title=%s",
        result["filename"], result["title"],
    )
    return result
