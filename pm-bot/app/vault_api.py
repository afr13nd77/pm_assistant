"""
vault_api.py — FastAPI REST server for reading Obsidian vault.

Serves JSON data parsed from the Obsidian vault filesystem.
Endpoints provide ideas, meetings, tasks, epics, reports,
capture (create note via Claude), and pipeline proxy.

Uses domain-based vault structure:
  wiki/domains/<domain>/ideas/
  wiki/domains/<domain>/tasks/
  wiki/domains/<domain>/epics/
  wiki/domains/<domain>/prds/
  wiki/meetings/
  wiki/daily-logs/
  wiki/reports/
"""

import json
import logging
import os
import re
import subprocess
import threading
import time as _time
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import domain_config
from .vault_paths import (
    VAULT_PATH,
    all_domains,
    wiki_domain_dir,
    wiki_meetings,
    wiki_reports,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory TTL cache for vault scan results
# ---------------------------------------------------------------------------


class _VaultCache:
    """Simple TTL cache for expensive vault scan + parse results."""

    def __init__(self, ttl_seconds: float = 5.0):
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, any]] = {}

    def get(self, key: str):
        entry = self._store.get(key)
        if entry is None:
            return None
        ts, value = entry
        if (_time.time() - ts) > self._ttl:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value):
        self._store[key] = (_time.time(), value)

    def invalidate(self, prefix: str = ""):
        if not prefix:
            self._store.clear()
        else:
            keys_to_del = [k for k in self._store if k.startswith(prefix)]
            for k in keys_to_del:
                del self._store[k]


_cache = _VaultCache(ttl_seconds=30.0)

_jira_sync_lock = threading.Lock()

app = FastAPI(title="PM Vault API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _warm_cache():
    """Pre-populate cache on server start so first request is fast."""
    logger.info("_warm_cache: pre-populating vault cache")
    try:
        get_domains()
        get_ideas()
        get_tasks()
        get_epics()
        get_meetings()
        await system_status()
        await overview_queue()
        logger.info("_warm_cache: cache populated successfully")
    except Exception as exc:
        logger.warning("_warm_cache: partial failure — %s", exc)
    try:
        vault_health()
    except Exception as exc:
        logger.warning("_warm_cache: vault_health failed: %s", exc)


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


class DomainConfigEntry(BaseModel):
    display_name: str
    description: str = ""
    color: str = "#607D8B"
    jira_labels: list[str] = []


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


class IdeaStatusUpdateRequest(BaseModel):
    status: str

class IdeaStatusUpdateResponse(BaseModel):
    status: str
    new_status: str
    readiness: int
    updated: str
    filename: str


# ---------------------------------------------------------------------------
# Service file exclusion
# ---------------------------------------------------------------------------

_SERVICE_FILES = frozenset({"index.md", "log.md"})

_VALID_IDEA_STATUSES = frozenset({
    "Новая",
    "Проверка гипотезы",
    "Готова к производству",
    "Отсев",
})


def _is_service_file(path: Path) -> bool:
    """Return True if the file is a service file (index.md, log.md)."""
    return path.name.lower() in _SERVICE_FILES


# ---------------------------------------------------------------------------
# Domain-based helpers
# ---------------------------------------------------------------------------

def _scan_domain_folders(
    artifact_type: str, domain_filter: str | None = None
) -> list[Path]:
    """Collect .md files from wiki/domains/*/artifact_type/.

    If domain_filter is set, only scan that domain.
    Excludes service files (index.md, log.md).
    """
    logger.debug(
        "_scan_domain_folders: artifact_type=%s domain_filter=%s",
        artifact_type, domain_filter,
    )
    files: list[Path] = []
    if domain_filter:
        try:
            folder = wiki_domain_dir(domain_filter, artifact_type)
        except ValueError as exc:
            logger.error("_scan_domain_folders: invalid artifact_type — %s", exc)
            return []
        if folder.exists():
            files.extend(
                f for f in folder.glob("*.md") if not _is_service_file(f)
            )
    else:
        for domain in all_domains():
            try:
                folder = wiki_domain_dir(domain, artifact_type)
            except ValueError as exc:
                logger.error("_scan_domain_folders: invalid artifact_type — %s", exc)
                return []
            if folder.exists():
                files.extend(
                    f for f in folder.glob("*.md") if not _is_service_file(f)
                )
    result = sorted(files, reverse=True)
    logger.debug("_scan_domain_folders: found %d files", len(result))
    return result


def _domain_from_path(path: Path) -> str:
    """Extract domain name from wiki/domains/<domain>/type/file.md path."""
    parts = path.parts
    try:
        idx = parts.index("domains")
        return parts[idx + 1]
    except (ValueError, IndexError):
        return "unknown"


def _find_idea_file(filename: str) -> Path | None:
    """Find an idea file by filename across all domain folders."""
    logger.info("_find_idea_file: searching for %s", filename)
    for domain in all_domains():
        try:
            folder = wiki_domain_dir(domain, "ideas")
        except ValueError:
            continue
        candidate = folder / filename
        if candidate.exists():
            logger.info("_find_idea_file: found %s in domain %s", filename, domain)
            return candidate
    logger.info("_find_idea_file: %s not found in any domain", filename)
    return None


def _update_frontmatter_field(text: str, key: str, value: str) -> str:
    """Replace or insert a frontmatter field in markdown text."""
    logger.info("_update_frontmatter_field: key=%s value=%s", key, value)
    pattern = r"(?<=\n)" + re.escape(key) + r":[ \t]+[^\n]*"
    if re.search(pattern, text):
        result = re.sub(pattern, key + ": " + value, text, count=1)
        logger.info("_update_frontmatter_field: replaced existing key %s", key)
        return result
    # Key not found — insert before closing ---
    # Find the second --- (closing frontmatter)
    parts = text.split("---", 2)
    if len(parts) >= 3:
        result = parts[0] + "---" + parts[1] + key + ": " + value + "\n---" + parts[2]
        logger.info("_update_frontmatter_field: inserted new key %s", key)
        return result
    logger.warning("_update_frontmatter_field: no frontmatter found, returning unchanged")
    return text


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

def parse_note(path: Path) -> dict:
    """Parse a .md file with optional YAML frontmatter.

    Returns a dict with at least: filename, date, title, body, and any
    frontmatter keys found.
    """
    logger.debug("parse_note: parsing file %s", path)
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.error("parse_note: failed to read %s — %s", path, exc)
        raise

    meta: dict = {}
    body = text

    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].strip().splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    val = v.strip()
                    if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                        val = val[1:-1]
                    meta[k.strip()] = val
            body = parts[2].strip()

    title_match = re.search(r"^# (.+)$", body, re.MULTILINE)
    meta["title"] = title_match.group(1) if title_match else path.stem
    meta["body"] = body
    meta["filename"] = path.name
    if "date" not in meta:
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", path.stem)
        if date_match:
            meta["date"] = date_match.group(1)
        else:
            date_match2 = re.search(r"(\d{4})(\d{2})(\d{2})", path.stem)
            if date_match2:
                meta["date"] = f"{date_match2.group(1)}-{date_match2.group(2)}-{date_match2.group(3)}"
            elif meta.get("created"):
                meta["date"] = str(meta["created"])
            else:
                meta["date"] = ""

    logger.debug("parse_note: success — file=%s title=%s", path.name, meta["title"])
    return meta


