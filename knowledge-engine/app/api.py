"""Knowledge Engine HTTP API.

Thin FastAPI wrapper over existing CLI business logic.
Each endpoint mirrors a CLI command from cli.py and returns
the same JSON structure that _output_json() would print.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import re
import shutil
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from shared import vault_paths as _vp

from .prompt_registry import PROMPT_REGISTRY
from .signal_moderator import invalidate_prompt_cache

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


class ProcessQueueRequest(BaseModel):
    limit: Optional[int] = None
    notify: bool = False


class DigestGenerateRequest(BaseModel):
    filepath: str
    force: bool = False


class DigestBulkRequest(BaseModel):
    domain: Optional[str] = None
    type: Optional[str] = None
    force: bool = False


class ResearchRunRequest(BaseModel):
    target_file: Optional[str] = None
    notify: bool = False


class ResearchRetryRequest(BaseModel):
    filename: str


# ---------------------------------------------------------------------------
# Prompt helpers (BL-197)
# ---------------------------------------------------------------------------

_PROMPT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
MAX_PROMPT_SIZE = 50 * 1024


class PromptSaveRequest(BaseModel):
    content: str = Field(..., max_length=MAX_PROMPT_SIZE)


def _validate_prompt_name(name: str) -> None:
    if not _PROMPT_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid prompt name")


def _safe_prompt_path(name: str, prompts_dir: pathlib.Path) -> pathlib.Path:
    _validate_prompt_name(name)
    path = (prompts_dir / f"{name}.txt").resolve()
    if not str(path).startswith(str(prompts_dir.resolve())):
        raise HTTPException(status_code=400, detail="Invalid prompt name")
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Prompt not found: {name}")
    return path


def _is_modified(prompt_path: pathlib.Path) -> bool:
    default_path = prompt_path.with_suffix(".txt.default")
    if not default_path.exists():
        return False
    return prompt_path.read_text(encoding="utf-8") != default_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
def _configure_vault():
    # Create *.txt.default backups for prompt files (before any other init)
    prompts_dir = pathlib.Path(__file__).parent / "prompts"
    for txt_file in prompts_dir.glob("*.txt"):
        default_file = txt_file.with_suffix(".txt.default")
        if not default_file.exists():
            shutil.copy2(txt_file, default_file)
            logger.info("Created default backup: %s", default_file.name)

    vault_path = os.getenv("VAULT_PATH", "/vault")
    _vp.VAULT_PATH = pathlib.Path(vault_path)
    logger.info("KE API startup: vault_path=%s", _vp.VAULT_PATH)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _vault_path_str() -> str:
    """Return current vault path as a string."""
    return str(_vp.VAULT_PATH)


def _file_mtime_iso(path: pathlib.Path) -> str:
    """File modification time as ISO string."""
    ts = os.path.getmtime(path)
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def _compute_slug(topic: str) -> str:
    """Compute slug from topic (same as ResearchTask.slug)."""
    s = re.sub(r"[^a-zA-Zа-яА-Яё0-9]", "-", topic)[:50]
    return re.sub(r"-+", "-", s).strip("-").lower()


def _parse_queue_file(path: pathlib.Path) -> dict | None:
    """Parse a single research queue JSON file."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning(f"_parse_queue_file: file disappeared: {path.name}")
        return None
    except Exception as exc:
        logger.error(f"_parse_queue_file: read error {path.name}: {exc}")
        return None

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning(f"_parse_queue_file: invalid JSON: {path.name}")
        return {
            "filename": path.name,
            "topic": path.stem,
            "questions": [],
            "questions_count": 0,
            "scope": "",
            "signal_source": "",
            "signal_date": "",
            "competitor": "",
            "error": "parse error",
            "created_at": _file_mtime_iso(path),
        }

    return {
        "filename": path.name,
        "topic": data.get("topic", path.stem),
        "questions": data.get("questions", []),
        "questions_count": len(data.get("questions", [])),
        "scope": data.get("scope", ""),
        "signal_source": data.get("signal_source", ""),
        "signal_date": data.get("signal_date", ""),
        "competitor": data.get("competitor", ""),
        "created_at": _file_mtime_iso(path),
    }


