"""Waterfall context assembler from llm_wiki/ digests.

Assembles context for LLM prompts in three layers:
1. ONE-LINERS  — compact summaries from _index.md (budget: 3000 tokens)
2. CORE-DIGESTS — core_digest sections from digest files (budget: 10000 tokens)
3. EXTENDED-DIGESTS — extended_digest sections for focus artifacts (budget: 6000 tokens)

Controlled by DIGEST_CONTEXT_SOURCE env:
  "wiki"     (default) — kill switch, returns empty context with fallback_used=True
  "auto"     — llm_wiki/ with fallback to wiki/ when digest is missing
  "llm_wiki" — llm_wiki/ only, no fallback
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ONE_LINER_BUDGET = 3000
CORE_DIGEST_BUDGET = 10000
EXTENDED_DIGEST_BUDGET = 6000

_TIER_PRIORITY = {"core": 0, "active": 1, "warm": 2, "cold": 3, "archive": 4}

# ---------------------------------------------------------------------------
# tiktoken lazy-init (mirrors knowledge-engine/app/digest/token_counter.py)
# ---------------------------------------------------------------------------

_encoder = None


def _get_encoder():
    global _encoder
    if _encoder is None:
        import tiktoken

        logger.info("context_assembler: initializing tiktoken cl100k_base encoder")
        _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder


def _count_tokens(text: str) -> int:
    """Count tokens using tiktoken cl100k_base."""
    if not text:
        return 0
    return len(_get_encoder().encode(text))


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class AssembledContext:
    one_liners: str = ""
    core_digests: str = ""
    extended_digests: str = ""
    total_tokens: int = 0
    sources_used: list = field(default_factory=list)
    fallback_used: bool = False


# ---------------------------------------------------------------------------
# Index loader
# ---------------------------------------------------------------------------


def _load_index(vault_path: str) -> list[dict]:
    """Parse llm_wiki/_index.md Markdown table into list of dicts.

    Expected columns: ID | Type | Domain | Tier | Relevance | One-liner | Updated
    """
    index_path = Path(vault_path) / "llm_wiki" / "_index.md"

    if not index_path.exists():
        logger.warning(f"_load_index: _index.md not found at {index_path}")
        return []

    logger.info(f"_load_index: loading index from {index_path}")

    text = index_path.read_text(encoding="utf-8")
    lines = text.strip().splitlines()

    entries: list[dict] = []
    header_found = False
    column_keys = []

    # Canonical column name mapping (lowercase-stripped header -> dict key)
    _COL_MAP = {
        "id": "id",
        "type": "type",
        "domain": "domain",
        "tier": "tier",
        "relevance": "relevance",
        "one-liner": "one_liner",
        "one_liner": "one_liner",
        "updated": "updated",
    }

    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue

        cells = [c.strip() for c in stripped.split("|")]
        # split on | gives empty strings at start/end: ['', 'a', 'b', '']
        cells = [c for c in cells if c or c == ""]
        # Remove empty edge cells produced by leading/trailing |
        if cells and cells[0] == "":
            cells = cells[1:]
        if cells and cells[-1] == "":
            cells = cells[:-1]

        if not cells:
            continue

        # Detect header row
        if not header_found:
            column_keys = [_COL_MAP.get(c.strip().lower(), c.strip().lower()) for c in cells]
            header_found = True
            continue

        # Skip separator row (e.g., |---|---|...)
        if all(set(c.strip()) <= {"-", ":"} for c in cells):
            continue

        # Data row
        entry: dict = {}
        for i, key in enumerate(column_keys):
            entry[key] = cells[i].strip() if i < len(cells) else ""
        entries.append(entry)

    logger.info(f"_load_index: loaded {len(entries)} entries")
    return entries


# ---------------------------------------------------------------------------
# Relevance filter
# ---------------------------------------------------------------------------


def _select_relevant(
    entries: list[dict],
    query: str,
    domain: str,
    focus_artifacts: list | None,
) -> list[dict]:
    """Filter entries for core-digest loading.

    Rules:
    - tier must be in {active, warm, core}
    - if domain is set: also filter by domain match OR type in {decision, meeting}
    - focus_artifacts IDs are always included regardless of tier
    """
    focus_ids = set(focus_artifacts) if focus_artifacts else set()
    allowed_tiers = {"active", "warm", "core"}

    result = []
    for entry in entries:
        entry_id = entry.get("id", "")
        tier = entry.get("tier", "").lower()
        entry_domain = entry.get("domain", "").lower()
        entry_type = entry.get("type", "").lower()

        # Focus artifacts bypass tier filter
        if entry_id in focus_ids:
            result.append(entry)
            continue

        # Tier filter
        if tier not in allowed_tiers:
            continue

        # Domain filter
        if domain:
            if entry_domain != domain.lower() and entry_type not in {"decision", "meeting"}:
                continue

        result.append(entry)

    logger.info(
        f"_select_relevant: {len(result)} entries selected from {len(entries)} "
        f"(domain={domain!r}, focus={len(focus_ids)})"
    )
    return result


# ---------------------------------------------------------------------------
# Digest section loader
# ---------------------------------------------------------------------------


def _load_digest_section(digest_path: str | Path, section_header: str) -> str:
    """Load a specific section from a digest file.

    Reads the file, finds *section_header* (e.g. '## core_digest'),
    and returns everything until the next '## ' heading or EOF.
    Returns '' if the file does not exist or the section is not found.
    """
    p = Path(digest_path)
    if not p.exists():
        logger.debug(f"_load_digest_section: file not found {p}")
        return ""

    text = p.read_text(encoding="utf-8")
    lines = text.splitlines()

    collecting = False
    section_lines: list[str] = []
    header_lower = section_header.lower().strip()

    for line in lines:
        stripped = line.strip().lower()
        if stripped == header_lower:
            collecting = True
            continue
        if collecting:
            # Stop at next h2 heading
            if stripped.startswith("## "):
                break
            section_lines.append(line)

    result = "\n".join(section_lines).strip()
    if not result:
        logger.debug(f"_load_digest_section: section {section_header!r} empty or not found in {p}")
    return result


# ---------------------------------------------------------------------------
# Digest path resolution
# ---------------------------------------------------------------------------


def _digest_path_for_entry(vault_path: str, entry: dict) -> Path:
    """Resolve the digest file path for an index entry.

    Digest files live at: llm_wiki/domains/<domain>/<type>/<id>.md
    or llm_wiki/<type>/<id>.md for domain-less entries like meetings.
    """
    domain = entry.get("domain", "").strip()
    entry_type = entry.get("type", "").strip()
    entry_id = entry.get("id", "").strip()

    base = Path(vault_path) / "llm_wiki"

    if domain:
        return base / "domains" / domain / _pluralize_type(entry_type) / f"{entry_id}.md"
    else:
        return base / _pluralize_type(entry_type) / f"{entry_id}.md"


def _wiki_fallback_path(vault_path: str, entry: dict) -> Path:
    """Resolve the wiki/ fallback path for an entry (used when digest is missing)."""
    domain = entry.get("domain", "").strip()
    entry_type = entry.get("type", "").strip()
    entry_id = entry.get("id", "").strip()

    base = Path(vault_path) / "wiki"

    if domain:
        return base / "domains" / domain / _pluralize_type(entry_type) / f"{entry_id}.md"
    else:
        return base / _pluralize_type(entry_type) / f"{entry_id}.md"


def _pluralize_type(artifact_type: str) -> str:
    """Convert artifact type to directory name (pluralized)."""
    _PLURAL_MAP = {
        "idea": "ideas",
        "prd": "prds",
        "epic": "epics",
        "userstory": "userstories",
        "task": "tasks",
        "bug": "bugs",
        "knowledge": "knowledge",
        "decision": "knowledge",
        "meeting": "meetings",
        "daily-log": "daily-logs",
        "report": "reports",
    }
    return _PLURAL_MAP.get(artifact_type.lower(), f"{artifact_type}s")


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------


def assemble_context(
    query: str,
    domain: str = "",
    focus_artifacts: list | None = None,
    max_tokens: int = 19000,
) -> AssembledContext:
    """Waterfall context assembly from llm_wiki/ digests.

    Steps:
      0. Kill switch check (DIGEST_CONTEXT_SOURCE)
      1. ONE-LINERS from _index.md (budget: ONE_LINER_BUDGET)
      2. CORE-DIGESTS from digest files (budget: CORE_DIGEST_BUDGET)
      3. EXTENDED-DIGESTS for focus_artifacts (budget: EXTENDED_DIGEST_BUDGET)
      4. TOUCH accessed artifacts (core + extended, NOT one-liners)
    """
    logger.info(
        f"assemble_context: query={query!r}, domain={domain}, max_tokens={max_tokens}"
    )

    # -----------------------------------------------------------------------
    # Step 0: Kill switch
    # -----------------------------------------------------------------------
    context_source = os.getenv("DIGEST_CONTEXT_SOURCE", "wiki").lower().strip()

    if context_source == "wiki":
        logger.info("assemble_context: DIGEST_CONTEXT_SOURCE=wiki, returning empty (kill switch)")
        return AssembledContext(fallback_used=True)

    vault_path = os.getenv("VAULT_PATH", "/vault")

    # -----------------------------------------------------------------------
    # Step 1: ONE-LINERS
    # -----------------------------------------------------------------------
    all_entries = _load_index(vault_path)

    # Sort by tier priority
    all_entries.sort(key=lambda e: _TIER_PRIORITY.get(e.get("tier", "").lower(), 99))

    one_liner_lines: list[str] = []
    one_liner_tokens = 0
    one_liner_entries: list[dict] = []

    for entry in all_entries:
        entry_id = entry.get("id", "")
        one_liner = entry.get("one_liner", "")
        if not one_liner:
            continue

        line = f"- [{entry_id}] {one_liner}\n"
        line_tokens = _count_tokens(line)

        if one_liner_tokens + line_tokens > ONE_LINER_BUDGET:
            # Try trimming: drop archive first, then cold
            tier = entry.get("tier", "").lower()
            if tier in {"archive", "cold"}:
                continue
            # Over budget for non-archive/cold — stop
            if one_liner_tokens + line_tokens > ONE_LINER_BUDGET:
                break

        one_liner_lines.append(line)
        one_liner_tokens += line_tokens
        one_liner_entries.append(entry)

    one_liners_text = "".join(one_liner_lines)

    # -----------------------------------------------------------------------
    # Step 2: CORE-DIGESTS
    # -----------------------------------------------------------------------
    relevant = _select_relevant(all_entries, query, domain, focus_artifacts)

    core_parts: list[str] = []
    core_tokens = 0
    core_entries: list[dict] = []
    sources_used: list[str] = []
    fallback_used = False
    touched_filepaths: list[str] = []

    focus_ids = set(focus_artifacts) if focus_artifacts else set()

    for entry in relevant:
        entry_id = entry.get("id", "")
        tier = entry.get("tier", "").lower()

        # AC-13: cold/archive excluded from core-digests
        # (focus_artifacts bypass this — they go to extended-digests instead)
        if tier in {"cold", "archive"} and entry_id not in focus_ids:
            continue

        digest_path = _digest_path_for_entry(vault_path, entry)
        section_text = _load_digest_section(digest_path, "## core_digest")

        # Fallback logic
        if not section_text and context_source == "auto":
            wiki_path = _wiki_fallback_path(vault_path, entry)
            if wiki_path.exists():
                logger.warning(
                    f"assemble_context: digest not found for {entry_id}, falling back to wiki/"
                )
                raw_text = wiki_path.read_text(encoding="utf-8")
                # Truncate to 500 tokens
                encoder = _get_encoder()
                tokens = encoder.encode(raw_text)
                if len(tokens) > 500:
                    section_text = encoder.decode(tokens[:500])
                else:
                    section_text = raw_text
                fallback_used = True

        if not section_text:
            continue

        block = f"### {entry_id}\n{section_text}\n\n"
        block_tokens = _count_tokens(block)

        if core_tokens + block_tokens > CORE_DIGEST_BUDGET:
            break

        core_parts.append(block)
        core_tokens += block_tokens
        core_entries.append(entry)
        sources_used.append(entry_id)

        # Record filepath for touch (Step 4)
        filepath = str(digest_path.relative_to(Path(vault_path)))
        touched_filepaths.append(filepath)

    core_digests_text = "".join(core_parts)

    # -----------------------------------------------------------------------
    # Step 3: EXTENDED-DIGESTS
    # -----------------------------------------------------------------------
    extended_parts: list[str] = []
    extended_tokens = 0

    if focus_artifacts:
        # Limit to max 3 focus artifacts
        focus_list = focus_artifacts[:3]

        for focus_id in focus_list:
            # Find entry in index
            entry = next((e for e in all_entries if e.get("id") == focus_id), {})
            if not entry:
                logger.debug(f"assemble_context: focus artifact {focus_id} not found in index")
                continue

            digest_path = _digest_path_for_entry(vault_path, entry)
            section_text = _load_digest_section(digest_path, "## extended_digest")

            if not section_text:
                continue

            block = f"### {focus_id}\n{section_text}\n\n"
            block_tokens = _count_tokens(block)

            if extended_tokens + block_tokens > EXTENDED_DIGEST_BUDGET:
                break

            extended_parts.append(block)
            extended_tokens += block_tokens

            if focus_id not in sources_used:
                sources_used.append(focus_id)

            # Record for touch
            filepath = str(digest_path.relative_to(Path(vault_path)))
            if filepath not in touched_filepaths:
                touched_filepaths.append(filepath)

    extended_digests_text = "".join(extended_parts)

    # -----------------------------------------------------------------------
    # Step 4: TOUCH (AC-14: NOT for one-liners)
    # -----------------------------------------------------------------------
    for filepath in touched_filepaths:
        try:
            from app import ke_client

            logger.debug(f"assemble_context: touch {filepath}")
            ke_client.touch(filepath)
        except Exception as exc:
            logger.warning(f"assemble_context: touch failed for {filepath}: {exc}")

    # -----------------------------------------------------------------------
    # Result
    # -----------------------------------------------------------------------
    total_tokens = one_liner_tokens + core_tokens + extended_tokens

    logger.info(
        f"assemble_context: done, one_liners={len(one_liner_entries)}, "
        f"core_digests={len(core_entries)}, total_tokens={total_tokens}"
    )

    return AssembledContext(
        one_liners=one_liners_text,
        core_digests=core_digests_text,
        extended_digests=extended_digests_text,
        total_tokens=total_tokens,
        sources_used=sources_used,
        fallback_used=fallback_used,
    )


# ---------------------------------------------------------------------------
# Creative recall enrichment
# ---------------------------------------------------------------------------


def _infer_type_from_filepath(filepath: str) -> str:
    """Infer artifact type from filepath directory component.

    E.g. 'wiki/domains/general/ideas/my-idea.md' -> 'idea'
    """
    parts = filepath.replace("\\", "/").split("/")
    _DIR_TYPE_MAP = {
        "ideas": "idea",
        "tasks": "task",
        "epics": "epic",
        "bugs": "bug",
        "knowledge": "knowledge",
        "prds": "prd",
        "userstories": "userstory",
        "meetings": "meeting",
        "daily-logs": "daily-log",
        "reports": "report",
    }
    for part in parts:
        if part in _DIR_TYPE_MAP:
            return _DIR_TYPE_MAP[part]
    return "idea"


def enrich_creative_recall(creative_results: list[dict]) -> list[dict]:
    """Enrich creative recall results with one-liners from llm_wiki/.

    For each artifact returned by get_creative():
    - Try to find its digest in llm_wiki/ and extract one_liner
    - If no digest: use title from the original result
    - touch() is NOT called (creative recall must not reset decay)
    """
    logger.info(f"enrich_creative_recall: enriching {len(creative_results)} items")

    vault_path = os.getenv("VAULT_PATH", "/vault")
    enriched = []

    for item in creative_results:
        enriched_item = dict(item)  # copy

        title = item.get("title", "")
        domain = item.get("domain", "")
        artifact_id = item.get("id", "")
        filepath = item.get("filepath", "")

        # Infer artifact type from filepath (get_creative returns ideas/tasks)
        artifact_type = _infer_type_from_filepath(filepath) if filepath else "idea"

        # Build digest path using existing _digest_path_for_entry()
        entry = {"domain": domain, "type": artifact_type, "id": artifact_id}
        digest_path = _digest_path_for_entry(vault_path, entry)

        one_liner = ""
        if digest_path.exists():
            try:
                one_liner = _load_digest_section(digest_path, "## one_liner").strip()
                if one_liner:
                    logger.debug(f"enrich_creative_recall: found one_liner for {title}")
            except Exception as exc:
                logger.debug(f"enrich_creative_recall: failed to read digest for {title}: {exc}")

        enriched_item["one_liner"] = one_liner if one_liner else title
        enriched.append(enriched_item)

    digests_found = sum(1 for e in enriched if e.get("one_liner") != e.get("title", ""))
    logger.info(f"enrich_creative_recall: enriched {len(enriched)} items, {digests_found} with digests")
    return enriched
