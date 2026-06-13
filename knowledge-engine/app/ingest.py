"""Ingest processor for web clippings from raw/inbound/clippings/.

Reads clipping files created by Obsidian Web Clipper, detects domain,
and creates structured knowledge files in wiki/.
"""

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from . import vault_paths
from .domain_manager import append_domain_log, update_domain_index
from .file_writer import atomic_write, locked_append
from .frontmatter_utils import read_frontmatter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tag-to-domain mapping (fallback, primary source is domain-config.yaml)
# ---------------------------------------------------------------------------

TAG_TO_DOMAIN: dict[str, str] = {
    # static-metadata
    "static": "static-metadata",
    "dictionary": "static-metadata",
    "catalog": "static-metadata",
    "reference": "static-metadata",
    "metadata": "static-metadata",
    "property": "static-metadata",
    "amenities": "static-metadata",
    "rules": "static-metadata",
    "beds": "static-metadata",
    "types": "static-metadata",
    # suggester
    "suggester": "suggester",
    "typeahead": "suggester",
    "autocomplete": "suggester",
    # search-engine
    "search": "search-engine",
    "search-engine": "search-engine",
    "ranking": "search-engine",
    "indexing": "search-engine",
    # partner-search-engine
    "partner": "partner-search-engine",
    "partner_search": "partner-search-engine",
    "b2b": "partner-search-engine",
    "supplier": "partner-search-engine",
    "affiliate": "partner-search-engine",
    # general
    "general": "general",
}

# Tags that are ignored during domain detection
IGNORED_TAGS: frozenset[str] = frozenset({"clippings", "clipping"})

# Priority for tag-based domain resolution (Step 1).
# B2B tag is an explicit domain marker, so partner-search-engine wins over static.
TAG_PRIORITY: dict[str, int] = {
    "partner-search-engine": 100,
    "static-metadata": 80,
    "search-engine": 70,
    "suggester": 50,
    "general": 10,
}

# Priority for keyword-based domain resolution (Step 2).
# Content keywords are indirect — static/search are more specific than b2b mentions.
KEYWORD_PRIORITY: dict[str, int] = {
    "static-metadata": 100,
    "search-engine": 80,
    "suggester": 60,
    "partner-search-engine": 40,
    "general": 10,
}


# ---------------------------------------------------------------------------
# Keyword-to-domain mapping (content scan)
# ---------------------------------------------------------------------------

KEYWORD_TO_DOMAIN: dict[str, str] = {
    # static-metadata
    "справочник": "static-metadata",
    "классификатор": "static-metadata",
    "атрибут": "static-metadata",
    "enum": "static-metadata",
    "словарь": "static-metadata",
    "статика": "static-metadata",
    "карточка объекта": "static-metadata",
    "amenities": "static-metadata",
    "property type": "static-metadata",
    # suggester
    "подсказчик": "suggester",
    "автокомплит": "suggester",
    "подсказка": "suggester",
    "typeahead": "suggester",
    "префикс": "suggester",
    "по мере ввода": "suggester",
    # search-engine
    "поиск": "search-engine",
    "релевантность": "search-engine",
    "индексация": "search-engine",
    "fulltext": "search-engine",
    "фильтрация": "search-engine",
    "ранжирование": "search-engine",
    "выдача": "search-engine",
    "getresults": "search-engine",
    "searchoffers": "search-engine",
    # partner-search-engine
    "партнёр": "partner-search-engine",
    "поставщик": "partner-search-engine",
    "b2b": "partner-search-engine",
    "supplier": "partner-search-engine",
    "подключение партнёра": "partner-search-engine",
    "аффилиат": "partner-search-engine",
}


# ---------------------------------------------------------------------------
# YAML quoting helper
# ---------------------------------------------------------------------------

_YAML_SPECIAL_CHARS = set(':#[]{}"\',')


def _yaml_quote(value: str) -> str:
    """Quote a YAML value if it contains special characters.

    Args:
        value: The string to potentially quote.

    Returns:
        Quoted string if special chars present, otherwise unchanged.
    """
    logger.debug("_yaml_quote: quoting value of length %d", len(value) if value else 0)
    if not value:
        return '""'
    if any(ch in value for ch in _YAML_SPECIAL_CHARS):
        escaped = value.replace('"', '\\"')
        return f'"{escaped}"'
    return value