def _match_report(slug: str, vault_path: str) -> dict | None:
    """Find matching report for a research task by slug."""
    reports_dir = _vp.wiki_reports()
    if not reports_dir.exists():
        return None

    pattern = f"*-{slug}*.md"
    matches = list(reports_dir.glob(pattern))
    if not matches:
        return None

    report_file = matches[0]
    try:
        from shared.frontmatter_utils import read_frontmatter
        meta, _ = read_frontmatter(report_file)
        completeness = meta.get("completeness")
        if isinstance(completeness, str):
            try:
                completeness = int(completeness)
            except ValueError:
                completeness = None
        rel_path = str(report_file.relative_to(pathlib.Path(vault_path)))
        return {
            "completeness": completeness,
            "report_path": rel_path,
            "outcome": meta.get("outcome"),
            "outcome_details": meta.get("outcome_details", ""),
            "ideas_count": meta.get("ideas_count", 0),
        }
    except Exception as exc:
        logger.warning(f"_match_report: failed to read frontmatter {report_file.name}: {exc}")
        return {"completeness": None, "report_path": str(report_file.relative_to(pathlib.Path(vault_path)))}


def _parse_idea_body(body: str) -> dict:
    """Parse markdown body of an idea file by headings (BL-199)."""
    sections = {"problem": "", "solution": "", "rationale": ""}
    section_map = {"проблема": "problem", "решение": "solution", "анализ": "rationale"}
    current_key = None
    current_lines: list[str] = []

    for line in body.splitlines():
        stripped = line.strip().lower()
        if stripped.startswith("## "):
            if current_key:
                sections[current_key] = "\n".join(current_lines).strip()
            heading = stripped[3:].strip()
            current_key = section_map.get(heading)
            current_lines = []
        elif current_key is not None:
            current_lines.append(line)

    if current_key:
        sections[current_key] = "\n".join(current_lines).strip()

    return sections


def _build_reports_list(vault_path: str, limit: int = 50) -> list[dict]:
    """Scan wiki/signals/ for signal reports with frontmatter (BL-198)."""
    logger.info("_build_reports_list: scanning")
    reports_dir = _vp.wiki_signals()
    if not reports_dir.exists():
        logger.info("_build_reports_list: signals dir does not exist")
        return []

    from shared.frontmatter_utils import read_frontmatter

    reports: list[dict] = []
    for f in sorted(reports_dir.glob("*.md"), reverse=True):
        if len(reports) >= limit:
            break
        try:
            meta, _ = read_frontmatter(f)
            if meta.get("type") != "signal-report":
                continue
            reports.append({
                "filename": f.name,
                "topic": meta.get("title", f.stem),
                "date": meta.get("signal_date") or meta.get("created", ""),
                "outcome": meta.get("outcome"),
                "outcome_details": meta.get("outcome_details", ""),
                "ideas_count": meta.get("ideas_count", 0),
                "completeness": meta.get("completeness"),
                "signal_source": meta.get("source_url") or meta.get("signal_source", ""),
                "ideas_refs": meta.get("ideas_refs", []) if meta.get("ideas_count", 0) > 0 else [],
            })
        except Exception as exc:
            logger.warning(f"_build_reports_list: failed to read {f.name}: {exc}")

    logger.info(f"_build_reports_list: found {len(reports)} signal reports")
    return reports


def _build_extracted_ideas(reports_list: list[dict], vault_path: str) -> list[dict]:
    """Collect idea files referenced by research reports (BL-199)."""
    logger.info("_build_extracted_ideas: collecting")
    from shared.frontmatter_utils import read_frontmatter

    # Build reverse map: idea_filename -> report_filename
    idea_to_report: dict[str, str] = {}
    seen: set[str] = set()
    for report in reports_list:
        for ref in report.get("ideas_refs", []):
            if ref not in seen:
                idea_to_report[ref] = report["filename"]
                seen.add(ref)

    if not seen:
        logger.info("_build_extracted_ideas: no idea refs found")
        return []

    ideas_dir = pathlib.Path(vault_path) / "raw" / "inbound" / "ideas"
    results = []

    for idea_filename in seen:
        idea_path = ideas_dir / idea_filename
        if not idea_path.exists():
            logger.warning(f"_build_extracted_ideas: idea file not found: {idea_filename}")
            continue
        try:
            meta, body = read_frontmatter(idea_path)
        except Exception as exc:
            logger.warning(f"_build_extracted_ideas: failed to read {idea_filename}: {exc}")
            continue

        body_sections = _parse_idea_body(body)
        results.append({
            "filename": idea_filename,
            "title": meta.get("title", idea_filename),
            "domain": meta.get("domain", ""),
            "status": meta.get("status", ""),
            "problem": body_sections["problem"],
            "solution": body_sections["solution"],
            "rationale": body_sections["rationale"],
            "report_ref": idea_to_report.get(idea_filename, ""),
            "signal_date": meta.get("signal_date", ""),
            "created": meta.get("created", ""),
            "priority_hint": meta.get("priority_hint"),
        })

    results.sort(key=lambda x: x.get("created") or x.get("signal_date") or "", reverse=True)
    logger.info(f"_build_extracted_ideas: found {len(results)} ideas")
    return results


