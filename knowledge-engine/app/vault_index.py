import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from shared import vault_paths
from shared.frontmatter_utils import read_frontmatter

logger = logging.getLogger(__name__)

# Mapping of artifact_type directory name to index category
_ARTIFACT_CATEGORY = {
    "ideas": "idea",
    "prds": "prd",
    "epics": "epic",
    "userstories": "userstory",
    "tasks": "task",
    "bugs": "bug",
    "knowledge": "knowledge",
}

# Cross-domain wiki directories mapped to categories
_CROSS_DOMAIN_DIRS = {
    "meetings": "meeting",
    "daily-logs": "daily-log",
    "reports": "report",
}


@dataclass
class VaultEntry:
    path: str
    title: str
    tags: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    category: str = "other"
    domain: str = ""


@dataclass
class VaultIndex:
    entries: list[VaultEntry] = field(default_factory=list)
    built_at: str = ""
    vault_path: str = ""

    def search(self, keywords: list[str], tags: list[str]) -> list[tuple[VaultEntry, int]]:
        results = []
        keywords_lower = [k.lower() for k in keywords if len(k) > 2]
        tags_lower = [t.lower() for t in tags]

        for entry in self.entries:
            score = 0
            entry_keywords_lower = [k.lower() for k in entry.keywords if k]
            entry_tags_lower = [t.lower() for t in entry.tags if t]

            for kw in keywords_lower:
                for ekw in entry_keywords_lower:
                    if kw in ekw or ekw in kw:
                        score += 1

            for tag in tags_lower:
                if tag in entry_tags_lower:
                    score += 2

            if score > 0:
                results.append((entry, score))

        results.sort(key=lambda x: x[1], reverse=True)
        logger.info(f"Search found {len(results)} matches (top score: {results[0][1] if results else 0})")
        return results[:10]


def build_index(vault_path: str) -> VaultIndex:
    vault = Path(vault_path)
    start = time.time()
    logger.info(f"Building vault index from: {vault}")

    entries = []

    # Scan domain-based artifact directories: wiki/domains/*/ideas/, etc.
    domains = vault_paths.all_domains()
    logger.info(f"Discovered {len(domains)} domains: {domains}")

    for domain in domains:
        for artifact_type, category in _ARTIFACT_CATEGORY.items():
            scan_dir = vault_paths.wiki_domain_dir(domain, artifact_type)
            if not scan_dir.exists():
                logger.info(f"Skipping (not found): wiki/domains/{domain}/{artifact_type}")
                continue

            for md_file in scan_dir.glob("*.md"):
                entry = _index_file(md_file, vault, category, domain)
                if entry:
                    entries.append(entry)

    # Scan cross-domain directories: wiki/meetings/, wiki/daily-logs/, wiki/reports/
    cross_domain_scanners = {
        "meetings": vault_paths.wiki_meetings,
        "daily-logs": vault_paths.wiki_daily_logs,
        "reports": vault_paths.wiki_reports,
    }
    for dir_name, path_fn in cross_domain_scanners.items():
        category = _CROSS_DOMAIN_DIRS[dir_name]
        scan_dir = path_fn()
        if not scan_dir.exists():
            logger.info(f"Skipping (not found): wiki/{dir_name}")
            continue

        for md_file in scan_dir.glob("*.md"):
            entry = _index_file(md_file, vault, category, "cross-domain")
            if entry:
                entries.append(entry)

    elapsed = time.time() - start
    index = VaultIndex(
        entries=entries,
        built_at=datetime.now().isoformat(),
        vault_path=str(vault),
    )
    logger.info(f"Vault index built: {len(entries)} entries in {elapsed:.2f}s")
    return index


def _index_file(filepath: Path, vault_root: Path, category: str, domain: str) -> VaultEntry | None:
    try:
        rel_path = str(filepath.relative_to(vault_root)).replace("\\", "/")

        try:
            metadata, body = read_frontmatter(filepath)
        except Exception:
            metadata = {}
            body = filepath.read_text(encoding="utf-8")

        title = _extract_title(body, filepath)
        tags = metadata.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",")]

        keywords = _extract_keywords(title, body)

        return VaultEntry(
            path=rel_path,
            title=title,
            tags=tags,
            keywords=keywords,
            category=category,
            domain=domain,
        )
    except Exception as e:
        logger.warning(f"Failed to index {filepath.name}: {e}")
        return None


def _extract_title(body: str, filepath: Path) -> str:
    for line in body.split("\n"):
        line = line.strip()
        if line.startswith("# ") and not line.startswith("## "):
            return line[2:].strip()
    return filepath.stem


def _extract_keywords(title: str, body: str) -> list[str]:
    import re
    keywords = set()

    for word in re.split(r"[\s\-_/,.:;!?()\"']+", title):
        word = word.strip().lower()
        if len(word) > 2:
            keywords.add(word)

    headings = re.findall(r"^#{1,3}\s+(.+)$", body, re.MULTILINE)
    for heading in headings:
        for word in re.split(r"[\s\-_/,.:;!?()\"']+", heading):
            word = word.strip().lower()
            if len(word) > 2:
                keywords.add(word)

    snippet = body[:300]
    for word in re.split(r"[\s\-_/,.:;!?()\"']+", snippet):
        word = word.strip().lower()
        if len(word) > 3:
            keywords.add(word)

    return list(keywords)
