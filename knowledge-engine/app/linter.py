import logging
import re
import time
from pathlib import Path

from shared import vault_paths
from shared.frontmatter_utils import read_frontmatter

from .status_migrator import VALID_STATUSES

logger = logging.getLogger(__name__)

_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
_ARTIFACT_TYPES = ("ideas", "prds", "epics", "userstories", "tasks", "bugs")
_SERVICE_FILES = frozenset({"index.md", "log.md", "decisions.md", "glossary.md"})
_STALE_DRAFT_DAYS = 30
_DRAFT_STATUSES = frozenset({"новая"})
_ATTACHMENT_EXTS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp",
    ".pdf", ".csv", ".xlsx", ".xls", ".docx", ".pptx",
    ".mp3", ".mp4", ".wav", ".zip", ".tar", ".gz",
})


def _resolve_wikilink_target(raw: str) -> str:
    """Extract the target filename from a raw wikilink string.

    Handles pipe syntax: [[target|display text]] → target.
    Adds .md extension only when the target has no extension.
    """
    raw = raw.replace("\\|", "|")
    if "|" in raw:
        target = raw.split("|", 1)[0].strip()
    else:
        target = raw.strip()

    # Add .md only if the filename part has no extension
    if "." not in target.rsplit("/", 1)[-1]:
        target = target + ".md"
    return target


def _is_ignorable_link(raw: str) -> bool:
    """Return True if the raw wikilink target is not a vault markdown file.

    Filters out: attachments (images, PDFs, etc.), @mentions,
    template variables ({{...}}), and URLs.
    """
    stripped = raw.strip()
    stripped = stripped.replace("\\|", "|")
    lower = stripped.lower()

    # @mentions
    if stripped.startswith("@"):
        return True

    # Template variables
    if "{{" in stripped and "}}" in stripped:
        return True

    # URLs
    if lower.startswith("http://") or lower.startswith("https://"):
        return True

    # Attachment file extensions — check the raw target before .md is appended
    # Handle pipe syntax: [[display|target]]
    target_part = stripped.split("|", 1)[0].strip() if "|" in stripped else stripped
    dot_pos = target_part.rfind(".")
    if dot_pos != -1:
        ext = target_part[dot_pos:].lower()
        if ext in _ATTACHMENT_EXTS:
            return True

    # Person names — 2-3 capitalized words, no path-like chars
    if "/" not in stripped and ".md" not in lower and "." not in stripped and "_" not in stripped and "-" not in stripped:
        words = stripped.split()
        if 2 <= len(words) <= 3:
            all_capitalized = all(
                len(w) > 0 and (
                    w[0].isupper()  # covers both Latin A-Z and Cyrillic А-Я
                )
                for w in words
            )
            if all_capitalized:
                logger.debug("_is_ignorable_link: treating as person name: %s", stripped)
                return True

    return False


def _build_file_index(vault: Path) -> dict:
    """Build an index of all .md files under wiki/ for multi-level wikilink resolution.

    Returns dict with keys:
        by_name: dict mapping filename.lower() -> list of relative paths from vault
        by_stem: dict mapping stem.lower() (no .md) -> list of relative paths from vault
        all_paths: list of all relative paths (lowercased, forward slashes)
    """
    logger.info("_build_file_index: building index for vault %s", vault)

    wiki_dir = vault / "wiki"
    if not wiki_dir.exists():
        logger.info("_build_file_index: wiki/ not found, returning empty index")
        return {"by_name": {}, "by_stem": {}, "all_paths": []}

    by_name: dict[str, list[str]] = {}
    by_stem: dict[str, list[str]] = {}
    all_paths: list[str] = []

    for scan_dir in (wiki_dir, vault / "raw"):
        if not scan_dir.exists():
            continue
        patterns = ["*.md"] if scan_dir.name == "wiki" else ["*.md", "*.txt"]
        for pattern in patterns:
            for file in scan_dir.rglob(pattern):
                rel_path = str(file.relative_to(vault)).replace("\\", "/").lower()
                name = file.name.lower()
                stem = file.stem.lower()

                by_name.setdefault(name, []).append(rel_path)
                by_stem.setdefault(stem, []).append(rel_path)
                all_paths.append(rel_path)

    logger.info(
        "_build_file_index: indexed %d files, %d unique names, %d unique stems",
        len(all_paths),
        len(by_name),
        len(by_stem),
    )

    return {"by_name": by_name, "by_stem": by_stem, "all_paths": all_paths}