# ---------------------------------------------------------------------------
# Merged tag map: hardcoded + domain-config.yaml
# ---------------------------------------------------------------------------

def _merged_tag_map() -> dict[str, str]:
    """Merge hardcoded TAG_TO_DOMAIN with domain-config.yaml tags.

    Priority: domain-config.yaml > hardcoded.
    Handles ImportError/AttributeError gracefully with fallback.

    Returns:
        Merged tag-to-domain mapping dict.
    """
    logger.info("_merged_tag_map: building merged tag map")
    result = dict(TAG_TO_DOMAIN)

    try:
        from .domain_config import build_tag_map
        config_tags = build_tag_map()
        if config_tags:
            result.update(config_tags)
            logger.info(
                "_merged_tag_map: overlayed %d tags from domain-config.yaml",
                len(config_tags),
            )
    except (ImportError, AttributeError) as exc:
        logger.warning(
            "_merged_tag_map: could not load build_tag_map from domain_config, "
            "using hardcoded TAG_TO_DOMAIN only: %s",
            exc,
        )
    except Exception as exc:
        logger.warning(
            "_merged_tag_map: unexpected error loading config tags, "
            "using hardcoded TAG_TO_DOMAIN only: %s",
            exc,
        )

    logger.info("_merged_tag_map: total %d entries in merged map", len(result))
    return result


# ---------------------------------------------------------------------------
# Merged keyword map: hardcoded + domain-config.yaml
# ---------------------------------------------------------------------------

def _merged_keyword_map() -> dict[str, str]:
    """Merge hardcoded KEYWORD_TO_DOMAIN with domain-config.yaml keywords."""
    logger.info("_merged_keyword_map: building merged keyword map")
    result = dict(KEYWORD_TO_DOMAIN)

    try:
        from .domain_config import build_keyword_map
        config_keywords = build_keyword_map()
        if config_keywords:
            result.update(config_keywords)
            logger.info(
                "_merged_keyword_map: overlayed %d keywords from domain-config.yaml",
                len(config_keywords),
            )
    except (ImportError, AttributeError) as exc:
        logger.warning(
            "_merged_keyword_map: could not load build_keyword_map from domain_config, "
            "using hardcoded KEYWORD_TO_DOMAIN only: %s",
            exc,
        )
    except Exception as exc:
        logger.warning(
            "_merged_keyword_map: unexpected error loading config keywords, "
            "using hardcoded KEYWORD_TO_DOMAIN only: %s",
            exc,
        )

    logger.info("_merged_keyword_map: total %d entries in merged map", len(result))
    return result


# ---------------------------------------------------------------------------
# Domain detection (3-step algorithm)
# ---------------------------------------------------------------------------

