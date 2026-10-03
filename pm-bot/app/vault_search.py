"""
vault_search.py — полнотекстовый поисковый индекс по Obsidian vault.

Строит in-memory индекс по идеям, задачам, эпикам, PRD, багам, встречам
и отчётам, использует TTL-кэш из vault_cache для lazy-построения индекса.
"""

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from shared.vault_paths import VAULT_PATH, all_domains, wiki_domain_dir, wiki_meetings, wiki_reports

from .vault_cache import _cache
from .vault_parsers import _parse_tags, parse_epic_note, parse_note
from .vault_scanner import _is_service_file

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Search index
# ---------------------------------------------------------------------------

_CATEGORY_URL = {
    "idea": "ideas.html",
    "task": "board.html",
    "epic": "roadmap.html",
    "meeting": "dashboard.html",
    "prd": "roadmap.html",
    "bug": "board.html",
    "report": "report.html",
}


@dataclass
class _SearchEntry:
    path: str
    title: str
    tags: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    artifact_id: str = ""
    category: str = ""
    domain: str = ""
    date: str = ""
    url: str = ""


def _extract_search_keywords(title: str, body: str) -> list[str]:
    """Extract search keywords from title and body text.

    Splits title into words (len > 2), extracts ## headings into words (len > 2),
    and takes first 300 chars of body (after removing headings) into words (len > 3).
    All words are lowercased and deduplicated.
    """
    splitter = r'[\s\-_/,.:;!?()\[\]{}#*>~|"\']+'
    keywords: set[str] = set()

    # Title words: len > 2
    for word in re.split(splitter, title):
        word = word.strip().lower()
        if len(word) > 2:
            keywords.add(word)

    # Heading words from ## headings: len > 2
    headings = re.findall(r"^##\s+(.+)$", body, re.MULTILINE)
    for heading in headings:
        for word in re.split(splitter, heading):
            word = word.strip().lower()
            if len(word) > 2:
                keywords.add(word)

    # Body snippet (first 300 chars, headings removed): len > 3
    body_clean = re.sub(r"^#{1,6}\s+.*$", "", body, flags=re.MULTILINE)
    snippet = body_clean[:300]
    for word in re.split(splitter, snippet):
        word = word.strip().lower()
        if len(word) > 3:
            keywords.add(word)

    logger.debug("_extract_search_keywords: extracted %d keywords from title='%s'", len(keywords), title[:50])
    return list(keywords)


def _extract_artifact_id(note: dict, filepath: Path) -> str:
    """Extract artifact ID from frontmatter or filename.

    Checks: frontmatter 'id' field, frontmatter 'jira_key' field,
    then filename patterns like IDEA-NNNN, GO-NNN, PLATFORM-NNNNN, etc.
    """
    # 1. frontmatter id field
    fm_id = note.get("id", "")
    if fm_id:
        return str(fm_id).strip()

    # 2. frontmatter jira_key field
    jira_key = note.get("jira_key", "")
    if jira_key:
        return str(jira_key).strip()

    # 3. Filename pattern: PREFIX-NUMBER (IDEA-0023, GO-156, PLATFORM-10272, etc.)
    match = re.match(r"^([A-Za-z]+-\d+)", filepath.stem)
    if match:
        return match.group(1)

    return ""


