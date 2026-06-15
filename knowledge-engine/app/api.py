"""Knowledge Engine HTTP API.

Thin FastAPI wrapper over existing CLI business logic.
Each endpoint mirrors a CLI command from cli.py and returns
the same JSON structure that _output_json() would print.
"""

from __future__ import annotations

import logging
import os
import pathlib
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from shared import vault_paths as _vp

logger = logging.getLogger(__name__)

app = FastAPI(title="Knowledge Engine API", version="1.0.0")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class EnrichRequest(BaseModel):
    filepath: str
    dry_run: bool = False


class SynthesizeRequest(BaseModel):
    notify: bool = False
    dry_run: bool = False
    min_ideas: int = 1


class FetchMeetingsRequest(BaseModel):
    notify: bool = False
    dry_run: bool = False


class JiraSyncRequest(BaseModel):
    notify: bool = False
    dry_run: bool = False


class JiraImportRequest(BaseModel):
    key: str


class JiraCreateRequest(BaseModel):
    file: str
    project: str
    type: str = "Task"
    summary: str = ""
    epic: str = ""


class DomainCreateRequest(BaseModel):
    name: str
    display_name: Optional[str] = None
    color: Optional[str] = None
    labels: Optional[str] = None


class LintRequest(BaseModel):
    pass


class RebuildIndexRequest(BaseModel):
    domain: Optional[str] = None


class IngestClippingsRequest(BaseModel):
    dry_run: bool = False
    notify: bool = False


class JiraKeySyncPatchRequest(BaseModel):
    filepath: str
    keys_map: dict[str, str]


class JiraKeySyncSyncRequest(BaseModel):
    content: str


class DecayRecalcRequest(BaseModel):
    dry_run: bool = False


class DecayTouchRequest(BaseModel):
    filepath: str


class DecaySetTierRequest(BaseModel):
    filepath: str
    tier: str


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
def _configure_vault():
    vault_path = os.getenv("VAULT_PATH", "/vault")
    _vp.VAULT_PATH = pathlib.Path(vault_path)
    logger.info("KE API startup: vault_path=%s", _vp.VAULT_PATH)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _vault_path_str() -> str:
    """Return current vault path as a string."""
    return str(_vp.VAULT_PATH)


# ---------------------------------------------------------------------------
# 1. POST /api/v1/enrich
# ---------------------------------------------------------------------------