def detect_domain(metadata: dict, body: str) -> tuple[str, str]:
    """Detect domain for a clipping based on tags and content.

    Three-step algorithm:
    1. Tag matching against merged tag map
    2. Content keyword matching
    3. Fallback to "none" (routes to concepts/)

    Args:
        metadata: Parsed YAML frontmatter dict.
        body: File body content (Markdown).

    Returns:
        Tuple of (domain, detection_method):
        - domain: detected domain slug or "none"
        - detection_method: "tag", "keyword", or "none"
    """
    logger.info("detect_domain: starting domain detection")

    # Step 1: Tag matching
    tags = metadata.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]
    logger.info("detect_domain: found %d tags in metadata", len(tags))

    tag_map = _merged_tag_map()
    matched_domains: list[tuple[str, str]] = []  # (domain, matched_tag)

    for tag in tags:
        tag_lower = tag.strip().lower()

        # Skip service tags
        if tag_lower in IGNORED_TAGS:
            logger.debug("detect_domain: ignoring service tag: %s", tag)
            continue

        if tag_lower in tag_map:
            matched_domains.append((tag_map[tag_lower], tag))
            logger.debug("detect_domain: tag %r matched domain %r", tag, tag_map[tag_lower])

    # Step 2: Content keyword matching (only if Step 1 gave no results)
    if not matched_domains:
        logger.info("detect_domain: no tag matches, trying keyword matching")
        keyword_map = _merged_keyword_map()
        body_lower = body.lower()
        seen_domains: set[str] = set()
        for keyword, domain in keyword_map.items():
            if domain in seen_domains:
                continue
            if keyword.lower() in body_lower:
                matched_domains.append((domain, f"keyword:{keyword}"))
                seen_domains.add(domain)
                logger.info("detect_domain: keyword %r matched domain %r", keyword, domain)

    # Step 3: Fallback
    if not matched_domains:
        logger.info("detect_domain: no match found, routing to concepts/")
        return ("none", "none")

    # If multiple domains matched -- use highest priority
    if len(matched_domains) > 1:
        domains_str = ", ".join(f"{d}({t})" for d, t in matched_domains)
        # Pick priority dict based on match source (tag vs keyword)
        is_keyword = matched_domains[0][1].startswith("keyword:")
        priority = KEYWORD_PRIORITY if is_keyword else TAG_PRIORITY
        matched_domains.sort(
            key=lambda dm: priority.get(dm[0], 0),
            reverse=True,
        )
        logger.warning(
            "detect_domain: multiple domains matched: %s -- using highest %s priority: %s",
            domains_str, "keyword" if is_keyword else "tag", matched_domains[0][0],
        )

    domain, match_source = matched_domains[0]
    method = "tag" if not match_source.startswith("keyword:") else "keyword"
    logger.info("detect_domain: matched domain=%s via %s", domain, match_source)
    return (domain, method)


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------

def generate_knowledge_id(domain: str, knowledge_dir: Path) -> str:
    """Generate sequential K-<DOMAIN>-<NUM> ID.

    Scans existing files in knowledge_dir for the highest existing number.

    Args:
        domain: Domain slug (e.g. "static-metadata").
        knowledge_dir: Path to the knowledge directory.

    Returns:
        New ID string (e.g. "K-STATIC-METADATA-0001").
    """
    logger.info("generate_knowledge_id: generating ID for domain=%s in %s", domain, knowledge_dir)
    prefix = f"K-{domain.upper()}-"
    max_num = 0

    if knowledge_dir.exists():
        for f in knowledge_dir.glob("K-*.md"):
            match = re.match(r"K-[A-Z\-]+-(\d+)", f.stem)
            if match:
                num = int(match.group(1))
                if num > max_num:
                    max_num = num
                    logger.debug("generate_knowledge_id: found existing ID with num=%d: %s", num, f.name)

    new_num = max_num + 1
    new_id = f"{prefix}{new_num:04d}"
    logger.info("generate_knowledge_id: generated ID=%s (max_existing=%d)", new_id, max_num)
    return new_id


