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
import threading
import time as _time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests
import yaml
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from shared import domain_config
from shared.vault_paths import (
    VAULT_PATH,
    all_domains,
    wiki_domain_dir,
    wiki_meetings,
    wiki_reports,
)

from . import calendar_client, ke_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory TTL cache for vault scan results
# ---------------------------------------------------------------------------


class _VaultCache:
    """Simple TTL cache for expensive vault scan + parse results."""

    def __init__(self, ttl_seconds: float = 5.0):
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}

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

_caldav_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="caldav")

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


class DecayTouchRequest(BaseModel):
    filepath: str


class DecaySetTierRequest(BaseModel):
    filepath: str
    tier: str


class IdeaStatusUpdateRequest(BaseModel):
    status: str

class IdeaStatusUpdateResponse(BaseModel):
    status: str
    new_status: str
    readiness: int
    updated: str
    filename: str


class TodoCreateRequest(BaseModel):
    title: str
    due_date: str | None = None
    context: str | None = None


class TodoUpdateRequest(BaseModel):
    status: str
    result: str | None = None


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


def _find_artifact_file(filename: str) -> Path | None:
    """Find artifact file by filename across all domain folders and meetings."""
    logger.info("_find_artifact_file: searching for %s", filename)
    try:
        domains = all_domains()
    except Exception as exc:
        logger.error("_find_artifact_file: all_domains() failed: %s", exc)
        domains = []
    for artifact_type in ("ideas", "tasks", "epics", "prds", "bugs"):
        for domain in domains:
            try:
                folder = wiki_domain_dir(domain, artifact_type)
            except ValueError:
                continue
            candidate = folder / filename
            if candidate.exists():
                logger.info("_find_artifact_file: found %s in %s/%s", filename, domain, artifact_type)
                return candidate
    # Search in meetings
    meetings_dir = VAULT_PATH / "wiki" / "meetings"
    if meetings_dir.exists():
        candidate = meetings_dir / filename
        if candidate.exists():
            logger.info("_find_artifact_file: found %s in meetings", filename)
            return candidate
    logger.info("_find_artifact_file: %s not found", filename)
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
# Search index
# ---------------------------------------------------------------------------

_CATEGORY_URL = {
    "idea": "ideas.html",
    "task": "board.html",
    "epic": "roadmap.html",
    "meeting": "dashboard.html",
    "prd": "roadmap.html",
    "bug": "board.html",
    "report": "report.html",
}


@dataclass
class _SearchEntry:
    path: str
    title: str
    tags: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    artifact_id: str = ""
    category: str = ""
    domain: str = ""
    date: str = ""
    url: str = ""


def _extract_search_keywords(title: str, body: str) -> list[str]:
    """Extract search keywords from title and body text.

    Splits title into words (len > 2), extracts ## headings into words (len > 2),
    and takes first 300 chars of body (after removing headings) into words (len > 3).
    All words are lowercased and deduplicated.
    """
    splitter = r'[\s\-_/,.:;!?()\[\]{}#*>~|"\']+'
    keywords: set[str] = set()

    # Title words: len > 2
    for word in re.split(splitter, title):
        word = word.strip().lower()
        if len(word) > 2:
            keywords.add(word)

    # Heading words from ## headings: len > 2
    headings = re.findall(r"^##\s+(.+)$", body, re.MULTILINE)
    for heading in headings:
        for word in re.split(splitter, heading):
            word = word.strip().lower()
            if len(word) > 2:
                keywords.add(word)

    # Body snippet (first 300 chars, headings removed): len > 3
    body_clean = re.sub(r"^#{1,6}\s+.*$", "", body, flags=re.MULTILINE)
    snippet = body_clean[:300]
    for word in re.split(splitter, snippet):
        word = word.strip().lower()
        if len(word) > 3:
            keywords.add(word)

    logger.debug("_extract_search_keywords: extracted %d keywords from title='%s'", len(keywords), title[:50])
    return list(keywords)


def _extract_artifact_id(note: dict, filepath: Path) -> str:
    """Extract artifact ID from frontmatter or filename.

    Checks: frontmatter 'id' field, frontmatter 'jira_key' field,
    then filename patterns like IDEA-NNNN, GO-NNN, PLATFORM-NNNNN, etc.
    """
    # 1. frontmatter id field
    fm_id = note.get("id", "")
    if fm_id:
        return str(fm_id).strip()

    # 2. frontmatter jira_key field
    jira_key = note.get("jira_key", "")
    if jira_key:
        return str(jira_key).strip()

    # 3. Filename pattern: PREFIX-NUMBER (IDEA-0023, GO-156, PLATFORM-10272, etc.)
    match = re.match(r"^([A-Za-z]+-\d+)", filepath.stem)
    if match:
        return match.group(1)

    return ""


