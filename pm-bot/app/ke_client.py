"""HTTP client for Knowledge Engine API."""

from __future__ import annotations

import logging
import os
from typing import Optional

import requests

from shared.settings import get as get_setting

logger = logging.getLogger(__name__)

KE_API_URL = os.getenv("KE_API_URL", "http://knowledge-engine:8001")


def _get_timeout(operation: str) -> int:
    """Get timeout for operation from settings."""
    return get_setting(f"timeouts.{operation}", get_setting("timeouts.default", 60))


def _post(path: str, timeout: int, json: dict | None = None) -> dict:
    """POST request to KE API."""
    url = f"{KE_API_URL}{path}"
    logger.info("ke_client POST %s", url)
    resp = requests.post(url, json=json or {}, timeout=timeout)
    resp.raise_for_status()
    result = resp.json()
    logger.info("ke_client POST %s -> status=%s", url, result.get("status", "ok"))
    return result


def _get(path: str, timeout: int, params: dict | None = None) -> dict:
    """GET request to KE API."""
    url = f"{KE_API_URL}{path}"
    logger.info("ke_client GET %s", url)
    resp = requests.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    result = resp.json()
    status = result.get("status", "ok") if isinstance(result, dict) else "ok"
    logger.info("ke_client GET %s -> status=%s, type=%s", url, status, type(result).__name__)
    return result


# ---------------------------------------------------------------------------
# 1. POST /api/v1/enrich
# ---------------------------------------------------------------------------

def enrich(filepath: str, dry_run: bool = False) -> dict:
    """Enrich a vault artifact with metadata."""
    return _post("/api/v1/enrich", _get_timeout("enrich"),
                 json={"filepath": filepath, "dry_run": dry_run})


# ---------------------------------------------------------------------------
# 2. POST /api/v1/synthesize
# ---------------------------------------------------------------------------

def synthesize(notify: bool = False, dry_run: bool = False,
               min_ideas: int = 1) -> dict:
    """Run synthesis across vault ideas."""
    return _post("/api/v1/synthesize", _get_timeout("synthesize"),
                 json={"notify": notify, "dry_run": dry_run,
                        "min_ideas": min_ideas})


# ---------------------------------------------------------------------------
# 3. POST /api/v1/fetch-meetings
# ---------------------------------------------------------------------------

def fetch_meetings(notify: bool = False, dry_run: bool = False) -> dict:
    """Fetch new meetings from calendar sources."""
    return _post("/api/v1/fetch-meetings", _get_timeout("fetch_meetings"),
                 json={"notify": notify, "dry_run": dry_run})


# ---------------------------------------------------------------------------
# 4. POST /api/v1/jira-sync
# ---------------------------------------------------------------------------

def jira_sync(notify: bool = False, dry_run: bool = False) -> dict:
    """Synchronize Jira issues with vault."""
    return _post("/api/v1/jira-sync", _get_timeout("jira_sync"),
                 json={"notify": notify, "dry_run": dry_run})


# ---------------------------------------------------------------------------
# 5. POST /api/v1/jira-import
# ---------------------------------------------------------------------------

def jira_import(key: str) -> dict:
    """Import a single Jira issue by key."""
    return _post("/api/v1/jira-import", _get_timeout("jira_import"),
                 json={"key": key})


# ---------------------------------------------------------------------------
# 6. POST /api/v1/jira-create
# ---------------------------------------------------------------------------

def jira_create(file: str, project: str, type: str = "Task",
                summary: str = "", epic: str = "") -> dict:
    """Create a Jira issue from a vault artifact."""
    return _post("/api/v1/jira-create", _get_timeout("jira_create"),
                 json={"file": file, "project": project, "type": type,
                        "summary": summary, "epic": epic})


# ---------------------------------------------------------------------------
# 7. GET /api/v1/jira-projects
# ---------------------------------------------------------------------------

def jira_projects() -> dict:
    """List accessible Jira projects."""
    return _get("/api/v1/jira-projects", _get_timeout("jira_projects"))


# ---------------------------------------------------------------------------
# 8. GET /api/v1/jira-epics
# ---------------------------------------------------------------------------

def jira_epics(project: str) -> dict:
    """List epics for a Jira project."""
    return _get("/api/v1/jira-epics", _get_timeout("jira_epics"),
                params={"project": project})


# ---------------------------------------------------------------------------
# 9. GET /api/v1/jira-issue-types
# ---------------------------------------------------------------------------

def jira_issue_types(project: str) -> dict:
    """List issue types for a Jira project."""
    return _get("/api/v1/jira-issue-types", _get_timeout("jira_issue_types"),
                params={"project": project})


# ---------------------------------------------------------------------------
# 10. GET /api/v1/jira-search
# ---------------------------------------------------------------------------

def jira_search(
    project: str, type: str = "", status: str = "", max_results: int = 50
) -> dict:
    """Search Jira issues by project with optional filters."""
    logger.info("jira_search: project=%s type=%r status=%r max=%d", project, type, status, max_results)
    params: dict = {"project": project, "max_results": max_results}
    if type:
        params["type"] = type
    if status:
        params["status"] = status
    return _get("/api/v1/jira-search", _get_timeout("jira_search"), params=params)


# ---------------------------------------------------------------------------
# 11. GET /api/v1/domains
# ---------------------------------------------------------------------------

def domain_list() -> dict:
    """List all vault domains."""
    return _get("/api/v1/domains", _get_timeout("default"))


