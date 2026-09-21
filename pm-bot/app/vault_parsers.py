"""
vault_parsers.py — базовые парсеры .md заметок Obsidian vault.

Не зависит от vault_api.py, vault_cache.py или routers/ — модуль базового
уровня, содержит только чистые функции парсинга frontmatter/body без
побочных эффектов на кеш или FastAPI приложение.
"""

import logging
import re
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


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