class _SearchIndex:
    """In-memory full-text search index over vault entries."""

    def __init__(self) -> None:
        self.entries: list[_SearchEntry] = []

    def query(self, q: str, limit: int = 20) -> list[dict]:
        """Search entries by query string. Returns top results sorted by score."""
        logger.info("_SearchIndex.query: q='%s' limit=%d", q, limit)
        words = [w.lower() for w in re.split(r'[\s\-_/,.:;!?]+', q) if len(w) >= 2]
        if not words:
            logger.info("_SearchIndex.query: no valid words after filtering, returning []")
            return []

        # Normalized query for exact artifact ID match
        q_normalized = q.strip().lower()

        scored: list[tuple[_SearchEntry, int]] = []
        for entry in self.entries:
            score = 0

            # +10 for exact artifact_id match
            if entry.artifact_id and q_normalized == entry.artifact_id.lower():
                score += 10

            title_lower = entry.title.lower()

            # +3 for title substring match
            for w in words:
                if w in title_lower:
                    score += 3

            # +2 for exact tag match (case-insensitive)
            entry_tags_lower = [t.lower() for t in entry.tags]
            for w in words:
                if w in entry_tags_lower:
                    score += 2

            # +1 for keyword bidirectional substring match (max 1 per word per entry)
            for w in words:
                for kw in entry.keywords:
                    if w in kw or kw in w:
                        score += 1
                        break

            if score > 0:
                scored.append((entry, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        results = [
            {
                "title": e.title,
                "category": e.category,
                "domain": e.domain,
                "date": e.date,
                "tags": e.tags,
                "score": s,
                "path": e.path,
                "url": e.url,
                "artifact_id": e.artifact_id,
            }
            for e, s in scored[:limit]
        ]
        logger.info("_SearchIndex.query: found %d results (top score=%d)", len(results), results[0]["score"] if results else 0)
        return results


def _build_search_index() -> _SearchIndex:
    """Build a search index by scanning all vault artifact directories."""
    logger.info("_build_search_index: starting index build")
    index = _SearchIndex()

    # Scan domain-based directories
    scan_map = {
        "ideas": "idea",
        "tasks": "task",
        "epics": "epic",
        "prds": "prd",
        "bugs": "bug",
    }

    for domain in all_domains():
        for artifact_type, category in scan_map.items():
            try:
                folder = wiki_domain_dir(domain, artifact_type)
            except ValueError as exc:
                logger.error("_build_search_index: invalid artifact_type %s — %s", artifact_type, exc)
                continue
            if not folder.exists():
                continue

            for md_file in folder.glob("*.md"):
                if _is_service_file(md_file):
                    continue
                try:
                    if artifact_type == "epics":
                        note = parse_epic_note(md_file)
                    else:
                        note = parse_note(md_file)

                    title = note.get("title", md_file.stem)
                    raw_tags = note.get("tags", "")
                    tags = _parse_tags(raw_tags) if isinstance(raw_tags, str) else raw_tags if isinstance(raw_tags, list) else []
                    date = str(note.get("date", ""))
                    body = note.get("body", "")
                    keywords = _extract_search_keywords(title, body)
                    artifact_id = _extract_artifact_id(note, md_file)
                    rel_path = str(md_file.relative_to(VAULT_PATH)).replace("\\", "/")
                    url = _CATEGORY_URL.get(category, "")

                    index.entries.append(_SearchEntry(
                        path=rel_path,
                        title=title,
                        tags=tags,
                        keywords=keywords,
                        artifact_id=artifact_id,
                        category=category,
                        domain=domain,
                        date=date,
                        url=url,
                    ))
                except Exception as exc:
                    logger.error("_build_search_index: failed to index %s — %s", md_file.name, exc)

    # Scan cross-domain directories: meetings, reports
    cross_domain = [
        (wiki_meetings, "meeting", "cross-domain"),
        (wiki_reports, "report", "cross-domain"),
    ]
    for folder_fn, category, domain_name in cross_domain:
        folder = folder_fn()
        if not folder.exists():
            continue
        for md_file in folder.glob("*.md"):
            if _is_service_file(md_file):
                continue
            try:
                note = parse_note(md_file)
                title = note.get("title", md_file.stem)
                raw_tags = note.get("tags", "")
                tags = _parse_tags(raw_tags) if isinstance(raw_tags, str) else raw_tags if isinstance(raw_tags, list) else []
                date = str(note.get("date", ""))
                body = note.get("body", "")
                keywords = _extract_search_keywords(title, body)
                artifact_id = _extract_artifact_id(note, md_file)
                rel_path = str(md_file.relative_to(VAULT_PATH)).replace("\\", "/")
                url = _CATEGORY_URL.get(category, "")

                index.entries.append(_SearchEntry(
                    path=rel_path,
                    title=title,
                    tags=tags,
                    keywords=keywords,
                    artifact_id=artifact_id,
                    category=category,
                    domain=domain_name,
                    date=date,
                    url=url,
                ))
            except Exception as exc:
                logger.error("_build_search_index: failed to index %s — %s", md_file.name, exc)

    logger.info("_build_search_index: indexed %d entries", len(index.entries))
    return index


def _get_search_index() -> _SearchIndex:
    """Get or build the search index, using TTL cache."""
    cached = _cache.get("search_index")
    if cached is not None:
        logger.info("_get_search_index: cache hit")
        return cached
    logger.info("_get_search_index: cache miss, building")
    index = _build_search_index()
    _cache.set("search_index", index)
    return index


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


# ---------------------------------------------------------------------------
# Decision Journal helpers
# ---------------------------------------------------------------------------

_EMPTY_DECISION_PATTERNS = [
    "решений не принято",
    "решения отсутствуют",
    "нет решений",
    "не обсуждались",
]

_DOMAIN_KEYWORDS_FALLBACK = {
    "search-engine": [
        "поиск", "индексаци", "ранжирован", "выдач", "фильтр",
        "getresults", "searchoffers", "bbox",
    ],
    "suggester": ["автокомплит", "подсказк", "typeahead", "suggest"],
    "static-metadata": [
        "справочник", "классификатор", "атрибут", "метаданн",
        "каталог", "контент", "комнат", "статик",
    ],
    "partner-search-engine": [
        "партнёр", "партнер", "level travel", "канал продаж", "дистрибуц",
    ],
}


def _parse_decision_bullets(raw: str) -> list[str]:
    """Parse bullet items from raw Решения section text."""
    decisions: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            text = stripped[2:].strip()
            if text and text != "-":
                decisions.append(text)
        elif stripped.startswith("* "):
            text = stripped[2:].strip()
            if text:
                decisions.append(text)
        elif stripped and not stripped.startswith("#") and len(stripped) > 3:
            decisions.append(stripped)
    return decisions


def _is_empty_decisions(raw: str) -> bool:
    """Check if decisions section is effectively empty."""
    lower = raw.strip().lower()
    for pattern in _EMPTY_DECISION_PATTERNS:
        if pattern in lower:
            return True
    return len(_parse_decision_bullets(raw)) == 0


def _detect_domain_for_decision(text: str) -> str:
    """Detect domain for a decision via keyword matching."""
    lower = text.lower()
    try:
        from shared.domain_config import load as load_domain_config
        config = load_domain_config()
        for slug, entry in config.get("domains", {}).items():
            if not isinstance(entry, dict):
                continue
            for kw in entry.get("keywords", []):
                if isinstance(kw, str) and kw.lower() in lower:
                    return slug
    except Exception:
        pass
    for dom, keywords in _DOMAIN_KEYWORDS_FALLBACK.items():
        for kw in keywords:
            if kw in lower:
                return dom
    return "general"


def _load_domain_display_map() -> dict[str, dict]:
    """Load display_name and color for each domain from domain-config.yaml."""
    try:
        from shared.domain_config import load as load_domain_config
        config = load_domain_config()
        result: dict[str, dict] = {}
        for slug, entry in config.get("domains", {}).items():
            if isinstance(entry, dict):
                result[slug] = {
                    "display_name": entry.get("display_name", slug),
                    "color": entry.get("color", "#607D8B"),
                }
        return result
    except Exception:
        return {}


def _normalize_participants(raw) -> str:
    """Convert participants from frontmatter to comma-separated string."""
    if not raw:
        return ""
    if isinstance(raw, list):
        return ", ".join(str(p) for p in raw)
    text = str(raw).strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return text.strip()


def _decision_matches_query(text: str, context: str, q: str) -> bool:
    """Check if decision text or context matches search query (case-insensitive)."""
    lower_q = q.lower()
    return lower_q in text.lower() or (bool(context) and lower_q in context.lower())


# ---------------------------------------------------------------------------
# Decision Journal endpoint
# ---------------------------------------------------------------------------


@app.get("/api/v1/decisions")
def get_decisions(
    domain: str | None = Query(default=None, description="Filter by domain slug"),
    q: str | None = Query(default=None, description="Full-text search in decision text and context"),
    date_from: str | None = Query(default=None, description="Start date YYYY-MM-DD inclusive"),
    date_to: str | None = Query(default=None, description="End date YYYY-MM-DD inclusive"),
):
    """Aggregated list of decisions from all meeting protocols."""
    logger.info(
        "get_decisions: domain=%s, q=%s, date_from=%s, date_to=%s",
        domain, q, date_from, date_to,
    )

    cache_key = f"decisions:{domain or ''}:{q or ''}:{date_from or ''}:{date_to or ''}"
    cached = _cache.get(cache_key)
    if cached is not None:
        logger.info("get_decisions: cache hit, returning %d decisions", len(cached))
        return cached

    folder = wiki_meetings()
    if not folder.exists():
        logger.info("get_decisions: meetings folder does not exist")
        _cache.set(cache_key, [])
        return []

    files = sorted(folder.glob("*.md"), reverse=True)
    logger.info("get_decisions: scanning %d meeting files", len(files))

    domain_cfg = _load_domain_display_map()
    results: list[dict] = []

    for f in files:
        try:
            note = parse_note(f)
        except Exception as exc:
            logger.debug("get_decisions: failed to parse %s: %s", f.name, exc)
            continue

        note_date = str(note.get("date", ""))
        if date_from and note_date < date_from:
            continue
        if date_to and note_date > date_to:
            continue

        body = note.get("body", "")
        decisions_raw = _extract_section(body, "Решения")
        if not decisions_raw:
            continue
        if _is_empty_decisions(decisions_raw):
            continue

        context = _extract_section(body, "Контекст") or ""
        action_items_raw = _extract_section(body, "Action Items")
        action_items = [
            line.strip()
            for line in (action_items_raw or "").splitlines()
            if "- [ ]" in line or "- [x]" in line
        ]
        blockers = _extract_section(body, "Блокеры и риски") or ""

        participants = _normalize_participants(note.get("participants"))
        source_title = note.get("title", "")
        meeting_type = note.get("type", "")

        for decision_text in _parse_decision_bullets(decisions_raw):
            detected_domain = _detect_domain_for_decision(decision_text)

            if domain and detected_domain != domain:
                continue
            if q and not _decision_matches_query(decision_text, context, q):
                continue

            display_info = domain_cfg.get(detected_domain, {})

            results.append({
                "text": decision_text,
                "date": note_date,
                "domain": detected_domain,
                "domain_display": display_info.get("display_name", detected_domain),
                "domain_color": display_info.get("color", "#607D8B"),
                "source_file": note.get("filename", f.name),
                "source_title": source_title,
                "participants": participants,
                "meeting_type": meeting_type,
                "context": context,
                "action_items": action_items,
                "blockers": blockers,
            })

    results.sort(key=lambda x: x["date"], reverse=True)
    logger.info("get_decisions: returning %d decisions", len(results))
    _cache.set(cache_key, results)
    return results


@app.get("/api/v1/meetings/{filename}")
def get_meeting_by_filename(filename: str):
    """Return the full content of a specific meeting protocol file."""
    logger.info("GET /api/v1/meetings/%s — start", filename)

    # --- Security validation ---
    if not filename.endswith(".md"):
        logger.error("GET /api/v1/meetings/%s — rejected: filename does not end with .md", filename)
        raise HTTPException(status_code=400, detail="Filename must end with .md")

    if "/" in filename or "\\" in filename:
        logger.error("GET /api/v1/meetings/%s — rejected: path separators in filename", filename)
        raise HTTPException(status_code=400, detail="Filename must not contain path separators")

    folder = wiki_meetings()
    filepath = folder / filename

    if not filepath.exists():
        logger.info("GET /api/v1/meetings/%s — file not found", filename)
        raise HTTPException(status_code=404, detail="Meeting not found")

    try:
        content = filepath.read_text(encoding="utf-8")
        date = filepath.stem[:10] if len(filepath.stem) >= 10 else filepath.stem
        logger.info("GET /api/v1/meetings/%s — returning meeting (%d chars)", filename, len(content))
        return {"filename": filename, "content": content, "date": date}
    except Exception as exc:
        logger.error("GET /api/v1/meetings/%s — failed to read file: %s", filename, exc)
        raise HTTPException(status_code=500, detail="Failed to read meeting")


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
                    "body": body,
                }
            )
        except Exception as exc:
            logger.error("GET /api/v1/epics — failed to parse %s: %s", f.name, exc)
            continue

    logger.info(f"GET /api/v1/epics — returning {len(results)} epics")
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


