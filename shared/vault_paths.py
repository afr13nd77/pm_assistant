"""Centralized vault path logic for the pm_assistant project.

All functions return pathlib.Path objects. Directory-returning functions
ensure the directory exists (mkdir parents=True, exist_ok=True).

VAULT_PATH is read from the environment variable VAULT_PATH, defaulting
to /vault if not set.
"""

import logging
import os
import re
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

VAULT_PATH = Path(os.getenv("VAULT_PATH", "/vault"))

_VALID_ARTIFACT_TYPES = frozenset({
    "ideas", "prds", "epics", "userstories", "tasks", "bugs", "knowledge",
})


def _ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def vault_root() -> Path:
    return _ensure_dir(VAULT_PATH)


def raw_ideas() -> Path:
    return _ensure_dir(VAULT_PATH / "raw" / "inbound" / "ideas")


def raw_meetings() -> Path:
    return _ensure_dir(VAULT_PATH / "raw" / "inbound" / "meeting-notes")


def raw_daily_logs() -> Path:
    return _ensure_dir(VAULT_PATH / "raw" / "inbound" / "daily-logs")


def raw_tasks() -> Path:
    return _ensure_dir(VAULT_PATH / "raw" / "inbound" / "tasks")


def raw_clippings() -> Path:
    return _ensure_dir(VAULT_PATH / "raw" / "inbound" / "clippings")


def raw_misc() -> Path:
    return _ensure_dir(VAULT_PATH / "raw" / "inbound" / "misc")


def raw_competitors() -> Path:
    return _ensure_dir(VAULT_PATH / "raw" / "competitors")


def raw_metrics() -> Path:
    return _ensure_dir(VAULT_PATH / "raw" / "metrics")


def raw_research_queue() -> Path:
    return _ensure_dir(VAULT_PATH / "raw" / "inbound" / "research-queue")


def raw_research_queue_processed() -> Path:
    return _ensure_dir(VAULT_PATH / "raw" / "inbound" / "research-queue" / "processed")


def raw_research_queue_failed() -> Path:
    return _ensure_dir(VAULT_PATH / "raw" / "inbound" / "research-queue" / "failed")


def wiki_domain_dir(domain: str, artifact_type: str) -> Path:
    if artifact_type not in _VALID_ARTIFACT_TYPES:
        raise ValueError(
            f"Invalid artifact_type '{artifact_type}'. "
            f"Must be one of: {', '.join(sorted(_VALID_ARTIFACT_TYPES))}"
        )
    return _ensure_dir(VAULT_PATH / "wiki" / "domains" / domain / artifact_type)


def wiki_meetings() -> Path:
    return _ensure_dir(VAULT_PATH / "wiki" / "meetings")


def wiki_daily_logs() -> Path:
    return _ensure_dir(VAULT_PATH / "wiki" / "daily-logs")


def wiki_reports() -> Path:
    return _ensure_dir(VAULT_PATH / "wiki" / "reports")


def wiki_morning_digests() -> Path:
    return _ensure_dir(VAULT_PATH / "wiki" / "reports" / "morning-digest")


def wiki_daily_news() -> Path:
    return _ensure_dir(VAULT_PATH / "wiki" / "reports" / "daily-news")


def wiki_todos() -> Path:
    return VAULT_PATH / "wiki" / "domains" / "general" / "tasks" / "todo.md"


def llm_wiki_root() -> Path:
    return _ensure_dir(VAULT_PATH / "llm_wiki")


def llm_wiki_domain_dir(domain: str, artifact_type: str) -> Path:
    if artifact_type not in _VALID_ARTIFACT_TYPES:
        raise ValueError(
            f"Invalid artifact_type '{artifact_type}'. "
            f"Must be one of: {', '.join(sorted(_VALID_ARTIFACT_TYPES))}"
        )
    return _ensure_dir(VAULT_PATH / "llm_wiki" / "domains" / domain / artifact_type)


def llm_wiki_meetings() -> Path:
    return _ensure_dir(VAULT_PATH / "llm_wiki" / "meetings")


def llm_wiki_daily_logs() -> Path:
    return _ensure_dir(VAULT_PATH / "llm_wiki" / "daily-logs")


def llm_wiki_reports() -> Path:
    return _ensure_dir(VAULT_PATH / "llm_wiki" / "reports")


def llm_wiki_index_file() -> Path:
    return VAULT_PATH / "llm_wiki" / "_index.md"


def llm_wiki_cowork_session() -> Path:
    """Return path to llm_wiki/_cowork-session.md."""
    return VAULT_PATH / "llm_wiki" / "_cowork-session.md"


