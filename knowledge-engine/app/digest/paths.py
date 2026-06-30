"""Path mapping between wiki/ and llm_wiki/ layers."""

import logging
from pathlib import Path

from shared import vault_paths

logger = logging.getLogger(__name__)


def wiki_to_llm_wiki(wiki_path: Path, vault_root: Path) -> Path:
    """Convert wiki/X.md path to llm_wiki/X.md path."""
    try:
        rel = wiki_path.relative_to(vault_root / "wiki")
    except ValueError:
        raise ValueError(f"Path {wiki_path} is not under {vault_root / 'wiki'}")
    return vault_root / "llm_wiki" / rel


def llm_wiki_to_wiki(llm_wiki_path: Path, vault_root: Path) -> Path:
    """Convert llm_wiki/X.md path back to wiki/X.md path."""
    try:
        rel = llm_wiki_path.relative_to(vault_root / "llm_wiki")
    except ValueError:
        raise ValueError(f"Path {llm_wiki_path} is not under {vault_root / 'llm_wiki'}")
    return vault_root / "wiki" / rel


def llm_wiki_index(vault_root: Path) -> Path:
    """Return path to llm_wiki/_index.md (does NOT create file)."""
    return vault_root / "llm_wiki" / "_index.md"


def ensure_llm_wiki_structure(vault_root: Path) -> None:
    """Create mirrored llm_wiki/ directory structure from wiki/."""
    logger.info("ensure_llm_wiki_structure: creating llm_wiki/ under %s", vault_root)
    llm_wiki = vault_root / "llm_wiki"
    llm_wiki.mkdir(parents=True, exist_ok=True)

    for subdir in ("meetings", "daily-logs", "reports"):
        (llm_wiki / subdir).mkdir(parents=True, exist_ok=True)
        logger.debug("ensure_llm_wiki_structure: ensured %s", llm_wiki / subdir)

    domains_dir = vault_root / "wiki" / "domains"
    if domains_dir.exists():
        for domain_dir in sorted(domains_dir.iterdir()):
            if not domain_dir.is_dir():
                continue
            for type_dir in sorted(domain_dir.iterdir()):
                if not type_dir.is_dir():
                    continue
                mirror = llm_wiki / "domains" / domain_dir.name / type_dir.name
                mirror.mkdir(parents=True, exist_ok=True)
                logger.debug("ensure_llm_wiki_structure: ensured %s", mirror)

    logger.info("ensure_llm_wiki_structure: done")