# DEPRECATED (BL-237): замена — search_vault() / LanceDB hybrid search; оставлен как fallback
class _SearchIndex:
    """In-memory full-text search index over vault entries."""

    def __init__(self) -> None:
        self.entries: list[_SearchEntry] = []

    def query(self, q: str, limit: int = 20) -> list[dict]:
        """Search entries by query string. Returns top results sorted by score."""
        logger.info("_SearchIndex.query: q='%s' limit=%d", q, limit)
        words = [w.lower() for w in re.split(r'[\s\-_/,.:;!?]+', q) if len(w) >= 2]
        if not words:
            logger.info("_SearchIndex.query: no valid words after filtering, returning []")
            return []

        # Normalized query for exact artifact ID match
        q_normalized = q.strip().lower()

        scored: list[tuple[_SearchEntry, int]] = []
        for entry in self.entries:
            score = 0

            # +10 for exact artifact_id match
            if entry.artifact_id and q_normalized == entry.artifact_id.lower():
                score += 10

            title_lower = entry.title.lower()

            # +3 for title substring match
            for w in words:
                if w in title_lower:
                    score += 3

            # +2 for exact tag match (case-insensitive)
            entry_tags_lower = [t.lower() for t in entry.tags]
            for w in words:
                if w in entry_tags_lower:
                    score += 2

            # +1 for keyword bidirectional substring match (max 1 per word per entry)
            for w in words:
                for kw in entry.keywords:
                    if w in kw or kw in w:
                        score += 1
                        break

            if score > 0:
                scored.append((entry, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        results = [
            {
                "title": e.title,
                "category": e.category,
                "domain": e.domain,
                "date": e.date,
                "tags": e.tags,
                "score": s,
                "path": e.path,
                "url": e.url,
                "artifact_id": e.artifact_id,
            }
            for e, s in scored[:limit]
        ]
        logger.info("_SearchIndex.query: found %d results (top score=%d)", len(results), results[0]["score"] if results else 0)
        return results


def _build_search_index() -> _SearchIndex:
    """Build a search index by scanning all vault artifact directories."""
    logger.info("_build_search_index: starting index build")
    index = _SearchIndex()

    # Scan domain-based directories
    scan_map = {
        "ideas": "idea",
        "tasks": "task",
        "epics": "epic",
        "prds": "prd",
        "bugs": "bug",
    }

    for domain in all_domains():
        for artifact_type, category in scan_map.items():
            try:
                folder = wiki_domain_dir(domain, artifact_type)
            except ValueError as exc:
                logger.error("_build_search_index: invalid artifact_type %s — %s", artifact_type, exc)
                continue
            if not folder.exists():
                continue

            for md_file in folder.glob("*.md"):
                if _is_service_file(md_file):
                    continue
                try:
                    if artifact_type == "epics":
                        note = parse_epic_note(md_file)
                    else:
                        note = parse_note(md_file)

                    title = note.get("title", md_file.stem)
                    raw_tags = note.get("tags", "")
                    tags = _parse_tags(raw_tags) if isinstance(raw_tags, str) else raw_tags if isinstance(raw_tags, list) else []
                    date = str(note.get("date", ""))
                    body = note.get("body", "")
                    keywords = _extract_search_keywords(title, body)
                    artifact_id = _extract_artifact_id(note, md_file)
                    rel_path = str(md_file.relative_to(VAULT_PATH)).replace("\\", "/")
                    url = _CATEGORY_URL.get(category, "")

                    index.entries.append(_SearchEntry(
                        path=rel_path,
                        title=title,
                        tags=tags,
                        keywords=keywords,
                        artifact_id=artifact_id,
                        category=category,
                        domain=domain,
                        date=date,
                        url=url,
                    ))
                except Exception as exc:
                    logger.error("_build_search_index: failed to index %s — %s", md_file.name, exc)

    # Scan cross-domain directories: meetings, reports
    cross_domain = [
        (wiki_meetings, "meeting", "cross-domain"),
        (wiki_reports, "report", "cross-domain"),
    ]
    for folder_fn, category, domain_name in cross_domain:
        folder = folder_fn()
        if not folder.exists():
            continue
        for md_file in folder.glob("*.md"):
            if _is_service_file(md_file):
                continue
            try:
                note = parse_note(md_file)
                title = note.get("title", md_file.stem)
                raw_tags = note.get("tags", "")
                tags = _parse_tags(raw_tags) if isinstance(raw_tags, str) else raw_tags if isinstance(raw_tags, list) else []
                date = str(note.get("date", ""))
                body = note.get("body", "")
                keywords = _extract_search_keywords(title, body)
                artifact_id = _extract_artifact_id(note, md_file)
                rel_path = str(md_file.relative_to(VAULT_PATH)).replace("\\", "/")
                url = _CATEGORY_URL.get(category, "")

                index.entries.append(_SearchEntry(
                    path=rel_path,
                    title=title,
                    tags=tags,
                    keywords=keywords,
                    artifact_id=artifact_id,
                    category=category,
                    domain=domain_name,
                    date=date,
                    url=url,
                ))
            except Exception as exc:
                logger.error("_build_search_index: failed to index %s — %s", md_file.name, exc)

    logger.info("_build_search_index: indexed %d entries", len(index.entries))
    return index


def _get_search_index() -> _SearchIndex:
    """Get or build the search index, using TTL cache."""
    cached = _cache.get("search_index")
    if cached is not None:
        logger.info("_get_search_index: cache hit")
        return cached
    logger.info("_get_search_index: cache miss, building")
    index = _build_search_index()
    _cache.set("search_index", index)
    return index


# ---------------------------------------------------------------------------
# BL-237: hybrid search (LanceDB) with fallback to legacy index
# ---------------------------------------------------------------------------

def _vector_store_enabled() -> bool:
    return os.getenv("VECTOR_STORE_ENABLED", "0") == "1"


def _legacy_search(query: str, limit: int, domain: str | None, artifact_type: str | None) -> list[dict]:
    """Legacy O(N*M) search; filters by domain/type are applied post-query."""
    results = _get_search_index().query(query, limit=limit if not (domain or artifact_type) else 1000)
    if domain:
        results = [r for r in results if r.get("domain") == domain]
    if artifact_type:
        results = [r for r in results if r.get("category") == artifact_type]
    results = results[:limit]
    for r in results:
        r.setdefault("one_liner", "")
        r.setdefault("snippet", "")
        r.setdefault("semantic_score", None)
    return results


def _to_api_dict(r) -> dict:
    """Map vector_store.SearchResult to the API format (backward compatible + new fields)."""
    return {
        "title": r.title,
        "category": r.type,
        "domain": r.domain,
        "date": "",
        "tags": [],
        "score": r.score,
        "path": r.source_path,
        "url": _CATEGORY_URL.get(r.type, ""),
        "artifact_id": r.id,
        "one_liner": r.one_liner,
        "snippet": r.snippet,
        "semantic_score": r.semantic_score,
    }


def search_vault(
    query: str,
    limit: int = 20,
    domain: str | None = None,
    artifact_type: str | None = None,
) -> list[dict]:
    """Search the vault: hybrid LanceDB search if VECTOR_STORE_ENABLED=1, else legacy index."""
    if not _vector_store_enabled():
        logger.info("search_vault: VECTOR_STORE_ENABLED=0, legacy search q=%r", query)
        return _legacy_search(query, limit, domain, artifact_type)

    try:
        from shared import embedding_client, vector_store

        emb_result = embedding_client.embed(query)
        # Если эмбеддинг недоступен — hybrid_search работает в keyword-only режиме
        vector = emb_result.vector if emb_result is not None else None
        found = vector_store.hybrid_search(query, vector, limit, domain, artifact_type)
        results = [_to_api_dict(r) for r in found]
        logger.info("search_vault: hybrid search returned %d results for q=%r", len(results), query)
        return results
    except Exception as exc:
        logger.error("search_vault: hybrid search failed (%s), falling back to legacy index", exc)
        return _legacy_search(query, limit, domain, artifact_type)
