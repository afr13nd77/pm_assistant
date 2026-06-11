"""
Classifier module for Meeting Fetcher.

Parses protocol type from YAML frontmatter, routes to the correct vault folder,
and generates vault-compatible filenames.
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import frontmatter

from ..vault_paths import next_daily_filename

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))

TYPE_FOLDER_MAP = {
    "daily": "wiki/daily-logs",
    "sync": "wiki/meetings",
    "review": "wiki/meetings",
    "planning": "wiki/meetings",
}

DEFAULT_FOLDER = "wiki/meetings"

_VALID_TYPES = frozenset(TYPE_FOLDER_MAP.keys())

# Prefix commonly added by Telemost email notifications
_TELEMOST_PREFIX_RE = re.compile(r"^Запись встречи:\s*", re.IGNORECASE)

# Characters not allowed in filenames (Windows + common FS restrictions)
_UNSAFE_CHARS_RE = re.compile(r'[\\/:*?"<>|]')

# Collapse multiple hyphens into one
_MULTI_HYPHEN_RE = re.compile(r"-{2,}")

# Whitespace and underscores -> hyphens
_SEPARATOR_RE = re.compile(r"[\s_]+")

_MAX_SLUG_LEN = 50


def extract_type(protocol_md: str) -> str:
    """
    Parse the 'type' field from YAML frontmatter in the protocol markdown.

    Returns one of: daily, sync, review, planning.
    Falls back to 'sync' if type is missing or unrecognized.
    """
    logger.info("Extracting protocol type from frontmatter")
    try:
        post = frontmatter.loads(protocol_md)
        raw_type = post.metadata.get("type", "sync")
        protocol_type = str(raw_type).strip().lower()

        if protocol_type not in _VALID_TYPES:
            logger.warning(
                "Unrecognized protocol type '%s'; falling back to 'sync'",
                raw_type,
            )
            return "sync"

        logger.info("Extracted protocol type: '%s'", protocol_type)
        return protocol_type
    except Exception as e:
        logger.error("Failed to extract type from frontmatter: %s", e)
        raise


def route_protocol(protocol_type: str) -> str:
    """
    Map protocol type to vault-relative folder path.

    Returns 'wiki/daily-logs' for daily, or 'wiki/meetings'
    for sync / review / planning (and any unknown type).
    """
    logger.info("Routing protocol type '%s' to vault folder", protocol_type)
    folder = TYPE_FOLDER_MAP.get(protocol_type, DEFAULT_FOLDER)
    logger.info("Protocol type '%s' routed to folder: '%s'", protocol_type, folder)
    return folder


def sanitize_filename(name: str) -> str:
    """Remove characters not allowed in filenames."""
    logger.info("Sanitizing filename component")
    try:
        sanitized = _UNSAFE_CHARS_RE.sub("", name).strip()
        logger.info("Filename sanitized successfully")
        return sanitized
    except Exception as e:
        logger.error("Failed to sanitize filename: %s", e)
        raise


def _truncate_slug(slug: str, max_len: int) -> str:
    """Truncate slug to max_len at word (hyphen) boundary."""
    if len(slug) <= max_len:
        return slug

    # Find last hyphen before or at max_len position
    truncated = slug[:max_len]
    last_hyphen = truncated.rfind("-")
    if last_hyphen > 0:
        truncated = truncated[:last_hyphen]
    # else: no hyphen found, just hard-cut at max_len (already done)

    return truncated.rstrip("-")


def make_filename(msg_date: datetime, subject: str) -> str:
    """
    Generate vault-compatible filename from email date and subject.

    Pattern: YYYY-MM-DD-HHMM-<slug>.md

    Example: 2026-04-25-1000-daily-standup.md
    """
    logger.info("Generating filename for subject='%s', date='%s'", subject, msg_date)
    try:
        # 1. Date part in MSK timezone
        date_part = msg_date.astimezone(MSK).strftime("%Y-%m-%d-%H%M")

        # 2. Build slug from subject
        slug = subject

        # Remove Telemost prefix
        slug = _TELEMOST_PREFIX_RE.sub("", slug)

        # Remove unsafe filesystem characters
        slug = sanitize_filename(slug)

        # Replace spaces and underscores with hyphens
        slug = _SEPARATOR_RE.sub("-", slug)

        # Lowercase
        slug = slug.lower()

        # Collapse multiple hyphens
        slug = _MULTI_HYPHEN_RE.sub("-", slug)

        # Strip leading/trailing hyphens
        slug = slug.strip("-")

        # Truncate to 50 chars at word boundary
        slug = _truncate_slug(slug, _MAX_SLUG_LEN)

        # If slug is empty after all processing, use default
        if not slug:
            logger.warning("Subject produced empty slug; using default 'meeting'")
            slug = "meeting"

        filename = f"{date_part}-{slug}.md"
        logger.info("Generated filename: '%s'", filename)
        return filename
    except Exception as e:
        logger.error("Failed to generate filename: %s", e)
        raise


def make_daily_filename(daily_dir: Path) -> str:
    """Generate filename for daily protocols using the global sequence."""
    logger.info("make_daily_filename: generating daily filename in %s", daily_dir)
    filename = next_daily_filename(daily_dir)
    logger.info("make_daily_filename: generated '%s'", filename)
    return filename