def _extract_report_type(text: str) -> str:
    """Extract ``type`` from YAML frontmatter, defaulting to ``other``."""
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return "other"

    end = stripped.find("---", 3)
    if end == -1:
        return "other"

    frontmatter = stripped[3:end]
    for line in frontmatter.splitlines():
        if line.strip().startswith("type:"):
            value = line.split(":", 1)[1].strip().strip("'\"")
            if value:
                logger.debug(f"_extract_report_type — found type: {value}")
                return value

    return "other"


_DATE_IN_FILENAME_RE = re.compile(r"(\d{4})[.\-](\d{2})[.\-](\d{2})")


def _extract_report_date(text: str, stem: str, path: Path | None = None) -> str:
    """Extract report date. Priority: frontmatter ``date:``/``created:`` → filename."""
    stripped = text.lstrip()
    if stripped.startswith("---"):
        end = stripped.find("---", 3)
        if end != -1:
            for field in ("date:", "created:"):
                for line in stripped[3:end].splitlines():
                    if line.strip().startswith(field):
                        val = line.split(":", 1)[1].strip().strip("'\"")
                        fm = _DATE_IN_FILENAME_RE.search(val)
                        if fm:
                            date_str = f"{fm.group(1)}-{fm.group(2)}-{fm.group(3)}"
                            logger.debug(f"_extract_report_date — frontmatter {field} {date_str} for '{stem}'")
                            return date_str

    m = _DATE_IN_FILENAME_RE.search(stem)
    if m:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            date_str = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            logger.debug(f"_extract_report_date — filename date {date_str} for '{stem}'")
            return date_str
        logger.debug(f"_extract_report_date — invalid filename date {year}-{month}-{day} in '{stem}'")

    logger.debug(f"_extract_report_date — no date found for '{stem}'")
    return "0000-00-00"


@app.get("/api/v1/reports")
def list_reports(type: str | None = None):
    """Return a list of all available reports from wiki/reports/.

    Each entry contains ``filename``, ``date`` (extracted from frontmatter or
    filename), and ``title`` (first ``# `` heading in the file body, or
    the filename stem when no heading is found).

    Reports are sorted by date descending (newest first).
    Service files (index.md, log.md) are excluded.

    Optional query parameter ``type`` filters by comma-separated report types,
    e.g. ``?type=weekly-status-report,feature-analysis-report``.
    """
    type_filter = {t.strip() for t in type.split(",")} if type else None
    logger.info(f"GET /api/v1/reports — start (type_filter={type_filter})")
    folder = wiki_reports()

    if not folder.exists():
        logger.info(
            "GET /api/v1/reports — reports folder not found, returning empty list"
        )
        return {"reports": []}

    try:
        files = [f for f in folder.glob("*.md") if not _is_service_file(f)]
        logger.info(f"GET /api/v1/reports — found {len(files)} files total")
    except Exception as exc:
        logger.error(f"GET /api/v1/reports — error listing files: {exc}")
        return {"reports": []}

    results: list[dict] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
            report_type = _extract_report_type(text)
            if type_filter and report_type not in type_filter:
                continue
            date = _extract_report_date(text, f.stem, f)
            title = _extract_report_title(text) or f.stem
            results.append(
                {"filename": f.name, "date": date, "title": title, "type": report_type}
            )
            logger.info(
                f"GET /api/v1/reports — parsed {f.name} (date={date}, title={title}, type={report_type})"
            )
        except Exception as exc:
            logger.error(
                f"GET /api/v1/reports — failed to parse {f.name}: {exc}"
            )
            continue

    results.sort(key=lambda r: r["date"], reverse=True)
    logger.info(f"GET /api/v1/reports — returning {len(results)} reports (sorted by date)")
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


@app.post("/api/v1/reports/{filename}/pdf")
def export_report_pdf(filename: str):
    """Export a report as PDF.

    Reads the markdown report, renders it to PDF via WeasyPrint,
    and returns the PDF file as a downloadable attachment.
    """
    logger.info("POST /api/v1/reports/%s/pdf — start", filename)

    if not filename.endswith(".md"):
        raise HTTPException(status_code=400, detail="Filename must end with .md")
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Filename must not contain path separators")

    folder = wiki_reports()
    filepath = folder / filename

    if not filepath.exists():
        logger.error("POST /api/v1/reports/%s/pdf — file not found", filename)
        raise HTTPException(status_code=404, detail="Report not found")

    try:
        from shared.system_log import LoggedProcess

        content = filepath.read_text(encoding="utf-8")

        with LoggedProcess(process_type="pdf-export", source="pm-bot") as lp:
            from pathlib import Path as _Path

            from app.pdf_exporter import render_pdf

            pdf_bytes = render_pdf(content, _Path("/web/pdf-export.css"))
            lp.summary = f"PDF exported: {filename}"
            lp.details = {"filename": filename, "size_bytes": len(pdf_bytes)}

        pdf_name = filename.rsplit(".", 1)[0] + ".pdf"
        logger.info("POST /api/v1/reports/%s/pdf — done, size=%d", filename, len(pdf_bytes))

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{pdf_name}"'},
        )
    except ImportError as exc:
        logger.error("POST /api/v1/reports/%s/pdf — WeasyPrint not installed: %s", filename, exc)
        raise HTTPException(status_code=500, detail="PDF export unavailable: WeasyPrint not installed")
    except ValueError as exc:
        logger.error("POST /api/v1/reports/%s/pdf — validation error: %s", filename, exc)
        raise HTTPException(status_code=413, detail=str(exc))
    except Exception as exc:
        logger.error("POST /api/v1/reports/%s/pdf — error: %s", filename, exc)
        raise HTTPException(status_code=500, detail="PDF export failed")


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


@app.post("/api/v1/jira/import", response_model=JiraImportResponse)
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


@app.post("/api/v1/jira/create", response_model=JiraCreateResponse)
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


@app.get("/api/v1/jira/projects")
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


@app.get("/api/v1/jira/projects/{project_key}/epics")
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


@app.get("/api/v1/jira/projects/{projectKey}/issue-types")
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


@app.get("/api/v1/jira/search")
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

@app.post("/api/v1/jira/sync")
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


# ---------------------------------------------------------------------------
# Fetch Meetings (email import) endpoint
# ---------------------------------------------------------------------------


class FetchMeetingsRequest(BaseModel):
    notify: bool = False
    dry_run: bool = False


class FetchMeetingsResponse(BaseModel):
    status: str
    total_emails: int = 0
    already_processed: int = 0
    newly_processed: int = 0
    errors: int = 0
    details: list = []
    message: str = ""


