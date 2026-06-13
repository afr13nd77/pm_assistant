"""Domain management for the pm_assistant knowledge engine.

Provides functions to create, list, and maintain domain scaffolding in the
wiki/domains/ section of the vault.
"""

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from . import vault_paths
from .file_writer import atomic_write, file_lock, locked_append
from .frontmatter_utils import read_frontmatter

logger = logging.getLogger(__name__)

_ARTIFACT_TYPES = ("ideas", "prds", "epics", "userstories", "tasks", "bugs", "knowledge")
_DOMAIN_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _is_service_file(name: str) -> bool:
    """Return True if the filename is a service file (index.md or log.md)."""
    return name in ("index.md", "log.md")


def _domain_root(name: str) -> Path:
    return vault_paths.VAULT_PATH / "wiki" / "domains" / name


def _index_content(domain: str, artifact_type: str) -> str:
    title = domain.replace("-", " ").title()
    atype_title = artifact_type.replace("-", " ").title()
    return (
        f"---\n"
        f"type: index\n"
        f"domain: {domain}\n"
        f"artifact_type: {artifact_type}\n"
        f"---\n"
        f"\n"
        f"# {title} — {atype_title}\n"
        f"\n"
        f"| File | Title | Status | Created |\n"
        f"|------|-------|--------|---------|\n"
    )


def _log_content(domain: str, artifact_type: str) -> str:
    title = domain.replace("-", " ").title()
    atype_title = artifact_type.replace("-", " ").title()
    return (
        f"---\n"
        f"type: log\n"
        f"domain: {domain}\n"
        f"artifact_type: {artifact_type}\n"
        f"---\n"
        f"\n"
        f"# {title} — {atype_title} Log\n"
        f"\n"
    )


def _decisions_content(domain: str) -> str:
    title = domain.replace("-", " ").title()
    return (
        f"---\n"
        f"type: decisions\n"
        f"domain: {domain}\n"
        f"---\n"
        f"\n"
        f"# {title} — Decisions\n"
        f"\n"
    )


def _glossary_content(domain: str) -> str:
    title = domain.replace("-", " ").title()
    return (
        f"---\n"
        f"type: glossary\n"
        f"domain: {domain}\n"
        f"---\n"
        f"\n"
        f"# {title} — Glossary\n"
        f"\n"
    )


def create_domain(name: str) -> Path:
    """Create full domain scaffolding under wiki/domains/<name>/.

    Args:
        name: Domain name — must be lowercase alphanumeric with hyphens.

    Returns:
        Path to the domain root directory.

    Raises:
        ValueError: If the name is invalid or the domain already exists.
    """
    logger.info("create_domain: validating name=%r", name)

    if not name or not _DOMAIN_NAME_RE.match(name):
        logger.error(
            "create_domain: invalid domain name=%r; "
            "must be lowercase alphanumeric with hyphens only",
            name,
        )
        raise ValueError(
            f"Invalid domain name {name!r}. "
            "Must be non-empty, lowercase alphanumeric, hyphens allowed."
        )

    domain_root = _domain_root(name)
    if domain_root.exists():
        logger.error("create_domain: domain already exists at %s", domain_root)
        raise ValueError(f"Domain {name!r} already exists at {domain_root}")

    logger.info("create_domain: creating scaffolding for domain=%r at %s", name, domain_root)

    for artifact_type in _ARTIFACT_TYPES:
        artifact_dir = domain_root / artifact_type
        artifact_dir.mkdir(parents=True, exist_ok=True)
        logger.info("create_domain: created directory %s", artifact_dir)

        index_path = artifact_dir / "index.md"
        atomic_write(index_path, _index_content(name, artifact_type))
        logger.info("create_domain: wrote %s", index_path)

        log_path = artifact_dir / "log.md"
        atomic_write(log_path, _log_content(name, artifact_type))
        logger.info("create_domain: wrote %s", log_path)

    decisions_path = domain_root / "decisions.md"
    atomic_write(decisions_path, _decisions_content(name))
    logger.info("create_domain: wrote %s", decisions_path)

    glossary_path = domain_root / "glossary.md"
    atomic_write(glossary_path, _glossary_content(name))
    logger.info("create_domain: wrote %s", glossary_path)

    logger.info("create_domain: domain=%r created successfully at %s", name, domain_root)

    # After scaffold creation, write entry to domain-config.yaml
    try:
        from . import domain_config
        domain_config.set_domain(name, {
            "display_name": name,
            "description": "",
            "color": "#607D8B",
            "jira_labels": [],
        })
        logger.info("create_domain: added config entry for domain %r", name)
    except ValueError as exc:
        logger.info(
            "create_domain: config entry for domain %r already exists, skipping: %s",
            name,
            exc,
        )
    except Exception as exc:
        logger.warning(
            "create_domain: failed to write config entry for %r: %s (scaffold was created)",
            name,
            exc,
        )

    return domain_root