def generate_concept_id(concepts_dir: Path) -> str:
    """Generate sequential C-<NUM> ID for concept files.

    Scans existing files in concepts_dir for the highest existing number.

    Args:
        concepts_dir: Path to the concepts directory.

    Returns:
        New ID string (e.g. "C-0001").
    """
    logger.info("generate_concept_id: generating ID in %s", concepts_dir)
    max_num = 0

    if concepts_dir.exists():
        for f in concepts_dir.glob("C-*.md"):
            match = re.match(r"C-(\d+)", f.stem)
            if match:
                num = int(match.group(1))
                if num > max_num:
                    max_num = num
                    logger.debug("generate_concept_id: found existing ID with num=%d: %s", num, f.name)

    new_num = max_num + 1
    new_id = f"C-{new_num:04d}"
    logger.info("generate_concept_id: generated ID=%s (max_existing=%d)", new_id, max_num)
    return new_id


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def is_already_ingested(source_file_rel: str, vault_root: Path) -> bool:
    """Check if a raw file has already been ingested.

    Scans wiki/domains/*/knowledge/ and wiki/concepts/ for files
    with source_file == source_file_rel.

    Args:
        source_file_rel: Relative path from vault root
            (e.g. "raw/inbound/clippings/file.md").
        vault_root: Vault root path.

    Returns:
        True if already ingested.
    """
    logger.info("is_already_ingested: checking source_file_rel=%r", source_file_rel)

    # Scan domain knowledge dirs
    domains_dir = vault_root / "wiki" / "domains"
    if domains_dir.exists():
        for domain_dir in domains_dir.iterdir():
            if not domain_dir.is_dir():
                continue
            knowledge_dir = domain_dir / "knowledge"
            if not knowledge_dir.exists():
                continue
            for md_file in knowledge_dir.glob("*.md"):
                try:
                    metadata, _ = read_frontmatter(md_file)
                    if metadata.get("source_file") == source_file_rel:
                        logger.info(
                            "is_already_ingested: found duplicate in %s", md_file,
                        )
                        return True
                except Exception:
                    continue

    # Scan concepts
    concepts_dir = vault_root / "wiki" / "concepts"
    if concepts_dir.exists():
        for md_file in concepts_dir.glob("*.md"):
            try:
                metadata, _ = read_frontmatter(md_file)
                if metadata.get("source_file") == source_file_rel:
                    logger.info(
                        "is_already_ingested: found duplicate in %s", md_file,
                    )
                    return True
            except Exception:
                continue

    logger.info("is_already_ingested: not found, source_file_rel=%r is new", source_file_rel)
    return False


def _collect_ingested_sources(vault_root: Path) -> set[str]:
    """Build set of all source_file values from existing wiki knowledge files.

    Single pass optimization for batch processing.

    Args:
        vault_root: Vault root path.

    Returns:
        Set of source_file relative paths already ingested.
    """
    logger.info("_collect_ingested_sources: scanning vault for existing source_file values")
    sources: set[str] = set()

    domains_dir = vault_root / "wiki" / "domains"
    if domains_dir.exists():
        for domain_dir in domains_dir.iterdir():
            if not domain_dir.is_dir():
                continue
            knowledge_dir = domain_dir / "knowledge"
            if not knowledge_dir.exists():
                continue
            for md_file in knowledge_dir.glob("*.md"):
                try:
                    metadata, _ = read_frontmatter(md_file)
                    sf = metadata.get("source_file", "")
                    if sf:
                        sources.add(sf)
                except Exception:
                    continue

    concepts_dir = vault_root / "wiki" / "concepts"
    if concepts_dir.exists():
        for md_file in concepts_dir.glob("*.md"):
            try:
                metadata, _ = read_frontmatter(md_file)
                sf = metadata.get("source_file", "")
                if sf:
                    sources.add(sf)
            except Exception:
                continue

    logger.info("_collect_ingested_sources: found %d already-ingested sources", len(sources))
    return sources


# ---------------------------------------------------------------------------
# Wiki content builder
# ---------------------------------------------------------------------------

def _build_wiki_content(
    file_id: str,
    domain: str,
    source_file_rel: str,
    metadata: dict,
    body: str,
) -> str:
    """Build wiki knowledge file content with frontmatter.

    Args:
        file_id: Generated ID (K-DOMAIN-NUM or C-NUM).
        domain: Detected domain or "none".
        source_file_rel: Relative path to source file from vault root.
        metadata: Original clipping frontmatter.
        body: Original clipping body.

    Returns:
        Complete Markdown string with YAML frontmatter.
    """
    logger.info("_build_wiki_content: building content for id=%s domain=%s", file_id, domain)

    title = metadata.get("title", "Untitled")
    source = metadata.get("source", "")
    author = metadata.get("author", "")
    created = metadata.get("created", "")

    # Normalize author (may be list or string)
    if isinstance(author, list):
        author = ", ".join(str(a) for a in author)
    logger.debug("_build_wiki_content: title=%r, author=%r, created=%r", title, author, created)

    # Assemble tags: original + knowledge + clipping
    original_tags = metadata.get("tags", [])
    if isinstance(original_tags, str):
        original_tags = [t.strip() for t in original_tags.split(",")]
    tags_set = set(original_tags)
    tags_set.add("knowledge")
    tags_set.add("clipping")
    # Remove "clippings" (plural) if present, keep "clipping" (singular)
    tags_set.discard("clippings")
    tags = sorted(tags_set)
    logger.info("_build_wiki_content: assembled %d tags", len(tags))

    ingested_at = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    # YAML frontmatter
    tags_yaml = "\n".join(f"  - {t}" for t in tags)

    frontmatter = (
        f"---\n"
        f"id: {file_id}\n"
        f"type: knowledge\n"
        f"domain: {domain}\n"
        f"title: {_yaml_quote(title)}\n"
        f"source: {_yaml_quote(source)}\n"
        f"source_file: {_yaml_quote(source_file_rel)}\n"
        f"author: {_yaml_quote(str(author))}\n"
        f"tags:\n{tags_yaml}\n"
        f"created: {created}\n"
        f'ingested_at: "{ingested_at}"\n'
        f"status: inbox\n"
        f"---\n"
    )

    # Body: heading + content
    heading = f"# {title}"
    content = f"{frontmatter}\n{heading}\n\n{body}\n"

    logger.info("_build_wiki_content: built content for %s (%d chars)", file_id, len(content))
    return content