def _resolve_wikilink(target: str, file_index: dict) -> bool:
    """Resolve a wikilink target using 3-level strategy against the file index.

    Level 1: Exact name match (filename in by_name).
    Level 2: Suffix match (any path in all_paths ends with target).
    Level 3: Stem match (target without .md in by_stem).

    Returns True if the target resolves to at least one existing file.
    """
    target_lower = target.lower()

    # Level 1: Exact name match
    if target_lower in file_index["by_name"]:
        logger.debug("_resolve_wikilink: target=%s resolved at level %d", target, 1)
        return True

    # Level 2: Suffix match
    target_normalized = target_lower.replace("\\", "/")
    for path in file_index["all_paths"]:
        if path.endswith(target_normalized):
            logger.debug("_resolve_wikilink: target=%s resolved at level %d", target, 2)
            return True

    # Level 3: Stem match
    if target_lower.endswith(".md"):
        stem = target_lower[:-3]
    else:
        stem = target_lower
    if stem in file_index["by_stem"]:
        logger.debug("_resolve_wikilink: target=%s resolved at level %d", target, 3)
        return True

    logger.debug("_resolve_wikilink: target=%s not resolved at any level", target)
    return False


def check_broken_links(vault_path: str) -> list[dict]:
    """Scan wiki/ for wikilinks whose targets do not exist in the vault.

    Returns a list of dicts with keys: file, line, link, reason.
    """
    vault = Path(vault_path)
    logger.info("check_broken_links: starting scan under %s/wiki/", vault)

    wiki_dir = vault / "wiki"
    if not wiki_dir.exists():
        logger.info("check_broken_links: wiki/ not found, returning empty")
        return []

    file_index = _build_file_index(vault)
    logger.info("check_broken_links: built file index with %d files", len(file_index["all_paths"]))

    broken = []
    scanned_files = 0

    for md_file in wiki_dir.rglob("*.md"):
        scanned_files += 1
        try:
            text = md_file.read_text(encoding="utf-8")
        except Exception as exc:
            logger.error("check_broken_links: cannot read %s: %s", md_file, exc)
            continue

        lines = text.splitlines()
        body_start = 0  # 0-indexed position where body starts

        # Skip YAML frontmatter delimited by --- ... ---
        if lines and lines[0].strip() == "---":
            for i in range(1, len(lines)):
                if lines[i].strip() == "---":
                    body_start = i + 1
                    logger.debug(
                        "check_broken_links: %s — skipping frontmatter (lines 1-%d)",
                        md_file.name, body_start,
                    )
                    break

        for idx in range(body_start, len(lines)):
            line_no = idx + 1  # 1-based for reporting
            line = lines[idx]
            for match in _WIKILINK_RE.finditer(line):
                raw = match.group(1)
                if _is_ignorable_link(raw):
                    continue
                target = _resolve_wikilink_target(raw)
                # Skip non-markdown targets (image/attachment embeds like [[files/image.png]])
                allowed_exts = (".md", ".txt")
                if not any(target.lower().endswith(ext) for ext in allowed_exts):
                    logger.debug("check_broken_links: skipping non-md/txt target: %s", target)
                    continue
                # Resolve relative paths (../) against the current file's directory
                if "../" in target:
                    resolved_path = (md_file.parent / target).resolve()
                    if resolved_path.exists():
                        logger.debug(
                            "check_broken_links: relative path %s resolved to existing file %s",
                            target, resolved_path,
                        )
                        continue
                    else:
                        broken.append({
                            "file": str(md_file.relative_to(vault)).replace("\\", "/"),
                            "line": line_no,
                            "link": raw,
                            "reason": "relative path target not found",
                        })
                        logger.debug(
                            "check_broken_links: relative path %s did not resolve (tried %s)",
                            target, resolved_path,
                        )
                        continue
                if not _resolve_wikilink(target, file_index):
                    broken.append({
                        "file": str(md_file.relative_to(vault)).replace("\\", "/"),
                        "line": line_no,
                        "link": raw,
                        "reason": "target not found",
                    })

    logger.info(
        "check_broken_links: scanned %d files, found %d broken links",
        scanned_files,
        len(broken),
    )
    return broken