def _build_research_queue_status(vault_path: str) -> dict:
    """Scan research queue dirs and build full status response."""
    logger.info("_build_research_queue_status: scanning")

    pending = []
    processed = []
    failed = []

    # Pending
    queue_dir = _vp.raw_research_queue()
    if queue_dir.exists():
        for f in sorted(queue_dir.glob("*.json")):
            item = _parse_queue_file(f)
            if item:
                pending.append(item)

    # Processed
    proc_dir = _vp.raw_research_queue_processed()
    if proc_dir.exists():
        for f in sorted(proc_dir.glob("*.json")):
            item = _parse_queue_file(f)
            if item:
                item["processed_at"] = item.pop("created_at")
                slug = _compute_slug(item["topic"])
                report_info = _match_report(slug, vault_path)
                if report_info:
                    item["completeness"] = report_info["completeness"]
                    item["quality_warning"] = (
                        report_info["completeness"] is not None
                        and report_info["completeness"] < 5
                    )
                    item["report_path"] = report_info["report_path"]
                    item["outcome"] = report_info.get("outcome")
                    item["outcome_details"] = report_info.get("outcome_details", "")
                    item["ideas_count"] = report_info.get("ideas_count", 0)
                else:
                    item["completeness"] = None
                    item["quality_warning"] = False
                    item["report_path"] = None
                    item["outcome"] = None
                    item["outcome_details"] = ""
                    item["ideas_count"] = 0
                item["method"] = "internal"
                item["tokens_in"] = None
                item["tokens_out"] = None
                processed.append(item)

    # Failed
    fail_dir = _vp.raw_research_queue_failed()
    if fail_dir.exists():
        for f in sorted(fail_dir.glob("*.json")):
            item = _parse_queue_file(f)
            if item:
                item["failed_at"] = item.pop("created_at")
                if "error" not in item:
                    item["error"] = "Ошибка обработки (подробности в system log)"
                failed.append(item)

    # Summary
    completeness_values = [
        p["completeness"] for p in processed
        if p["completeness"] is not None
    ]
    avg_completeness = (
        round(sum(completeness_values) / len(completeness_values), 1)
        if completeness_values else None
    )

    # Reports count
    reports_list = _build_reports_list(vault_path)
    reports_count = len(reports_list)

    # Extracted ideas from reports (BL-199)
    extracted_ideas = _build_extracted_ideas(reports_list, vault_path)

    logger.info(
        f"_build_research_queue_status: pending={len(pending)}, "
        f"processed={len(processed)}, failed={len(failed)}"
    )

    return {
        "status": "ok",
        "pending": pending,
        "processed": processed,
        "failed": failed,
        "summary": {
            "pending": len(pending),
            "processed": len(processed),
            "failed": len(failed),
            "avg_completeness": avg_completeness,
        },
        "reports": reports_list,
        "reports_count": reports_count,
        "extracted_ideas": extracted_ideas,
    }


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
# 10. GET /api/v1/jira-search
# ---------------------------------------------------------------------------

def _map_jira_issue(raw: dict) -> dict:
    fields = raw.get("fields", {})
    return {
        "key": raw.get("key", ""),
        "summary": fields.get("summary", ""),
        "type": (fields.get("issuetype") or {}).get("name", ""),
        "status": (fields.get("status") or {}).get("name", ""),
        "assignee": (fields.get("assignee") or {}).get("displayName", ""),
        "labels": fields.get("labels", []),
        "priority": (fields.get("priority") or {}).get("name", ""),
        "url": f"{os.getenv('JIRA_URL', '').rstrip('/')}/browse/{raw.get('key', '')}",
    }