def wiki_concepts() -> Path:
    """Return path to wiki/concepts/ directory, ensuring it exists."""
    logger.info("wiki_concepts: resolving wiki/concepts/ directory")
    return _ensure_dir(VAULT_PATH / "wiki" / "concepts")


def wiki_domain_knowledge(domain: str) -> Path:
    """Return path to wiki/domains/<domain>/knowledge/, ensuring it exists."""
    logger.info("wiki_domain_knowledge: resolving knowledge dir for domain=%s", domain)
    return wiki_domain_dir(domain, "knowledge")


def domain_config_path() -> Path:
    return VAULT_PATH / "domain-config.yaml"


def user_prefs_path() -> Path:
    return VAULT_PATH / ".pm-user-prefs.json"


def wiki_index() -> Path:
    return VAULT_PATH / "wiki" / "INDEX.md"


def wiki_log() -> Path:
    return VAULT_PATH / "wiki" / "LOG.md"


def wiki_service_index() -> Path:
    return _ensure_dir(VAULT_PATH / "wiki" / "_index")


def raw_signals() -> Path:
    """raw/inbound/signals/ — иммутабельные raw JSON сигналов."""
    logger.info("raw_signals: resolving raw/inbound/signals/ directory")
    return _ensure_dir(VAULT_PATH / "raw" / "inbound" / "signals")


def wiki_signals() -> Path:
    """wiki/reports/signals/ — wiki-копии сигналов + аналитические отчёты."""
    logger.info("wiki_signals: resolving wiki/reports/signals/ directory")
    return _ensure_dir(VAULT_PATH / "wiki" / "reports" / "signals")


def templates() -> Path:
    return _ensure_dir(VAULT_PATH / "templates")


def all_domains() -> list[str]:
    domains_dir = VAULT_PATH / "wiki" / "domains"
    if not domains_dir.exists():
        return []
    return sorted(
        entry.name
        for entry in domains_dir.iterdir()
        if entry.is_dir()
    )


def next_daily_filename(daily_dir: Path) -> str:
    """Generate the next sequential daily-summary filename.

    Scans *daily_dir* for files matching the pattern
    ``YYYY.MM.DD-NNN-Daily-summary.md``, finds the maximum sequence number
    NNN, and returns a new filename with NNN+1 for today's date.
    If no matching files exist the sequence starts from 001.
    """
    pattern = re.compile(r"^\d{4}\.\d{2}\.\d{2}-(\d{3})-Daily-summary\.md$")

    existing_numbers: list[int] = []
    if daily_dir.exists():
        for entry in daily_dir.iterdir():
            m = pattern.match(entry.name)
            if m:
                existing_numbers.append(int(m.group(1)))

    max_num = max(existing_numbers) if existing_numbers else 0
    next_num = max_num + 1
    today_str = date.today().strftime("%Y.%m.%d")
    filename = f"{today_str}-{next_num:03d}-Daily-summary.md"

    logger.info(
        "next_daily_filename: found %d existing daily files, max_number=%d, "
        "generated filename=%s",
        len(existing_numbers),
        max_num,
        filename,
    )
    return filename


def ensure_structure() -> None:
    logger.info("ensure_structure: creating raw/ subdirectories under %s", VAULT_PATH)
    raw_dirs = [
        raw_ideas,
        raw_meetings,
        raw_daily_logs,
        raw_tasks,
        raw_clippings,
        raw_misc,
        raw_competitors,
        raw_metrics,
        raw_signals,  # BL-203: Signal-артефакты
    ]
    for fn in raw_dirs:
        path = fn()
        logger.info("ensure_structure: ensured %s", path)
    logger.info("ensure_structure: done — all raw/ subdirectories exist")


def max_idea_number() -> int:
    """Scan raw/ideas and wiki/domains/*/ideas/ for the highest IDEA-NNNN number."""
    max_num = 0
    pattern = re.compile(r"IDEA-(\d{4})")

    # 1. Scan raw/ideas
    raw_dir = raw_ideas()
    if raw_dir.exists():
        for f in raw_dir.glob("IDEA-*.md"):
            m = pattern.match(f.name)
            if m:
                max_num = max(max_num, int(m.group(1)))

    # 2. Scan wiki/domains/*/ideas/
    domains_dir = VAULT_PATH / "wiki" / "domains"
    if domains_dir.exists():
        for domain_entry in domains_dir.iterdir():
            if not domain_entry.is_dir():
                continue
            ideas_dir = domain_entry / "ideas"
            if ideas_dir.exists():
                for f in ideas_dir.glob("IDEA-*.md"):
                    m = pattern.match(f.name)
                    if m:
                        max_num = max(max_num, int(m.group(1)))

    logger.info("max_idea_number: scanned vault, max_num=%d", max_num)
    return max_num
