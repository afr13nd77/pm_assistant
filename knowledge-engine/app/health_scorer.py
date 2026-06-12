import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import vault_paths
from .file_writer import atomic_write
from .frontmatter_utils import read_frontmatter
from .linter import check_broken_links, check_orphan_pages, check_stale_drafts, check_unsorted_misc

logger = logging.getLogger(__name__)

_HISTORY_FILENAME = ".health-history.json"
_HISTORY_TTL_DAYS = 90

_WEIGHTS = {
    "broken_links": 3,
    "orphan_pages": 5,
    "dead_ends": 1,
    "stale_drafts": 1,
    "unsorted_misc": 0.5,
    "ingest_backlog": 0.2,
}

_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
_ARTIFACT_TYPES = ("ideas", "prds", "epics", "userstories", "tasks", "bugs")
_SERVICE_FILES = frozenset({"index.md", "log.md", "decisions.md", "glossary.md"})


def calculate_health(vault_path: str) -> dict:
    logger.info("calculate_health: starting, vault_path=%s", vault_path)

    breakdown = {}

    # broken_links
    try:
        items = check_broken_links(vault_path)
        count = len(items)
        breakdown["broken_links"] = {
            "count": count,
            "weight": _WEIGHTS["broken_links"],
            "penalty": count * _WEIGHTS["broken_links"],
            "items": items,
        }
        logger.info("calculate_health: broken_links count=%d", count)
    except Exception as exc:
        logger.warning("calculate_health: broken_links check failed: %s", exc, exc_info=True)
        breakdown["broken_links"] = {
            "count": 0,
            "weight": _WEIGHTS["broken_links"],
            "penalty": 0,
            "items": [],
            "error": f"check failed: {exc}",
        }

    # orphan_pages
    try:
        items = check_orphan_pages(vault_path)
        count = len(items)
        breakdown["orphan_pages"] = {
            "count": count,
            "weight": _WEIGHTS["orphan_pages"],
            "penalty": count * _WEIGHTS["orphan_pages"],
            "items": items,
        }
        logger.info("calculate_health: orphan_pages count=%d", count)
    except Exception as exc:
        logger.warning("calculate_health: orphan_pages check failed: %s", exc, exc_info=True)
        breakdown["orphan_pages"] = {
            "count": 0,
            "weight": _WEIGHTS["orphan_pages"],
            "penalty": 0,
            "items": [],
            "error": f"check failed: {exc}",
        }

    # dead_ends
    try:
        items = _check_dead_ends(vault_path)
        count = len(items)
        breakdown["dead_ends"] = {
            "count": count,
            "weight": _WEIGHTS["dead_ends"],
            "penalty": count * _WEIGHTS["dead_ends"],
            "items": items,
        }
        logger.info("calculate_health: dead_ends count=%d", count)
    except Exception as exc:
        logger.warning("calculate_health: dead_ends check failed: %s", exc, exc_info=True)
        breakdown["dead_ends"] = {
            "count": 0,
            "weight": _WEIGHTS["dead_ends"],
            "penalty": 0,
            "items": [],
            "error": f"check failed: {exc}",
        }

    # stale_drafts
    try:
        items = check_stale_drafts(vault_path)
        count = len(items)
        breakdown["stale_drafts"] = {
            "count": count,
            "weight": _WEIGHTS["stale_drafts"],
            "penalty": count * _WEIGHTS["stale_drafts"],
            "items": items,
        }
        logger.info("calculate_health: stale_drafts count=%d", count)
    except Exception as exc:
        logger.warning("calculate_health: stale_drafts check failed: %s", exc, exc_info=True)
        breakdown["stale_drafts"] = {
            "count": 0,
            "weight": _WEIGHTS["stale_drafts"],
            "penalty": 0,
            "items": [],
            "error": f"check failed: {exc}",
        }

    # unsorted_misc
    try:
        items = check_unsorted_misc(vault_path)
        count = len(items)
        breakdown["unsorted_misc"] = {
            "count": count,
            "weight": _WEIGHTS["unsorted_misc"],
            "penalty": count * _WEIGHTS["unsorted_misc"],
            "items": items,
        }
        logger.info("calculate_health: unsorted_misc count=%d", count)
    except Exception as exc:
        logger.warning("calculate_health: unsorted_misc check failed: %s", exc, exc_info=True)
        breakdown["unsorted_misc"] = {
            "count": 0,
            "weight": _WEIGHTS["unsorted_misc"],
            "penalty": 0,
            "items": [],
            "error": f"check failed: {exc}",
        }

    # ingest_backlog
    try:
        items = _check_ingest_backlog(vault_path)
        count = len(items)
        breakdown["ingest_backlog"] = {
            "count": count,
            "weight": _WEIGHTS["ingest_backlog"],
            "penalty": count * _WEIGHTS["ingest_backlog"],
            "items": items,
        }
        logger.info("calculate_health: ingest_backlog count=%d", count)
    except Exception as exc:
        logger.warning("calculate_health: ingest_backlog check failed: %s", exc, exc_info=True)
        breakdown["ingest_backlog"] = {
            "count": 0,
            "weight": _WEIGHTS["ingest_backlog"],
            "penalty": 0,
            "items": [],
            "error": f"check failed: {exc}",
        }

    # description_coverage
    try:
        coverage = _check_description_coverage(vault_path)
        pct = coverage["pct"]
        if pct < 50:
            penalty = 10
        elif pct < 70:
            penalty = 5
        else:
            penalty = 0
        breakdown["description_coverage"] = {
            "pct": pct,
            "penalty": penalty,
            "total_pages": coverage["total_pages"],
            "pages_with_description": coverage["pages_with_description"],
        }
        logger.info("calculate_health: description_coverage pct=%d penalty=%d", pct, penalty)
    except Exception as exc:
        logger.warning("calculate_health: description_coverage check failed: %s", exc, exc_info=True)
        breakdown["description_coverage"] = {
            "pct": 100,
            "penalty": 0,
            "total_pages": 0,
            "pages_with_description": 0,
            "error": f"check failed: {exc}",
        }

    score, grade = _compute_score(breakdown)
    calculated_at = datetime.now(timezone.utc).isoformat()

    result = {
        "score": score,
        "grade": grade,
        "breakdown": breakdown,
        "calculated_at": calculated_at,
    }

    logger.info("calculate_health: completed, score=%d grade=%s", score, grade)
    return result