def parse_epic_note(path: Path) -> dict:
    """Parse an epic .md file using yaml.safe_load for complex frontmatter.

    Epic files contain structured YAML with tickets as a list of objects,
    so the simple line-by-line parser is insufficient.
    """
    logger.debug("parse_epic_note: parsing epic file %s", path)
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.error("parse_epic_note: failed to read %s — %s", path, exc)
        raise

    meta: dict = {}
    body = text

    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                parsed_yaml = yaml.safe_load(parts[1])
                if isinstance(parsed_yaml, dict):
                    meta = parsed_yaml
                else:
                    logger.warning(
                        "parse_epic_note: frontmatter is not a dict in %s", path
                    )
            except yaml.YAMLError as exc:
                logger.error(
                    "parse_epic_note: YAML parse error in %s — %s", path, exc
                )
            body = parts[2].strip()

    title_match = re.search(r"^# (.+)$", body, re.MULTILINE)
    meta["title"] = meta.get("title", title_match.group(1) if title_match else path.stem)
    meta["body"] = body
    meta["filename"] = path.name
    if "date" not in meta:
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", path.stem)
        if date_match:
            meta["date"] = date_match.group(1)
        else:
            date_match2 = re.search(r"(\d{4})(\d{2})(\d{2})", path.stem)
            if date_match2:
                meta["date"] = f"{date_match2.group(1)}-{date_match2.group(2)}-{date_match2.group(3)}"
            elif meta.get("created"):
                meta["date"] = str(meta["created"])
            else:
                meta["date"] = ""

    logger.debug(
        "parse_epic_note: success — file=%s title=%s", path.name, meta["title"]
    )
    return meta


def _extract_section(body: str, header: str) -> str:
    """Extract content under a ## header until next ## or end of file.

    Args:
        body: The markdown body text.
        header: The header text to search for (without ##).

    Returns:
        The section content as a string, or empty string if not found.
    """
    logger.debug("_extract_section: looking for section '%s'", header)
    pattern = rf"^## {re.escape(header)}\s*\n(.*?)(?=^## |\Z)"
    match = re.search(pattern, body, re.MULTILINE | re.DOTALL)
    if match:
        result = match.group(1).strip()
        logger.debug(
            "_extract_section: found section '%s' (%d chars)", header, len(result)
        )
        return result
    logger.debug("_extract_section: section '%s' not found", header)
    return ""


def _parse_tags(raw: str) -> list[str]:
    """Parse tags from frontmatter value.

    Handles both YAML list format '[tag1, tag2]' and comma-separated strings.
    """
    if not raw:
        return []
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    return [t.strip().strip('"').strip("'") for t in raw.split(",") if t.strip()]


