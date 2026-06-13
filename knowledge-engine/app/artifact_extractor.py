"""Extract domain artifacts from processed meetings and daily-logs.

Parses markdown files from wiki/meetings/ and wiki/daily-logs/ and routes
extracted action items, decisions, and ideas to the appropriate domain
directories under wiki/domains/<domain>/.
"""

import json
import logging
import re
from datetime import date
from pathlib import Path

from shared import vault_paths
from shared.file_writer import atomic_write

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Domain detection keywords
# ---------------------------------------------------------------------------

_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "search-engine": [
        "поиск", "индексаци", "ранжирован", "выдач", "фильтр",
    ],
    "suggester": [
        "автокомплит", "подсказк", "typeahead", "suggest",
    ],
    "static-metadata": [
        "справочник", "классификатор", "атрибут", "метаданн", "каталог", "контент",
    ],
}

_DEFAULT_DOMAIN = "general"


def _merged_keyword_map() -> dict[str, list[str]]:
    """Merge hardcoded _DOMAIN_KEYWORDS with domain-config.yaml keywords."""
    logger.info("_merged_keyword_map: building merged keyword map")
    result: dict[str, list[str]] = {}

    # Start with hardcoded
    for domain, kw_list in _DOMAIN_KEYWORDS.items():
        result[domain] = list(kw_list)

    # Overlay config keywords
    try:
        from shared import domain_config
        config = domain_config.load()
        domains = config.get("domains", {})
        config_count = 0
        for slug, entry in domains.items():
            if not isinstance(entry, dict):
                continue
            config_keywords = entry.get("keywords", [])
            if not config_keywords:
                continue
            if slug not in result:
                result[slug] = []
            existing_lower = {kw.lower() for kw in result[slug]}
            for kw in config_keywords:
                if isinstance(kw, str) and kw and kw.lower() not in existing_lower:
                    result[slug].append(kw)
                    existing_lower.add(kw.lower())
                    config_count += 1
        logger.info(
            "_merged_keyword_map: added %d keyword(s) from config across %d domain(s)",
            config_count, len(domains),
        )
    except Exception as exc:
        logger.warning(
            "_merged_keyword_map: could not load config keywords, "
            "using hardcoded only: %s", exc,
        )

    logger.info(
        "_merged_keyword_map: total %d domain(s), %d keyword(s)",
        len(result), sum(len(v) for v in result.values()),
    )
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_artifacts(source_path: Path) -> dict:
    """Main entry point: read *source_path*, extract artifacts, write them out.

    Returns a summary dict::

        {
            "source": "<relative path inside vault>",
            "artifacts": [
                {"type": "task", "domain": "search-engine", "filename": "..."},
                ...
            ]
        }
    """
    source_path = Path(source_path)
    logger.info("extract_artifacts: starting for %s", source_path)

    if not source_path.exists():
        logger.error("extract_artifacts: source file not found: %s", source_path)
        return {"source": str(source_path), "artifacts": []}

    body = source_path.read_text(encoding="utf-8")
    logger.info(
        "extract_artifacts: read %d chars from %s", len(body), source_path.name,
    )

    source_type = _detect_source_type(source_path)
    logger.info("extract_artifacts: detected source type '%s'", source_type)

    action_items = _extract_action_items(body)
    logger.info(
        "extract_artifacts: found %d action items", len(action_items),
    )

    decisions = _extract_decisions(body)
    logger.info("extract_artifacts: found %d decisions", len(decisions))

    ideas = _extract_ideas(body)
    logger.info("extract_artifacts: found %d ideas", len(ideas))

    artifacts: list[dict] = []

    # Relative path for wiki-link (relative to VAULT_PATH)
    try:
        rel_source = source_path.relative_to(vault_paths.VAULT_PATH)
    except ValueError:
        rel_source = Path(source_path.name)
    logger.info(
        "extract_artifacts: relative source path for links: %s", rel_source,
    )

    # --- action items -> tasks ------------------------------------------
    for idx, item in enumerate(action_items, start=1):
        domain = _detect_domain(item["text"])
        logger.info(
            "extract_artifacts: action item %d -> domain '%s'", idx, domain,
        )
        written_path = _write_task_artifact(
            item["text"], domain, rel_source, idx,
        )
        artifacts.append({
            "type": "task",
            "domain": domain,
            "filename": written_path.name,
        })

    # --- decisions -> decisions.md --------------------------------------
    for idx, decision_text in enumerate(decisions, start=1):
        domain = _detect_domain(decision_text)
        logger.info(
            "extract_artifacts: decision %d -> domain '%s'", idx, domain,
        )
        _append_decision(decision_text, domain, rel_source)
        artifacts.append({
            "type": "decision",
            "domain": domain,
            "filename": "decisions.md",
        })

    # --- ideas -> ideas -------------------------------------------------
    for idx, idea_text in enumerate(ideas, start=1):
        domain = _detect_domain(idea_text)
        logger.info(
            "extract_artifacts: idea %d -> domain '%s'", idx, domain,
        )
        written_path = _write_idea_artifact(
            idea_text, domain, rel_source, idx,
        )
        artifacts.append({
            "type": "idea",
            "domain": domain,
            "filename": written_path.name,
        })

    logger.info(
        "extract_artifacts: done — %d artifacts extracted from %s",
        len(artifacts),
        source_path.name,
    )

    return {
        "source": rel_source.as_posix(),
        "artifacts": artifacts,
    }


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