# ---------------------------------------------------------------------------
# Knowledge scaffold for existing domains
# ---------------------------------------------------------------------------

def _ensure_knowledge_scaffold(domain: str) -> None:
    """Ensure knowledge/ directory has index.md and log.md.

    For existing domains that were created before knowledge/ was added
    to the artifact types, this ensures the scaffold files exist.

    Args:
        domain: Domain slug.
    """
    logger.info("_ensure_knowledge_scaffold: checking scaffold for domain=%s", domain)

    knowledge_dir = vault_paths.wiki_domain_dir(domain, "knowledge")
    index_path = knowledge_dir / "index.md"
    log_path = knowledge_dir / "log.md"

    if not index_path.exists():
        from .domain_manager import _index_content
        atomic_write(index_path, _index_content(domain, "knowledge"))
        logger.info("_ensure_knowledge_scaffold: created %s", index_path)
    else:
        logger.debug("_ensure_knowledge_scaffold: index.md already exists for domain=%s", domain)

    if not log_path.exists():
        from .domain_manager import _log_content
        atomic_write(log_path, _log_content(domain, "knowledge"))
        logger.info("_ensure_knowledge_scaffold: created %s", log_path)
    else:
        logger.debug("_ensure_knowledge_scaffold: log.md already exists for domain=%s", domain)


# ---------------------------------------------------------------------------
# Root LOG.md (for concepts)
# ---------------------------------------------------------------------------

def _append_root_log(entry: str) -> None:
    """Append entry to wiki/LOG.md.

    Args:
        entry: Log line to append.
    """
    logger.info("_append_root_log: appending entry to wiki/LOG.md")
    log_path = vault_paths.wiki_log()
    if not log_path.exists():
        logger.info("_append_root_log: LOG.md not found, creating at %s", log_path)
        atomic_write(log_path, "# Wiki Log\n\n")

    try:
        locked_append(log_path, entry)
        logger.info("_append_root_log: entry appended successfully")
    except Exception as exc:
        logger.error("_append_root_log: failed to append entry: %s", exc)
        raise


# ---------------------------------------------------------------------------
# Core processing: single file
# ---------------------------------------------------------------------------

