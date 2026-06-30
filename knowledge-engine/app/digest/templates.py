"""Artifact type detection and digest template loading."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

ARTIFACT_TYPE_MAP: dict[str, str] = {
    "ideas": "idea",
    "prds": "prd",
    "epics": "epic",
    "userstories": "userstory",
    "tasks": "jira-draft",
    "bugs": "bug",
    "knowledge": "knowledge",
}

CROSS_DOMAIN_TYPE_MAP: dict[str, str] = {
    "meetings": "meeting",
    "daily-logs": "daily-log",
    "reports": "sprint-report",
}

ALL_TYPES: frozenset[str] = frozenset(
    list(ARTIFACT_TYPE_MAP.values())
    + list(CROSS_DOMAIN_TYPE_MAP.values())
    + ["decision", "competitor-analysis", "concept"]
)

_REQUIRED_FIELDS: dict[str, list[str]] = {
    "prd": ["статус", "цель", "ключевые_требования", "зависимости"],
    "decision": ["решение", "дата", "контекст", "статус"],
    "sprint-report": ["спринт", "период", "velocity", "ключевые_результаты"],
    "meeting": ["тип", "дата", "участники", "решения"],
    "competitor-analysis": ["дата_анализа", "конкуренты", "фокус"],
    "jira-draft": ["тикет", "тип", "статус", "суть"],
    "idea": ["суть", "статус", "domain"],
    "epic": ["суть", "статус", "прогресс"],
    "daily-log": ["дата", "ключевые_события"],
    "bug": ["суть", "severity", "статус"],
    "knowledge": ["суть", "категория"],
    "userstory": ["суть", "acceptance_criteria", "статус"],
    "concept": ["суть", "статус"],
}

_PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"

_PROMPT_FILENAME: dict[str, str] = {
    "prd": "digest_prd.txt",
    "decision": "digest_decision.txt",
    "sprint-report": "digest_sprint.txt",
    "meeting": "digest_meeting.txt",
    "competitor-analysis": "digest_competitor.txt",
    "jira-draft": "digest_jira.txt",
    "idea": "digest_idea.txt",
    "epic": "digest_epic.txt",
    "daily-log": "digest_daily.txt",
    "bug": "digest_bug.txt",
    "knowledge": "digest_knowledge.txt",
    "userstory": "digest_userstory.txt",
    "concept": "digest_concept.txt",
}


def get_template(artifact_type: str) -> str:
    """Load type-specific prompt template from prompts/ directory."""
    filename = _PROMPT_FILENAME.get(artifact_type)
    if not filename:
        logger.warning("templates: no prompt template for type '%s', using generic", artifact_type)
        return ""
    path = _PROMPT_DIR / filename
    if not path.exists():
        logger.warning("templates: prompt file %s not found, using generic", path)
        return ""
    logger.debug("templates: loaded template for type '%s' from %s", artifact_type, filename)
    return path.read_text(encoding="utf-8")


def get_required_fields(artifact_type: str) -> list[str]:
    """Return list of required core-digest fields for artifact type."""
    return _REQUIRED_FIELDS.get(artifact_type, [])


def detect_type(source_path: Path, metadata: dict) -> str:
    """Detect artifact type from path structure and/or frontmatter.

    Priority: frontmatter 'type' field -> path-based detection -> fallback 'idea'.
    """
    fm_type = metadata.get("type", "")
    if fm_type and fm_type in ALL_TYPES:
        logger.debug("templates: type '%s' from frontmatter for %s", fm_type, source_path.name)
        return fm_type

    parts = source_path.parts
    for i, part in enumerate(parts):
        if part in CROSS_DOMAIN_TYPE_MAP:
            detected = CROSS_DOMAIN_TYPE_MAP[part]
            logger.debug("templates: type '%s' from cross-domain path for %s", detected, source_path.name)
            return detected
        if part in ARTIFACT_TYPE_MAP:
            detected = ARTIFACT_TYPE_MAP[part]
            logger.debug("templates: type '%s' from domain path for %s", detected, source_path.name)
            return detected

    logger.warning("templates: could not detect type for %s, falling back to 'idea'", source_path.name)
    return "idea"