def _compute_score(breakdown: dict) -> tuple:
    logger.info("_compute_score: starting")

    raw = 100.0
    raw -= breakdown.get("broken_links", {}).get("count", 0) * 3
    raw -= breakdown.get("orphan_pages", {}).get("count", 0) * 5
    raw -= breakdown.get("dead_ends", {}).get("count", 0) * 1
    raw -= breakdown.get("stale_drafts", {}).get("count", 0) * 1
    raw -= breakdown.get("unsorted_misc", {}).get("count", 0) * 0.5
    raw -= breakdown.get("ingest_backlog", {}).get("count", 0) * 0.2
    raw -= breakdown.get("description_coverage", {}).get("penalty", 0)

    score = int(max(0, min(100, raw)))

    if score >= 80:
        grade = "healthy"
    elif score >= 50:
        grade = "warning"
    else:
        grade = "critical"

    logger.info("_compute_score: completed, raw=%.1f score=%d grade=%s", raw, score, grade)
    return score, grade


def save_history(vault_path: str, score_entry: dict) -> None:
    logger.info("save_history: starting, vault_path=%s", vault_path)

    history_path = Path(vault_path) / _HISTORY_FILENAME

    history = {"version": 1, "entries": []}
    if history_path.exists():
        try:
            raw = history_path.read_text(encoding="utf-8")
            loaded = json.loads(raw)
            if isinstance(loaded, dict) and isinstance(loaded.get("entries"), list):
                history = loaded
            else:
                logger.warning("save_history: invalid schema, creating fresh history")
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("save_history: cannot read existing history: %s, creating fresh", exc)

    today = datetime.now(timezone.utc).date()
    cutoff = (today - timedelta(days=_HISTORY_TTL_DAYS)).isoformat()

    entries = [e for e in history["entries"] if e.get("date", "") >= cutoff]
    logger.info("save_history: TTL cleanup removed %d old entries", len(history["entries"]) - len(entries))

    entry_date = score_entry.get("date", "")
    entries = [e for e in entries if e.get("date") != entry_date]
    entries.append(score_entry)

    entries.sort(key=lambda e: e.get("date", ""), reverse=True)

    history["version"] = 1
    history["entries"] = entries

    content = json.dumps(history, ensure_ascii=False, indent=2)
    atomic_write(str(history_path), content)

    logger.info("save_history: completed, total_entries=%d", len(entries))


