"""News Digest Converter (BL-191).

Parses daily-news markdown files from wiki/reports/daily-news/
and generates JSON digests for Signal Moderator in raw/inbound/news/.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# Pattern for a news item line:
#   - **[title](url)** -- source
_ITEM_RE = re.compile(
    r"^- \*\*\[(.+?)\]\((.+?)\)\*\*\s*—\s*(.+)$"
)

# Lines that signal end of current item's summary
_ITEM_BOUNDARY_RE = re.compile(r"^(- \*\*\[|## )")

# Italic-only lines (empty category blocks)
_ITALIC_RE = re.compile(r"^_[^_]+_$")


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Split YAML frontmatter and body from markdown text.

    Returns (frontmatter_dict, body_str).
    """
    if not text.startswith("---"):
        logger.debug("_split_frontmatter: no frontmatter delimiter found")
        return {}, text

    parts = text.split("---", 2)
    if len(parts) < 3:
        logger.debug("_split_frontmatter: incomplete frontmatter block")
        return {}, text

    fm_text = parts[1].strip()
    body = parts[2]

    fm: dict = {}
    for line in fm_text.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            fm[key.strip()] = value.strip()

    logger.debug(f"_split_frontmatter: parsed {len(fm)} keys")
    return fm, body


def parse_daily_news(markdown_path: Path) -> dict | None:
    """Parse a daily-news markdown file and extract news items.

    Args:
        markdown_path: Path to the daily-news .md file.

    Returns:
        Dict with date, source, items list -- or None if no items found.
    """
    logger.info(f"parse_daily_news: reading {markdown_path}")

    text = markdown_path.read_text(encoding="utf-8")
    fm, body = _split_frontmatter(text)
    news_date = fm.get("date", "")
    logger.debug(f"parse_daily_news: date from frontmatter = {news_date!r}")

    items: list[dict] = []
    current_item: dict | None = None

    for raw_line in body.splitlines():
        line = raw_line.rstrip()

        # Skip italic-only lines (empty sections)
        stripped = line.strip()
        if _ITALIC_RE.match(stripped):
            logger.debug(f"parse_daily_news: skipping italic line: {stripped[:60]}")
            continue

        # Try to match a new item
        match = _ITEM_RE.match(stripped)
        if match:
            # Flush previous item
            if current_item is not None:
                current_item["summary"] = current_item["summary"].strip()
                items.append(current_item)
                logger.debug(
                    f"parse_daily_news: flushed item: {current_item['title'][:50]}"
                )

            current_item = {
                "title": match.group(1),
                "source_url": match.group(2),
                "source": match.group(3).strip(),
                "summary": "",
            }
            continue

        # If we have a current item and this line is continuation (summary)
        if current_item is not None:
            # Check boundary -- new item or new section
            if _ITEM_BOUNDARY_RE.match(stripped):
                # Flush and let next iteration handle this line
                current_item["summary"] = current_item["summary"].strip()
                items.append(current_item)
                logger.debug(
                    f"parse_daily_news: flushed item at boundary: "
                    f"{current_item['title'][:50]}"
                )
                current_item = None
                # Re-check if this line is a new item
                match2 = _ITEM_RE.match(stripped)
                if match2:
                    current_item = {
                        "title": match2.group(1),
                        "source_url": match2.group(2),
                        "source": match2.group(3).strip(),
                        "summary": "",
                    }
                continue

            # Accumulate summary text
            text_part = stripped
            if text_part:
                if current_item["summary"]:
                    current_item["summary"] += " " + text_part
                else:
                    current_item["summary"] = text_part

    # Flush last item
    if current_item is not None:
        current_item["summary"] = current_item["summary"].strip()
        items.append(current_item)
        logger.debug(
            f"parse_daily_news: flushed last item: {current_item['title'][:50]}"
        )

    if not items:
        logger.info(f"parse_daily_news: no items found in {markdown_path}")
        return None

    result = {
        "date": news_date,
        "source": "daily-news",
        "items": items,
    }
    logger.info(f"parse_daily_news: found {len(items)} items")
    return result


def convert_news_digest(
    vault_path: str, date_str: str | None = None
) -> Path | None:
    """Convert a daily-news markdown file to JSON digest.

    Args:
        vault_path: Root path of the Obsidian vault.
        date_str: Date string YYYY-MM-DD. Defaults to yesterday.

    Returns:
        Path to created JSON file, or None if no conversion needed.

    Raises:
        FileNotFoundError: If the source markdown file does not exist.
    """
    if date_str is None:
        date_str = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        logger.info(f"convert_news_digest: using default date (yesterday): {date_str}")
    else:
        logger.info(f"convert_news_digest: using provided date: {date_str}")

    vault = Path(vault_path)
    source_path = vault / "wiki" / "reports" / "daily-news" / f"{date_str}-news.md"

    if not source_path.exists():
        msg = f"Daily news file not found: {source_path}"
        logger.error(f"convert_news_digest: {msg}")
        raise FileNotFoundError(msg)

    output_dir = vault / "raw" / "inbound" / "news"
    output_path = output_dir / f"{date_str}-digest.json"

    if output_path.exists():
        logger.info(f"convert_news_digest: already exists: {output_path}")
        return None

    digest = parse_daily_news(source_path)
    if digest is None:
        logger.info(
            f"convert_news_digest: no items found in {source_path}, "
            f"skipping JSON creation"
        )
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(digest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(
        f"convert_news_digest: Converted: {len(digest['items'])} items "
        f"-> {output_path}"
    )
    return output_path