def list_domains() -> list[dict]:
    """List all domains with artifact counts and last_updated timestamp.

    Returns:
        List of dicts with keys: name, ideas, prds, epics, userstories,
        tasks, bugs, total, last_updated (ISO string or "").
    """
    logger.info("list_domains: scanning domains")
    domain_names = vault_paths.all_domains()
    result = []

    for domain_name in domain_names:
        domain_root = _domain_root(domain_name)
        counts: dict[str, int] = {atype: 0 for atype in _ARTIFACT_TYPES}
        latest_mtime: float | None = None

        for artifact_type in _ARTIFACT_TYPES:
            artifact_dir = domain_root / artifact_type
            if not artifact_dir.exists():
                continue
            for md_file in artifact_dir.glob("*.md"):
                if _is_service_file(md_file.name):
                    continue
                counts[artifact_type] += 1
                mtime = md_file.stat().st_mtime
                if latest_mtime is None or mtime > latest_mtime:
                    latest_mtime = mtime

        total = sum(counts.values())
        last_updated = (
            datetime.fromtimestamp(latest_mtime, tz=timezone.utc).isoformat()
            if latest_mtime is not None
            else ""
        )

        entry = {
            "name": domain_name,
            **counts,
            "total": total,
            "last_updated": last_updated,
        }
        result.append(entry)
        logger.info(
            "list_domains: domain=%r total=%d last_updated=%r",
            domain_name,
            total,
            last_updated,
        )

    logger.info("list_domains: found %d domains", len(result))
    return result


def update_domain_index(domain: str, artifact_type: str) -> Path:
    """Rebuild the index.md table for a given domain and artifact type.

    Scans all .md files (excluding index.md and log.md), extracts metadata,
    and overwrites the table body of index.md.

    Args:
        domain: Domain name.
        artifact_type: One of the valid artifact types.

    Returns:
        Path to the updated index.md.
    """
    logger.info(
        "update_domain_index: domain=%r artifact_type=%r", domain, artifact_type
    )

    artifact_dir = vault_paths.wiki_domain_dir(domain, artifact_type)
    index_path = artifact_dir / "index.md"

    with file_lock(index_path):
        # Collect artifact files
        artifact_files = sorted(
            f for f in artifact_dir.glob("*.md") if not _is_service_file(f.name)
        )
        logger.info(
            "update_domain_index: found %d artifact files in %s",
            len(artifact_files),
            artifact_dir,
        )

        # Build table rows
        rows: list[str] = []
        for md_file in artifact_files:
            try:
                metadata, body = read_frontmatter(md_file)
            except Exception as exc:
                logger.error(
                    "update_domain_index: failed to read frontmatter from %s: %s",
                    md_file.name,
                    exc,
                )
                metadata, body = {}, ""

            # Extract title: first # heading in body, fall back to filename stem
            title = md_file.stem
            for line in body.splitlines():
                stripped = line.strip()
                if stripped.startswith("# "):
                    title = stripped[2:].strip()
                    break

            status = str(metadata.get("status", ""))
            created = str(
                metadata.get("created_at", metadata.get("date", metadata.get("created", "")))
            )

            rows.append(
                f"| [[{md_file.name}]] | {title} | {status} | {created} |"
            )

        # Preserve or bootstrap the frontmatter of index.md
        if index_path.exists():
            try:
                existing_meta, _ = read_frontmatter(index_path)
            except Exception as exc:
                logger.error(
                    "update_domain_index: failed to read existing index.md frontmatter: %s",
                    exc,
                )
                existing_meta = {"type": "index", "domain": domain, "artifact_type": artifact_type}
        else:
            existing_meta = {"type": "index", "domain": domain, "artifact_type": artifact_type}

        # Rebuild frontmatter block
        fm_lines = ["---"]
        for key, value in existing_meta.items():
            fm_lines.append(f"{key}: {value}")
        fm_lines.append("---")
        frontmatter_block = "\n".join(fm_lines)

        title_line = domain.replace("-", " ").title()
        atype_title = artifact_type.replace("-", " ").title()
        table_header = (
            "| File | Title | Status | Created |\n"
            "|------|-------|--------|---------|"
        )
        table_body = "\n".join(rows)
        if table_body:
            table_section = table_header + "\n" + table_body + "\n"
        else:
            table_section = table_header + "\n"

        new_content = (
            f"{frontmatter_block}\n"
            f"\n"
            f"# {title_line} — {atype_title}\n"
            f"\n"
            f"{table_section}"
        )

        atomic_write(index_path, new_content)
        logger.info(
            "update_domain_index: indexed %d entries into %s", len(rows), index_path
        )
    return index_path


def append_domain_log(
    domain: str,
    artifact_type: str,
    action: str,
    target: str,
    result: str,
) -> Path:
    """Append a timestamped entry to the artifact-type log.md.

    Args:
        domain: Domain name.
        artifact_type: One of the valid artifact types.
        action: Short action label (e.g. "CREATE", "UPDATE").
        target: The subject of the action (e.g. filename or title).
        result: Outcome description.

    Returns:
        Path to the log.md file.
    """
    logger.info(
        "append_domain_log: domain=%r artifact_type=%r action=%r target=%r",
        domain,
        artifact_type,
        action,
        target,
    )

    artifact_dir = vault_paths.wiki_domain_dir(domain, artifact_type)
    log_path = artifact_dir / "log.md"

    if not log_path.exists():
        logger.info(
            "append_domain_log: log.md not found, creating at %s", log_path
        )
        atomic_write(log_path, _log_content(domain, artifact_type))

    timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    entry = f"[{timestamp}] {action} {target} → {result}\n"

    try:
        locked_append(log_path, entry)
        logger.info(
            "append_domain_log: appended entry to %s", log_path
        )
    except Exception as exc:
        logger.error(
            "append_domain_log: failed to append to %s: %s", log_path, exc
        )
        raise

    return log_path