def load_history(vault_path: str, days: int = 90) -> list:
    logger.info("load_history: starting, vault_path=%s days=%d", vault_path, days)

    history_path = Path(vault_path) / _HISTORY_FILENAME

    if not history_path.exists():
        logger.warning("load_history: file not found at %s, returning empty", history_path)
        return []

    try:
        raw = history_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("load_history: cannot read/parse %s: %s, returning empty", history_path, exc)
        return []

    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        logger.warning("load_history: invalid schema in %s, returning empty", history_path)
        return []

    today = datetime.now(timezone.utc).date()
    cutoff = (today - timedelta(days=days)).isoformat()

    filtered = [e for e in data["entries"] if e.get("date", "") >= cutoff]
    filtered.sort(key=lambda e: e.get("date", ""))

    logger.info("load_history: completed, returned %d entries (filtered from %d)", len(filtered), len(data["entries"]))
    return filtered


def _check_dead_ends(vault_path: str) -> list:
    """Find artifact pages with zero outgoing wikilinks in their body.

    Scans wiki/domains/<domain>/<artifact_type>/*.md for all 6 artifact types.
    Excludes service files. A page is a dead-end if the body (everything after
    the second ``---`` of frontmatter) contains no ``[[wikilink]]`` patterns.

    Returns list[dict] with keys ``file`` (relative to vault, forward slashes)
    and ``domain``.
    """
    logger.info("_check_dead_ends: starting, vault_path=%s", vault_path)

    vault = Path(vault_path)
    domains = vault_paths.all_domains()
    dead_ends: list[dict] = []
    scanned = 0
    jira_skipped = 0

    for domain in domains:
        for artifact_type in _ARTIFACT_TYPES:
            artifact_dir = vault / "wiki" / "domains" / domain / artifact_type
            if not artifact_dir.is_dir():
                continue

            for md_file in artifact_dir.iterdir():
                if not md_file.is_file() or md_file.suffix.lower() != ".md":
                    continue
                if md_file.name in _SERVICE_FILES:
                    continue

                scanned += 1

                try:
                    metadata, body = read_frontmatter(md_file)
                except Exception as exc:
                    logger.error(
                        "_check_dead_ends: cannot read %s: %s", md_file, exc
                    )
                    continue

                if metadata.get("jira_key"):
                    jira_skipped += 1
                    continue

                if not _WIKILINK_RE.search(body):
                    rel_path = md_file.relative_to(vault).as_posix()
                    dead_ends.append({"file": rel_path, "domain": domain})

    logger.info(
        "_check_dead_ends: completed, scanned=%d dead_ends=%d jira_skipped=%d",
        scanned,
        len(dead_ends),
        jira_skipped,
    )
    return dead_ends


def _check_description_coverage(vault_path: str) -> dict:
    """Check how many artifact pages have a meaningful description (>= 2 sentences).

    Scans wiki/domains/<domain>/<artifact_type>/*.md for all 6 artifact types.
    Excludes service files. Uses frontmatter_utils.read_frontmatter to extract
    the body text (after YAML frontmatter). Counts sentences by splitting on
    sentence-ending patterns ('. ', '! ', '? ', '\\n\\n') and filtering empties.

    Returns dict with keys total_pages, pages_with_description, pct.
    """
    logger.info("_check_description_coverage: starting, vault_path=%s", vault_path)

    vault = Path(vault_path)
    domains = vault_paths.all_domains()
    total_pages = 0
    pages_with_description = 0
    sentence_split_re = re.compile(r"\.\s|!\s|\?\s|\n\n")

    for domain in domains:
        for artifact_type in _ARTIFACT_TYPES:
            artifact_dir = vault / "wiki" / "domains" / domain / artifact_type
            if not artifact_dir.is_dir():
                continue

            for md_file in artifact_dir.iterdir():
                if not md_file.is_file() or md_file.suffix.lower() != ".md":
                    continue
                if md_file.name in _SERVICE_FILES:
                    continue

                total_pages += 1

                try:
                    _metadata, body = read_frontmatter(md_file)
                except Exception as exc:
                    logger.error(
                        "_check_description_coverage: cannot read %s: %s",
                        md_file,
                        exc,
                    )
                    continue

                parts = sentence_split_re.split(body)
                sentence_count = sum(1 for part in parts if part.strip())

                if sentence_count >= 2:
                    pages_with_description += 1

    pct = round(pages_with_description / total_pages * 100) if total_pages > 0 else 100

    logger.info(
        "_check_description_coverage: completed, total_pages=%d pages_with_description=%d pct=%d",
        total_pages,
        pages_with_description,
        pct,
    )
    return {
        "total_pages": total_pages,
        "pages_with_description": pages_with_description,
        "pct": pct,
    }


