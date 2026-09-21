"""
vault_scanner.py — сканирование файловой системы Obsidian vault.

Содержит служебные константы и функции для обхода domain-based структуры
vault (wiki/domains/<domain>/<artifact_type>/), поиска файлов артефактов
и точечного обновления полей frontmatter.
"""

import logging
import re
from pathlib import Path

from shared.vault_paths import VAULT_PATH, all_domains, wiki_domain_dir

logger = logging.getLogger(__name__)


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
# Artifact types
# ---------------------------------------------------------------------------

_ARTIFACT_TYPES = ("ideas", "prds", "epics", "userstories", "tasks", "bugs")
