"""Vault Operations: timeline, synthesize, pipeline proxy, vault health, search, overview queue.

Endpoints:
  GET  /api/v1/timeline/{ticket_id}
  POST /api/v1/synthesize
  GET  /api/v1/pipeline
  GET  /api/v1/vault/health
  GET  /api/v1/search
  GET  /api/v1/overview/queue
"""

import logging
import urllib.parse
from datetime import datetime, timedelta

import requests
from fastapi import APIRouter, HTTPException, Query

from shared.vault_paths import (
    VAULT_PATH,
    all_domains,
    wiki_domain_dir,
    wiki_meetings,
    wiki_reports,
)

from .. import ke_client
from ..vault_cache import _cache
from ..vault_parsers import (
    _calculate_readiness,
    _extract_section,
    _parse_tags,
    parse_note,
)
from ..vault_scanner import (
    _domain_from_path,
    _is_service_file,
    _scan_domain_folders,
)
from ..vault_search import _get_search_index

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Vault Operations"])


@router.get("/api/v1/timeline/{ticket_id}")
def get_timeline(ticket_id: str):
    """Search all vault folders for mentions of ticket_id and build chronological timeline.

    Searches domain-based folders (ideas, tasks, epics, prds per domain)
    and cross-domain folders (meetings, reports).
    """
    logger.info("GET /api/v1/timeline/%s — start", ticket_id)

    events = []
    # --- Domain-based folders ---
    domain_searches = [
        ("ideas", "idea"),
        ("tasks", "jira"),
        ("epics", "epic"),
        ("prds", "pm"),
    ]
    for artifact_type, default_stage in domain_searches:
        for domain in all_domains():
            try:
                folder = wiki_domain_dir(domain, artifact_type)
            except ValueError:
                continue
            if not folder.exists():
                continue
            folder_label = f"wiki/domains/{domain}/{artifact_type}"
            logger.info(
                "GET /api/v1/timeline/%s — searching %s", ticket_id, folder_label
            )
            for f in folder.glob("*.md"):
                if _is_service_file(f):
                    continue
                try:
                    file_content = f.read_text(encoding="utf-8")
                    if ticket_id.lower() not in file_content.lower():
                        continue

                    note = parse_note(f)
                    stage = default_stage
                    tags_raw = note.get("tags", "")
                    tags = _parse_tags(tags_raw) if isinstance(tags_raw, str) else tags_raw
                    if "pipeline" in tags and "prd" in tags:
                        stage = "pm"
                    elif "pipeline" in tags and "enriched" in [t.lower() for t in tags]:
                        stage = "enriched"
                    stage_val = note.get("stage", stage)

                    events.append({
                        "stage": stage_val,
                        "date": note["date"],
                        "title": note["title"],
                        "detail": note["body"][:200],
                        "body": note["body"],
                        "source_file": f"{folder_label}/{f.name}",
                    })
                    logger.info(
                        "GET /api/v1/timeline/%s — found mention in %s/%s (stage=%s)",
                        ticket_id, folder_label, f.name, stage_val,
                    )
                except Exception as exc:
                    logger.error(
                        "GET /api/v1/timeline — error reading %s: %s", f.name, exc
                    )
                    continue

    # --- Cross-domain folders ---
    cross_domain_searches = [
        (wiki_meetings, "meeting", "wiki/meetings"),
        (wiki_reports, "report", "wiki/reports"),
    ]
    for folder_fn, default_stage, folder_label in cross_domain_searches:
        folder = folder_fn()
        if not folder.exists():
            logger.info(
                "GET /api/v1/timeline/%s — folder %s not found, skipping",
                ticket_id, folder_label,
            )
            continue
        logger.info(
            "GET /api/v1/timeline/%s — searching %s", ticket_id, folder_label
        )
        for f in folder.glob("*.md"):
            if _is_service_file(f):
                continue
            try:
                file_content = f.read_text(encoding="utf-8")
                if ticket_id.lower() not in file_content.lower():
                    continue

                note = parse_note(f)
                stage = default_stage
                tags_raw = note.get("tags", "")
                tags = _parse_tags(tags_raw) if isinstance(tags_raw, str) else tags_raw
                if "pipeline" in tags and "prd" in tags:
                    stage = "pm"
                elif "pipeline" in tags and "enriched" in [t.lower() for t in tags]:
                    stage = "enriched"
                stage_val = note.get("stage", stage)

                events.append({
                    "stage": stage_val,
                    "date": note["date"],
                    "title": note["title"],
                    "detail": note["body"][:200],
                    "body": note["body"],
                    "source_file": f"{folder_label}/{f.name}",
                })
                logger.info(
                    "GET /api/v1/timeline/%s — found mention in %s/%s (stage=%s)",
                    ticket_id, folder_label, f.name, stage_val,
                )
            except Exception as exc:
                logger.error(
                    "GET /api/v1/timeline — error reading %s: %s", f.name, exc
                )
                continue

    # Sort by date
    events.sort(key=lambda e: e["date"])

    # Calculate metrics
    metrics = {}
    if events:
        dates = [e["date"] for e in events if e["date"]]
        if len(dates) >= 2:
            try:
                first = datetime.strptime(dates[0], "%Y-%m-%d")
                last = datetime.strptime(dates[-1], "%Y-%m-%d")
                metrics["days_to_ship"] = (last - first).days
            except ValueError:
                logger.error(
                    "GET /api/v1/timeline/%s — failed to parse dates for days_to_ship: %s, %s",
                    ticket_id, dates[0], dates[-1],
                )

        idea_dates = [e["date"] for e in events if e["stage"] == "idea"]
        prd_dates = [e["date"] for e in events if e["stage"] == "pm"]
        if idea_dates and prd_dates:
            try:
                idea_d = datetime.strptime(idea_dates[0], "%Y-%m-%d")
                prd_d = datetime.strptime(prd_dates[0], "%Y-%m-%d")
                metrics["idea_to_prd_days"] = (prd_d - idea_d).days
            except ValueError:
                logger.error(
                    "GET /api/v1/timeline/%s — failed to parse dates for idea_to_prd_days: %s, %s",
                    ticket_id, idea_dates[0], prd_dates[0],
                )

    logger.info("GET /api/v1/timeline/%s — returning %d events", ticket_id, len(events))
    return {
        "ticket_id": ticket_id,
        "events": events,
        "metrics": metrics,
    }