# ---------------------------------------------------------------------------
# 12. POST /api/v1/domains
# ---------------------------------------------------------------------------

def domain_create(name: str, display_name: Optional[str] = None,
                  color: Optional[str] = None,
                  labels: Optional[str] = None) -> dict:
    """Create a new vault domain."""
    body: dict = {"name": name}
    if display_name is not None:
        body["display_name"] = display_name
    if color is not None:
        body["color"] = color
    if labels is not None:
        body["labels"] = labels
    return _post("/api/v1/domains", _get_timeout("default"), json=body)


# ---------------------------------------------------------------------------
# 13. POST /api/v1/lint
# ---------------------------------------------------------------------------

def lint() -> dict:
    """Run vault health lint check."""
    return _post("/api/v1/lint", _get_timeout("lint"))


# ---------------------------------------------------------------------------
# 14. GET /api/v1/status
# ---------------------------------------------------------------------------

def status() -> dict:
    """Get vault status summary."""
    return _get("/api/v1/status", _get_timeout("status"))


# ---------------------------------------------------------------------------
# 15. POST /api/v1/rebuild-index
# ---------------------------------------------------------------------------

def rebuild_index(domain: Optional[str] = None) -> dict:
    """Rebuild domain indices."""
    body: dict = {}
    if domain is not None:
        body["domain"] = domain
    return _post("/api/v1/rebuild-index", _get_timeout("rebuild_index"),
                 json=body)


# ---------------------------------------------------------------------------
# 16. POST /api/v1/ingest-clippings
# ---------------------------------------------------------------------------

def ingest_clippings(dry_run: bool = False, notify: bool = False) -> dict:
    """Ingest Kindle clippings into vault."""
    return _post("/api/v1/ingest-clippings", _get_timeout("ingest_clippings"),
                 json={"dry_run": dry_run, "notify": notify})


# ---------------------------------------------------------------------------
# 17. GET /api/v1/health
# ---------------------------------------------------------------------------

def health() -> dict:
    """Get vault health score and trends."""
    return _get("/api/v1/health", _get_timeout("health"))


# ---------------------------------------------------------------------------
# 18. POST /api/v1/jira-key-sync/patch
# ---------------------------------------------------------------------------

def jira_key_sync_patch(filepath: str, keys_map: dict[str, str]) -> dict:
    """Patch daily note with Jira key links."""
    return _post("/api/v1/jira-key-sync/patch", _get_timeout("default"),
                 json={"filepath": filepath, "keys_map": keys_map})


# ---------------------------------------------------------------------------
# 19. POST /api/v1/jira-key-sync/sync
# ---------------------------------------------------------------------------

def jira_key_sync_sync(content: str) -> dict:
    """Sync Jira keys found in daily note content."""
    return _post("/api/v1/jira-key-sync/sync", _get_timeout("default"),
                 json={"content": content})


# ---------------------------------------------------------------------------
# 20. POST /api/v1/decay/touch
# ---------------------------------------------------------------------------

def touch(filepath: str) -> dict:
    """Touch a vault artifact to reset its decay timer."""
    return _post("/api/v1/decay/touch", _get_timeout("default"),
                 json={"filepath": filepath})


# ---------------------------------------------------------------------------
# 21. POST /api/v1/decay/set-tier
# ---------------------------------------------------------------------------

def set_tier(filepath: str, tier: str) -> dict:
    """Set decay tier for a vault artifact."""
    return _post("/api/v1/decay/set-tier", _get_timeout("default"),
                 json={"filepath": filepath, "tier": tier})


# ---------------------------------------------------------------------------
# 22. GET /api/v1/creative
# ---------------------------------------------------------------------------

def get_creative(count: int = 5) -> list:
    """Get creative ideas from vault via KE."""
    return _get("/api/v1/creative", _get_timeout("default"),
                params={"count": count})


# ---------------------------------------------------------------------------
# 23. GET /api/v1/decay/snapshot
# ---------------------------------------------------------------------------

def decay_snapshot() -> dict:
    """Get full decay state snapshot from KE."""
    return _get("/api/v1/decay/snapshot", _get_timeout("default"))


# ---------------------------------------------------------------------------
# 24. POST /api/v1/digest/generate
# ---------------------------------------------------------------------------

def digest_generate(filepath: str, force: bool = False) -> dict:
    """Generate digest for a single wiki artifact."""
    logger.info("digest_generate: filepath=%s, force=%s", filepath, force)
    return _post("/api/v1/digest/generate", _get_timeout("default"),
                 json={"filepath": filepath, "force": force})


# ---------------------------------------------------------------------------
# 25. POST /api/v1/digest/bulk
# ---------------------------------------------------------------------------

def digest_bulk(domain: Optional[str] = None, type: Optional[str] = None,
                force: bool = False) -> dict:
    """Generate digests in bulk for wiki artifacts."""
    logger.info("digest_bulk: domain=%s, type=%s, force=%s", domain, type, force)
    body: dict = {"force": force}
    if domain is not None:
        body["domain"] = domain
    if type is not None:
        body["type"] = type
    return _post("/api/v1/digest/bulk", _get_timeout("long"),
                 json=body)


# ---------------------------------------------------------------------------
# 26. GET /api/v1/digest/status
# ---------------------------------------------------------------------------

def digest_status() -> dict:
    """Get digest coverage statistics."""
    logger.info("digest_status: fetching coverage stats")
    return _get("/api/v1/digest/status", _get_timeout("default"))