def _check_ingest_backlog(vault_path: str) -> list:
    """Find raw inbound files not yet ingested into wiki.

    Scans ``raw/inbound/ideas/*.md`` and ``raw/inbound/tasks/*.md``.

    **Ideas** use id-based matching: reads the ``id`` field from frontmatter
    of both raw and wiki files.  A raw idea is considered ingested when a wiki
    idea with the same ``id`` exists (comparison is case-insensitive after
    strip).  If a raw idea has no ``id`` in its frontmatter, falls back to
    stem matching.

    **Tasks** use stem matching: a raw task is considered ingested when a wiki
    task file with the same stem (case-insensitive) exists in any domain.

    Returns list[dict] with keys ``file`` (relative to vault, forward slashes)
    and ``type`` ("ideas" or "tasks").
    """
    logger.info("_check_ingest_backlog: starting, vault_path=%s", vault_path)

    vault = Path(vault_path)
    domains_dir = vault / "wiki" / "domains"

    # ------------------------------------------------------------------
    # 1. Collect wiki ids for ideas and wiki stems for tasks
    # ------------------------------------------------------------------
    wiki_idea_ids: set[str] = set()
    wiki_idea_stems: set[str] = set()  # fallback for ideas without id
    wiki_task_stems: set[str] = set()

    if domains_dir.exists():
        for domain_dir in domains_dir.iterdir():
            if not domain_dir.is_dir():
                continue

            # Ideas: collect ids from frontmatter + stems as fallback
            ideas_dir = domain_dir / "ideas"
            if ideas_dir.exists():
                for f in ideas_dir.glob("*.md"):
                    wiki_idea_stems.add(f.stem.lower())
                    try:
                        meta, _ = read_frontmatter(f)
                        idea_id = meta.get("id")
                        if idea_id and isinstance(idea_id, str):
                            wiki_idea_ids.add(idea_id.strip().lower())
                    except Exception:
                        logger.warning(
                            "_check_ingest_backlog: failed to read frontmatter from wiki idea %s, using stem only",
                            f,
                        )

            # Tasks: collect stems only
            tasks_dir = domain_dir / "tasks"
            if tasks_dir.exists():
                for f in tasks_dir.glob("*.md"):
                    wiki_task_stems.add(f.stem.lower())

    logger.info(
        "_check_ingest_backlog: collected %d wiki idea ids, %d wiki idea stems, %d wiki task stems from %s",
        len(wiki_idea_ids),
        len(wiki_idea_stems),
        len(wiki_task_stems),
        domains_dir,
    )

    # ------------------------------------------------------------------
    # 2. Scan raw inbound directories
    # ------------------------------------------------------------------
    backlog: list[dict] = []
    raw_scanned = 0

    for art_type in ("ideas", "tasks"):
        raw_dir = vault / "raw" / "inbound" / art_type
        if not raw_dir.exists():
            logger.info(
                "_check_ingest_backlog: raw dir does not exist, skipping: %s",
                raw_dir,
            )
            continue

        for f in raw_dir.glob("*.md"):
            raw_scanned += 1

            if art_type == "ideas":
                # Try id-based matching first
                raw_id: str | None = None
                try:
                    meta, _ = read_frontmatter(f)
                    raw_id_val = meta.get("id")
                    if raw_id_val and isinstance(raw_id_val, str):
                        raw_id = raw_id_val.strip().lower()
                except Exception:
                    logger.warning(
                        "_check_ingest_backlog: failed to read frontmatter from raw idea %s, skipping",
                        f,
                    )
                    continue  # cannot determine id -> skip, do not count as backlog

                if raw_id is not None:
                    # id-based matching
                    if raw_id not in wiki_idea_ids:
                        backlog.append({
                            "file": str(f.relative_to(vault)).replace("\\", "/"),
                            "type": art_type,
                        })
                else:
                    # Fallback: stem matching (raw idea has no id)
                    if f.stem.lower() not in wiki_idea_stems:
                        backlog.append({
                            "file": str(f.relative_to(vault)).replace("\\", "/"),
                            "type": art_type,
                        })

            else:
                # Tasks: stem matching
                if f.stem.lower() not in wiki_task_stems:
                    backlog.append({
                        "file": str(f.relative_to(vault)).replace("\\", "/"),
                        "type": art_type,
                    })

    logger.info(
        "_check_ingest_backlog: completed, raw_scanned=%d backlog=%d",
        raw_scanned,
        len(backlog),
    )
    return backlog
