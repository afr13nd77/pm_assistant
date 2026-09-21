"""Роутер Jira: импорт/создание задач, список проектов/эпиков/типов задач,
проксирование поиска, принудительный sync и статус последней синхронизации.
"""

import logging
import os
import re

import requests
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .. import ke_client
from ..vault_cache import _PLATFORM_DATA, _cache, _jira_sync_lock
from .user_prefs import _read_user_prefs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Jira"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class JiraImportRequest(BaseModel):
    key: str

class JiraImportResponse(BaseModel):
    status: str
    key: str = ""
    domain: str = ""
    task_status: str = ""
    title: str = ""
    action: str = ""
    filename: str = ""
    message: str = ""


class JiraCreateRequest(BaseModel):
    filename: str
    project_key: str
    issue_type: str
    summary: str
    epic_key: str = ""

class JiraCreateResponse(BaseModel):
    status: str
    jira_key: str = ""
    jira_url: str = ""
    message: str = ""
    vault_updated: bool = True


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/api/v1/jira/import", response_model=JiraImportResponse)
def jira_import(req: JiraImportRequest):
    """Import a single Jira issue by key via knowledge-engine."""
    logger.info("POST /api/v1/jira/import — start, key=%s", req.key)

    if not re.match(r'^[A-Z][A-Z0-9]+-\d+$', req.key):
        logger.error("POST /api/v1/jira/import — invalid key format: %s", req.key)
        raise HTTPException(status_code=400, detail=f"Invalid Jira key format: {req.key}. Expected: PROJECT-123")

    try:
        data = ke_client.jira_import(req.key)
        _cache.invalidate()
        logger.info("POST /api/v1/jira/import — success: %s", data.get("message"))
        return JiraImportResponse(**data)
    except requests.RequestException as exc:
        logger.error("POST /api/v1/jira/import — ke_client.jira_import failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"KE API error: {exc}")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("POST /api/v1/jira/import — error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/v1/jira/create", response_model=JiraCreateResponse)
def jira_create(req: JiraCreateRequest):
    """Create a new Jira issue from a vault task file via knowledge-engine."""
    logger.info(
        "POST /api/v1/jira/create — start, filename=%s project_key=%s issue_type=%s summary_len=%d",
        req.filename, req.project_key, req.issue_type, len(req.summary),
    )

    # --- Validation ---
    if not req.filename.endswith(".md"):
        logger.error("POST /api/v1/jira/create — rejected: filename does not end with .md")
        raise HTTPException(status_code=400, detail="filename must end with .md")

    if "/" in req.filename or "\\" in req.filename or ".." in req.filename:
        logger.error("POST /api/v1/jira/create — rejected: invalid characters in filename")
        raise HTTPException(status_code=400, detail="filename must not contain '/', '\\', or '..'")

    if not re.match(r'^[A-Z][A-Z0-9]+$', req.project_key):
        logger.error("POST /api/v1/jira/create — rejected: invalid project_key=%s", req.project_key)
        raise HTTPException(status_code=400, detail="project_key must match ^[A-Z][A-Z0-9]+$")

    if not req.issue_type.strip():
        logger.error("POST /api/v1/jira/create — rejected: empty issue_type")
        raise HTTPException(status_code=400, detail="issue_type must not be empty")

    if not req.summary.strip():
        logger.error("POST /api/v1/jira/create — rejected: empty summary")
        raise HTTPException(status_code=400, detail="summary must not be empty")

    if len(req.summary) > 255:
        logger.error("POST /api/v1/jira/create — rejected: summary too long (%d chars)", len(req.summary))
        raise HTTPException(status_code=400, detail="summary must not exceed 255 characters")

    if req.epic_key and not re.match(r'^[A-Z][A-Z0-9]+-\d+$', req.epic_key):
        logger.error("POST /api/v1/jira/create — rejected: invalid epic_key=%s", req.epic_key)
        raise HTTPException(status_code=400, detail="epic_key must match ^[A-Z][A-Z0-9]+-\\d+$")

    # --- KE API call ---
    logger.info(
        "POST /api/v1/jira/create — calling ke_client.jira_create(file=%s, project=%s, type=%s)",
        req.filename, req.project_key, req.issue_type,
    )
    try:
        data = ke_client.jira_create(
            file=req.filename,
            project=req.project_key,
            type=req.issue_type,
            summary=req.summary,
            epic=req.epic_key,
        )
        _cache.invalidate()
        logger.info(
            "POST /api/v1/jira/create — success: jira_key=%s", data.get("jira_key")
        )
        return JiraCreateResponse(**data)
    except requests.RequestException as exc:
        logger.error("POST /api/v1/jira/create — ke_client.jira_create failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"KE API error: {exc}")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("POST /api/v1/jira/create — error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/v1/jira/projects")
def jira_projects():
    """List available Jira projects via knowledge-engine."""
    logger.info("GET /api/v1/jira/projects — start")
    try:
        data = ke_client.jira_projects()
        projects = data.get("projects", data) if isinstance(data, dict) else data
        logger.info("GET /api/v1/jira/projects — success, count=%d", len(projects))
        return projects
    except requests.RequestException as exc:
        logger.error("GET /api/v1/jira/projects — ke_client.jira_projects failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"KE API error: {exc}")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("GET /api/v1/jira/projects — error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/v1/jira/projects/{project_key}/epics")
def jira_project_epics(project_key: str):
    """List epics for a given Jira project via knowledge-engine."""
    logger.info("GET /api/v1/jira/projects/%s/epics — start", project_key)

    if not re.match(r'^[A-Z][A-Z0-9]+$', project_key):
        logger.error(
            "GET /api/v1/jira/projects/%s/epics — rejected: invalid project_key", project_key
        )
        raise HTTPException(status_code=400, detail="project_key must match ^[A-Z][A-Z0-9]+$")

    try:
        data = ke_client.jira_epics(project=project_key)
        epics = data.get("epics", data) if isinstance(data, dict) else data
        logger.info(
            "GET /api/v1/jira/projects/%s/epics — success, count=%d",
            project_key, len(epics),
        )
        return epics
    except requests.RequestException as exc:
        logger.error(
            "GET /api/v1/jira/projects/%s/epics — ke_client.jira_epics failed: %s",
            project_key, exc,
        )
        raise HTTPException(status_code=502, detail=f"KE API error: {exc}")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "GET /api/v1/jira/projects/%s/epics — error: %s", project_key, exc, exc_info=True
        )
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/v1/jira/projects/{projectKey}/issue-types")
def get_jira_issue_types(projectKey: str):
    """Fetch available issue types for a Jira project."""
    logger.info("GET /api/v1/jira/projects/%s/issue-types — start", projectKey)

    if not re.match(r'^[A-Z][A-Z0-9]+$', projectKey):
        logger.error(
            "GET /api/v1/jira/projects/%s/issue-types — rejected: invalid projectKey", projectKey
        )
        raise HTTPException(status_code=400, detail="Invalid project key format")

    try:
        data = ke_client.jira_issue_types(project=projectKey)
        issue_types = data.get("issue_types", data) if isinstance(data, dict) else data
        logger.info(
            "GET /api/v1/jira/projects/%s/issue-types — success, count=%d",
            projectKey, len(issue_types),
        )
        return issue_types
    except requests.RequestException as exc:
        logger.error(
            "GET /api/v1/jira/projects/%s/issue-types — ke_client.jira_issue_types failed: %s",
            projectKey, exc,
        )
        raise HTTPException(status_code=502, detail=f"KE API error: {exc}")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "GET /api/v1/jira/projects/%s/issue-types — error: %s", projectKey, exc, exc_info=True
        )
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/v1/jira/search")
async def jira_search_proxy(
    project: str = Query(..., description="Jira project key (e.g. SUP)"),
    type: str = Query("", description="Issue type filter"),
    status: str = Query("", description="Status filter"),
    max_results: int = Query(50, ge=1, le=100, description="Max issues"),
):
    """Proxy to KE jira-search endpoint."""
    logger.info(
        "GET /api/v1/jira/search — start, project=%s type=%r status=%r max=%d",
        project, type, status, max_results,
    )
    # Validate project key
    if not re.match(r"^[A-Z][A-Z0-9]+$", project):
        logger.error("GET /api/v1/jira/search — rejected: invalid project=%s", project)
        raise HTTPException(status_code=400, detail=f"Invalid project key: {project}")
    try:
        result = ke_client.jira_search(project, type, status, max_results)
        logger.info(
            "GET /api/v1/jira/search — success, total=%d",
            result.get("total", 0) if isinstance(result, dict) else 0,
        )
        return result
    except requests.RequestException as exc:
        logger.error("GET /api/v1/jira/search — KE API error: %s", exc)
        raise HTTPException(status_code=502, detail=f"KE API error: {exc}")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("GET /api/v1/jira/search — error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Jira Sync (force) endpoint
# ---------------------------------------------------------------------------

@router.post("/api/v1/jira/sync")
def jira_sync():
    """Trigger forced Jira sync via knowledge-engine ke_client."""
    import json as _json

    logger.info("POST /api/v1/jira/sync — start")

    if not _jira_sync_lock.acquire(blocking=False):
        logger.warning("POST /api/v1/jira/sync — rejected: sync already running")
        raise HTTPException(status_code=409, detail="Jira sync is already running")

    try:
        prefs = _read_user_prefs()
        should_notify = prefs.get("jira_sync_notify", True)
        logger.info("POST /api/v1/jira/sync — should_notify=%s", should_notify)

        data = ke_client.jira_sync(notify=should_notify)
        logger.info("POST /api/v1/jira/sync — ke_client.jira_sync returned")

        sync_result = {
            "status": data.get("status", "ok"),
            "new": data.get("new", 0),
            "updated": data.get("updated", 0),
            "closed": data.get("closed", 0),
            "errors": data.get("errors", 0),
            "logged": data.get("logged", 0),
            "message": data.get("message", "Sync completed"),
        }

        # Write last_run_result back into state file atomically
        state_file = _PLATFORM_DATA / ".jira-sync-state.json"
        try:
            if state_file.exists():
                state = _json.loads(state_file.read_text(encoding="utf-8"))
            else:
                state = {}
            state["last_run_result"] = {
                "new": sync_result["new"],
                "updated": sync_result["updated"],
                "closed": sync_result["closed"],
                "errors": sync_result["errors"],
            }
            tmp_file = _PLATFORM_DATA / ".jira-sync-state.json.tmp"
            tmp_file.write_text(
                _json.dumps(state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(str(tmp_file), str(state_file))
            logger.info("POST /api/v1/jira/sync — state file updated")
        except Exception as exc:
            logger.error("POST /api/v1/jira/sync — failed to update state file: %s", exc)

        _cache.invalidate()
        logger.info(
            "POST /api/v1/jira/sync — success: new=%d updated=%d closed=%d errors=%d",
            sync_result["new"], sync_result["updated"],
            sync_result["closed"], sync_result["errors"],
        )
        return sync_result

    except requests.RequestException as exc:
        logger.error("POST /api/v1/jira/sync — ke_client.jira_sync failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"KE API error: {exc}")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("POST /api/v1/jira/sync — error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        _jira_sync_lock.release()


@router.get("/api/v1/jira/sync-status")
def jira_sync_status():
    """Read .jira-sync-state.json from vault and return sync status summary."""
    import json as _json

    logger.info("GET /api/v1/jira/sync-status — start")

    cached = _cache.get("jira_sync_status")
    if cached is not None:
        logger.info("GET /api/v1/jira/sync-status — returning cached")
        return cached

    state_file = _PLATFORM_DATA / ".jira-sync-state.json"
    state = {}

    if not state_file.exists():
        logger.info("GET /api/v1/jira/sync-status — state file not found, returning nulls")
    else:
        try:
            state = _json.loads(state_file.read_text(encoding="utf-8"))
        except (ValueError, TypeError, OSError) as exc:
            logger.error("GET /api/v1/jira/sync-status — failed to read/parse state file: %s", exc)

    result = {
        "last_sync": state.get("last_sync") or None,
        "tracked": len(state.get("issues", {})),
        "last_new": state.get("last_run_result", {}).get("new"),
        "last_updated": state.get("last_run_result", {}).get("updated"),
        "last_closed": state.get("last_run_result", {}).get("closed"),
        "last_errors": state.get("last_run_result", {}).get("errors"),
    }

    _cache.set("jira_sync_status", result)
    logger.info("GET /api/v1/jira/sync-status — success, tracked=%d", result["tracked"])
    return result