@app.post("/api/v1/fetch-meetings", response_model=FetchMeetingsResponse)
def fetch_meetings_endpoint(req: FetchMeetingsRequest):
    """Fetch and process new meeting transcripts from email via knowledge-engine."""
    logger.info("POST /api/v1/fetch-meetings — start, notify=%s, dry_run=%s", req.notify, req.dry_run)
    try:
        data = ke_client.fetch_meetings(notify=req.notify, dry_run=req.dry_run)
        _cache.invalidate()
        logger.info("POST /api/v1/fetch-meetings — success: newly_processed=%s", data.get("newly_processed", 0))
        return FetchMeetingsResponse(**data)
    except requests.RequestException as exc:
        logger.error("POST /api/v1/fetch-meetings — ke_client error: %s", exc)
        raise HTTPException(status_code=502, detail=f"KE API error: {exc}")
    except Exception as exc:
        logger.error("POST /api/v1/fetch-meetings — error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


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
    from shared import domain_config

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
    from shared import domain_config as _domain_config

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
    from shared import domain_config as _domain_config

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
_VALID_TRANSCRIPTION_PROVIDERS = frozenset({"default", "openrouter"})
_VALID_CAPTURE_MODES = frozenset({"simple", "extended"})
_VALID_FALLBACK_PROVIDERS = frozenset({"claude", "ollama", "openrouter"})
_CALDAV_PASSWORD_MASK = "••••••••"
_DEFAULT_USER_PREFS = {
    "refresh_mode": "auto",
    "theme": "matrix",
    "llm_provider": "claude",
    "ollama_url": "",
    "ollama_model": "qwen3.5:latest",
    "jira_sync_notify": True,
    "transcription_provider": "default",
    "openrouter_model": "qwen/qwen3-32b",
    "capture_mode": "simple",
    "capture_fallback": ["claude"],
    "transcription_fallback": ["claude"],
    "analysis_fallback": ["claude"],
    "pipeline_fallback": ["claude"],
    "caldav_username": "",
    "caldav_password": "",
    "caldav_timezone": "Europe/Moscow",
    "caldav_url": "https://caldav.yandex.ru/",
}


class UserPrefs(BaseModel):
    refresh_mode: str = "auto"
    theme: str = "matrix"
    llm_provider: str = "claude"
    ollama_url: str = ""
    ollama_model: str = "qwen3.5:latest"
    jira_sync_notify: bool = True
    transcription_provider: str = "default"
    openrouter_model: str = "qwen/qwen3-32b"
    capture_mode: str = "simple"
    # NOTE: intentionally `list[Any]`, not `list[str]` -- elements can be either
    # legacy provider-name strings ("openrouter") or new-format step objects
    # ({"provider": "openrouter", "model": "..."}), see design.md §2.1/§3.4
    # (T-07). Full validation of element shape happens in put_user_prefs(),
    # not at the pydantic-field level, so both formats reach our code intact
    # instead of being rejected/mangled by automatic str coercion.
    capture_fallback: list[Any] = ["claude"]
    transcription_fallback: list[Any] = ["claude"]
    analysis_fallback: list[Any] = ["claude"]
    pipeline_fallback: list[Any] = ["claude"]
    caldav_username: str = ""
    caldav_password: str = ""
    caldav_timezone: str = "Europe/Moscow"
    caldav_url: str = "https://caldav.yandex.ru/"


def _read_user_prefs() -> dict:
    from shared.vault_paths import user_prefs_path
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

    from shared.file_writer import atomic_write
    from shared.vault_paths import user_prefs_path
    path = user_prefs_path()
    content = _json.dumps(prefs, indent=2, ensure_ascii=False) + "\n"
    logger.info("_write_user_prefs: writing to %s", path)
    atomic_write(path, content)
    logger.info("_write_user_prefs: success")


def _normalize_fallback_step_for_read(el, default_openrouter_model: str) -> dict:
    """Normalize one fallback-chain element into the canonical object form
    {provider, model} for GET /api/v1/user-prefs (design.md §2.1/§3.2).

    - legacy string "openrouter"      -> {"provider": "openrouter", "model": default_openrouter_model}
    - legacy string "claude"/"ollama" -> {"provider": <that>, "model": None}
    - object {"provider":..,"model":..} for openrouter -> model kept if it's a
      non-empty string, otherwise falls back to default_openrouter_model
    - object {"provider":..} for claude/ollama -> {"provider": <that>, "model": None}
      (any "model" field present on the stored object is ignored, same as PUT
      validation/dedup logic in put_user_prefs()).

    This is read-only / in-memory normalization -- it never rewrites
    .pm-user-prefs.json (design.md §3.2, lazy migration; the file is only
    rewritten when the user explicitly saves via PUT).

    NOTE: intentionally NOT importing the private `_normalize_step`/
    `_default_model_for` helpers from shared/llm_client.py -- same
    architectural decision as T-07's local validation logic in
    put_user_prefs() (see its note above `default_openrouter_model`):
    keeping this module's own small, explicit normalization avoids leaking a
    private cross-module abstraction and avoids coupling GET's "always show a
    default" read semantics to llm_client's execution-resolution semantics,
    which may evolve independently.
    """
    if isinstance(el, str):
        provider = el
        model = default_openrouter_model if provider == "openrouter" else None
        return {"provider": provider, "model": model}
    if isinstance(el, dict):
        provider_val: str | None = el.get("provider")
        if provider_val == "openrouter":
            raw_model = el.get("model")
            model = raw_model if isinstance(raw_model, str) and raw_model.strip() else default_openrouter_model
        else:
            model = None
        return {"provider": provider_val, "model": model}
    # Unknown/invalid shape -- caller filters these out before normalizing
    # (provider extraction below returns None, which is never a valid provider).
    return {"provider": None, "model": None}


def _fallback_step_provider(el):
    """Extract the provider name from a fallback-chain element regardless of
    whether it's a legacy string or a new-format {"provider": ...} object.
    Used only for the GET-side validity filter (see get_user_prefs())."""
    if isinstance(el, str):
        return el
    if isinstance(el, dict):
        return el.get("provider")
    return None


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
    if "transcription_provider" not in prefs:
        prefs["transcription_provider"] = "default"
    if "openrouter_model" not in prefs:
        prefs["openrouter_model"] = "qwen/qwen3-32b"
    if prefs.get("capture_mode") not in _VALID_CAPTURE_MODES:
        prefs["capture_mode"] = "simple"
    # --- fallback chains ---
    if "capture_fallback" not in prefs:
        prefs["capture_fallback"] = ["claude"]
    if "transcription_fallback" not in prefs:
        prefs["transcription_fallback"] = ["claude"]
    if "analysis_fallback" not in prefs:
        prefs["analysis_fallback"] = ["claude"]
    if "pipeline_fallback" not in prefs:
        prefs["pipeline_fallback"] = ["claude"]
    # --- CalDAV ---
    if "caldav_username" not in prefs:
        prefs["caldav_username"] = ""
    if "caldav_password" not in prefs:
        prefs["caldav_password"] = ""
    if "caldav_timezone" not in prefs:
        prefs["caldav_timezone"] = "Europe/Moscow"
    if "caldav_url" not in prefs:
        prefs["caldav_url"] = "https://caldav.yandex.ru/"
    from shared.openrouter_client import DEFAULT_MODEL as _OR_DEFAULT_MODEL
    default_openrouter_model = prefs.get("openrouter_model") or _OR_DEFAULT_MODEL
    for key in ("capture_fallback", "transcription_fallback", "analysis_fallback", "pipeline_fallback"):
        val = prefs[key]
        if not isinstance(val, list) or len(val) == 0:
            logger.info("GET /api/v1/user-prefs — %s invalid (not list or empty), resetting to default", key)
            prefs[key] = [{"provider": "claude", "model": None}]
        else:
            # T-08: filter must recognize BOTH legacy string elements AND
            # new-format {"provider": ..., "model": ...} step objects (T-07
            # bug -- the old `p in _VALID_FALLBACK_PROVIDERS` check compared a
            # dict against a frozenset of strings, which is always False, so
            # every object-format step was silently dropped here).
            filtered = [el for el in val if _fallback_step_provider(el) in _VALID_FALLBACK_PROVIDERS]
            if not filtered:
                logger.info("GET /api/v1/user-prefs — %s has no valid providers, resetting to default", key)
                prefs[key] = [{"provider": "claude", "model": None}]
            else:
                # Normalize every valid element to the canonical object form
                # {provider, model} so the UI always receives the same shape,
                # regardless of how the step is actually stored on disk
                # (design.md §2.1/§3.2). Read-only -- does not rewrite the file.
                prefs[key] = [
                    _normalize_fallback_step_for_read(el, default_openrouter_model)
                    for el in filtered
                ]
    # Mask CalDAV password before returning
    if prefs.get("caldav_password"):
        prefs["caldav_password"] = _CALDAV_PASSWORD_MASK
    logger.info(
        "GET /api/v1/user-prefs — returning refresh_mode=%s theme=%s"
        " llm_provider=%s caldav_username=%s",
        prefs["refresh_mode"], prefs["theme"],
        prefs["llm_provider"], prefs.get("caldav_username", ""),
    )
    return prefs


@app.put("/api/v1/user-prefs")
def put_user_prefs(body: UserPrefs):
    logger.info(
        "PUT /api/v1/user-prefs — start, refresh_mode=%s theme=%s"
        " capture_mode=%s caldav_username=%s",
        body.refresh_mode, body.theme,
        body.capture_mode, body.caldav_username,
    )
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
    if body.transcription_provider not in _VALID_TRANSCRIPTION_PROVIDERS:
        logger.warning("PUT /api/v1/user-prefs — invalid transcription_provider: %s", body.transcription_provider)
        raise HTTPException(
            status_code=422,
            detail=f"transcription_provider must be one of: {', '.join(sorted(_VALID_TRANSCRIPTION_PROVIDERS))}"
        )
    if body.capture_mode not in _VALID_CAPTURE_MODES:
        logger.warning("PUT /api/v1/user-prefs — invalid capture_mode: %s", body.capture_mode)
        raise HTTPException(
            status_code=422,
            detail=f"capture_mode must be one of: {', '.join(sorted(_VALID_CAPTURE_MODES))}"
        )
    # Fallback-chain element can be a legacy provider-name string ("openrouter")
    # or a new-format step object ({"provider": "openrouter", "model": "..."}).
    # The old "no duplicate providers" check is intentionally REMOVED here --
    # it directly blocked BL-155's goal of multiple openrouter steps with
    # different models in one chain (design.md §3.4). Uniqueness is now
    # considered per (provider, model) pair, and only ADJACENT identical
    # pairs are collapsed (see dedup below) rather than rejected outright.
    from shared.openrouter_client import DEFAULT_MODEL as _OR_DEFAULT_MODEL
    default_openrouter_model = body.openrouter_model or _OR_DEFAULT_MODEL

    for key in ("capture_fallback", "transcription_fallback", "analysis_fallback", "pipeline_fallback"):
        chain = getattr(body, key)
        if not isinstance(chain, list) or len(chain) == 0:
            logger.warning("PUT /api/v1/user-prefs — %s is empty or not a list, rejecting", key)
            raise HTTPException(
                status_code=422,
                detail=f"{key} must be a non-empty list of providers: {', '.join(sorted(_VALID_FALLBACK_PROVIDERS))}"
            )

        providers: list = []
        pairs: list = []  # (provider, effective_model) per element, used only to detect adjacent dups
        for el in chain:
            provider: str | None
            model: str | None
            is_object: bool
            if isinstance(el, str):
                provider, model, is_object = el, None, False
            elif isinstance(el, dict):
                provider, model, is_object = el.get("provider"), el.get("model"), True
            else:
                provider, model, is_object = None, None, True
            providers.append(provider)

            if provider == "openrouter" and is_object and (not isinstance(model, str) or not model.strip()):
                logger.warning(
                    "PUT /api/v1/user-prefs — %s has an openrouter step without a valid model: %r",
                    key, el,
                )
                raise HTTPException(
                    status_code=422,
                    detail="OpenRouter step requires a non-empty model",
                )

            if provider == "openrouter":
                effective_model = model if is_object else default_openrouter_model
            else:
                # claude/ollama are single-model providers -- any "model" field
                # on the step object is ignored for validation/dedup purposes
                # (design.md §2.1).
                effective_model = None
            pairs.append((provider, effective_model))

        invalid = [p for p in providers if p not in _VALID_FALLBACK_PROVIDERS]
        if invalid:
            logger.warning("PUT /api/v1/user-prefs — %s contains invalid providers: %s", key, invalid)
            raise HTTPException(
                status_code=422,
                detail=f"{key} contains invalid providers: {', '.join(str(p) for p in invalid)}. Valid: {', '.join(sorted(_VALID_FALLBACK_PROVIDERS))}"
            )

        # Collapse ADJACENT identical steps (design.md §3.4) -- e.g. two
        # consecutive openrouter steps with the exact same model, or two
        # consecutive legacy "openrouter" strings (which resolve to the same
        # default model), add no value and would just repeat the same failed
        # network call twice. Non-adjacent identical steps are left as-is.
        deduped_chain: list = []
        prev_pair = None
        for el, pair in zip(chain, pairs):
            if pair == prev_pair:
                logger.info("PUT /api/v1/user-prefs — %s: collapsing adjacent duplicate step %r", key, el)
                continue
            deduped_chain.append(el)
            prev_pair = pair

        setattr(body, key, deduped_chain)
        logger.info("PUT /api/v1/user-prefs — %s validated: %s", key, deduped_chain)
    # CalDAV password sentinel: masked value means "keep current", empty means "clear"
    if body.caldav_password == _CALDAV_PASSWORD_MASK:
        current = _read_user_prefs()
        body.caldav_password = current.get("caldav_password", "")
        logger.info("PUT /api/v1/user-prefs — caldav_password sentinel detected, preserving current value")
    prefs = body.model_dump()
    try:
        _write_user_prefs(prefs)
    except Exception as exc:
        logger.error("PUT /api/v1/user-prefs — write failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    _cache.invalidate()
    try:
        from app.calendar_client import _calendar_cache
        _calendar_cache.invalidate()
        logger.info("PUT /api/v1/user-prefs — CalDAV cache invalidated")
    except ImportError:
        pass
    try:
        from shared.llm_client import invalidate_cache as _invalidate_llm_cache
        _invalidate_llm_cache()
    except ImportError:
        pass
    logger.info("PUT /api/v1/user-prefs — saved successfully")
    return {"status": "ok", "refresh_mode": body.refresh_mode, "theme": body.theme,
            "llm_provider": body.llm_provider, "ollama_url": body.ollama_url,
            "ollama_model": body.ollama_model, "jira_sync_notify": body.jira_sync_notify,
            "transcription_provider": body.transcription_provider,
            "openrouter_model": body.openrouter_model,
            "capture_mode": body.capture_mode,
            "capture_fallback": body.capture_fallback,
            "transcription_fallback": body.transcription_fallback,
            "analysis_fallback": body.analysis_fallback,
            "pipeline_fallback": body.pipeline_fallback,
            "caldav_username": body.caldav_username,
            "caldav_timezone": body.caldav_timezone,
            "caldav_url": body.caldav_url}


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
# OpenRouter integration
# ---------------------------------------------------------------------------


class TestOpenRouterRequest(BaseModel):
    model: str = "qwen/qwen3-32b"


@app.get("/api/v1/openrouter-key-status")
def openrouter_key_status():
    logger.info("GET /api/v1/openrouter-key-status — start")
    has_key = bool(os.getenv("OPENROUTER_API_KEY"))
    logger.info("GET /api/v1/openrouter-key-status — has_key=%s", has_key)
    return {"has_key": has_key}


@app.post("/api/v1/test-openrouter")
def test_openrouter(body: TestOpenRouterRequest):
    logger.info("POST /api/v1/test-openrouter — model=%s", body.model)
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        logger.warning("POST /api/v1/test-openrouter — OPENROUTER_API_KEY not set")
        return {"status": "error", "detail": "OPENROUTER_API_KEY is not set in environment"}
    try:
        from shared.openrouter_client import test_connection
        result = test_connection(api_key, body.model)
        logger.info("POST /api/v1/test-openrouter — result=%s", result.get("status"))
        return result
    except Exception as exc:
        logger.error("POST /api/v1/test-openrouter — error: %s", exc)
        return {"status": "error", "detail": str(exc)}


@app.get("/api/v1/openrouter-models")
def openrouter_models():
    logger.info("GET /api/v1/openrouter-models — start")
    from shared import settings as app_settings
    from shared.openrouter_client import list_models

    api_key = os.getenv("OPENROUTER_API_KEY")
    ttl = app_settings.get("cache_ttl.openrouter_models_seconds", 3600)
    result = list_models(api_key, ttl)
    logger.info(
        "GET /api/v1/openrouter-models — source=%s count=%d cached=%s",
        result.get("source"), result.get("count"), result.get("cached"),
    )
    return result


# ---------------------------------------------------------------------------
# Test CalDAV connectivity
# ---------------------------------------------------------------------------


class TestCaldavRequest(BaseModel):
    url: str = "https://caldav.yandex.ru/"
    username: str
    password: str


def _test_caldav_sync(url: str, username: str, password: str) -> dict:
    """Test CalDAV connection synchronously (runs in executor)."""
    import caldav

    logger.info("_test_caldav_sync -- connecting to %s, username=%s", url, username)
    try:
        client = caldav.DAVClient(
            url=url,
            username=username,
            password=password,
        )
        principal = client.principal()
        logger.info("_test_caldav_sync -- authenticated successfully")

        calendars = principal.calendars()
        calendar_names = [getattr(c, "name", "") for c in calendars]
        logger.info("_test_caldav_sync -- found %d calendars: %s", len(calendars), calendar_names)

        return {
            "status": "ok",
            "calendars_count": len(calendars),
            "calendar_names": calendar_names,
        }
    except Exception as exc:
        exc_str = str(exc)
        if "401" in exc_str or "unauthorized" in exc_str.lower() or "authorization" in exc_str.lower():
            logger.warning("_test_caldav_sync -- authorization failed: %s", exc)
            return {"status": "error", "detail": f"Authorization failed: {exc_str}"}
        if "timeout" in exc_str.lower() or isinstance(exc, TimeoutError):
            logger.warning("_test_caldav_sync -- timeout: %s", exc)
            return {"status": "error", "detail": "Connection timeout"}
        logger.error("_test_caldav_sync -- unexpected error: %s", exc)
        return {"status": "error", "detail": exc_str}


@app.post("/api/v1/test-caldav")
async def test_caldav(body: TestCaldavRequest):
    logger.info("POST /api/v1/test-caldav -- url=%s, username=%s", body.url, body.username)
    import asyncio

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        _caldav_executor,
        _test_caldav_sync,
        body.url,
        body.username,
        body.password,
    )
    logger.info("POST /api/v1/test-caldav -- result status=%s", result.get("status"))
    return result


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


@app.patch("/api/v1/artifact/{filename}/field")
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


@app.patch("/api/v1/artifact/{filename}/body")
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
# Decay proxy endpoints
# ---------------------------------------------------------------------------

@app.post("/api/v1/decay/touch")
def decay_touch(req: DecayTouchRequest):
    """Reset decay timer for a vault artifact via knowledge-engine."""
    logger.info("POST /api/v1/decay/touch — start, filepath=%s", req.filepath)
    try:
        result = ke_client.touch(req.filepath)
        logger.info("POST /api/v1/decay/touch — success: %s", result)
        return result
    except requests.RequestException as exc:
        logger.error("POST /api/v1/decay/touch — ke_client.touch failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"KE API error: {exc}")
    except Exception as exc:
        logger.error("POST /api/v1/decay/touch — error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/v1/decay/set-tier")
def decay_set_tier(req: DecaySetTierRequest):
    """Set decay tier for a vault artifact via knowledge-engine."""
    logger.info("POST /api/v1/decay/set-tier — start, filepath=%s, tier=%s", req.filepath, req.tier)
    try:
        result = ke_client.set_tier(req.filepath, req.tier)
        logger.info("POST /api/v1/decay/set-tier — success: %s", result)
        return result
    except requests.RequestException as exc:
        logger.error("POST /api/v1/decay/set-tier — ke_client.set_tier failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"KE API error: {exc}")
    except Exception as exc:
        logger.error("POST /api/v1/decay/set-tier — error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Decay snapshot endpoint
# ---------------------------------------------------------------------------

@app.get("/api/v1/decay/snapshot")
def get_decay_snapshot():
    """Get full decay state snapshot via knowledge-engine."""
    logger.info("GET /api/v1/decay/snapshot — start")
    try:
        result = ke_client.decay_snapshot()
        total = result.get("total", 0) if isinstance(result, dict) else 0
        logger.info("GET /api/v1/decay/snapshot — success, total=%d", total)
        return result
    except requests.RequestException as exc:
        logger.error("GET /api/v1/decay/snapshot — ke_client failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"KE API error: {exc}")
    except Exception as exc:
        logger.error("GET /api/v1/decay/snapshot — error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


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
# Full-text Search endpoint
# ---------------------------------------------------------------------------

@app.get("/api/v1/search")
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
# Single Artifact endpoint
# ---------------------------------------------------------------------------

@app.get("/api/v1/artifact")
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


# ---------------------------------------------------------------------------
# Creative Ideas (KE proxy)
# ---------------------------------------------------------------------------

@app.get("/api/v1/ideas/creative")
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


# ---------------------------------------------------------------------------
# Playground — Pydantic models
# ---------------------------------------------------------------------------

class PlaygroundChatRequest(BaseModel):
    provider: str
    model: str | None = None
    messages: list[dict] = Field(..., min_length=1)
    max_tokens: int = Field(default=4096, ge=1, le=16384)


class PlaygroundChatResponse(BaseModel):
    content: str
    provider: str
    model: str
    elapsed_seconds: float
    usage: dict | None = None


# ---------------------------------------------------------------------------
# Playground — GET /api/v1/playground/providers
# ---------------------------------------------------------------------------

@app.get("/api/v1/playground/providers")
def playground_providers():
    """Return list of LLM providers with availability status and models."""
    logger.info("GET /api/v1/playground/providers — start")

    from shared.llm_client import _is_provider_available, _load_llm_prefs
    from shared.openrouter_client import list_models as or_list_models

    prefs = _load_llm_prefs()
    result = []

    # Claude
    claude_available = _is_provider_available("claude", prefs)
    result.append({
        "id": "claude",
        "name": "Claude API",
        "available": claude_available,
        "models": [{"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4"}],
        "default_model": "claude-sonnet-4-6",
        **({"reason": "CLAUDE_API_KEY not set"} if not claude_available else {}),
    })

    # Ollama
    ollama_url = prefs.get("ollama_url", "")
    ollama_model = prefs.get("ollama_model", "qwen3.5:latest")
    ollama_available = _is_provider_available("ollama", prefs)
    ollama_entry = {
        "id": "ollama",
        "name": "Ollama",
        "available": ollama_available,
        "models": [{"id": ollama_model, "name": ollama_model}] if ollama_available else [],
        "default_model": ollama_model,
    }
    if ollama_available:
        ollama_entry["url"] = ollama_url
    else:
        ollama_entry["reason"] = "Ollama URL not configured in Settings"
    result.append(ollama_entry)

    # OpenRouter
    or_available = _is_provider_available("openrouter", prefs)
    or_model = prefs.get("openrouter_model", "qwen/qwen3-32b")
    or_api_key = os.getenv("OPENROUTER_API_KEY")
    or_data = or_list_models(or_api_key)
    or_models = or_data.get("models", [])
    result.append({
        "id": "openrouter",
        "name": "OpenRouter",
        "available": or_available,
        "models": or_models,
        "default_model": or_model,
        **({"reason": "OPENROUTER_API_KEY not set"} if not or_available else {}),
    })

    logger.info(
        "GET /api/v1/playground/providers — returning %d providers, available: %s",
        len(result),
        [p["id"] for p in result if p["available"]],
    )
    return {"providers": result}


# ---------------------------------------------------------------------------
# Playground — POST /api/v1/playground/chat
# ---------------------------------------------------------------------------

_PLAYGROUND_VALID_PROVIDERS = frozenset({"claude", "ollama", "openrouter"})
_PLAYGROUND_TIMEOUTS = {"claude": 60, "ollama": 300, "openrouter": 120}
_PLAYGROUND_DEFAULT_MODELS = {
    "claude": "claude-sonnet-4-6",
    "ollama": "qwen3.5:latest",
    "openrouter": "qwen/qwen3-32b",
}


@app.post("/api/v1/playground/chat")
def playground_chat(body: PlaygroundChatRequest):
    """Send a chat request to a specific LLM provider (no fallback)."""
    import time as _t

    logger.info(
        "POST /api/v1/playground/chat — provider=%s, model=%s, messages=%d, max_tokens=%d",
        body.provider, body.model, len(body.messages), body.max_tokens,
    )

    # Validate provider
    if body.provider not in _PLAYGROUND_VALID_PROVIDERS:
        logger.warning("playground/chat: invalid provider: %s", body.provider)
        raise HTTPException(
            status_code=422,
            detail=f"Invalid provider '{body.provider}'. Must be one of: {', '.join(sorted(_PLAYGROUND_VALID_PROVIDERS))}"
        )

    # Check availability
    from shared.llm_client import _call_provider, _is_provider_available, _load_llm_prefs
    prefs = _load_llm_prefs()

    if not _is_provider_available(body.provider, prefs):
        reason_map = {
            "claude": "CLAUDE_API_KEY not set",
            "ollama": "Ollama URL not configured in Settings",
            "openrouter": "OPENROUTER_API_KEY not set",
        }
        logger.warning("playground/chat: provider %s not available", body.provider)
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{body.provider}' is not available: {reason_map.get(body.provider, 'unknown reason')}"
        )

    # Validate messages format
    for i, msg in enumerate(body.messages):
        if "role" not in msg or "content" not in msg:
            logger.warning("playground/chat: message %d missing role or content", i)
            raise HTTPException(
                status_code=422,
                detail=f"Message at index {i} must have 'role' and 'content' fields"
            )
        if msg["role"] not in ("user", "assistant"):
            logger.warning("playground/chat: message %d has invalid role: %s", i, msg["role"])
            raise HTTPException(
                status_code=422,
                detail=f"Message role must be 'user' or 'assistant', got '{msg['role']}'"
            )

    # Validate total input size
    total_chars = sum(len(msg.get("content", "")) for msg in body.messages)
    if total_chars > 100_000:
        logger.warning("playground/chat: input too large: %d chars", total_chars)
        raise HTTPException(
            status_code=413,
            detail=f"Total input size ({total_chars} chars) exceeds limit of 100,000 chars"
        )

    # Resolve model
    model = body.model
    if not model:
        if body.provider == "ollama":
            model = prefs.get("ollama_model", _PLAYGROUND_DEFAULT_MODELS["ollama"])
        elif body.provider == "openrouter":
            model = prefs.get("openrouter_model", _PLAYGROUND_DEFAULT_MODELS["openrouter"])
        else:
            model = _PLAYGROUND_DEFAULT_MODELS.get(body.provider, "claude-sonnet-4-6")
        logger.info("playground/chat: model resolved to default: %s", model)

    # Override model in prefs for _call_provider compatibility
    call_prefs = dict(prefs)
    if body.provider == "ollama" and model:
        call_prefs["ollama_model"] = model
    elif body.provider == "openrouter" and model:
        call_prefs["openrouter_model"] = model

    timeout = _PLAYGROUND_TIMEOUTS.get(body.provider, 60)

    # Call provider
    # T-04: _call_provider now takes a normalized step {provider, model} instead
    # of a bare provider string, so the resolved playground model (including a
    # user-picked OpenRouter model) is threaded through to _call_openrouter.
    start = _t.time()
    try:
        content, _usage = _call_provider(
            step={"provider": body.provider, "model": model},
            prefs=call_prefs,
            messages=body.messages,
            max_tokens=body.max_tokens,
            system=None,
            timeout=timeout,
        )
        elapsed = round(_t.time() - start, 2)
        logger.info(
            "POST /api/v1/playground/chat — success, provider=%s, model=%s, elapsed=%.2f, output_len=%d",
            body.provider, model, elapsed, len(content),
        )
        return PlaygroundChatResponse(
            content=content,
            provider=body.provider,
            model=model,
            elapsed_seconds=elapsed,
            usage=None,
        )
    except Exception as exc:
        elapsed = round(_t.time() - start, 2)
        error_msg = str(exc)
        logger.error(
            "POST /api/v1/playground/chat — provider error: %s, provider=%s, model=%s, elapsed=%.2f",
            error_msg, body.provider, model, elapsed,
        )
        raise HTTPException(
            status_code=502,
            detail=error_msg,
        )


# ---------------------------------------------------------------------------
# System Log endpoints
# ---------------------------------------------------------------------------


@app.get("/api/v1/system-log")
async def get_system_log(
    period: str = "24h",
    process_type: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    """Журнал системных операций с фильтрацией и пагинацией."""
    logger.info(
        "GET /api/v1/system-log — period=%s process_type=%s status=%s limit=%d offset=%d",
        period, process_type, status, limit, offset,
    )
    try:
        from shared.system_log import query_log
        result = query_log(
            period=period,
            process_type=process_type,
            status=status,
            limit=limit,
            offset=offset,
        )
        logger.info("GET /api/v1/system-log — returning %d entries (total=%d)", len(result["entries"]), result["total"])
        return result
    except Exception as exc:
        logger.error("GET /api/v1/system-log — error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/v1/system-log/stats")
async def get_system_log_stats():
    """Статистика ошибок за 24ч для overview badge."""
    logger.info("GET /api/v1/system-log/stats")
    try:
        from shared.system_log import get_stats
        result = get_stats()
        logger.info("GET /api/v1/system-log/stats — total=%d errors=%d", result["last_24h"]["total"], result["last_24h"]["error"])
        return result
    except Exception as exc:
        logger.error("GET /api/v1/system-log/stats — error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Today — Morning Digest
# ---------------------------------------------------------------------------


@app.get("/api/v1/today/digest")
async def get_today_digest(refresh: bool = False):
    """Утренний дайджест: парсинг последнего morning-digest файла из vault."""
    logger.info("GET /today/digest — start, refresh=%s", refresh)
    try:
        if refresh:
            _cache.invalidate("today:digest")

        cached = _cache.get("today:digest")
        if cached is not None:
            logger.info("GET /today/digest — returning cached")
            return cached

        from datetime import date

        from shared.vault_paths import wiki_morning_digests

        from .today_parsers import find_latest_file, parse_digest

        digest_dir = wiki_morning_digests()
        today = date.today()

        file_path, is_today = find_latest_file(digest_dir, "morning-digest", today)

        if file_path is None:
            result = {
                "date": None,
                "filename": None,
                "is_today": False,
                "focus": None,
                "sections": [],
                "full_markdown": None,
            }
            _cache.set("today:digest", result)
            logger.info("GET /today/digest — no digest files found")
            return result

        text = file_path.read_text(encoding="utf-8")
        parsed = parse_digest(text)

        # Extract date from filename (YYYY-MM-DD-morning-digest.md)
        file_date = file_path.stem[:10]  # "2026-07-22"

        result = {
            "date": file_date,
            "filename": file_path.name,
            "is_today": is_today,
            "focus": parsed["focus"],
            "sections": parsed["sections"],
            "full_markdown": parsed["full_markdown"],
        }

        _cache.set("today:digest", result)
        logger.info("GET /today/digest — success, date=%s, is_today=%s", file_date, is_today)
        return result
    except Exception as e:
        logger.error("GET /today/digest — error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to read morning digest")


# ---------------------------------------------------------------------------
# TODO CRUD endpoints
# ---------------------------------------------------------------------------


@app.get("/api/v1/todos")
async def get_todos(status: str = "open"):
    """Получить список TODO-задач с фильтрацией по статусу."""
    logger.info(f"GET /todos — start, status={status}")
    try:
        cache_key = f"todos:{status}"
        cached = _cache.get(cache_key)
        if cached is not None:
            logger.info(f"GET /todos — returning cached, status={status}")
            return cached

        from .today_parsers import parse_todos

        from shared.vault_paths import wiki_todos

        todo_path = wiki_todos()
        if not todo_path.exists():
            result = {"count": 0, "todos": []}
            _cache.set(cache_key, result)
            logger.info(f"GET /todos — file not found, returning empty, status={status}")
            return result

        text = todo_path.read_text(encoding="utf-8")
        logger.info(f"GET /todos — read {len(text)} chars from {todo_path.name}")
        all_todos = parse_todos(text)

        if status == "open":
            filtered = [t for t in all_todos if t["status"] in ("todo", "in-progress")]
        elif status == "done":
            filtered = [t for t in all_todos if t["status"] in ("done", "cancelled")]
        else:  # "all"
            filtered = all_todos

        result = {"count": len(filtered), "todos": filtered}
        _cache.set(cache_key, result)
        logger.info(f"GET /todos — success, count={len(filtered)}")
        return result
    except Exception as e:
        logger.error(f"GET /todos — error: {e}")
        raise HTTPException(status_code=500, detail="Failed to read TODOs")


@app.post("/api/v1/todos", status_code=201)
async def create_todo(req: TodoCreateRequest):
    """Создать новый TODO в vault."""
    logger.info(f"POST /todos — start, title={req.title[:50]}")
    try:
        if not req.title.strip():
            logger.warning("POST /todos — empty title rejected")
            raise HTTPException(status_code=400, detail="Title is required")

        from datetime import date
        import re

        from .today_parsers import format_todo_block, parse_todos

        from shared.file_writer import atomic_write, file_lock
        from shared.vault_paths import wiki_todos

        todo_path = wiki_todos()

        # Ensure parent dir exists
        todo_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"POST /todos — todo_path={todo_path}")

        if todo_path.exists():
            text = todo_path.read_text(encoding="utf-8")
            logger.info(f"POST /todos — read existing file, {len(text)} chars")
        else:
            text = "---\ntype: personal-todo\nowner: '@igor'\n---\n\n## Открытые задачи\n\n## Закрытые задачи\n"
            logger.info("POST /todos — file not found, using template")

        # Find max TODO-NNN
        ids = [int(m) for m in re.findall(r"\[TODO-(\d+)\]", text)]
        next_num = max(ids) + 1 if ids else 1
        todo_id = f"TODO-{next_num:03d}"
        logger.info(f"POST /todos — generated id={todo_id}")

        # Format date for display
        created = date.today().strftime("%d.%m.%Y")
        due_display = None
        if req.due_date:
            # Input is ISO YYYY-MM-DD, display as DD.MM.YYYY
            parts = req.due_date.split("-")
            if len(parts) == 3:
                due_display = f"{parts[2]}.{parts[1]}.{parts[0]}"

        block = format_todo_block(
            todo_id=todo_id,
            title=req.title.strip(),
            status="todo",
            created=created,
            due_date=due_display,
            context=req.context,
            result=None,
        )
        logger.info(f"POST /todos — formatted block for {todo_id}")

        # Insert before "## Закрытые задачи" or at end
        closed_marker = "## Закрытые задачи"
        if closed_marker in text:
            idx = text.index(closed_marker)
            new_text = text[:idx] + block + "\n" + text[idx:]
        else:
            new_text = text + "\n" + block

        with file_lock(todo_path):
            atomic_write(todo_path, new_text)
        logger.info(f"POST /todos — file written for {todo_id}")

        _cache.invalidate("todos")

        result = {
            "id": todo_id,
            "title": req.title.strip(),
            "status": "todo",
            "created": date.today().isoformat(),
            "due_date": req.due_date,
        }
        logger.info(f"POST /todos — success, created {todo_id}")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"POST /todos — error: {e}")
        raise HTTPException(status_code=500, detail="Failed to create TODO")


@app.patch("/api/v1/todos/{todo_id}")
async def update_todo(todo_id: str, req: TodoUpdateRequest):
    """Обновить статус существующего TODO."""
    logger.info(f"PATCH /todos/{todo_id} — start, status={req.status}")
    try:
        valid_statuses = {"todo", "in-progress", "done", "cancelled"}
        if req.status not in valid_statuses:
            logger.warning(f"PATCH /todos/{todo_id} — invalid status={req.status}")
            raise HTTPException(
                status_code=400,
                detail=f"Status must be one of: {', '.join(sorted(valid_statuses))}",
            )

        from datetime import date
        import re

        from shared.file_writer import atomic_write, file_lock
        from shared.vault_paths import wiki_todos

        todo_path = wiki_todos()
        if not todo_path.exists():
            logger.warning(f"PATCH /todos/{todo_id} — file not found")
            raise HTTPException(status_code=404, detail=f"{todo_id} not found")

        text = todo_path.read_text(encoding="utf-8")
        logger.info(f"PATCH /todos/{todo_id} — read {len(text)} chars")

        # Find the section ### [TODO-NNN]
        section_pattern = rf"(### \[{re.escape(todo_id)}\] .+?)(?=### \[TODO-|\Z)"
        match = re.search(section_pattern, text, re.DOTALL)
        if not match:
            logger.warning(f"PATCH /todos/{todo_id} — section not found in file")
            raise HTTPException(status_code=404, detail=f"{todo_id} not found")

        section = match.group(1)
        new_section = section

        # Update status
        new_section = re.sub(
            r"\*\*Статус:\*\*\s*.+",
            f"**Статус:** {req.status}",
            new_section,
        )
        logger.info(f"PATCH /todos/{todo_id} — status updated to {req.status}")

        # Add closed date if done/cancelled
        if req.status in ("done", "cancelled"):
            closed_date = date.today().strftime("%d.%m.%Y")
            if "**Закрыто:**" not in new_section:
                # Insert after **Статус:** line
                new_section = re.sub(
                    r"(\*\*Статус:\*\* .+)",
                    rf"\1\n**Закрыто:** {closed_date}",
                    new_section,
                )
                logger.info(f"PATCH /todos/{todo_id} — added closed date {closed_date}")
            else:
                new_section = re.sub(
                    r"\*\*Закрыто:\*\*\s*.+",
                    f"**Закрыто:** {closed_date}",
                    new_section,
                )
                logger.info(f"PATCH /todos/{todo_id} — updated closed date {closed_date}")

        # Add result if provided
        if req.result:
            if "**Результат:**" not in new_section:
                new_section = new_section.rstrip() + f"\n**Результат:** {req.result}\n"
                logger.info(f"PATCH /todos/{todo_id} — added result")
            else:
                new_section = re.sub(
                    r"\*\*Результат:\*\*\s*.+",
                    f"**Результат:** {req.result}",
                    new_section,
                )
                logger.info(f"PATCH /todos/{todo_id} — updated result")

        new_text = text.replace(section, new_section)

        with file_lock(todo_path):
            atomic_write(todo_path, new_text)
        logger.info(f"PATCH /todos/{todo_id} — file written")

        _cache.invalidate("todos")

        result = {
            "id": todo_id,
            "status": req.status,
            "closed": date.today().isoformat() if req.status in ("done", "cancelled") else None,
        }
        logger.info(f"PATCH /todos/{todo_id} — success")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"PATCH /todos/{todo_id} — error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update {todo_id}")


# ---------------------------------------------------------------------------
# Today — Daily News
# ---------------------------------------------------------------------------


@app.get("/api/v1/today/news")
async def get_today_news(refresh: bool = False):
    """Ежедневные новости: парсинг последнего daily-news файла из vault."""
    logger.info(f"GET /today/news — start, refresh={refresh}")
    try:
        if refresh:
            _cache.invalidate("today:news")

        cached = _cache.get("today:news")
        if cached is not None:
            logger.info("GET /today/news — returning cached")
            return cached

        from datetime import date

        from shared.vault_paths import wiki_daily_news

        from .today_parsers import find_latest_file, parse_news

        news_dir = wiki_daily_news()
        today = date.today()

        file_path, is_today = find_latest_file(news_dir, "news", today)

        if file_path is None:
            result = {
                "date": None,
                "filename": None,
                "is_today": False,
                "categories": {"competitors": [], "ai_llm": []},
            }
            _cache.set("today:news", result)
            logger.info("GET /today/news — no news files found")
            return result

        text = file_path.read_text(encoding="utf-8")
        parsed = parse_news(text)

        # Extract date from filename (YYYY-MM-DD-news.md)
        file_date = file_path.stem[:10]  # "2026-07-21"

        result = {
            "date": file_date,
            "filename": file_path.name,
            "is_today": is_today,
            "categories": parsed["categories"],
        }

        _cache.set("today:news", result)
        logger.info(f"GET /today/news — success, date={file_date}, is_today={is_today}")
        return result
    except Exception as e:
        logger.error(f"GET /today/news — error: {e}")
        raise HTTPException(status_code=500, detail="Failed to read daily news")


# ---------------------------------------------------------------------------
# GET /api/v1/today/meetings — CalDAV meetings for today
# ---------------------------------------------------------------------------


@app.get("/api/v1/today/meetings")
async def get_today_meetings(refresh: bool = False):
    """Return today's meetings from CalDAV calendar (graceful degradation)."""
    logger.info(f"GET /today/meetings — start, refresh={refresh}")
    try:
        from datetime import date

        import asyncio

        today = date.today().isoformat()

        if not calendar_client.is_enabled():
            result = {
                "date": today,
                "count": 0,
                "source": "disabled",
                "meetings": [],
            }
            logger.info("GET /today/meetings — CalDAV disabled")
            return result

        if refresh:
            calendar_client._calendar_cache.invalidate()

        try:
            # Run synchronous CalDAV in executor
            loop = asyncio.get_event_loop()
            meetings = await loop.run_in_executor(
                _caldav_executor,
                calendar_client.get_today_meetings,
            )

            result = {
                "date": today,
                "count": len(meetings),
                "source": "caldav",
                "meetings": meetings,
            }
            logger.info(f"GET /today/meetings — success, count={len(meetings)}")
            return result
        except Exception as caldav_err:
            logger.error(f"GET /today/meetings — CalDAV error: {caldav_err}")
            return {
                "date": today,
                "count": 0,
                "source": "error",
                "meetings": [],
            }
    except Exception as e:
        logger.error(f"GET /today/meetings — error: {e}")
        return {
            "date": date.today().isoformat() if "date" in dir() else None,
            "count": 0,
            "source": "error",
            "meetings": [],
        }