_DATE_PREFIX_RE = re.compile(r"^\d{4}[-\.]\d{2}[-\.]\d{2}")


def check_orphan_pages(vault_path: str) -> list[dict]:
    """Find raw/inbound/ files (daily-logs, meeting-notes) with no wiki counterpart.

    Only checks two categories that have a transformation pipeline and are NOT
    covered by other checks:

    * ``raw/inbound/daily-logs/`` -- matched against ``wiki/daily-logs/YYYY-MM-DD.md``
      by extracting the date prefix from the raw filename.
    * ``raw/inbound/meeting-notes/`` -- matched against ``wiki/meetings/YYYY-MM-DD*.md``
      by extracting the date prefix from the raw filename.

    Categories excluded from this check (covered elsewhere):

    * ideas, tasks -- covered by ``_check_ingest_backlog`` (stem matching)
    * misc -- covered by ``check_unsorted_misc`` (wikilink reference matching)
    * clippings -- reference material, no transformation expected

    Returns:
        list[dict] with keys:
          - file  -- relative path from vault root (forward slashes)
          - type  -- "daily-logs" or "meeting-notes"
    """
    vault = Path(vault_path)
    logger.info("check_orphan_pages: starting scan for orphan daily-logs/meeting-notes in %s", vault)

    # ------------------------------------------------------------------
    # Step 1: Collect dates from wiki/daily-logs/*.md
    # ------------------------------------------------------------------
    wiki_daily_dates: set[str] = set()
    wiki_daily_dir = vault / "wiki" / "daily-logs"
    if wiki_daily_dir.exists():
        for md_file in wiki_daily_dir.glob("*.md"):
            # stem is expected to be "YYYY-MM-DD"
            m = _DATE_PREFIX_RE.match(md_file.stem)
            if m:
                wiki_daily_dates.add(m.group(0).replace(".", "-"))

    logger.info(
        "check_orphan_pages: collected %d wiki daily-log dates from %s",
        len(wiki_daily_dates),
        wiki_daily_dir,
    )

    # ------------------------------------------------------------------
    # Step 2: Collect dates from wiki/meetings/*.md
    # ------------------------------------------------------------------
    wiki_meeting_dates: set[str] = set()
    wiki_meetings_dir = vault / "wiki" / "meetings"
    if wiki_meetings_dir.exists():
        for md_file in wiki_meetings_dir.glob("*.md"):
            m = _DATE_PREFIX_RE.match(md_file.stem)
            if m:
                wiki_meeting_dates.add(m.group(0).replace(".", "-"))

    logger.info(
        "check_orphan_pages: collected %d wiki meeting dates from %s",
        len(wiki_meeting_dates),
        wiki_meetings_dir,
    )

    # ------------------------------------------------------------------
    # Step 3-5: Scan raw/inbound/daily-logs and meeting-notes, find orphans
    # ------------------------------------------------------------------
    raw_inbound = vault / "raw" / "inbound"
    if not raw_inbound.exists():
        logger.info("check_orphan_pages: raw/inbound/ not found, returning empty")
        return []

    orphans: list[dict] = []
    raw_scanned = 0

    # meeting-notes can transform into wiki/daily-logs/ (Daily standups)
    # or wiki/meetings/ (other meetings), so check both sets
    scan_config = [
        ("daily-logs", wiki_daily_dates),
        ("meeting-notes", wiki_meeting_dates | wiki_daily_dates),
    ]

    for sub_type, wiki_dates in scan_config:
        raw_dir = raw_inbound / sub_type
        if not raw_dir.exists():
            logger.info("check_orphan_pages: %s not found, skipping", raw_dir)
            continue

        for raw_file in raw_dir.iterdir():
            if not raw_file.is_file():
                continue
            raw_scanned += 1

            date_match = _DATE_PREFIX_RE.match(raw_file.stem)
            if not date_match:
                # No date prefix -- cannot match, treat as orphan
                rel_path = str(raw_file.relative_to(vault)).replace("\\", "/")
                orphans.append({"file": rel_path, "type": sub_type})
                continue

            date_str = date_match.group(0).replace(".", "-")
            if date_str not in wiki_dates:
                rel_path = str(raw_file.relative_to(vault)).replace("\\", "/")
                orphans.append({"file": rel_path, "type": sub_type})

    logger.info(
        "check_orphan_pages: scanned %d raw files, found %d orphans",
        raw_scanned,
        len(orphans),
    )
    return orphans


