"""Decision Journal: агрегированный список решений из протоколов встреч."""

import logging

from fastapi import APIRouter, Query

from shared.vault_paths import wiki_meetings

from ..vault_cache import _cache
from ..vault_parsers import _extract_section, parse_note

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Decisions"])


# ---------------------------------------------------------------------------
# Decision Journal helpers
# ---------------------------------------------------------------------------

_EMPTY_DECISION_PATTERNS = [
    "решений не принято",
    "решения отсутствуют",
    "нет решений",
    "не обсуждались",
]

_DOMAIN_KEYWORDS_FALLBACK = {
    "search-engine": [
        "поиск", "индексаци", "ранжирован", "выдач", "фильтр",
        "getresults", "searchoffers", "bbox",
    ],
    "suggester": ["автокомплит", "подсказк", "typeahead", "suggest"],
    "static-metadata": [
        "справочник", "классификатор", "атрибут", "метаданн",
        "каталог", "контент", "комнат", "статик",
    ],
    "partner-search-engine": [
        "партнёр", "партнер", "level travel", "канал продаж", "дистрибуц",
    ],
}


def _parse_decision_bullets(raw: str) -> list[str]:
    """Parse bullet items from raw Решения section text."""
    decisions: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            text = stripped[2:].strip()
            if text and text != "-":
                decisions.append(text)
        elif stripped.startswith("* "):
            text = stripped[2:].strip()
            if text:
                decisions.append(text)
        elif stripped and not stripped.startswith("#") and len(stripped) > 3:
            decisions.append(stripped)
    return decisions


def _is_empty_decisions(raw: str) -> bool:
    """Check if decisions section is effectively empty."""
    lower = raw.strip().lower()
    for pattern in _EMPTY_DECISION_PATTERNS:
        if pattern in lower:
            return True
    return len(_parse_decision_bullets(raw)) == 0


def _detect_domain_for_decision(text: str) -> str:
    """Detect domain for a decision via keyword matching."""
    lower = text.lower()
    try:
        from shared.domain_config import load as load_domain_config
        config = load_domain_config()
        for slug, entry in config.get("domains", {}).items():
            if not isinstance(entry, dict):
                continue
            for kw in entry.get("keywords", []):
                if isinstance(kw, str) and kw.lower() in lower:
                    return slug
    except Exception:
        pass
    for dom, keywords in _DOMAIN_KEYWORDS_FALLBACK.items():
        for kw in keywords:
            if kw in lower:
                return dom
    return "general"


def _load_domain_display_map() -> dict[str, dict]:
    """Load display_name and color for each domain from domain-config.yaml."""
    try:
        from shared.domain_config import load as load_domain_config
        config = load_domain_config()
        result: dict[str, dict] = {}
        for slug, entry in config.get("domains", {}).items():
            if isinstance(entry, dict):
                result[slug] = {
                    "display_name": entry.get("display_name", slug),
                    "color": entry.get("color", "#607D8B"),
                }
        return result
    except Exception:
        return {}


def _normalize_participants(raw) -> str:
    """Convert participants from frontmatter to comma-separated string."""
    if not raw:
        return ""
    if isinstance(raw, list):
        return ", ".join(str(p) for p in raw)
    text = str(raw).strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return text.strip()


def _decision_matches_query(text: str, context: str, q: str) -> bool:
    """Check if decision text or context matches search query (case-insensitive)."""
    lower_q = q.lower()
    return lower_q in text.lower() or (bool(context) and lower_q in context.lower())


# ---------------------------------------------------------------------------
# Decision Journal endpoint
# ---------------------------------------------------------------------------


@router.get("/api/v1/decisions")
def get_decisions(
    domain: str | None = Query(default=None, description="Filter by domain slug"),
    q: str | None = Query(default=None, description="Full-text search in decision text and context"),
    date_from: str | None = Query(default=None, description="Start date YYYY-MM-DD inclusive"),
    date_to: str | None = Query(default=None, description="End date YYYY-MM-DD inclusive"),
):
    """Aggregated list of decisions from all meeting protocols."""
    logger.info(
        "get_decisions: domain=%s, q=%s, date_from=%s, date_to=%s",
        domain, q, date_from, date_to,
    )

    cache_key = f"decisions:{domain or ''}:{q or ''}:{date_from or ''}:{date_to or ''}"
    cached = _cache.get(cache_key)
    if cached is not None:
        logger.info("get_decisions: cache hit, returning %d decisions", len(cached))
        return cached

    folder = wiki_meetings()
    if not folder.exists():
        logger.info("get_decisions: meetings folder does not exist")
        _cache.set(cache_key, [])
        return []

    files = sorted(folder.glob("*.md"), reverse=True)
    logger.info("get_decisions: scanning %d meeting files", len(files))

    domain_cfg = _load_domain_display_map()
    results: list[dict] = []

    for f in files:
        try:
            note = parse_note(f)
        except Exception as exc:
            logger.debug("get_decisions: failed to parse %s: %s", f.name, exc)
            continue

        note_date = str(note.get("date", ""))
        if date_from and note_date < date_from:
            continue
        if date_to and note_date > date_to:
            continue

        body = note.get("body", "")
        decisions_raw = _extract_section(body, "Решения")
        if not decisions_raw:
            continue
        if _is_empty_decisions(decisions_raw):
            continue

        context = _extract_section(body, "Контекст") or ""
        action_items_raw = _extract_section(body, "Action Items")
        action_items = [
            line.strip()
            for line in (action_items_raw or "").splitlines()
            if "- [ ]" in line or "- [x]" in line
        ]
        blockers = _extract_section(body, "Блокеры и риски") or ""

        participants = _normalize_participants(note.get("participants"))
        source_title = note.get("title", "")
        meeting_type = note.get("type", "")

        for decision_text in _parse_decision_bullets(decisions_raw):
            detected_domain = _detect_domain_for_decision(decision_text)

            if domain and detected_domain != domain:
                continue
            if q and not _decision_matches_query(decision_text, context, q):
                continue

            display_info = domain_cfg.get(detected_domain, {})

            results.append({
                "text": decision_text,
                "date": note_date,
                "domain": detected_domain,
                "domain_display": display_info.get("display_name", detected_domain),
                "domain_color": display_info.get("color", "#607D8B"),
                "source_file": note.get("filename", f.name),
                "source_title": source_title,
                "participants": participants,
                "meeting_type": meeting_type,
                "context": context,
                "action_items": action_items,
                "blockers": blockers,
            })

    results.sort(key=lambda x: x["date"], reverse=True)
    logger.info("get_decisions: returning %d decisions", len(results))
    _cache.set(cache_key, results)
    return results