def _safe_int(value, default: int = 0) -> int:
    """Safely convert a value to int, returning default on failure."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_readiness(raw) -> int:
    """Parse readiness value like '44%' or '44' into integer 0-100."""
    if not raw:
        return 0
    cleaned = str(raw).strip().rstrip("%").strip()
    try:
        val = int(cleaned)
        return max(0, min(100, val))
    except (ValueError, TypeError):
        return 0


# ---------------------------------------------------------------------------
# Dynamic readiness calculation from idea body sections
# ---------------------------------------------------------------------------

_IDEA_SECTION_HEADINGS = [
    r"### 1\.",
    r"### 2\.",
    r"### 3\.",
    r"### 4\.",
    r"### 5\.",
    r"### 6\.",
    r"### 7\.",
    r"### 8\.",
    r"### 9\.",
]


def _calculate_readiness(body: str) -> int:
    """Count filled sections (1-9) in idea body and return readiness 0-100.

    A section is considered "filled" if there is meaningful (non-whitespace)
    text between its ``### N.`` heading (after stripping HTML comments and
    the heading line itself) and the next section boundary (``###``, ``##``,
    ``---``, or end of file).

    Args:
        body: The markdown body text of the idea (after frontmatter).

    Returns:
        Integer 0-100 representing percentage of filled sections.
    """
    if not body:
        logger.debug("_calculate_readiness: empty body → 0%%")
        return 0

    filled = 0
    for heading_pat in _IDEA_SECTION_HEADINGS:
        # Find this section heading
        match = re.search(heading_pat, body)
        if not match:
            continue

        # Everything after the heading pattern match
        rest = body[match.end():]

        # Find the end boundary: next ### or ## or --- or end of string
        boundary = re.search(r"^(?:###\s|##\s|---)", rest, re.MULTILINE)
        section_text = rest[: boundary.start()] if boundary else rest

        # Strip HTML comments (possibly multi-line) and whitespace
        section_text = re.sub(r"<!--.*?-->", "", section_text, flags=re.DOTALL)

        # Strip the remainder of the heading line itself (everything up to first newline)
        section_text = re.sub(r"^[^\n]*\n?", "", section_text, count=1)

        section_text = section_text.strip()

        if section_text:
            filled += 1

    readiness = int((filled / 9) * 100) if filled > 0 else 0
    logger.debug("_calculate_readiness: %d/9 sections filled → %d%%", filled, readiness)
    return readiness


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

_ARTIFACT_TYPES = ("ideas", "prds", "epics", "userstories", "tasks", "bugs")


@app.get("/api/v1/domains")
def get_domains():
    """List all domains with artifact counts and last_updated.

    For each domain, counts .md files (excluding service files like index.md
    and log.md) in every artifact subdirectory, and finds the most recent
    file modification time across all artifact directories.

    Returns a list of domain objects sorted alphabetically by name.
    """
    logger.info("GET /api/v1/domains -- start")

    cached = _cache.get("domains")
    if cached is not None:
        logger.info("GET /api/v1/domains -- returning cached (%d domains)", len(cached))
        return cached

    domains = all_domains()
    logger.info("GET /api/v1/domains -- found %d domains", len(domains))

    results = []
    for domain in domains:
        logger.debug("GET /api/v1/domains -- processing domain '%s'", domain)
        counts: dict[str, int] = {}
        latest_mtime: float | None = None

        for artifact_type in _ARTIFACT_TYPES:
            try:
                folder = wiki_domain_dir(domain, artifact_type)
            except ValueError as exc:
                logger.error(
                    "GET /api/v1/domains -- invalid artifact_type '%s': %s",
                    artifact_type, exc,
                )
                counts[f"{artifact_type}_count"] = 0
                continue

            if not folder.exists():
                logger.debug(
                    "GET /api/v1/domains -- folder does not exist: %s/%s",
                    domain, artifact_type,
                )
                counts[f"{artifact_type}_count"] = 0
                continue

            md_files = [
                f for f in folder.glob("*.md") if not _is_service_file(f)
            ]
            counts[f"{artifact_type}_count"] = len(md_files)
            logger.debug(
                "GET /api/v1/domains -- %s/%s: %d files",
                domain, artifact_type, len(md_files),
            )

            if md_files:
                try:
                    dir_mtime = folder.stat().st_mtime
                    if latest_mtime is None or dir_mtime > latest_mtime:
                        latest_mtime = dir_mtime
                except OSError as exc:
                    logger.debug(
                        "GET /api/v1/domains -- failed to stat folder %s: %s",
                        folder, exc,
                    )

        total = sum(counts.values())

        if latest_mtime is not None:
            last_updated = datetime.fromtimestamp(latest_mtime).strftime(
                "%Y-%m-%d"
            )
        else:
            last_updated = None

        logger.debug(
            "GET /api/v1/domains -- domain '%s': total=%d, last_updated=%s",
            domain, total, last_updated,
        )

        results.append(
            {
                "name": domain,
                **counts,
                "total_count": total,
                "last_updated": last_updated,
            }
        )

    results.sort(key=lambda d: d["name"])

    # Enrich each domain with metadata from domain-config.yaml
    try:
        config = domain_config.load()
        config_domains = config.get("domains", {})
        for item in results:
            name = item["name"]
            if name in config_domains:
                cfg = config_domains[name]
                item["display_name"] = cfg.get("display_name", name)
                item["description"] = cfg.get("description", "")
                item["color"] = cfg.get("color", "#607D8B")
                item["jira_labels"] = cfg.get("jira_labels", [])
                logger.debug(
                    "GET /api/v1/domains -- enriched domain '%s' from config"
                    " (display_name=%r, color=%r, jira_labels=%r)",
                    name,
                    item["display_name"],
                    item["color"],
                    item["jira_labels"],
                )
            else:
                item["display_name"] = name
                item["description"] = ""
                item["color"] = "#607D8B"
                item["jira_labels"] = []
                logger.debug(
                    "GET /api/v1/domains -- domain '%s' not in config, using defaults",
                    name,
                )
        logger.info(
            "GET /api/v1/domains -- config enrichment complete for %d domains",
            len(results),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "GET /api/v1/domains -- config enrichment failed, using defaults: %s",
            exc,
        )
        for item in results:
            item.setdefault("display_name", item["name"])
            item.setdefault("description", "")
            item.setdefault("color", "#607D8B")
            item.setdefault("jira_labels", [])

    logger.info("GET /api/v1/domains -- returning %d domains", len(results))
    _cache.set("domains", results)
    return results


@app.get("/api/v1/ideas")
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
            results.append(
                {
                    "filename": note["filename"],
                    "date": note["date"],
                    "updated": note.get("updated", note["date"]),
                    "title": note["title"],
                    "tags": _parse_tags(note.get("tags", "")),
                    "status": note.get("status", "Новая"),
                    "body": note["body"],
                    "domain": _domain_from_path(f),
                    "id": note.get("id", ""),
                    "readiness": _calculate_readiness(note["body"]),
                }
            )
        except Exception as exc:
            logger.error("GET /api/v1/ideas — failed to parse %s: %s", f.name, exc)
            continue

    results.sort(key=lambda x: x["date"], reverse=True)
    logger.info("GET /api/v1/ideas — returning %d notes", len(results))
    _cache.set(cache_key, results)
    return results


@app.get("/api/v1/meetings")
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


@app.get("/api/v1/tasks")
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

    logger.info("_build_task_indices: %d status entries, %d epic entries", len(status_index), len(epic_index))
    result = (status_index, epic_index)
    _cache.set("_task_indices", result)
    return result


@app.get("/api/v1/tasks/by-key/{jira_key}")
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


@app.get("/api/v1/epics")
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

    task_status_index, epic_task_index = _build_task_indices()

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
                    _STATUS_WEIGHT.get(t["status"].lower(), 20)
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
                }
            )
        except Exception as exc:
            logger.error("GET /api/v1/epics — failed to parse %s: %s", f.name, exc)
            continue

    logger.info("GET /api/v1/epics — returning %d epics", len(results))
    _cache.set(cache_key, results)
    return results


def _extract_report_title(text: str) -> str | None:
    """Extract the first markdown heading from text after stripping frontmatter.

    Returns the heading text (without the ``# `` prefix), or None if no
    heading is found.
    """
    body = text
    stripped = text.lstrip()
    if stripped.startswith("---"):
        end = stripped.find("---", 3)
        if end != -1:
            body = stripped[end + 3:].lstrip("\n")

    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


@app.get("/api/v1/reports")
def list_reports():
    """Return a list of all available reports from wiki/reports/.

    Each entry contains ``filename``, ``date`` (extracted from filename prefix
    YYYY-MM-DD), and ``title`` (first ``# `` heading in the file body, or
    the filename stem when no heading is found).

    Reports are sorted by filename descending (newest first).
    Service files (index.md, log.md) are excluded.
    """
    logger.info("GET /api/v1/reports — start")
    folder = wiki_reports()

    if not folder.exists():
        logger.info(
            "GET /api/v1/reports — reports folder not found, returning empty list"
        )
        return {"reports": []}

    try:
        files = sorted(
            (f for f in folder.glob("*.md") if not _is_service_file(f)),
            reverse=True,
        )
        logger.info("GET /api/v1/reports — found %d report files", len(files))
    except Exception as exc:
        logger.error("GET /api/v1/reports — error listing files: %s", exc)
        return {"reports": []}

    results: list[dict] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
            date = f.stem[:10] if len(f.stem) >= 10 else f.stem
            title = _extract_report_title(text) or f.stem
            results.append(
                {"filename": f.name, "date": date, "title": title}
            )
            logger.info(
                "GET /api/v1/reports — parsed %s (date=%s, title=%s)",
                f.name, date, title,
            )
        except Exception as exc:
            logger.error(
                "GET /api/v1/reports — failed to parse %s: %s", f.name, exc
            )
            continue

    logger.info("GET /api/v1/reports — returning %d reports", len(results))
    return {"reports": results}


@app.get("/api/v1/reports/{filename}")
def get_report_by_filename(filename: str):
    """Return the full content of a specific report file.

    ``filename`` must end with ``.md`` and must not contain path separators
    (security check).  Returns 404 when the file does not exist.
    """
    logger.info("GET /api/v1/reports/%s — start", filename)

    # --- Security validation ---
    if not filename.endswith(".md"):
        logger.error(
            "GET /api/v1/reports/%s — rejected: filename does not end with .md",
            filename,
        )
        raise HTTPException(
            status_code=400,
            detail="Filename must end with .md",
        )

    if "/" in filename or "\\" in filename:
        logger.error(
            "GET /api/v1/reports/%s — rejected: path separators in filename",
            filename,
        )
        raise HTTPException(
            status_code=400,
            detail="Filename must not contain path separators",
        )

    folder = wiki_reports()
    filepath = folder / filename

    if not filepath.exists():
        logger.info(
            "GET /api/v1/reports/%s — file not found", filename
        )
        raise HTTPException(status_code=404, detail="Report not found")

    try:
        content = filepath.read_text(encoding="utf-8")
        date = filepath.stem[:10] if len(filepath.stem) >= 10 else filepath.stem
        logger.info(
            "GET /api/v1/reports/%s — returning report (%d chars)",
            filename, len(content),
        )
        return {"filename": filename, "content": content, "date": date}
    except Exception as exc:
        logger.error(
            "GET /api/v1/reports/%s — failed to read file: %s",
            filename, exc,
        )
        raise HTTPException(status_code=500, detail="Failed to read report")


@app.post("/api/v1/capture", response_model=CaptureResponse)
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
            try:
                content = process_jira_ticket(req.text)
                logger.info("POST /api/v1/capture — Claude returned %d chars", len(content))
            except Exception as llm_err:
                logger.warning("POST /api/v1/capture — Claude API failed, saving raw draft: %s", llm_err)
                content = _fallback_jira_content(req.text)

            filepath = write_jira_draft(content)
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
        response_content = json.dumps(content, ensure_ascii=False) if isinstance(content, dict) else content
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


@app.post("/api/v1/jira/import", response_model=JiraImportResponse)
def jira_import(req: JiraImportRequest):
    """Import a single Jira issue by key via knowledge-engine."""
    logger.info("POST /api/v1/jira/import — start, key=%s", req.key)

    if not re.match(r'^[A-Z][A-Z0-9]+-\d+$', req.key):
        logger.error("POST /api/v1/jira/import — invalid key format: %s", req.key)
        raise HTTPException(status_code=400, detail=f"Invalid Jira key format: {req.key}. Expected: PROJECT-123")

    try:
        result = subprocess.run(
            ["python", "-m", "knowledge_engine", "jira-import", req.key],
            capture_output=True, text=True, timeout=60,
        )
        logger.info("POST /api/v1/jira/import — subprocess exit code: %d", result.returncode)

        if result.returncode == 0:
            _cache.invalidate()
            import json as _json
            try:
                data = _json.loads(result.stdout)
                logger.info("POST /api/v1/jira/import — success: %s", data.get("message"))
                return JiraImportResponse(**data)
            except (ValueError, TypeError) as exc:
                logger.error("POST /api/v1/jira/import — failed to parse output: %s", exc)
                return JiraImportResponse(status="ok", key=req.key, message="Import completed")
        else:
            error_msg = result.stderr[:300]
            try:
                import json as _json
                data = _json.loads(result.stdout)
                error_msg = data.get("message", error_msg)
            except Exception:
                pass
            logger.error("POST /api/v1/jira/import — failed: %s", error_msg)
            raise HTTPException(status_code=502, detail=error_msg)

    except subprocess.TimeoutExpired:
        logger.error("POST /api/v1/jira/import — timeout for key=%s", req.key)
        raise HTTPException(status_code=504, detail="Import timed out after 60 seconds")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("POST /api/v1/jira/import — error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/v1/jira/create", response_model=JiraCreateResponse)
def jira_create(req: JiraCreateRequest):
    """Create a new Jira issue from a vault task file via knowledge-engine."""
    import json as _json

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

    # --- Subprocess call ---
    cmd = [
        "python", "-m", "knowledge_engine", "jira-create",
        "--file", req.filename,
        "--project", req.project_key,
        "--type", req.issue_type,
        "--summary", req.summary,
    ]
    if req.epic_key:
        cmd.extend(["--epic", req.epic_key])

    logger.info("POST /api/v1/jira/create — running subprocess: %s", cmd)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        logger.info("POST /api/v1/jira/create — subprocess exit code: %d", result.returncode)

        if result.returncode == 0:
            _cache.invalidate()
            try:
                data = _json.loads(result.stdout)
                logger.info(
                    "POST /api/v1/jira/create — success: jira_key=%s", data.get("jira_key")
                )
                return JiraCreateResponse(**data)
            except (ValueError, TypeError) as exc:
                logger.error("POST /api/v1/jira/create — failed to parse output: %s", exc)
                return JiraCreateResponse(status="ok", message="Issue created")
        else:
            error_msg = result.stderr[:300]
            try:
                data = _json.loads(result.stdout)
                error_msg = data.get("message", error_msg)
            except Exception:
                pass
            logger.error("POST /api/v1/jira/create — failed: %s", error_msg)
            raise HTTPException(status_code=502, detail=error_msg)

    except subprocess.TimeoutExpired:
        logger.error("POST /api/v1/jira/create — timeout")
        raise HTTPException(status_code=504, detail="jira-create timed out after 60 seconds")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("POST /api/v1/jira/create — error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/v1/jira/projects")
def jira_projects():
    """List available Jira projects via knowledge-engine."""
    import json as _json

    logger.info("GET /api/v1/jira/projects — start")
    try:
        result = subprocess.run(
            ["python", "-m", "knowledge_engine", "jira-projects"],
            capture_output=True, text=True, timeout=30,
        )
        logger.info("GET /api/v1/jira/projects — subprocess exit code: %d", result.returncode)

        if result.returncode == 0:
            try:
                data = _json.loads(result.stdout)
                projects = data.get("projects", data) if isinstance(data, dict) else data
                logger.info("GET /api/v1/jira/projects — success, count=%d", len(projects))
                return projects
            except (ValueError, TypeError) as exc:
                logger.error("GET /api/v1/jira/projects — failed to parse output: %s", exc)
                raise HTTPException(status_code=502, detail="Failed to parse projects response")
        else:
            error_msg = result.stderr[:300]
            try:
                data = _json.loads(result.stdout)
                error_msg = data.get("message", error_msg)
            except Exception:
                pass
            logger.error("GET /api/v1/jira/projects — failed: %s", error_msg)
            raise HTTPException(status_code=502, detail=error_msg)

    except subprocess.TimeoutExpired:
        logger.error("GET /api/v1/jira/projects — timeout")
        raise HTTPException(status_code=504, detail="jira-projects timed out after 30 seconds")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("GET /api/v1/jira/projects — error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/v1/jira/projects/{project_key}/epics")
def jira_project_epics(project_key: str):
    """List epics for a given Jira project via knowledge-engine."""
    import json as _json

    logger.info("GET /api/v1/jira/projects/%s/epics — start", project_key)

    if not re.match(r'^[A-Z][A-Z0-9]+$', project_key):
        logger.error(
            "GET /api/v1/jira/projects/%s/epics — rejected: invalid project_key", project_key
        )
        raise HTTPException(status_code=400, detail="project_key must match ^[A-Z][A-Z0-9]+$")

    try:
        result = subprocess.run(
            ["python", "-m", "knowledge_engine", "jira-epics", "--project", project_key],
            capture_output=True, text=True, timeout=30,
        )
        logger.info(
            "GET /api/v1/jira/projects/%s/epics — subprocess exit code: %d",
            project_key, result.returncode,
        )

        if result.returncode == 0:
            try:
                data = _json.loads(result.stdout)
                epics = data.get("epics", data) if isinstance(data, dict) else data
                logger.info(
                    "GET /api/v1/jira/projects/%s/epics — success, count=%d",
                    project_key, len(epics),
                )
                return epics
            except (ValueError, TypeError) as exc:
                logger.error(
                    "GET /api/v1/jira/projects/%s/epics — failed to parse output: %s",
                    project_key, exc,
                )
                raise HTTPException(status_code=502, detail="Failed to parse epics response")
        else:
            error_msg = result.stderr[:300]
            try:
                data = _json.loads(result.stdout)
                error_msg = data.get("message", error_msg)
            except Exception:
                pass
            logger.error(
                "GET /api/v1/jira/projects/%s/epics — failed: %s", project_key, error_msg
            )
            raise HTTPException(status_code=502, detail=error_msg)

    except subprocess.TimeoutExpired:
        logger.error("GET /api/v1/jira/projects/%s/epics — timeout", project_key)
        raise HTTPException(status_code=504, detail="jira-epics timed out after 30 seconds")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "GET /api/v1/jira/projects/%s/epics — error: %s", project_key, exc, exc_info=True
        )
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/v1/jira/projects/{projectKey}/issue-types")
def get_jira_issue_types(projectKey: str):
    """Fetch available issue types for a Jira project."""
    import json as _json

    logger.info("GET /api/v1/jira/projects/%s/issue-types — start", projectKey)

    if not re.match(r'^[A-Z][A-Z0-9]+$', projectKey):
        logger.error(
            "GET /api/v1/jira/projects/%s/issue-types — rejected: invalid projectKey", projectKey
        )
        raise HTTPException(status_code=400, detail="Invalid project key format")

    try:
        result = subprocess.run(
            ["python", "-m", "knowledge_engine", "jira-issue-types", "--project", projectKey],
            capture_output=True, text=True, timeout=30,
        )
        logger.info(
            "GET /api/v1/jira/projects/%s/issue-types — subprocess exit code: %d",
            projectKey, result.returncode,
        )

        if result.returncode == 0:
            try:
                data = _json.loads(result.stdout)
                issue_types = data.get("issue_types", data) if isinstance(data, dict) else data
                logger.info(
                    "GET /api/v1/jira/projects/%s/issue-types — success, count=%d",
                    projectKey, len(issue_types),
                )
                return issue_types
            except (ValueError, TypeError) as exc:
                logger.error(
                    "GET /api/v1/jira/projects/%s/issue-types — failed to parse output: %s",
                    projectKey, exc,
                )
                raise HTTPException(status_code=502, detail="Failed to parse issue-types response")
        else:
            error_msg = result.stderr[:300]
            try:
                data = _json.loads(result.stdout)
                error_msg = data.get("message", error_msg)
            except Exception:
                pass
            logger.error(
                "GET /api/v1/jira/projects/%s/issue-types — failed: %s", projectKey, error_msg
            )
            raise HTTPException(status_code=502, detail=error_msg)

    except subprocess.TimeoutExpired:
        logger.error("GET /api/v1/jira/projects/%s/issue-types — timeout", projectKey)
        raise HTTPException(status_code=504, detail="jira-issue-types timed out after 30 seconds")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "GET /api/v1/jira/projects/%s/issue-types — error: %s", projectKey, exc, exc_info=True
        )
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Jira Sync (force) endpoint
# ---------------------------------------------------------------------------

@app.post("/api/v1/jira/sync")
def jira_sync():
    """Trigger forced Jira sync via knowledge-engine subprocess."""
    import json as _json

    logger.info("POST /api/v1/jira/sync — start")

    if not _jira_sync_lock.acquire(blocking=False):
        logger.warning("POST /api/v1/jira/sync — rejected: sync already running")
        raise HTTPException(status_code=409, detail="Jira sync is already running")

    try:
        prefs = _read_user_prefs()
        should_notify = prefs.get("jira_sync_notify", True)
        cmd = ["python", "-m", "knowledge_engine", "jira-sync"]
        if should_notify:
            cmd.append("--notify")
        logger.info("POST /api/v1/jira/sync — should_notify=%s", should_notify)
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=180,
        )
        logger.info("POST /api/v1/jira/sync — subprocess exit code: %d", result.returncode)

        if result.returncode == 0:
            try:
                last_line = result.stdout.strip().split('\n')[-1]
                data = _json.loads(last_line)
            except (ValueError, TypeError, IndexError) as exc:
                logger.error("POST /api/v1/jira/sync — failed to parse output: %s", exc)
                data = {}

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
            state_file = VAULT_PATH / ".jira-sync-state.json"
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
                tmp_file = VAULT_PATH / ".jira-sync-state.json.tmp"
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
        else:
            error_msg = result.stderr[:300]
            logger.error("POST /api/v1/jira/sync — failed: %s", error_msg)
            raise HTTPException(status_code=502, detail=error_msg)

    except subprocess.TimeoutExpired:
        logger.error("POST /api/v1/jira/sync — timeout after 180 seconds")
        raise HTTPException(status_code=504, detail="Jira sync timed out after 180 seconds")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("POST /api/v1/jira/sync — error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        _jira_sync_lock.release()


@app.get("/api/v1/timeline/{ticket_id}")
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


@app.post("/api/v1/synthesize")
def synthesize_inbox():
    """Run knowledge-engine synthesize via subprocess."""
    import subprocess

    logger.info("POST /api/v1/synthesize — start")
    try:
        result = subprocess.run(
            ["python", "-m", "knowledge_engine", "synthesize"],
            capture_output=True, text=True, timeout=120,
        )
        logger.info("POST /api/v1/synthesize — exit code: %d", result.returncode)

        if result.returncode == 0:
            _cache.invalidate()
            import json as _json
            try:
                data = _json.loads(result.stdout)
                logger.info("POST /api/v1/synthesize — success: %s", data.get("status"))
                return data
            except ValueError:
                logger.info("POST /api/v1/synthesize — completed (non-JSON output)")
                return {"status": "ok", "message": "Synthesis completed"}
        else:
            logger.error("POST /api/v1/synthesize — failed: %s", result.stderr[:300])
            raise HTTPException(status_code=500, detail=result.stderr[:300])
    except subprocess.TimeoutExpired:
        logger.error("POST /api/v1/synthesize — timeout after 120s")
        raise HTTPException(status_code=504, detail="Synthesis timed out after 120 seconds")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("POST /api/v1/synthesize — error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/v1/pipeline")
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
# Domain config endpoints
# ---------------------------------------------------------------------------

@app.get("/api/v1/domain-config")
def get_domain_config():
    """Return the full domain configuration."""
    logger.info("GET /api/v1/domain-config — start")
    from . import domain_config

    try:
        config = domain_config.load()
        logger.info(
            "GET /api/v1/domain-config — loaded config with %d domain(s)",
            len(config.get("domains", {})),
        )
    except Exception as exc:
        logger.error("GET /api/v1/domain-config — failed to load config: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    if not config.get("domains"):
        logger.info("GET /api/v1/domain-config — no domains found, returning fallback response")
        return JSONResponse(content={
            "domains": {},
            "_fallback": True,
            "_message": "domain-config.yaml not found or empty",
        })

    logger.info(
        "GET /api/v1/domain-config — returning %d domain(s)", len(config["domains"])
    )
    return config


@app.put("/api/v1/domain-config/{domain_slug}")
def put_domain_config(domain_slug: str, entry: DomainConfigEntry):
    """Create or update a domain config entry."""
    logger.info("PUT /api/v1/domain-config/%s — start", domain_slug)
    from . import domain_config as _domain_config

    # Check if domain exists before update
    try:
        existing = _domain_config.get_domain(domain_slug)
    except Exception as exc:
        logger.error(
            "PUT /api/v1/domain-config/%s — error checking existing domain: %s",
            domain_slug, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(exc))

    is_new = existing is None
    logger.info(
        "PUT /api/v1/domain-config/%s — is_new=%s", domain_slug, is_new
    )

    try:
        _domain_config.set_domain(domain_slug, entry.model_dump())
        _cache.invalidate()
        logger.info(
            "PUT /api/v1/domain-config/%s — set_domain succeeded", domain_slug
        )
    except ValueError as exc:
        error_msg = str(exc)
        logger.warning(
            "PUT /api/v1/domain-config/%s — validation error: %s", domain_slug, error_msg
        )
        if "already owned by" in error_msg or "already mapped" in error_msg:
            raise HTTPException(status_code=409, detail=error_msg)
        raise HTTPException(status_code=422, detail=error_msg)
    except Exception as exc:
        logger.error(
            "PUT /api/v1/domain-config/%s — unexpected error: %s",
            domain_slug, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(exc))

    # Scaffold domain directories if this is a new domain
    scaffold = False
    if is_new:
        domain_base = VAULT_PATH / "wiki" / "domains" / domain_slug
        if not domain_base.exists():
            logger.info(
                "PUT /api/v1/domain-config/%s — domain dir not found, scaffolding: %s",
                domain_slug, domain_base,
            )
            try:
                for art_type in _ARTIFACT_TYPES:
                    art_dir = domain_base / art_type
                    art_dir.mkdir(parents=True, exist_ok=True)
                    logger.info(
                        "PUT /api/v1/domain-config/%s — created dir: %s",
                        domain_slug, art_dir,
                    )
                scaffold = True
                logger.info(
                    "PUT /api/v1/domain-config/%s — scaffold complete (%d dirs created)",
                    domain_slug, len(_ARTIFACT_TYPES),
                )
            except Exception as exc:
                logger.error(
                    "PUT /api/v1/domain-config/%s — scaffold failed: %s",
                    domain_slug, exc, exc_info=True,
                )
        else:
            logger.info(
                "PUT /api/v1/domain-config/%s — domain dir already exists, skipping scaffold",
                domain_slug,
            )

    status_code = 201 if is_new else 200
    action = "created" if is_new else "updated"
    logger.info(
        "PUT /api/v1/domain-config/%s — returning status=%d action=%s scaffold=%s",
        domain_slug, status_code, action, scaffold,
    )
    return JSONResponse(
        content={
            "status": "ok",
            "domain": domain_slug,
            "action": action,
            "scaffold": scaffold,
        },
        status_code=status_code,
    )


@app.post("/api/v1/domain-config/seed")
def seed_domain_config():
    """Seed config from hardcoded defaults + filesystem domains. Idempotent."""
    logger.info("POST /api/v1/domain-config/seed — start")
    from . import domain_config as _domain_config

    # Hardcoded label→domain map (mirrors knowledge-engine mapper defaults)
    LABEL_TO_DOMAIN = {
        "dictionary": "static-metadata",
        "suggester": "suggester",
        "search": "search-engine",
        "partner_search": "partner-search-engine",
    }
    logger.info(
        "POST /api/v1/domain-config/seed — hardcoded map has %d label(s)", len(LABEL_TO_DOMAIN)
    )

    existing = all_domains()
    logger.info(
        "POST /api/v1/domain-config/seed — found %d filesystem domain(s)", len(existing)
    )

    path = _domain_config.config_path()
    already_exists = path.exists()
    logger.info(
        "POST /api/v1/domain-config/seed — config already_exists=%s at %s",
        already_exists, path,
    )

    try:
        config = _domain_config.seed_from_defaults(LABEL_TO_DOMAIN, existing)
        _cache.invalidate()
        domains_count = len(config.get("domains", {}))
        logger.info(
            "POST /api/v1/domain-config/seed — seed_from_defaults returned %d domain(s)",
            domains_count,
        )
    except Exception as exc:
        logger.error(
            "POST /api/v1/domain-config/seed — seed_from_defaults failed: %s",
            exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(exc))

    action = "already_exists" if already_exists else "seeded"
    logger.info(
        "POST /api/v1/domain-config/seed — done, action=%s domains_count=%d",
        action, domains_count,
    )
    return {
        "status": "ok",
        "action": action,
        "domains_count": domains_count,
    }


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class SettingsModel(BaseModel):
    vault_path: str = ""
    transcripts_path: str = ""
    report_time: str = "09:00"
    report_day: str = "mon"
    prompts: dict = {}  # key: prompt name, value: prompt content


@app.get("/api/v1/settings")
def get_settings():
    """Read current settings from environment and prompt files."""
    logger.info("GET /api/v1/settings — start")

    settings = {
        "vault_path": os.getenv("VAULT_PATH", "/vault"),
        "transcripts_path": os.getenv("TRANSCRIPTS_INBOX", "/transcripts/inbox"),
        "report_time": "09:00",
        "report_day": "mon",
        "prompts": {},
    }

    # Read prompt files
    prompts_dir = Path(__file__).parent / "prompts"
    logger.info("GET /api/v1/settings — scanning prompts dir: %s", prompts_dir)
    if prompts_dir.exists():
        for f in prompts_dir.glob("*.txt"):
            try:
                settings["prompts"][f.stem] = f.read_text(encoding="utf-8")
                logger.info("GET /api/v1/settings — loaded prompt: %s", f.stem)
            except Exception as exc:
                logger.error(
                    "GET /api/v1/settings — failed to read prompt %s: %s",
                    f.name,
                    exc,
                )
    else:
        logger.warning(
            "GET /api/v1/settings — prompts dir not found: %s", prompts_dir
        )

    logger.info(
        "GET /api/v1/settings — returning %d prompts", len(settings["prompts"])
    )
    return settings


@app.post("/api/v1/settings")
def save_settings(settings: SettingsModel):
    """Save settings — currently only prompt files can be saved."""
    logger.info("POST /api/v1/settings — start")

    saved_count = 0
    prompts_dir = Path(__file__).parent / "prompts"

    for name, content in settings.prompts.items():
        # Security: reject path traversal attempts
        if ".." in name or "/" in name or "\\" in name:
            logger.warning(
                "POST /api/v1/settings — rejecting path traversal attempt: %s",
                name,
            )
            continue

        filepath = prompts_dir / f"{name}.txt"

        # Only allow writing to existing prompt files
        if not filepath.exists():
            logger.warning(
                "POST /api/v1/settings — skipping unknown prompt: %s", name
            )
            continue

        try:
            filepath.write_text(content, encoding="utf-8")
            saved_count += 1
            logger.info("POST /api/v1/settings — saved prompt: %s", name)
        except Exception as exc:
            logger.error(
                "POST /api/v1/settings — failed to save prompt %s: %s", name, exc
            )

    logger.info("POST /api/v1/settings — saved %d prompts", saved_count)
    _cache.invalidate()
    return {"status": "ok", "saved_prompts": saved_count}


# ---------------------------------------------------------------------------
# User preferences (refresh mode, etc.)
# ---------------------------------------------------------------------------

_VALID_REFRESH_MODES = frozenset({"auto", "manual"})
_VALID_THEMES = frozenset({"matrix", "light"})
_VALID_LLM_PROVIDERS = frozenset({"claude", "ollama", "hybrid"})
_DEFAULT_USER_PREFS = {
    "refresh_mode": "auto",
    "theme": "matrix",
    "llm_provider": "claude",
    "ollama_url": "",
    "ollama_model": "qwen3.5:latest",
    "jira_sync_notify": True,
}


class UserPrefs(BaseModel):
    refresh_mode: str = "auto"
    theme: str = "matrix"
    llm_provider: str = "claude"
    ollama_url: str = ""
    ollama_model: str = "qwen3.5:latest"
    jira_sync_notify: bool = True


def _read_user_prefs() -> dict:
    from .vault_paths import user_prefs_path
    path = user_prefs_path()
    if not path.exists():
        logger.info("_read_user_prefs: file not found at %s, returning defaults", path)
        return dict(_DEFAULT_USER_PREFS)
    try:
        import json as _json
        data = _json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            logger.warning("_read_user_prefs: file is not a JSON object, returning defaults")
            return dict(_DEFAULT_USER_PREFS)
        logger.info("_read_user_prefs: loaded prefs from %s", path)
        return data
    except Exception as exc:
        logger.warning("_read_user_prefs: failed to read %s: %s, returning defaults", path, exc)
        return dict(_DEFAULT_USER_PREFS)


def _write_user_prefs(prefs: dict) -> None:
    import json as _json

    from .file_writer import atomic_write
    from .vault_paths import user_prefs_path
    path = user_prefs_path()
    content = _json.dumps(prefs, indent=2, ensure_ascii=False) + "\n"
    logger.info("_write_user_prefs: writing to %s", path)
    atomic_write(path, content)
    logger.info("_write_user_prefs: success")


@app.get("/api/v1/user-prefs")
def get_user_prefs():
    logger.info("GET /api/v1/user-prefs — start")
    prefs = _read_user_prefs()
    if prefs.get("refresh_mode") not in _VALID_REFRESH_MODES:
        prefs["refresh_mode"] = "auto"
    if prefs.get("theme") not in _VALID_THEMES:
        prefs["theme"] = "matrix"
    if prefs.get("llm_provider") not in _VALID_LLM_PROVIDERS:
        prefs["llm_provider"] = "claude"
    if "ollama_url" not in prefs:
        prefs["ollama_url"] = ""
    if "ollama_model" not in prefs:
        prefs["ollama_model"] = "qwen3.5:latest"
    if "jira_sync_notify" not in prefs:
        prefs["jira_sync_notify"] = True
    logger.info("GET /api/v1/user-prefs — returning refresh_mode=%s theme=%s llm_provider=%s", prefs["refresh_mode"], prefs["theme"], prefs["llm_provider"])
    return prefs


@app.put("/api/v1/user-prefs")
def put_user_prefs(body: UserPrefs):
    logger.info("PUT /api/v1/user-prefs — start, refresh_mode=%s theme=%s", body.refresh_mode, body.theme)
    if body.refresh_mode not in _VALID_REFRESH_MODES:
        logger.warning("PUT /api/v1/user-prefs — invalid refresh_mode: %s", body.refresh_mode)
        raise HTTPException(
            status_code=422,
            detail=f"refresh_mode must be one of: {', '.join(sorted(_VALID_REFRESH_MODES))}"
        )
    if body.theme not in _VALID_THEMES:
        logger.warning("PUT /api/v1/user-prefs — invalid theme: %s", body.theme)
        raise HTTPException(
            status_code=422,
            detail=f"theme must be one of: {', '.join(sorted(_VALID_THEMES))}"
        )
    if body.llm_provider not in _VALID_LLM_PROVIDERS:
        logger.warning("PUT /api/v1/user-prefs — invalid llm_provider: %s", body.llm_provider)
        raise HTTPException(
            status_code=422,
            detail=f"llm_provider must be one of: {', '.join(sorted(_VALID_LLM_PROVIDERS))}"
        )
    prefs = body.model_dump()
    try:
        _write_user_prefs(prefs)
    except Exception as exc:
        logger.error("PUT /api/v1/user-prefs — write failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    _cache.invalidate()
    try:
        from .llm_client import invalidate_cache as _invalidate_llm_cache
        _invalidate_llm_cache()
    except ImportError:
        pass
    logger.info("PUT /api/v1/user-prefs — saved successfully")
    return {"status": "ok", "refresh_mode": body.refresh_mode, "theme": body.theme,
            "llm_provider": body.llm_provider, "ollama_url": body.ollama_url,
            "ollama_model": body.ollama_model, "jira_sync_notify": body.jira_sync_notify}


# ---------------------------------------------------------------------------
# Test Ollama connectivity
# ---------------------------------------------------------------------------


class TestOllamaRequest(BaseModel):
    url: str


@app.post("/api/v1/test-ollama")
def test_ollama(body: TestOllamaRequest):
    logger.info("POST /api/v1/test-ollama — url=%s", body.url)
    import httpx

    base = body.url.rstrip("/")
    try:
        with httpx.Client(timeout=5.0) as http:
            ver_resp = http.get(f"{base}/api/version")
            ver_resp.raise_for_status()
            version = ver_resp.json().get("version", "unknown")
            logger.info("test-ollama: version=%s", version)

            tags_resp = http.get(f"{base}/api/tags")
            tags_resp.raise_for_status()
            models_data = tags_resp.json().get("models", [])
            model_names = [m.get("name", "") for m in models_data if m.get("name")]
            logger.info("test-ollama: found %d models", len(model_names))
    except httpx.ConnectError as exc:
        logger.warning("test-ollama: connection failed: %s", exc)
        return {"status": "error", "detail": f"Connection refused: {base}"}
    except httpx.TimeoutException as exc:
        logger.warning("test-ollama: timeout: %s", exc)
        return {"status": "error", "detail": f"Timeout connecting to {base}"}
    except Exception as exc:
        logger.error("test-ollama: unexpected error: %s", exc)
        return {"status": "error", "detail": str(exc)}

    logger.info("POST /api/v1/test-ollama — success, version=%s, models=%s", version, model_names)
    return {"status": "ok", "ollama_version": version, "models": model_names}


# ---------------------------------------------------------------------------
# Report regeneration
# ---------------------------------------------------------------------------

@app.post("/api/v1/report/regenerate")
def regenerate_report():
    """Regenerate the weekly report."""
    logger.info("POST /api/v1/report/regenerate — start")
    try:
        from app.obsidian_writer import write_report
        from app.reporter import generate_weekly_report

        logger.info(
            "POST /api/v1/report/regenerate — calling generate_weekly_report"
        )
        report_md = generate_weekly_report()
        logger.info(
            "POST /api/v1/report/regenerate — generated %d chars", len(report_md)
        )

        logger.info("POST /api/v1/report/regenerate — calling write_report")
        filepath = write_report(report_md)
        _cache.invalidate()
        logger.info(
            "POST /api/v1/report/regenerate — saved to %s", filepath.name
        )

        return {"filename": filepath.name, "content": report_md}
    except Exception as exc:
        logger.error(
            "POST /api/v1/report/regenerate — error: %s", exc, exc_info=True
        )
        raise HTTPException(status_code=500, detail=str(exc))


@app.patch("/api/v1/ideas/{filename}/status")
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


# ---------------------------------------------------------------------------
# Health Score
# ---------------------------------------------------------------------------

@app.get("/api/v1/vault/health")
def vault_health():
    """Calculate or return cached vault health score with trends."""
    cache_key = "vault_health"
    cached = _cache.get(cache_key)
    if cached is not None:
        logger.info("vault_health: returning cached result")
        return cached

    logger.info("vault_health: cache miss, running health calculation via subprocess")

    try:
        result = subprocess.run(
            ["python", "-m", "knowledge_engine", "health", "--save", "--json"],
            capture_output=True, text=True, timeout=60,
        )
    except subprocess.TimeoutExpired:
        logger.error("vault_health: subprocess timed out after 60s")
        raise HTTPException(status_code=504, detail="Health calculation timed out after 60 seconds")
    except Exception as exc:
        logger.error("vault_health: subprocess failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Health calculation failed: {exc}")

    if result.returncode != 0:
        stderr_snippet = (result.stderr or "")[:300]
        logger.error("vault_health: subprocess returned %d, stderr=%s", result.returncode, stderr_snippet)
        raise HTTPException(status_code=502, detail=f"Health calculation failed: {stderr_snippet}")

    try:
        data = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error("vault_health: cannot parse subprocess output: %s", exc)
        raise HTTPException(status_code=502, detail="Health calculation returned invalid JSON")

    _cache.set(cache_key, data)
    logger.info("vault_health: completed, score=%s grade=%s", data.get("score"), data.get("grade"))
    return data


# ---------------------------------------------------------------------------
# System status endpoint
# ---------------------------------------------------------------------------

@app.get("/api/v1/system/status")
async def system_status():
    """Return system health: bot online flag, Jira sync time, STT status, vault freshness."""
    cached = _cache.get("system_status")
    if cached is not None:
        logger.info("system_status — returning cached")
        return cached

    # bot_online: the fact that this endpoint responds means the server is alive
    bot_online = True

    # stt_enabled: from environment variable
    stt_enabled = os.getenv("STT_ENABLED", "0").strip().lower() in ("1", "true", "yes")

    # vault_last_updated: check mtime of key directories instead of walking all files
    vault_last_updated = None
    try:
        check_dirs = [
            VAULT_PATH / "wiki" / "domains",
            VAULT_PATH / "wiki" / "meetings",
            VAULT_PATH / "wiki" / "reports",
        ]
        for d in check_dirs:
            if d.exists():
                try:
                    mtime = d.stat().st_mtime
                    if vault_last_updated is None or mtime > vault_last_updated:
                        vault_last_updated = mtime
                except OSError:
                    pass
    except Exception as exc:
        logger.warning("system_status — vault check error: %s", exc)

    vault_last_updated_iso = (
        datetime.utcfromtimestamp(vault_last_updated).isoformat() + "Z"
        if vault_last_updated is not None else None
    )

    # jira_last_sync: read from marker file written by Jira sync job
    jira_marker = VAULT_PATH / ".jira_last_sync"
    jira_last_sync = None
    if jira_marker.exists():
        try:
            content = jira_marker.read_text(encoding="utf-8").strip()
            jira_last_sync = content if content else None
        except Exception as exc:
            logger.warning("system_status — jira marker read error: %s", exc)

    logger.info(
        "system_status — bot_online=%s stt=%s vault_updated=%s jira_sync=%s",
        bot_online, stt_enabled, vault_last_updated_iso, jira_last_sync,
    )
    result = {
        "bot_online": bot_online,
        "jira_last_sync": jira_last_sync,
        "stt_enabled": stt_enabled,
        "vault_last_updated": vault_last_updated_iso,
    }
    _cache.set("system_status", result)
    return result


# ---------------------------------------------------------------------------
# Jira Sync Status endpoint
# ---------------------------------------------------------------------------

@app.get("/api/v1/jira/sync-status")
def jira_sync_status():
    """Read .jira-sync-state.json from vault and return sync status summary."""
    import json as _json

    logger.info("GET /api/v1/jira/sync-status — start")

    cached = _cache.get("jira_sync_status")
    if cached is not None:
        logger.info("GET /api/v1/jira/sync-status — returning cached")
        return cached

    state_file = VAULT_PATH / ".jira-sync-state.json"
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


# ---------------------------------------------------------------------------
# Today's Queue endpoint
# ---------------------------------------------------------------------------

@app.get("/api/v1/overview/queue")
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