_ACTION_ITEMS_HEADER = re.compile(
    r"^##\s*Action\s*Items", re.IGNORECASE | re.MULTILINE,
)

_DECISIONS_HEADER = re.compile(
    r"^##\s*(?:Решения|Decisions)", re.IGNORECASE | re.MULTILINE,
)

_IDEAS_HEADER = re.compile(
    r"^##\s*(?:Идеи|Ideas)", re.IGNORECASE | re.MULTILINE,
)

_CHECKBOX_RE = re.compile(r"^\s*-\s*\[\s*\]\s*(.+)", re.MULTILINE)

_ASSIGNEE_RE = re.compile(r"@(\S+)")

_NEXT_SECTION = re.compile(r"^##\s", re.MULTILINE)


def _get_section(body: str, header_re: re.Pattern) -> str | None:
    """Return the text of a section (from header to next ## or EOF)."""
    match = header_re.search(body)
    if match is None:
        return None
    start = match.end()
    next_header = _NEXT_SECTION.search(body, start)
    if next_header is not None:
        return body[start:next_header.start()]
    return body[start:]


def _extract_action_items(body: str) -> list[dict]:
    """Extract action items from ``## Action Items`` section.

    Returns list of ``{"text": str, "assignee": str}`` dicts.
    """
    logger.info("_extract_action_items: searching for Action Items section")

    section = _get_section(body, _ACTION_ITEMS_HEADER)
    if section is None:
        logger.info("_extract_action_items: no Action Items section found")
        return []

    items: list[dict] = []
    for m in _CHECKBOX_RE.finditer(section):
        raw_text = m.group(1).strip()
        assignee_match = _ASSIGNEE_RE.search(raw_text)
        assignee = assignee_match.group(1) if assignee_match else ""
        items.append({"text": raw_text, "assignee": assignee})
        logger.info(
            "_extract_action_items: found item '%s' (assignee='%s')",
            raw_text[:60],
            assignee,
        )

    logger.info("_extract_action_items: extracted %d items", len(items))
    return items


