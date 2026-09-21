"""Роутер эпиков (epics): список эпиков по доменам с расчётом прогресса.

Использует _build_task_indices и _STATUS_WEIGHT из роутера tasks.py
(кросс-зависимость, см. tasks.py docstring, T-19/T-20).
"""

import logging

from fastapi import APIRouter, Query

from ..vault_cache import _cache
from ..vault_parsers import _extract_section, parse_epic_note
from ..vault_scanner import _domain_from_path, _scan_domain_folders
from . import tasks as tasks_router

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Epics"])


@router.get("/api/v1/epics")
def get_epics(domain: str | None = Query(default=None)):
    """Read .md files from wiki/domains/*/epics/ with progress calculation.

    Uses yaml.safe_load for proper parsing of complex frontmatter
    (tickets as list of objects).

    Ticket statuses are resolved from synced task files (jira_key lookup).
    Progress is calculated as % of tickets in done/closed/resolved status.

    Optional ?domain=<name> query parameter to filter by one domain.
    Each returned item includes a 'domain' field.
    """
    logger.info("GET /api/v1/epics — start, domain=%s", domain)

    cache_key = f"epics:{domain or '__all__'}"
    cached = _cache.get(cache_key)
    if cached is not None:
        logger.info("GET /api/v1/epics -- returning cached (%d epics)", len(cached))
        return cached

    task_status_index, epic_task_index = tasks_router._build_task_indices()

    files = _scan_domain_folders("epics", domain_filter=domain)
    logger.info("GET /api/v1/epics — found %d files", len(files))

    results = []
    for f in files:
        try:
            note = parse_epic_note(f)
            tickets = note.get("tickets", [])
            if not isinstance(tickets, list):
                tickets = []

            normalized_tickets = []
            for t in tickets:
                if isinstance(t, dict):
                    ticket_id = str(t.get("id", ""))
                    epic_status = str(t.get("status", ""))
                    real_status = task_status_index.get(ticket_id, "")
                    normalized_tickets.append(
                        {
                            "id": ticket_id,
                            "title": str(t.get("title", "")),
                            "status": real_status if real_status else epic_status,
                        }
                    )

            epic_jira_id = str(note.get("jira_id") or note.get("jira_key") or "").strip()
            if epic_jira_id and epic_jira_id in epic_task_index:
                existing_ids = {t["id"] for t in normalized_tickets}
                for linked in epic_task_index[epic_jira_id]:
                    if linked["id"] not in existing_ids:
                        normalized_tickets.append(linked)

            total_count = len(normalized_tickets)
            if total_count > 0:
                total_weight = sum(
                    tasks_router._STATUS_WEIGHT.get(t["status"].lower(), 20)
                    for t in normalized_tickets
                )
                progress = round(total_weight / total_count)
            else:
                progress = 0

            body = note.get("body", "")
            results.append(
                {
                    "id": str(note.get("id") or f.stem),
                    "title": note["title"],
                    "horizon": str(note.get("horizon") or ""),
                    "priority": str(note.get("priority") or ""),
                    "status": str(note.get("status") or ""),
                    "progress": progress,
                    "prd_status": str(note.get("prd_status") or ""),
                    "confluence_link": str(note.get("confluence_link") or ""),
                    "tickets": normalized_tickets,
                    "goal": _extract_section(body, "Goal"),
                    "scope": _extract_section(body, "Scope"),
                    "acceptance_criteria": _extract_section(body, "Acceptance Criteria"),
                    "domain": _domain_from_path(f),
                    "jira_key": str(note.get("jira_key") or note.get("jira_id") or ""),
                    "jira_url": str(note.get("jira_url") or ""),
                    "filename": note["filename"],
                    "body": body,
                }
            )
        except Exception as exc:
            logger.error("GET /api/v1/epics — failed to parse %s: %s", f.name, exc)
            continue

    logger.info(f"GET /api/v1/epics — returning {len(results)} epics")
    _cache.set(cache_key, results)
    return results