def ingest_one(
    filepath: Path,
    vault_root: Path,
    dry_run: bool = False,
    ingested_sources: set[str] | None = None,
) -> dict:
    """Process a single clipping file.

    Args:
        filepath: Absolute path to the raw clipping .md file.
        vault_root: Vault root path.
        dry_run: If True, return what would be done without writing.
        ingested_sources: Pre-collected set of source_file values
            for batch deduplication. If None, will scan on its own.

    Returns:
        dict with keys:
        - status: "ok" | "skip" | "error"
        - message: human-readable description
        - id: generated file ID (if status == "ok")
        - domain: detected domain (if status == "ok")
        - target_path: path to created wiki file (if status == "ok")
    """
    logger.info("ingest_one: processing %s (dry_run=%s)", filepath.name, dry_run)

    # 1. Verify file exists and is .md
    if not filepath.exists():
        logger.error("ingest_one: file not found: %s", filepath)
        return {"status": "error", "message": f"File not found: {filepath}"}

    if filepath.suffix.lower() != ".md":
        logger.info("ingest_one: skipping non-md file: %s", filepath.name)
        return {"status": "skip", "message": f"Not a .md file: {filepath.name}"}

    # 2. Read frontmatter
    try:
        metadata, body = read_frontmatter(filepath)
        logger.info("ingest_one: frontmatter read OK for %s", filepath.name)
    except Exception as exc:
        logger.warning("ingest_one: invalid frontmatter in %s: %s", filepath.name, exc)
        return {"status": "skip", "message": f"invalid frontmatter: {exc}"}

    # 3. Check body is not empty
    if not body or not body.strip():
        logger.warning("ingest_one: empty body in %s", filepath.name)
        return {"status": "skip", "message": "empty body"}

    # 4. Compute relative source_file path
    try:
        source_file_rel = filepath.relative_to(vault_root).as_posix()
        logger.info("ingest_one: source_file_rel=%s", source_file_rel)
    except ValueError:
        # filepath is not under vault_root - use the raw path parts
        source_file_rel = filepath.as_posix()
        logger.warning(
            "ingest_one: filepath %s is not under vault_root %s, using absolute posix path",
            filepath, vault_root,
        )

    # 5. Deduplication check
    if ingested_sources is not None:
        if source_file_rel in ingested_sources:
            logger.info("ingest_one: already ingested (batch cache): %s", source_file_rel)
            return {"status": "skip", "message": "already ingested"}
    else:
        if is_already_ingested(source_file_rel, vault_root):
            logger.info("ingest_one: already ingested (scan): %s", source_file_rel)
            return {"status": "skip", "message": "already ingested"}

    # 6. Detect domain
    domain, method = detect_domain(metadata, body)
    logger.info("ingest_one: domain=%s method=%s for %s", domain, method, filepath.name)

    # 7. Determine target directory and generate ID
    if domain != "none":
        knowledge_dir = vault_paths.wiki_domain_knowledge(domain)
        file_id = generate_knowledge_id(domain, knowledge_dir)
        target_path = knowledge_dir / f"{file_id}.md"
    else:
        concepts_dir = vault_paths.wiki_concepts()
        file_id = generate_concept_id(concepts_dir)
        target_path = concepts_dir / f"{file_id}.md"

    logger.info("ingest_one: file_id=%s target_path=%s", file_id, target_path)

    # 8. Build wiki content
    content = _build_wiki_content(file_id, domain, source_file_rel, metadata, body)

    # 9. Dry run -- return without writing
    if dry_run:
        logger.info("ingest_one: dry_run=True, not writing %s", file_id)
        return {
            "status": "ok",
            "message": f"dry_run: would create {file_id}",
            "id": file_id,
            "domain": domain,
            "target_path": str(target_path),
        }

    # 10. Write file
    try:
        if domain != "none":
            _ensure_knowledge_scaffold(domain)
        atomic_write(target_path, content)
        logger.info("ingest_one: wrote %s", target_path)
    except Exception as exc:
        logger.error("ingest_one: failed to write %s: %s", target_path, exc)
        return {"status": "error", "message": f"Write failed: {exc}"}

    # 11. Update domain log/index or root LOG.md
    try:
        title = metadata.get("title", filepath.stem)
        if domain != "none":
            append_domain_log(
                domain=domain,
                artifact_type="knowledge",
                action="INGEST.CLIPPING",
                target=file_id,
                result=f'"{title}" -> {domain}/knowledge',
            )
            logger.info("ingest_one: appended domain log for %s", file_id)

            update_domain_index(domain, "knowledge")
            logger.info("ingest_one: updated domain index for %s/knowledge", domain)
        else:
            timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
            log_entry = f'[{timestamp}] INGEST.CLIPPING {file_id} "{title}" -> concepts/'
            _append_root_log(log_entry)
            logger.info("ingest_one: appended root log for %s", file_id)
    except Exception as exc:
        logger.error("ingest_one: failed to update log/index for %s: %s", file_id, exc)
        # File was already written, so we don't return error -- just log it
        # The file is created, dedup will prevent re-processing

    # 12. Update ingested_sources cache if provided
    if ingested_sources is not None:
        ingested_sources.add(source_file_rel)
        logger.debug("ingest_one: added %s to ingested_sources cache", source_file_rel)

    logger.info("ingest_one: successfully ingested %s -> %s", filepath.name, file_id)
    return {
        "status": "ok",
        "message": f"Ingested as {file_id}",
        "id": file_id,
        "domain": domain,
        "target_path": str(target_path),
    }


