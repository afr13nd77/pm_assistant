"""Роутер задач (tasks): список задач по доменам + поиск задачи по jira_key.

Также содержит общие для tasks/epics константы (_DONE_STATUSES,
_STATUS_WEIGHT) и хелпер _build_task_indices, которые импортируются
роутером epics.py (T-20).
"""

import logging

from fastapi import APIRouter, HTTPException, Query

from ..vault_cache import _cache
from ..vault_parsers import _parse_tags, _safe_int, parse_note
from ..vault_scanner import _domain_from_path, _scan_domain_folders

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Tasks"])


_DONE_STATUSES = frozenset({
    "done", "готово", "готово/closed", "closed", "resolved",
    "deploy", "staging",
})

_STATUS_WEIGHT = {
    "todo": 0,
    "backlog": 0,
    "draft": 0,
    "in-progress": 40,
    "development": 40,
    "in-review": 65,
    "code-review": 65,
    "in-testing": 80,
    "deploy": 100,
    "staging": 100,
    "done": 100,
    "готово": 100,
    "готово/closed": 100,
    "closed": 100,
    "resolved": 100,
}


def _build_task_indices() -> tuple[dict[str, str], dict[str, list[dict]]]:
    """Build both task_status and epic_task indices in a single scan pass."""
    cached = _cache.get("_task_indices")
    if cached is not None:
        return cached

    status_index: dict[str, str] = {}
    epic_index: dict[str, list[dict]] = {}

    try:
        task_files = _scan_domain_folders("tasks")
        for f in task_files:
            try:
                note = parse_note(f)
                jira_key = note.get("jira_key", "").strip()
                if jira_key:
                    status_index[jira_key] = note.get("status", "")
                    epic_key = note.get("epic_key", "").strip()
                    if epic_key:
                        epic_index.setdefault(epic_key, []).append({
                            "id": jira_key,
                            "title": note.get("title", ""),
                            "status": note.get("status", ""),
                        })
            except Exception:
                continue

        logger.info(
            "_build_task_indices: %d status entries, %d epic entries",
            len(status_index), len(epic_index),
        )
        result = (status_index, epic_index)
        _cache.set("_task_indices", result)
        return result
    except Exception as exc:
        logger.error("_build_task_indices — error: %s", exc)
        raise


@router.get("/api/v1/tasks")
def get_tasks(domain: str | None = Query(default=None)):
    """Read .md files from wiki/domains/*/tasks/.

    Optional ?domain=<name> query parameter to filter by one domain.
    Each returned item includes a 'domain' field.
    """
    logger.info("GET /api/v1/tasks — start, domain=%s", domain)

    cache_key = f"tasks:{domain or '__all__'}"
    cached = _cache.get(cache_key)
    if cached is not None:
        logger.info("GET /api/v1/tasks -- returning cached (%d tasks)", len(cached))
        return cached

    files = _scan_domain_folders("tasks", domain_filter=domain)
    logger.info("GET /api/v1/tasks — found %d files", len(files))

    results = []
    for f in files:
        try:
            note = parse_note(f)
            results.append(
                {
                    "filename": note["filename"],
                    "date": note["date"],
                    "title": note["title"],
                    "type": note.get("type", ""),
                    "priority": note.get("priority", ""),
                    "story_points": _safe_int(note.get("story_points", 0)),
                    "status": note.get("status", "draft"),
                    "domain": _domain_from_path(f),
                    "body": note["body"],
                    "jira_key": note.get("jira_key", ""),
                    "jira_url": note.get("jira_url", ""),
                    "epic_key": note.get("epic_key", ""),
                }
            )
        except Exception as exc:
            logger.error("GET /api/v1/tasks — failed to parse %s: %s", f.name, exc)
            continue

    results.sort(key=lambda x: x["date"], reverse=True)
    logger.info("GET /api/v1/tasks — returning %d tasks", len(results))
    _cache.set(cache_key, results)
    return results


@router.get("/api/v1/tasks/by-key/{jira_key}")
def get_task_by_key(jira_key: str):
    """Find a task file by its jira_key and return full details including body."""
    logger.info("GET /api/v1/tasks/by-key/%s — start", jira_key)

    task_files = _scan_domain_folders("tasks")
    for f in task_files:
        try:
            note = parse_note(f)
            if note.get("jira_key", "").strip() == jira_key:
                logger.info("GET /api/v1/tasks/by-key/%s — found: %s", jira_key, f.name)
                return {
                    "filename": note["filename"],
                    "date": note["date"],
                    "title": note["title"],
                    "type": note.get("type", ""),
                    "priority": note.get("priority", ""),
                    "story_points": _safe_int(note.get("story_points", 0)),
                    "status": note.get("status", "draft"),
                    "domain": _domain_from_path(f),
                    "body": note["body"],
                    "jira_key": jira_key,
                    "jira_url": note.get("jira_url", ""),
                    "tags": _parse_tags(note.get("tags", "")),
                }
        except Exception as exc:
            logger.error("GET /api/v1/tasks/by-key/%s — error parsing %s: %s", jira_key, f.name, exc)
            continue

    logger.info("GET /api/v1/tasks/by-key/%s — not found", jira_key)
    raise HTTPException(status_code=404, detail=f"Task with jira_key '{jira_key}' not found")