@router.post("/api/v1/synthesize")
def synthesize_inbox():
    """Run knowledge-engine synthesize via ke_client."""
    logger.info("POST /api/v1/synthesize — start")
    try:
        data = ke_client.synthesize()
        _cache.invalidate()
        logger.info("POST /api/v1/synthesize — success: %s", data.get("status"))
        return data
    except requests.RequestException as exc:
        logger.error("POST /api/v1/synthesize — ke_client.synthesize failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"KE API error: {exc}")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("POST /api/v1/synthesize — error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/v1/pipeline")
def get_pipeline():
    """Proxy to idea-pipeline service.

    Imports list_pipelines from app.pipeline_client and forwards the result.
    """
    logger.info("GET /api/v1/pipeline — start")
    try:
        from app.pipeline_client import list_pipelines

        logger.info("GET /api/v1/pipeline — calling list_pipelines")
        result = list_pipelines()
        logger.info("GET /api/v1/pipeline — success, total=%s", result.get("total", "?"))
        return result
    except Exception as exc:
        logger.error("GET /api/v1/pipeline — error: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Pipeline service error: {exc}")


# ---------------------------------------------------------------------------
# Health Score
# ---------------------------------------------------------------------------

@router.get("/api/v1/vault/health")
def vault_health():
    """Calculate or return cached vault health score with trends."""
    cache_key = "vault_health"
    cached = _cache.get(cache_key)
    if cached is not None:
        logger.info("vault_health: returning cached result")
        return cached

    logger.info("vault_health: cache miss, running health calculation via ke_client")

    try:
        data = ke_client.health()
    except requests.RequestException as exc:
        logger.error("vault_health: ke_client.health failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"KE API error: {exc}")
    except Exception as exc:
        logger.error("vault_health: health calculation failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Health calculation failed: {exc}")

    _cache.set(cache_key, data)
    logger.info("vault_health: completed, score=%s grade=%s", data.get("score"), data.get("grade"))
    return data


# ---------------------------------------------------------------------------
# Full-text Search endpoint
# ---------------------------------------------------------------------------

@router.get("/api/v1/search")
def search_vault(
    q: str = Query(..., min_length=2, max_length=200),
    limit: int = Query(default=20, ge=1, le=50),
):
    logger.info("GET /api/v1/search — q=%r, limit=%d", q, limit)
    try:
        index = _get_search_index()
    except Exception as exc:
        logger.error("GET /api/v1/search — index build failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Search index build failed: {exc}")
    results = index.query(q, limit=limit)
    logger.info("GET /api/v1/search — returning %d results for q=%r", len(results), q)
    return {
        "query": q,
        "total": len(results),
        "results": results,
    }


# ---------------------------------------------------------------------------
# Today's Queue endpoint
# ---------------------------------------------------------------------------

@router.get("/api/v1/overview/queue")
async def overview_queue():
    """Return prioritized list of items requiring PM attention today (max 5).

    Priority order:
      1 — Ideas with readiness=100, status='Готова к производству', no PRD found.
      2 — Ideas with readiness<50, status in {Новая, Проверка гипотезы}, stale >24h.
      3 — Meeting files without decisions AND without action_items.
      4 — Ideas with status='Проверка гипотезы', stale >48h (catch-all, deduped).
    """
    logger.info("GET /api/v1/overview/queue — start")
    cached = _cache.get("overview_queue")
    if cached is not None:
        logger.info("GET /api/v1/overview/queue — returning cached")
        return cached

    from datetime import timezone

    now = datetime.now(timezone.utc)
    cutoff_24h = now - timedelta(hours=24)
    cutoff_48h = now - timedelta(hours=48)

    items: list[dict] = []

    # ------------------------------------------------------------------
    # Scan all idea files once
    # ------------------------------------------------------------------
    try:
        idea_paths = _scan_domain_folders("ideas")
    except Exception as exc:
        logger.error("overview_queue — scan ideas error: %s", exc)
        idea_paths = []

    logger.info("overview_queue — found %d idea files to evaluate", len(idea_paths))

    for idea_path in idea_paths:
        try:
            note = parse_note(idea_path)
        except Exception as exc:
            logger.error("overview_queue — failed to parse idea %s: %s", idea_path.name, exc)
            continue

        readiness = _calculate_readiness(note.get("body", ""))
        status = note.get("status", "")

        filename = note.get("filename", "")
        title = note.get("title", idea_path.stem)
        idea_id = filename.replace(".md", "") if filename else idea_path.stem

        # File modification time (UTC-aware)
        try:
            mtime_ts = idea_path.stat().st_mtime
            mtime = datetime.fromtimestamp(mtime_ts, tz=timezone.utc)
        except OSError as exc:
            logger.warning("overview_queue — cannot stat %s: %s", idea_path, exc)
            mtime = None

        # Priority 1: readiness=100, status=ready, no PRD exists
        if readiness == 100 and status == "Готова к производству":
            domain = _domain_from_path(idea_path)
            has_prd = False
            if domain and domain != "unknown":
                prd_dir = VAULT_PATH / "wiki" / "domains" / domain / "prds"
                if prd_dir.exists():
                    has_prd = any(
                        idea_id.lower() in f.stem.lower()
                        for f in prd_dir.glob("*.md")
                    )
            if not has_prd:
                logger.info(
                    "overview_queue — priority 1 item: %s (readiness=100, no PRD)", idea_id
                )
                items.append({
                    "type": "idea",
                    "id": idea_id,
                    "title": title,
                    "reason": "readiness=100, PRD не создан",
                    "priority": 1,
                    "link": f"ideas.html?status={urllib.parse.quote('Готова к производству')}",
                })

        # Priority 2: readiness<50, active early status, stale >24h
        elif readiness < 50 and status in ("Новая", "Проверка гипотезы"):
            if mtime and mtime < cutoff_24h:
                hours_stale = int((now - mtime).total_seconds() // 3600)
                logger.info(
                    "overview_queue — priority 2 item: %s (%dh stale, readiness=%d%%)",
                    idea_id, hours_stale, readiness,
                )
                items.append({
                    "type": "idea",
                    "id": idea_id,
                    "title": title,
                    "reason": f"{hours_stale}ч без обновления, readiness={readiness}%",
                    "priority": 2,
                    "link": "ideas.html",
                })

    # ------------------------------------------------------------------
    # Priority 3: meeting files without decisions and without action_items
    # ------------------------------------------------------------------
    try:
        meetings_dir = wiki_meetings()
        if meetings_dir.exists():
            meeting_files = sorted(
                (f for f in meetings_dir.glob("*.md") if not _is_service_file(f)),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )[:20]
            for mf in meeting_files:
                try:
                    note = parse_note(mf)
                    body = note.get("body", "")
                    decisions_raw = _extract_section(body, "Решения")
                    decisions = [
                        line.strip()
                        for line in decisions_raw.splitlines()
                        if line.strip() and line.strip() != "-"
                    ] if decisions_raw else []
                    action_items_raw = _extract_section(body, "Action Items")
                    action_items = [
                        line.strip()
                        for line in action_items_raw.splitlines()
                        if "- [ ]" in line
                    ] if action_items_raw else []
                    if not decisions and not action_items:
                        logger.info(
                            "overview_queue — priority 3 item: meeting %s (no decisions/actions)",
                            mf.stem,
                        )
                        items.append({
                            "type": "meeting",
                            "id": mf.stem,
                            "title": note.get("title", mf.stem),
                            "reason": "decisions и action_items отсутствуют",
                            "priority": 3,
                            "link": "board.html",
                        })
                except Exception as exc:
                    logger.error(
                        "overview_queue — failed to parse meeting %s: %s", mf.name, exc
                    )
                    continue
        else:
            logger.info("overview_queue — meetings dir does not exist, skipping priority 3")
    except Exception as exc:
        logger.warning("overview_queue — meetings scan error: %s", exc)

    # ------------------------------------------------------------------
    # Priority 4: stale 'Проверка гипотезы' >48h (deduplicated vs priority 2)
    # ------------------------------------------------------------------
    already_ids = {i["id"] for i in items}
    for idea_path in idea_paths:
        try:
            note = parse_note(idea_path)
        except Exception as exc:
            logger.error(
                "overview_queue — failed to parse idea (p4) %s: %s", idea_path.name, exc
            )
            continue

        if note.get("status") != "Проверка гипотезы":
            continue

        filename = note.get("filename", "")
        idea_id = filename.replace(".md", "") if filename else idea_path.stem
        if idea_id in already_ids:
            continue

        readiness = _calculate_readiness(note.get("body", ""))

        try:
            mtime_ts = idea_path.stat().st_mtime
            mtime = datetime.fromtimestamp(mtime_ts, tz=timezone.utc)
        except OSError as exc:
            logger.warning("overview_queue — cannot stat %s (p4): %s", idea_path, exc)
            continue

        if mtime < cutoff_48h:
            logger.info(
                "overview_queue — priority 4 item: %s (in Проверка гипотезы >48h)", idea_id
            )
            items.append({
                "type": "idea",
                "id": idea_id,
                "title": note.get("title", idea_id),
                "reason": f"в проверке >48ч, readiness={readiness}%",
                "priority": 4,
                "link": f"ideas.html?status={urllib.parse.quote('Проверка гипотезы')}",
            })

    # Sort by priority ascending, return top 5
    items.sort(key=lambda x: x["priority"])
    result = items[:5]
    logger.info("overview_queue — returning %d items", len(result))
    _cache.set("overview_queue", result)
    return result