def _extract_decisions(body: str) -> list[str]:
    """Extract decisions from ``## Решения`` section.

    Returns list of decision strings (one per bullet/line).
    """
    logger.info("_extract_decisions: searching for Decisions section")

    section = _get_section(body, _DECISIONS_HEADER)
    if section is None:
        logger.info("_extract_decisions: no Decisions section found")
        return []

    decisions: list[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            decisions.append(stripped[2:].strip())
        elif stripped.startswith("* "):
            decisions.append(stripped[2:].strip())
        elif stripped and not stripped.startswith("#"):
            # Accept non-empty lines that aren't headers as decisions too
            # Only if the section exists and the line has meaningful content
            if len(stripped) > 3:
                decisions.append(stripped)

    # Filter out empty strings
    decisions = [d for d in decisions if d]

    logger.info("_extract_decisions: extracted %d decisions", len(decisions))
    return decisions


def _extract_ideas(body: str) -> list[str]:
    """Extract ideas from ``## Идеи`` section or inline idea mentions."""
    logger.info("_extract_ideas: searching for Ideas section")

    ideas: list[str] = []

    section = _get_section(body, _IDEAS_HEADER)
    if section is not None:
        for line in section.splitlines():
            stripped = line.strip()
            if stripped.startswith("- "):
                ideas.append(stripped[2:].strip())
            elif stripped.startswith("* "):
                ideas.append(stripped[2:].strip())

    # Filter out empty strings
    ideas = [i for i in ideas if i]

    logger.info("_extract_ideas: extracted %d ideas", len(ideas))
    return ideas


# ---------------------------------------------------------------------------
# Domain detection
# ---------------------------------------------------------------------------


def _detect_domain(text: str) -> str:
    """Determine the domain for an artifact based on keyword matching."""
    lower = text.lower()
    keyword_map = _merged_keyword_map()

    for domain, keywords in keyword_map.items():
        for kw in keywords:
            if kw.lower() in lower:
                logger.info(
                    "_detect_domain: matched keyword '%s' -> domain '%s'",
                    kw, domain,
                )
                return domain

    logger.info(
        "_detect_domain: no keyword match, defaulting to '%s'", _DEFAULT_DOMAIN
    )
    return _DEFAULT_DOMAIN


# ---------------------------------------------------------------------------
# Source type detection
# ---------------------------------------------------------------------------


def _detect_source_type(source_path: Path) -> str:
    """Determine if the source is a meeting or a daily-log from its path."""
    parts_lower = [p.lower() for p in source_path.parts]
    if "meetings" in parts_lower:
        return "meeting"
    if "daily-logs" in parts_lower:
        return "daily-log"
    return "unknown"


# ---------------------------------------------------------------------------
# Artifact writing
# ---------------------------------------------------------------------------

_TODAY = None  # allow override in tests


def _get_today() -> str:
    """Return today's date as YYYY-MM-DD string."""
    if _TODAY is not None:
        return _TODAY
    return date.today().isoformat()


def _write_task_artifact(
    text: str,
    domain: str,
    source_rel: Path,
    seq: int,
) -> Path:
    """Write an action-item as a task file under the domain's tasks/ dir."""
    today = _get_today()
    filename = f"{today}-action-{seq:02d}.md"
    tasks_dir = vault_paths.wiki_domain_dir(domain, "tasks")
    filepath = tasks_dir / filename

    logger.info(
        "_write_task_artifact: writing task to %s", filepath,
    )

    source_posix = Path(source_rel).as_posix()
    content = (
        f"---\n"
        f"tags: [action-item]\n"
        f"date: {today}\n"
        f"status: inbox\n"
        f"domain: {domain}\n"
        f'source: "[[{source_posix}]]"\n'
        f"type: Task\n"
        f"---\n\n"
        f"# {text}\n"
    )

    atomic_write(filepath, content)
    logger.info("_write_task_artifact: wrote %s", filepath.name)
    return filepath


def _append_decision(
    text: str,
    domain: str,
    source_rel: Path,
) -> None:
    """Append a decision to the domain's decisions.md file."""
    today = _get_today()
    domain_dir = vault_paths.VAULT_PATH / "wiki" / "domains" / domain
    domain_dir.mkdir(parents=True, exist_ok=True)
    decisions_path = domain_dir / "decisions.md"

    logger.info(
        "_append_decision: appending to %s", decisions_path,
    )

    if not decisions_path.exists():
        logger.info(
            "_append_decision: decisions.md does not exist for domain '%s', creating",
            domain,
        )
        header = f"# Решения — {domain}\n\n"
        decisions_path.write_text(header, encoding="utf-8")

    source_posix = Path(source_rel).as_posix()
    entry = (
        f"### [{today}] {text}\n\n"
        f"Источник: [[{source_posix}]]\n\n"
        f"---\n\n"
    )

    existing = decisions_path.read_text(encoding="utf-8")
    decisions_path.write_text(existing + entry, encoding="utf-8")

    logger.info("_append_decision: appended decision to %s", decisions_path.name)


def _write_idea_artifact(
    text: str,
    domain: str,
    source_rel: Path,
    seq: int,
) -> Path:
    """Write an idea as a file under the domain's ideas/ dir."""
    today = _get_today()
    filename = f"{today}-extracted-{seq:02d}.md"
    ideas_dir = vault_paths.wiki_domain_dir(domain, "ideas")
    filepath = ideas_dir / filename

    logger.info(
        "_write_idea_artifact: writing idea to %s", filepath,
    )

    source_posix = Path(source_rel).as_posix()
    content = (
        f"---\n"
        f"tags: [idea, extracted]\n"
        f"date: {today}\n"
        f"status: inbox\n"
        f"domain: {domain}\n"
        f'source: "[[{source_posix}]]"\n'
        f"type: Idea\n"
        f"---\n\n"
        f"# {text}\n"
    )

    atomic_write(filepath, content)
    logger.info("_write_idea_artifact: wrote %s", filepath.name)
    return filepath


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    if len(sys.argv) < 2:
        print("Usage: python -m app.artifact_extractor <path-to-source.md>")
        sys.exit(1)

    path = Path(sys.argv[1])
    result = extract_artifacts(path)
    print(json.dumps(result, indent=2, ensure_ascii=False))