# ---------------------------------------------------------------------------
# Core processing: batch
# ---------------------------------------------------------------------------

def ingest_batch(
    dry_run: bool = False,
    notify: bool = False,
) -> dict:
    """Process all unprocessed clippings in batch.

    Args:
        dry_run: If True, only report what would be done.
        notify: If True, send Telegram notification with summary.

    Returns:
        dict with keys:
        - status: "ok" | "skip" | "error"
        - processed: int -- number of successfully processed files
        - skipped: int -- number of skipped files (already processed or invalid)
        - errors: int -- number of files that caused errors
        - details: list[dict] -- per-file results
    """
    logger.info("ingest_batch: starting batch processing (dry_run=%s, notify=%s)", dry_run, notify)

    vroot = vault_paths.vault_root()
    clippings_dir = vault_paths.raw_clippings()
    logger.info("ingest_batch: vault_root=%s, clippings_dir=%s", vroot, clippings_dir)

    # Collect already-ingested sources in one pass
    ingested_sources = _collect_ingested_sources(vroot)
    logger.info("ingest_batch: found %d already-ingested sources", len(ingested_sources))

    # Scan clippings directory
    files: list[Path] = []
    if clippings_dir.exists():
        for filepath in sorted(clippings_dir.iterdir()):
            if not filepath.is_file():
                continue
            if filepath.suffix.lower() != ".md":
                logger.debug("ingest_batch: skipping non-md file: %s", filepath.name)
                continue
            files.append(filepath)

    logger.info("ingest_batch: found %d .md files to process", len(files))

    if not files:
        logger.info("ingest_batch: no files to process")
        return {
            "status": "skip",
            "processed": 0,
            "skipped": 0,
            "errors": 0,
            "details": [],
        }

    # Process each file
    processed = 0
    skipped = 0
    errors = 0
    details: list[dict] = []

    for filepath in files:
        logger.info("ingest_batch: processing file %s", filepath.name)
        result = ingest_one(filepath, vroot, dry_run=dry_run, ingested_sources=ingested_sources)
        status = result.get("status", "error")

        detail = {"file": filepath.name, "status": status}
        if status == "ok":
            processed += 1
            detail["id"] = result.get("id", "")
            detail["domain"] = result.get("domain", "")
        elif status == "skip":
            skipped += 1
            detail["message"] = result.get("message", "")
        else:
            errors += 1
            detail["message"] = result.get("message", "")

        details.append(detail)
        logger.info(
            "ingest_batch: file=%s status=%s", filepath.name, status,
        )

    # Determine overall status
    if errors > 0 and processed == 0:
        overall_status = "error"
    elif processed == 0 and skipped > 0:
        overall_status = "skip"
    else:
        overall_status = "ok"

    logger.info(
        "ingest_batch: completed -- processed=%d, skipped=%d, errors=%d, status=%s",
        processed, skipped, errors, overall_status,
    )

    # Send notification if requested
    if notify:
        logger.info("ingest_batch: sending Telegram notification")
        message = (
            f"Ingest clippings: {processed} обработано, "
            f"{skipped} пропущено, {errors} ошибок"
        )
        try:
            from .notifier import send_telegram
            send_telegram(message)
            logger.info("ingest_batch: notification sent successfully")
        except Exception as exc:
            logger.error("ingest_batch: failed to send notification: %s", exc)

    return {
        "status": overall_status,
        "processed": processed,
        "skipped": skipped,
        "errors": errors,
        "details": details,
    }