def check_stale_drafts(vault_path: str) -> list[dict]:
    """Find idea files with draft/inbox status whose mtime is older than 30 days.

    Returns a list of dicts with keys: file, domain, days_old, status.
    """
    vault = Path(vault_path)
    logger.info("check_stale_drafts: starting scan under %s/wiki/domains/*/ideas/", vault)

    domains = vault_paths.all_domains()
    logger.info("check_stale_drafts: scanning %d domains", len(domains))

    now = time.time()
    stale = []
    scanned = 0

    for domain in domains:
        ideas_dir = vault / "wiki" / "domains" / domain / "ideas"
        if not ideas_dir.exists():
            continue
        for md_file in ideas_dir.glob("*.md"):
            if md_file.name in _SERVICE_FILES:
                continue
            scanned += 1
            try:
                metadata, _ = read_frontmatter(md_file)
            except Exception as exc:
                logger.error(
                    "check_stale_drafts: cannot read frontmatter from %s: %s", md_file, exc
                )
                continue

            status = str(metadata.get("status", "")).strip().lower()
            if status not in _DRAFT_STATUSES:
                continue

            mtime = md_file.stat().st_mtime
            days_old = int((now - mtime) / 86400)
            if days_old >= _STALE_DRAFT_DAYS:
                stale.append({
                    "file": str(md_file.relative_to(vault)).replace("\\", "/"),
                    "domain": domain,
                    "days_old": days_old,
                    "status": status,
                })

    logger.info(
        "check_stale_drafts: scanned %d idea files, found %d stale drafts",
        scanned,
        len(stale),
    )
    return stale


def check_unsorted_misc(vault_path: str) -> list[dict]:
    """Find files in raw/inbound/misc/ that have no wikilink references from wiki/.

    Scans all wiki/**/*.md files for [[...]] wikilinks, builds a set of
    referenced targets (lowercased names and stems), then reports any misc
    file whose name or stem is not referenced.

    Returns a list of dicts with keys: file (relative path), name (filename).
    """
    vault = Path(vault_path)
    misc_dir = vault / "raw" / "inbound" / "misc"
    wiki_dir = vault / "wiki"
    logger.info("check_unsorted_misc: scanning %s", misc_dir)

    if not misc_dir.exists():
        logger.info("check_unsorted_misc: misc/ not found, returning empty")
        return []

    # --- Build set of all wikilink targets referenced from wiki/ ---
    referenced: set[str] = set()
    if wiki_dir.exists():
        for md_file in wiki_dir.rglob("*.md"):
            try:
                text = md_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for match in _WIKILINK_RE.finditer(text):
                raw = match.group(1).strip()
                raw = raw.replace("\\|", "|")
                # Handle pipe syntax: [[target|display]] → use target
                if "|" in raw:
                    target = raw.split("|", 1)[0].strip()
                else:
                    target = raw.strip()
                target_lower = target.lower()
                referenced.add(target_lower)
                # Also add the stem (without extension) if target has one
                target_path = Path(target)
                if target_path.suffix:
                    referenced.add(target_path.stem.lower())

    logger.info(
        "check_unsorted_misc: collected %d unique wikilink targets from wiki/",
        len(referenced),
    )

    # --- Scan misc files and check against referenced set ---
    unsorted = []
    scanned = 0
    referenced_count = 0

    for entry in misc_dir.iterdir():
        if not entry.is_file():
            continue
        scanned += 1
        name_lower = entry.name.lower()
        stem_lower = entry.stem.lower()
        rel_path = str(entry.relative_to(vault)).replace("\\", "/")
        is_referenced = name_lower in referenced or stem_lower in referenced
        if is_referenced:
            referenced_count += 1
        else:
            unsorted.append({
                "file": rel_path,
                "name": entry.name,
            })

    logger.info(
        "check_unsorted_misc: scanned %d files, %d referenced, %d unreferenced",
        scanned,
        referenced_count,
        len(unsorted),
    )
    return unsorted


