import logging
import re

from .vault_index import VaultEntry, VaultIndex

logger = logging.getLogger(__name__)

STOP_WORDS = {
    "это", "как", "для", "что", "при", "или", "все", "его", "она", "они",
    "быть", "было", "будет", "есть", "так", "уже", "нет", "если", "тоже",
    "можно", "нужно", "надо", "чтобы", "который", "которая", "которые",
    "этот", "этого", "этой", "этих", "свой", "своей", "своих",
    "the", "and", "for", "with", "from", "that", "this", "are", "was",
    "not", "but", "have", "has", "been", "will", "can", "should",
}


def find_links(
    text: str,
    tags: list[str],
    index: VaultIndex,
) -> list[tuple[VaultEntry, int, str]]:
    logger.info(f"Finding links for text ({len(text)} chars), tags={tags}")

    keywords = extract_keywords(text)
    logger.info(f"Extracted {len(keywords)} keywords: {keywords[:10]}")

    scored = index.search(keywords, tags)

    results = []
    for entry, score in scored:
        snippet = _get_snippet(entry)
        results.append((entry, score, snippet))

    logger.info(f"Matched {len(results)} entries, top-3: {[(r[0].title, r[1]) for r in results[:3]]}")
    return results


def extract_keywords(text: str) -> list[str]:
    text_clean = re.sub(r"^---.*?---", "", text, flags=re.DOTALL).strip()
    text_clean = re.sub(r"[#*\[\]()>`~|]", " ", text_clean)

    words = re.split(r"[\s\-_/,.:;!?\"']+", text_clean)

    keywords = []
    seen = set()
    for word in words:
        word = word.strip().lower()
        if len(word) > 2 and word not in STOP_WORDS and word not in seen:
            seen.add(word)
            keywords.append(word)

    return keywords


def _get_snippet(entry: VaultEntry) -> str:
    try:
        return f"{entry.title} ({entry.category})"
    except Exception:
        return entry.title