@app.get("/api/v1/jira-search")
def jira_search(
    project: str = Query(..., description="Jira project key (e.g. SUP)"),
    type: str = Query("", description="Issue type filter (e.g. Bug, Story)"),
    status: str = Query("", description="Status filter (e.g. In Progress)"),
    max_results: int = Query(50, ge=1, le=100, description="Max issues to return"),
):
    logger.info(
        "GET /api/v1/jira-search — start, project=%s type=%r status=%r max=%d",
        project, type, status, max_results,
    )
    if not re.match(r'^[A-Z][A-Z0-9]+$', project):
        raise HTTPException(status_code=400, detail=f"Invalid project key: {project!r}")

    jql_parts = [f'project = "{project}"']
    if type:
        jql_parts.append(f'issuetype = "{type}"')
    if status:
        jql_parts.append(f'status = "{status}"')
    jql = " AND ".join(jql_parts) + " ORDER BY updated DESC"

    try:
        from .jira_fetcher import client
        from .jira_fetcher.client import JiraClientError

        issues = client.search(jql, limit=max_results)
        mapped = [_map_jira_issue(i) for i in issues]
        logger.info("GET /api/v1/jira-search — success, count=%d", len(mapped))
        return {"status": "ok", "total": len(mapped), "issues": mapped}
    except JiraClientError as exc:
        logger.error("GET /api/v1/jira-search — error: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        logger.error("GET /api/v1/jira-search — error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# 11. GET /api/v1/domains
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


# ---------------------------------------------------------------------------
# 24. GET /api/v1/meeting-queue/status  (BL-145, US-03 — публичный контракт BL-144)
# ---------------------------------------------------------------------------

@app.get("/api/v1/meeting-queue/status")
def meeting_queue_status():
    """Счётчики очереди + список юнитов из всех 4 папок с их meta.

    Публичный контракт наблюдаемости для BL-144 (design §3.7, §6):
    {counts: {pending,processing,done,failed}, units: [{unit_id, source, subject,
    status, attempts, output_file, last_error, updated_at}, ...]}.
    """
    logger.info("API meeting-queue/status: collecting queue counts and units")
    try:
        import json as _json

        from shared.meeting_queue import (
            meeting_queue_done,
            meeting_queue_failed,
            meeting_queue_pending,
            meeting_queue_processing,
        )

        from .meeting_fetcher.queue import MeetingQueue

        vault_path = _vault_path_str()
        queue = MeetingQueue(vault_path)
        counts = queue.status_counts()

        folders = {
            "pending": meeting_queue_pending(vault_path),
            "processing": meeting_queue_processing(vault_path),
            "done": meeting_queue_done(vault_path),
            "failed": meeting_queue_failed(vault_path),
        }

        units: list[dict] = []
        for folder_status, folder in folders.items():
            for meta_file in sorted(folder.glob("*.meta.json")):
                unit_id = meta_file.name[: -len(".meta.json")]
                try:
                    meta = _json.loads(meta_file.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    logger.warning(
                        "API meeting-queue/status: unreadable meta %s: %s",
                        meta_file, exc,
                    )
                    units.append({
                        "unit_id": unit_id,
                        "source": None,
                        "subject": None,
                        "status": folder_status,
                        "attempts": None,
                        "output_file": None,
                        "last_error": "unreadable meta",
                        "updated_at": None,
                    })
                    continue
                units.append({
                    "unit_id": meta.get("unit_id", unit_id),
                    "source": meta.get("source"),
                    "subject": meta.get("subject"),
                    "status": meta.get("status", folder_status),
                    "attempts": meta.get("attempts", 0),
                    "output_file": meta.get("output_file"),
                    "last_error": meta.get("last_error"),
                    "updated_at": meta.get("updated_at"),
                })

        result = {"counts": counts, "units": units}
        logger.info(
            "API meeting-queue/status: completed, counts=%s, units=%d",
            counts, len(units),
        )
        return result
    except Exception as exc:
        logger.error("API meeting-queue/status error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# 25. POST /api/v1/process-queue  (BL-145, US-03 — ручной триггер обработки)
# ---------------------------------------------------------------------------

@app.post("/api/v1/process-queue")
def process_queue(req: ProcessQueueRequest):
    """Ручной триггер drain-прохода очереди: processor.process_pending (design §3.7).

    Тело: {limit: int|None, notify: bool=False}. Возвращает результат
    process_pending: {status, reclaimed, processed, failed, requeued, details}.
    """
    logger.info("API process-queue: limit=%s, notify=%s", req.limit, req.notify)
    try:
        from .meeting_fetcher.processor import process_pending

        result = process_pending(
            _vault_path_str(), limit=req.limit, notify=req.notify,
        )
        logger.info(
            "API process-queue: completed, status=%s, processed=%s, failed=%s",
            result.get("status"), result.get("processed"), result.get("failed"),
        )
        return result
    except Exception as exc:
        logger.error("API process-queue error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# 26. POST /api/v1/digest/generate
# ---------------------------------------------------------------------------

@app.post("/api/v1/digest/generate")
def digest_generate(req: DigestGenerateRequest):
    logger.info("API digest/generate: filepath=%s, force=%s", req.filepath, req.force)
    try:
        from .digest.generator import generate_digest

        result = generate_digest(
            source_path=pathlib.Path(req.filepath),
            vault_path=_vault_path_str(),
            force=req.force,
        )
        logger.info("API digest/generate: completed, status=%s", result.get("status"))
        return result
    except Exception as exc:
        logger.error("API digest/generate error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# 27. POST /api/v1/digest/bulk
# ---------------------------------------------------------------------------

@app.post("/api/v1/digest/bulk")
def digest_bulk(req: DigestBulkRequest):
    logger.info("API digest/bulk: domain=%s, type=%s, force=%s", req.domain, req.type, req.force)
    try:
        from .digest.generator import generate_bulk

        result = generate_bulk(
            vault_path=_vault_path_str(),
            domain=req.domain,
            artifact_type=req.type,
            force=req.force,
        )
        logger.info("API digest/bulk: completed, status=%s", result.get("status"))
        return result
    except Exception as exc:
        logger.error("API digest/bulk error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# 28. GET /api/v1/digest/status
# ---------------------------------------------------------------------------

@app.get("/api/v1/digest/status")
def digest_status():
    logger.info("API digest/status: collecting digest coverage stats")
    try:
        from shared.frontmatter_utils import read_frontmatter as _read_fm

        vault_root = pathlib.Path(_vault_path_str())
        llm_wiki = vault_root / "llm_wiki"
        wiki_dir = vault_root / "wiki"

        total_digests = 0
        passed = 0
        failed = 0
        total_wiki = 0

        if llm_wiki.exists():
            for md in llm_wiki.rglob("*.md"):
                if md.name == "_index.md":
                    continue
                total_digests += 1
                try:
                    meta, _ = _read_fm(md)
                    if meta.get("validation") == "passed":
                        passed += 1
                    else:
                        failed += 1
                except Exception:
                    failed += 1

        if wiki_dir.exists():
            for md in wiki_dir.rglob("*.md"):
                if md.name.upper() in {"INDEX.MD", "LOG.MD"} or md.name.startswith("_"):
                    continue
                total_wiki += 1

        missing = max(0, total_wiki - total_digests)
        coverage = round(total_digests / total_wiki * 100, 1) if total_wiki > 0 else 0.0

        result = {
            "status": "ok",
            "total_wiki_artifacts": total_wiki,
            "total_digests": total_digests,
            "valid_digests": passed,
            "failed_digests": failed,
            "missing_digests": missing,
            "coverage_percent": coverage,
        }
        logger.info(
            "API digest/status: completed, wiki=%d, digests=%d, coverage=%.1f%%",
            total_wiki, total_digests, coverage,
        )
        return result
    except Exception as exc:
        logger.error("API digest/status error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# 29. POST /api/v1/cowork-context  (BL-151)
# ---------------------------------------------------------------------------

@app.post("/api/v1/cowork-context")
def cowork_context():
    """Обновить оба llm_wiki файла: _index.md и _cowork-session.md."""
    logger.info("API cowork-context: starting")
    try:
        from shared.system_log import LoggedProcess

        from .cowork_context import generate_cowork_session
        from .digest.generator import regenerate_index

        with LoggedProcess("cowork-context", source="ke-api") as lp:
            index_result = regenerate_index(vault_path=_vault_path_str())
            session_result = generate_cowork_session(_vault_path_str())
            lp.summary = f"Cowork context: {session_result.get('status', 'unknown')}"
            lp.details = {
                "index_entries": index_result.get("entries", 0),
                "session_sections": session_result.get("session_sections", {}),
            }
            if session_result.get("status") == "error":
                lp.status = "error"

        result = {
            "status": session_result.get("status", "error"),
            "index_entries": index_result.get("entries", 0),
            "session_sections": session_result.get("session_sections", {}),
            "generated_at": session_result.get("generated_at", ""),
        }
        logger.info(f"API cowork-context: completed, status={result['status']}")
        return result
    except Exception as exc:
        logger.error(f"API cowork-context error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Signals diagnostics (BL-190)
# ---------------------------------------------------------------------------


@app.get("/api/v1/signals/runs")
def signals_runs(limit: int = Query(default=10, ge=1, le=100)):
    logger.info(f"API signals_runs: limit={limit}")
    try:
        from dataclasses import asdict
        from datetime import datetime

        from .signal_orchestrator import RunState

        runs_dir = pathlib.Path(_vault_path_str()) / "wiki" / "signals" / "runs"
        if not runs_dir.exists():
            return {"status": "ok", "runs": []}

        run_files = sorted(runs_dir.glob("*.json"), reverse=True)[:limit]
        runs = []
        for f in run_files:
            try:
                state = RunState.load(f)
                # Calculate duration_ms
                duration_ms = None
                if state.completed_at and state.started_at:
                    try:
                        started = datetime.fromisoformat(state.started_at)
                        completed = datetime.fromisoformat(state.completed_at)
                        duration_ms = int(
                            (completed - started).total_seconds() * 1000
                        )
                    except Exception:
                        pass

                # Items summary
                items_summary = []
                for key, item in state.items.items():
                    items_summary.append({
                        "key": key,
                        "title": item.title,
                        "status": item.status,
                        "reaction": item.reaction,
                        "iterations": item.iterations,
                        "errors": len(item.errors),
                        "source_url": item.source_url,
                        "result_ref": item.result_ref,
                        "relevance": item.relevance,
                        "reason": item.reason,
                    })

                summary = asdict(state.summary) if state.summary else {}
                runs.append({
                    "run_id": state.run_id,
                    "status": state.status,
                    "started_at": state.started_at,
                    "completed_at": state.completed_at,
                    "duration_ms": duration_ms,
                    "summary": summary,
                    "items": items_summary,
                })
            except Exception as e:
                logger.warning(f"signals_runs: skip corrupted {f.name}: {e}")

        return {"status": "ok", "runs": runs}
    except Exception as exc:
        logger.error(f"API signals_runs error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/v1/signals/runs/{run_id}")
def signals_run_detail(run_id: str):
    logger.info(f"API signals_run_detail: run_id={run_id}")
    try:
        from dataclasses import asdict

        from .signal_orchestrator import RunState

        run_file = (
            pathlib.Path(_vault_path_str())
            / "wiki" / "signals" / "runs" / f"{run_id}.json"
        )
        if not run_file.exists():
            raise HTTPException(
                status_code=404, detail=f"Run not found: {run_id}"
            )

        try:
            state = RunState.load(run_file)
        except Exception as e:
            logger.error(
                f"signals_run_detail: corrupted file {run_id}: {e}"
            )
            raise HTTPException(
                status_code=500, detail=f"Corrupted run file: {run_id}"
            )

        data = asdict(state)
        run_status = data.pop("status", "unknown")
        return {"status": "ok", "run_status": run_status, **data}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            f"API signals_run_detail error: {exc}", exc_info=True
        )
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/v1/signals/stats")
def signals_stats(days: int = Query(default=30, ge=1, le=365)):
    logger.info(f"API signals_stats: days={days}")
    try:
        from datetime import datetime, timedelta

        from .signal_memory import SignalMemory
        from .signal_orchestrator import load_config_from_settings

        config = load_config_from_settings()
        db_path = config.memory_db_path

        # Check if DB exists
        if not pathlib.Path(db_path).exists():
            return {
                "status": "ok",
                "runs_count": 0,
                "avg_quality_score": None,
                "escalation_rate": 0.0,
                "total_signals": 0,
                "top_entities": [],
            }

        memory = SignalMemory(db_path)
        conn = memory._get_conn()
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        # total_signals + avg_quality
        row = conn.execute(
            "SELECT COUNT(*), AVG(quality_score) FROM signals WHERE date >= ?",
            (cutoff,),
        ).fetchone()
        total_signals = row[0] if row else 0
        avg_quality = (
            round(row[1], 2) if row and row[1] is not None else None
        )

        # escalation_rate (attempts > 1 / total) — SUM(CASE) for SQLite
        esc_row = conn.execute(
            "SELECT SUM(CASE WHEN attempts > 1 THEN 1 ELSE 0 END), "
            "COUNT(*) FROM signals WHERE date >= ?",
            (cutoff,),
        ).fetchone()
        escalation_rate = (
            round(esc_row[0] / esc_row[1], 4)
            if esc_row and esc_row[1] > 0
            else 0.0
        )

        # runs_count — scan run files
        runs_dir = (
            pathlib.Path(_vault_path_str()) / "wiki" / "signals" / "runs"
        )
        runs_count = 0
        if runs_dir.exists():
            cutoff_date = (
                datetime.now() - timedelta(days=days)
            ).strftime("%Y-%m-%d")
            for f in runs_dir.glob("*.json"):
                # run_id format: YYYY-MM-DD-HHMM
                file_date = f.stem[:10]  # "2026-08-03"
                if file_date >= cutoff_date:
                    runs_count += 1

        # top_entities
        entity_rows = conn.execute(
            "SELECT entity, SUM(mention_count) as total FROM entity_trends "
            "GROUP BY entity ORDER BY total DESC LIMIT 10"
        ).fetchall()
        top_entities = [
            {"entity": r[0], "mention_count": r[1]} for r in entity_rows
        ]

        return {
            "status": "ok",
            "runs_count": runs_count,
            "avg_quality_score": avg_quality,
            "escalation_rate": escalation_rate,
            "total_signals": total_signals,
            "top_entities": top_entities,
        }
    except Exception as exc:
        logger.error(f"API signals_stats error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Research Queue (BL-195)
# ---------------------------------------------------------------------------


@app.get("/api/v1/research-queue/status")
def research_queue_status():
    logger.info("API research_queue_status: start")
    try:
        result = _build_research_queue_status(_vault_path_str())
        logger.info(
            f"API research_queue_status: completed, "
            f"pending={result['summary']['pending']}"
        )
        return result
    except Exception as exc:
        logger.error(f"API research_queue_status error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/v1/research-queue/run")
def research_queue_run(req: ResearchRunRequest):
    logger.info(
        f"API research_queue_run: start, target_file={req.target_file}, "
        f"notify={req.notify}"
    )
    try:
        from .research_runner import run_all

        results = run_all(
            _vault_path_str(),
            target_file=req.target_file,
            notify=req.notify,
        )
        completed = sum(1 for r in results if r.error is None)
        errors = sum(1 for r in results if r.error is not None)
        logger.info(
            f"API research_queue_run: completed={completed}, errors={errors}"
        )
        return {
            "status": "ok",
            "completed": completed,
            "failed": errors,
            "results": [
                {
                    "topic": r.topic,
                    "report_path": r.report_path,
                    "completeness": r.completeness,
                    "error": r.error,
                }
                for r in results
            ],
        }
    except Exception as exc:
        logger.error(f"API research_queue_run error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/v1/research-queue/retry")
def research_queue_retry(req: ResearchRetryRequest):
    logger.info(f"API research_queue_retry: start, filename={req.filename}")
    try:
        from .research_runner import retry_failed_task

        results = retry_failed_task(req.filename, _vault_path_str())
        completed = sum(1 for r in results if r.error is None)
        errors = sum(1 for r in results if r.error is not None)
        logger.info(
            f"API research_queue_retry: completed={completed}, errors={errors}"
        )
        return {
            "status": "ok",
            "completed": completed,
            "failed": errors,
            "results": [
                {
                    "topic": r.topic,
                    "report_path": r.report_path,
                    "completeness": r.completeness,
                    "error": r.error,
                }
                for r in results
            ],
        }
    except FileNotFoundError as exc:
        logger.warning(f"API research_queue_retry: not found: {exc}")
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error(f"API research_queue_retry error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Signal Triage — approve (BUG-033)
# ---------------------------------------------------------------------------


@app.post("/api/v1/signals/{signal_id}/approve")
def signal_approve(signal_id: str):
    """Approve a pending signal, creating an IDEA (BL-203, BUG-033)."""
    logger.info(f"API signal_approve: signal_id={signal_id}")
    try:
        from shared.frontmatter_utils import read_frontmatter, update_frontmatter

        vault_path = _vault_path_str()
        wiki_path = (
            pathlib.Path(vault_path)
            / "wiki"
            / "reports"
            / "signals"
            / f"{signal_id}.md"
        )
        if not wiki_path.exists():
            raise HTTPException(
                status_code=404, detail=f"Signal not found: {signal_id}"
            )

        fm, _body = read_frontmatter(wiki_path)
        current_status = fm.get("status", "")
        if current_status != "pending":
            raise HTTPException(
                status_code=409,
                detail=f"Signal status is '{current_status}', expected 'pending'",
            )

        # Read draft_idea from raw JSON
        raw_path = (
            pathlib.Path(vault_path)
            / "raw"
            / "inbound"
            / "signals"
            / f"{signal_id}.json"
        )
        draft_idea = None
        if raw_path.exists():
            try:
                raw_data = json.loads(raw_path.read_text(encoding="utf-8"))
                draft_idea = raw_data.get("draft_idea")
            except Exception as e:
                logger.error(f"signal_approve: failed to read raw JSON: {e}")

        if not draft_idea:
            raise HTTPException(
                status_code=400, detail="Signal has no draft_idea"
            )

        # Dispatch idea using signal_moderator (local import — KE has this module)
        from .signal_moderator import AnalysisResult, dispatch_idea

        analysis = AnalysisResult(
            reaction="idea",
            analysis=fm.get("title", ""),
            threat_level=fm.get("threat_level", "low"),
            idea_draft=draft_idea,
        )

        idea_ref = dispatch_idea(
            item={
                "title": draft_idea.get("title", fm.get("title", "")),
                "date": fm.get("signal_date", ""),
                "source_url": fm.get("source_url", ""),
                "source": fm.get("source", ""),
            },
            analysis=analysis,
            vault_path=vault_path,
            notify=True,
            dry_run=False,
        )

        # Update wiki frontmatter
        update_frontmatter(wiki_path, {
            "status": "approved",
            "result_ref": idea_ref or "",
        })

        logger.info(f"signal_approve: approved {signal_id}, idea_ref={idea_ref}")
        return {
            "status": "ok",
            "signal_id": signal_id,
            "idea_ref": idea_ref or "",
            "new_status": "approved",
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"API signal_approve error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Prompts API (BL-197)
# ---------------------------------------------------------------------------

_ke_prompts_dir = pathlib.Path(__file__).parent / "prompts"


@app.get("/api/v1/prompts")
def get_prompts():
    logger.info("GET /api/v1/prompts — start")
    prompts = []
    for name, meta in PROMPT_REGISTRY.items():
        path = _ke_prompts_dir / f"{name}.txt"
        if not path.exists():
            logger.warning("GET /api/v1/prompts — file not found: %s", path)
            continue
        content = path.read_text(encoding="utf-8")
        prompts.append({
            "name": name,
            "description": meta["description"],
            "content": content,
            "lines": content.count("\n") + 1,
            "variables": meta["variables"],
            "is_modified": _is_modified(path),
        })
    logger.info("GET /api/v1/prompts — returning %d prompts", len(prompts))
    return {"prompts": prompts}


@app.post("/api/v1/prompts/{name}")
def save_prompt(name: str, request: PromptSaveRequest):
    logger.info("POST /api/v1/prompts/%s — start, content_len=%d", name, len(request.content))
    path = _safe_prompt_path(name, _ke_prompts_dir)
    path.write_text(request.content, encoding="utf-8")
    invalidated = invalidate_prompt_cache(name)
    logger.info("POST /api/v1/prompts/%s — saved, cache_invalidated=%s", name, invalidated)
    return {
        "status": "ok",
        "name": name,
        "lines": request.content.count("\n") + 1,
        "is_modified": _is_modified(path),
        "cache_invalidated": True,
    }


@app.post("/api/v1/prompts/{name}/reset")
def reset_prompt(name: str):
    logger.info("POST /api/v1/prompts/%s/reset — start", name)
    path = _safe_prompt_path(name, _ke_prompts_dir)
    default_path = path.with_suffix(".txt.default")
    if not default_path.exists():
        raise HTTPException(status_code=404, detail=f"Default not found for: {name}")
    content = default_path.read_text(encoding="utf-8")
    path.write_text(content, encoding="utf-8")
    invalidated = invalidate_prompt_cache(name)
    logger.info("POST /api/v1/prompts/%s/reset — done, cache_invalidated=%s", name, invalidated)
    return {
        "status": "ok",
        "name": name,
        "content": content,
        "lines": content.count("\n") + 1,
        "is_modified": False,
        "cache_invalidated": True,
    }