def check_invalid_idea_statuses(vault_path: str) -> list[dict]:
    logger.info("check_invalid_idea_statuses: starting scan")
    results: list[dict[str, str | None]] = []
    root = Path(vault_path) / "wiki" / "domains"
    if not root.exists():
        logger.info("check_invalid_idea_statuses: wiki/domains not found, returning empty")
        return results

    for domain_dir in sorted(root.iterdir()):
        if not domain_dir.is_dir():
            continue
        ideas_dir = domain_dir / "ideas"
        if not ideas_dir.exists():
            continue
        domain = domain_dir.name
        for f in sorted(ideas_dir.glob("*.md")):
            if f.name in _SERVICE_FILES:
                continue
            try:
                metadata, _ = read_frontmatter(f)
                status = metadata.get("status")
                if status is None or status.strip() == "":
                    results.append({
                        "file": str(f.relative_to(Path(vault_path))),
                        "domain": domain,
                        "status": status,
                        "reason": "missing_status",
                    })
                elif status not in VALID_STATUSES:
                    results.append({
                        "file": str(f.relative_to(Path(vault_path))),
                        "domain": domain,
                        "status": status,
                        "reason": "unknown_status",
                    })
            except Exception as exc:
                logger.warning(f"check_invalid_idea_statuses: error reading {f.name}: {exc}")

    logger.info(f"check_invalid_idea_statuses: found {len(results)} invalid statuses")
    return results


def lint(vault_path: str) -> dict:
    """Run all vault health checks and return a structured report.

    Args:
        vault_path: Absolute path to the vault root directory.

    Returns:
        dict with keys: status, broken_links, orphan_pages, stale_drafts,
        unsorted_misc, summary.
    """
    logger.info("lint: starting vault health check for %s", vault_path)

    broken_links = check_broken_links(vault_path)
    orphan_pages = check_orphan_pages(vault_path)
    stale_drafts = check_stale_drafts(vault_path)
    unsorted_misc = check_unsorted_misc(vault_path)
    invalid_idea_statuses = check_invalid_idea_statuses(vault_path)

    summary = {
        "broken_links_count": len(broken_links),
        "orphan_pages_count": len(orphan_pages),
        "stale_drafts_count": len(stale_drafts),
        "unsorted_misc_count": len(unsorted_misc),
        "invalid_idea_statuses_count": len(invalid_idea_statuses),
        "total_issues": len(broken_links) + len(orphan_pages) + len(stale_drafts) + len(unsorted_misc) + len(invalid_idea_statuses),
    }

    logger.info(
        f"lint: completed — broken_links={summary['broken_links_count']} orphan_pages={summary['orphan_pages_count']} stale_drafts={summary['stale_drafts_count']} unsorted_misc={summary['unsorted_misc_count']} invalid_idea_statuses={summary['invalid_idea_statuses_count']} total={summary['total_issues']}"
    )

    return {
        "status": "ok",
        "broken_links": broken_links,
        "orphan_pages": orphan_pages,
        "stale_drafts": stale_drafts,
        "unsorted_misc": unsorted_misc,
        "invalid_idea_statuses": invalid_idea_statuses,
        "summary": summary,
    }