@app.post("/api/v1/enrich")
def enrich(req: EnrichRequest):
    logger.info("API enrich: filepath=%s, dry_run=%s", req.filepath, req.dry_run)
    try:
        from .enricher import enrich as do_enrich

        result = do_enrich(req.filepath, _vault_path_str(), dry_run=req.dry_run)
        logger.info("API enrich: completed, status=%s", result.get("status"))
        return result
    except Exception as exc:
        logger.error("API enrich error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# 2. POST /api/v1/synthesize
# ---------------------------------------------------------------------------

@app.post("/api/v1/synthesize")
def synthesize(req: SynthesizeRequest):
    logger.info(
        "API synthesize: notify=%s, dry_run=%s, min_ideas=%s",
        req.notify, req.dry_run, req.min_ideas,
    )
    try:
        from .synthesizer import synthesize as do_synthesize

        result = do_synthesize(
            _vault_path_str(),
            notify=req.notify,
            min_ideas=req.min_ideas,
            dry_run=req.dry_run,
        )
        logger.info("API synthesize: completed, status=%s", result.get("status"))
        return result
    except Exception as exc:
        logger.error("API synthesize error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# 3. POST /api/v1/fetch-meetings
# ---------------------------------------------------------------------------

@app.post("/api/v1/fetch-meetings")
def fetch_meetings(req: FetchMeetingsRequest):
    logger.info("API fetch-meetings: notify=%s, dry_run=%s", req.notify, req.dry_run)
    try:
        from .meeting_fetcher.fetcher import fetch_new_meetings

        result = fetch_new_meetings(
            _vault_path_str(), notify=req.notify, dry_run=req.dry_run,
        )
        logger.info("API fetch-meetings: completed, status=%s", result.get("status"))
        return result
    except Exception as exc:
        logger.error("API fetch-meetings error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# 4. POST /api/v1/jira-sync
# ---------------------------------------------------------------------------

@app.post("/api/v1/jira-sync")
def jira_sync(req: JiraSyncRequest):
    logger.info("API jira-sync: notify=%s, dry_run=%s", req.notify, req.dry_run)
    try:
        from .jira_fetcher.fetcher import sync

        result = sync(
            _vault_path_str(), notify=req.notify, dry_run=req.dry_run,
        )
        logger.info("API jira-sync: completed, status=%s", result.get("status"))
        return result
    except Exception as exc:
        logger.error("API jira-sync error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# 5. POST /api/v1/jira-import
# ---------------------------------------------------------------------------

@app.post("/api/v1/jira-import")
def jira_import(req: JiraImportRequest):
    logger.info("API jira-import: key=%s", req.key)
    try:
        from .jira_fetcher.fetcher import import_single_issue

        result = import_single_issue(req.key, _vault_path_str())
        logger.info("API jira-import: completed, status=%s", result.get("status"))
        return result
    except Exception as exc:
        logger.error("API jira-import error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# 6. POST /api/v1/jira-create
# ---------------------------------------------------------------------------

@app.post("/api/v1/jira-create")
def jira_create(req: JiraCreateRequest):
    logger.info(
        "API jira-create: file=%s, project=%s, type=%s, epic=%s",
        req.file, req.project, req.type, req.epic,
    )
    try:
        from .jira_fetcher.fetcher import create_and_sync

        result = create_and_sync(
            vault_path=_vault_path_str(),
            filename=req.file,
            project_key=req.project,
            issue_type=req.type,
            summary=req.summary,
            epic_key=req.epic,
        )
        logger.info("API jira-create: completed, status=%s", result.get("status"))
        return result
    except Exception as exc:
        logger.error("API jira-create error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# 7. GET /api/v1/jira-projects
# ---------------------------------------------------------------------------

@app.get("/api/v1/jira-projects")
def jira_projects():
    logger.info("API jira-projects: fetching accessible projects")
    try:
        from .jira_fetcher import client

        projects = client.get_projects()
        result = {
            "status": "ok",
            "projects": [{"key": p["key"], "name": p["name"]} for p in projects],
        }
        logger.info("API jira-projects: completed, count=%d", len(result["projects"]))
        return result
    except Exception as exc:
        logger.error("API jira-projects error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# 8. GET /api/v1/jira-epics
# ---------------------------------------------------------------------------

@app.get("/api/v1/jira-epics")
def jira_epics(project: str = Query(..., description="Jira project key (e.g. GO)")):
    logger.info("API jira-epics: project=%s", project)
    try:
        from .jira_fetcher import client

        epics = client.get_project_epics(project)
        result = {"status": "ok", "epics": epics}
        logger.info("API jira-epics: completed, count=%d", len(epics))
        return result
    except Exception as exc:
        logger.error("API jira-epics error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# 9. GET /api/v1/jira-issue-types
# ---------------------------------------------------------------------------

@app.get("/api/v1/jira-issue-types")
def jira_issue_types(project: str = Query(..., description="Jira project key (e.g. GO)")):
    logger.info("API jira-issue-types: project=%s", project)
    try:
        from .jira_fetcher import client

        issue_types = client.get_project_issue_types(project)
        result = {"status": "ok", "issue_types": issue_types}
        logger.info("API jira-issue-types: completed, count=%d", len(issue_types))
        return result
    except Exception as exc:
        logger.error("API jira-issue-types error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# 10. GET /api/v1/domains
# ---------------------------------------------------------------------------

@app.get("/api/v1/domains")
def domains_list():
    logger.info("API domains list: fetching all domains")
    try:
        from .domain_manager import list_domains

        domains = list_domains()
        result = {"status": "ok", "domains": domains, "count": len(domains)}
        logger.info("API domains list: completed, count=%d", len(domains))
        return result
    except Exception as exc:
        logger.error("API domains list error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# 11. POST /api/v1/domains
# ---------------------------------------------------------------------------

@app.post("/api/v1/domains")
def domains_create(req: DomainCreateRequest):
    logger.info(
        "API domains create: name=%s, display_name=%s, color=%s, labels=%s",
        req.name, req.display_name, req.color, req.labels,
    )
    try:
        from shared import domain_config as _dc

        from .domain_manager import create_domain

        path = create_domain(req.name)
        logger.info("API domains create: created domain=%s at %s", req.name, path)

        has_overrides = (
            req.display_name is not None
            or req.color is not None
            or req.labels is not None
        )
        if has_overrides:
            display_name = req.display_name if req.display_name is not None else req.name
            color = req.color if req.color is not None else "#607D8B"
            labels_raw = req.labels if req.labels is not None else ""
            jira_labels = (
                [lbl.strip() for lbl in labels_raw.split(",") if lbl.strip()]
                if labels_raw
                else []
            )
            entry = {
                "display_name": display_name,
                "color": color,
                "jira_labels": jira_labels,
            }
            try:
                _dc.set_domain(req.name, entry)
                logger.info(
                    "API domains create: updated domain-config.yaml for domain=%s "
                    "display_name=%s color=%s labels=%s",
                    req.name, display_name, color, jira_labels,
                )
            except ValueError as cfg_err:
                logger.error(
                    "API domains create: scaffold succeeded but config update failed "
                    "for domain=%s: %s",
                    req.name, cfg_err,
                )
                return {
                    "status": "error",
                    "message": f"Scaffold created at {path} but config update failed: {cfg_err}",
                    "domain": req.name,
                    "path": str(path),
                }

        return {"status": "ok", "domain": req.name, "path": str(path)}
    except ValueError as exc:
        logger.error("API domains create: validation error: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("API domains create error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# 12. POST /api/v1/lint
# ---------------------------------------------------------------------------

@app.post("/api/v1/lint")
def lint():
    logger.info("API lint: starting vault health check")
    try:
        from .linter import lint as do_lint

        result = do_lint(_vault_path_str())
        logger.info(
            "API lint: completed, total_issues=%d",
            result["summary"]["total_issues"],
        )
        return result
    except Exception as exc:
        logger.error("API lint error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# 13. GET /api/v1/status
# ---------------------------------------------------------------------------

@app.get("/api/v1/status")
def status():
    logger.info("API status: collecting vault status")
    try:
        from .domain_manager import list_domains
        from .linter import lint as do_lint

        domains = list_domains()
        lint_result = do_lint(_vault_path_str())

        raw_root = _vp.VAULT_PATH / "raw" / "inbound"
        raw_counts: dict[str, int] = {}
        if raw_root.exists():
            for subdir in raw_root.iterdir():
                if subdir.is_dir():
                    count = sum(1 for f in subdir.iterdir() if f.is_file())
                    raw_counts[subdir.name] = count

        total_artifacts = sum(d.get("total", 0) for d in domains)

        result = {
            "status": "ok",
            "domains": domains,
            "domains_count": len(domains),
            "total_artifacts": total_artifacts,
            "raw_counts": raw_counts,
            "health": lint_result["summary"],
        }
        logger.info(
            "API status: completed, domains=%d, total_artifacts=%d, issues=%d",
            len(domains), total_artifacts, lint_result["summary"]["total_issues"],
        )
        return result
    except Exception as exc:
        logger.error("API status error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# 14. POST /api/v1/rebuild-index
# ---------------------------------------------------------------------------

@app.post("/api/v1/rebuild-index")
def rebuild_index(req: RebuildIndexRequest):
    logger.info("API rebuild-index: domain=%s", req.domain)
    try:
        from shared.vault_paths import all_domains

        from .domain_manager import _ARTIFACT_TYPES, update_domain_index

        if req.domain:
            target_domains = [req.domain]
        else:
            target_domains = all_domains()

        logger.info("API rebuild-index: rebuilding for domains=%s", target_domains)
        rebuilt = []
        for domain in target_domains:
            for artifact_type in _ARTIFACT_TYPES:
                try:
                    index_path = update_domain_index(domain, artifact_type)
                    artifact_dir = index_path.parent
                    entries = sum(
                        1 for f in artifact_dir.glob("*.md")
                        if f.name not in ("index.md", "log.md")
                    )
                    rebuilt.append({
                        "domain": domain,
                        "artifact_type": artifact_type,
                        "entries": entries,
                    })
                    logger.info(
                        "API rebuild-index: rebuilt domain=%s artifact_type=%s entries=%d",
                        domain, artifact_type, entries,
                    )
                except Exception as exc:
                    logger.error(
                        "API rebuild-index: failed for domain=%s artifact_type=%s: %s",
                        domain, artifact_type, exc,
                    )

        result = {"status": "ok", "rebuilt": rebuilt, "total_indices": len(rebuilt)}
        logger.info("API rebuild-index: completed, total_indices=%d", len(rebuilt))
        return result
    except Exception as exc:
        logger.error("API rebuild-index error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# 15. POST /api/v1/ingest-clippings
# ---------------------------------------------------------------------------

@app.post("/api/v1/ingest-clippings")
def ingest_clippings(req: IngestClippingsRequest):
    logger.info(
        "API ingest-clippings: dry_run=%s, notify=%s", req.dry_run, req.notify,
    )
    try:
        from .ingest import ingest_batch

        result = ingest_batch(dry_run=req.dry_run, notify=req.notify)
        logger.info("API ingest-clippings: completed, status=%s", result.get("status"))
        return result
    except Exception as exc:
        logger.error("API ingest-clippings error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# 16. GET /api/v1/health
# ---------------------------------------------------------------------------

@app.get("/api/v1/health")
def health():
    logger.info("API health: calculating vault health score")
    try:

        from .health_scorer import calculate_health, load_history

        result = calculate_health(_vault_path_str())
        logger.info("API health: score=%d, grade=%s", result["score"], result["grade"])

        history = load_history(_vault_path_str(), days=90)
        trend_7d = [{"date": e["date"], "score": e["score"]} for e in history[-7:]]
        trend_30d = [{"date": e["date"], "score": e["score"]} for e in history[-30:]]

        output = {
            "score": result["score"],
            "grade": result["grade"],
            "breakdown": result["breakdown"],
            "trend_7d": trend_7d,
            "trend_30d": trend_30d,
            "calculated_at": result["calculated_at"],
        }

        pm = result.get("pipeline_metrics")
        if pm:
            pm_entries_7d = [e for e in history[-7:] if "pipeline_metrics" in e]
            pm_entries_30d = [e for e in history[-30:] if "pipeline_metrics" in e]
            pm_with_trends = dict(pm)
            pm_with_trends["trend_7d"] = [
                {
                    "date": e["date"],
                    "ingest_ratio": e["pipeline_metrics"].get("ingest_ratio"),
                    "avg_lag_hours": e["pipeline_metrics"].get("avg_lag_hours"),
                }
                for e in pm_entries_7d
            ]
            pm_with_trends["trend_30d"] = [
                {
                    "date": e["date"],
                    "ingest_ratio": e["pipeline_metrics"].get("ingest_ratio"),
                    "avg_lag_hours": e["pipeline_metrics"].get("avg_lag_hours"),
                }
                for e in pm_entries_30d
            ]
            output["pipeline_metrics"] = pm_with_trends

        logger.info("API health: completed")
        return output
    except Exception as exc:
        logger.error("API health error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# 17. POST /api/v1/jira-key-sync/patch
# ---------------------------------------------------------------------------

@app.post("/api/v1/jira-key-sync/patch")
def jira_key_sync_patch(req: JiraKeySyncPatchRequest):
    logger.info(
        "API jira-key-sync/patch: filepath=%s, keys_count=%d",
        req.filepath, len(req.keys_map),
    )
    try:
        from .jira_key_sync import patch_daily_links

        patch_daily_links(req.filepath, req.keys_map)
        logger.info("API jira-key-sync/patch: completed")
        return {"status": "ok", "patched_file": req.filepath, "keys_count": len(req.keys_map)}
    except Exception as exc:
        logger.error("API jira-key-sync/patch error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# 18. POST /api/v1/jira-key-sync/sync
# ---------------------------------------------------------------------------

@app.post("/api/v1/jira-key-sync/sync")
def jira_key_sync_sync(req: JiraKeySyncSyncRequest):
    logger.info("API jira-key-sync/sync: content_len=%d", len(req.content))
    try:
        from .jira_key_sync import sync_daily_jira_keys

        result = sync_daily_jira_keys(req.content, _vault_path_str())
        logger.info(
            "API jira-key-sync/sync: completed, keys=%d, missing=%d, imported=%d, failed=%d",
            len(result.get("keys", [])),
            len(result.get("missing", [])),
            len(result.get("imported", [])),
            len(result.get("failed", [])),
        )
        return result
    except Exception as exc:
        logger.error("API jira-key-sync/sync error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# 19. POST /api/v1/decay/recalc
# ---------------------------------------------------------------------------

@app.post("/api/v1/decay/recalc")
def decay_recalc(req: DecayRecalcRequest):
    logger.info("API decay/recalc: dry_run=%s", req.dry_run)
    try:
        from knowledge_engine.decay_engine import load_config, recalc_vault

        config = load_config()
        result = recalc_vault(_vault_path_str(), config, dry_run=req.dry_run)
        logger.info(
            "API decay/recalc: completed, processed=%d, skipped=%d",
            result.get("processed", 0), result.get("skipped", 0),
        )
        return result
    except Exception as exc:
        logger.error("API decay/recalc error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# 20. POST /api/v1/decay/touch
# ---------------------------------------------------------------------------

@app.post("/api/v1/decay/touch")
def decay_touch(req: DecayTouchRequest):
    logger.info("API decay/touch: filepath=%s", req.filepath)
    try:
        from knowledge_engine.decay_engine import load_config, touch

        config = load_config()
        result = touch(req.filepath, _vault_path_str(), config)
        if result.get("status") == "skip":
            logger.warning("API decay/touch: skip, reason=%s", result.get("reason"))
            raise HTTPException(status_code=404, detail=result.get("reason", "not found"))
        logger.info(
            "API decay/touch: completed, access_count=%s, tier=%s->%s",
            result.get("access_count"), result.get("old_tier"), result.get("new_tier"),
        )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("API decay/touch error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# 21. POST /api/v1/decay/set-tier
# ---------------------------------------------------------------------------

@app.post("/api/v1/decay/set-tier")
def decay_set_tier(req: DecaySetTierRequest):
    logger.info("API decay/set-tier: filepath=%s, tier=%s", req.filepath, req.tier)
    try:
        from knowledge_engine.decay_engine import set_tier

        result = set_tier(req.filepath, req.tier, _vault_path_str())
        if result.get("status") == "error":
            logger.warning("API decay/set-tier: error, reason=%s", result.get("reason"))
            raise HTTPException(status_code=400, detail=result.get("reason", "bad request"))
        if result.get("status") == "skip":
            logger.warning("API decay/set-tier: skip, reason=%s", result.get("reason"))
            raise HTTPException(status_code=404, detail=result.get("reason", "not found"))
        logger.info(
            "API decay/set-tier: completed, old_tier=%s, new_tier=%s",
            result.get("old_tier"), result.get("new_tier"),
        )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("API decay/set-tier error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# 22. GET /api/v1/creative
# ---------------------------------------------------------------------------

@app.get("/api/v1/creative")
def get_creative_items(count: int = 5):
    logger.info("API creative: count=%d", count)
    try:
        from knowledge_engine.decay_engine import get_creative

        items = get_creative(_vault_path_str(), count=count)
        logger.info("API creative: returning %d items", len(items))
        return items
    except Exception as exc:
        logger.error("API creative error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# 23. GET /api/v1/decay/snapshot
# ---------------------------------------------------------------------------

@app.get("/api/v1/decay/snapshot")
def decay_snapshot():
    logger.info("API decay/snapshot: start")
    try:
        from knowledge_engine.decay_engine import load_config, snapshot_vault

        config = load_config()
        result = snapshot_vault(_vault_path_str(), config)
        logger.info(
            "API decay/snapshot: completed, total=%d",
            result.get("total", 0),
        )
        return result
    except Exception as exc:
        logger.error("API decay/snapshot error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
