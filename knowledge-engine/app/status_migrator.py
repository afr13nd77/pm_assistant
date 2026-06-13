from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from shared import vault_paths
from shared.frontmatter_utils import read_frontmatter, update_frontmatter

logger = logging.getLogger(__name__)

STATUS_MAP: dict[str, str] = {
    "inbox": "Новая",
    "processed": "Проверка гипотезы",
    "draft": "Новая",
    "new": "Новая",
    "done": "Готова к производству",
    "rejected": "Отсев",
    "бэклог": "Новая",
    "enriched": "Новая",
}

VALID_STATUSES: frozenset[str] = frozenset({
    "Новая",
    "Проверка гипотезы",
    "Готова к производству",
    "Отсев",
})

_SERVICE_FILES = frozenset({"index.md", "log.md"})


def _classify_status(raw_value: str | None) -> tuple[str, str | None]:
    if raw_value is None or raw_value.strip() == "":
        return ("missing", "Новая")

    if raw_value in VALID_STATUSES:
        return ("skip", raw_value)

    normalized = raw_value.strip().lower()
    if normalized in STATUS_MAP:
        return ("migrate", STATUS_MAP[normalized])

    return ("unknown", None)


def migrate_statuses(vault_path: str, dry_run: bool = False) -> dict:
    logger.info(f"migrate_statuses: started, dry_run={dry_run}")

    details: list[dict] = []
    migrated = 0
    skipped = 0
    errors = 0
    unknown_statuses = 0
    today_iso = date.today().isoformat()

    domains = vault_paths.all_domains()
    logger.info(f"migrate_statuses: found {len(domains)} domains")

    for domain in domains:
        ideas_dir = Path(vault_path) / "wiki" / "domains" / domain / "ideas"
        if not ideas_dir.exists():
            logger.info(f"migrate_statuses: no ideas/ dir for domain={domain}, skipping")
            continue

        md_files = sorted(ideas_dir.glob("*.md"))
        logger.info(f"migrate_statuses: domain={domain}, found {len(md_files)} md files")

        for filepath in md_files:
            if filepath.name in _SERVICE_FILES:
                logger.info(f"migrate_statuses: skipping service file {filepath.name}")
                continue

            try:
                metadata, _ = read_frontmatter(filepath)
                old_status = metadata.get("status")
                action, new_status = _classify_status(old_status)

                if action == "skip":
                    skipped += 1
                    details.append({
                        "file": str(filepath),
                        "domain": domain,
                        "old_status": old_status,
                        "new_status": new_status,
                        "action": "skip",
                        "error": None,
                    })
                    logger.info(f"migrate_statuses: {filepath.name} already valid, skipped")

                elif action == "migrate":
                    if not dry_run:
                        update_frontmatter(filepath, {"status": new_status, "updated": today_iso})
                    migrated += 1
                    details.append({
                        "file": str(filepath),
                        "domain": domain,
                        "old_status": old_status,
                        "new_status": new_status,
                        "action": "migrate",
                        "error": None,
                    })
                    logger.info(f"migrate_statuses: {filepath.name} migrated '{old_status}' -> '{new_status}'")

                elif action == "missing":
                    if not dry_run:
                        update_frontmatter(filepath, {"status": new_status, "updated": today_iso})
                    migrated += 1
                    details.append({
                        "file": str(filepath),
                        "domain": domain,
                        "old_status": old_status,
                        "new_status": new_status,
                        "action": "missing",
                        "error": None,
                    })
                    logger.info(f"migrate_statuses: {filepath.name} had no status, set to '{new_status}'")

                elif action == "unknown":
                    unknown_statuses += 1
                    details.append({
                        "file": str(filepath),
                        "domain": domain,
                        "old_status": old_status,
                        "new_status": None,
                        "action": "unknown",
                        "error": None,
                    })
                    logger.warning(f"migrate_statuses: {filepath.name} has unknown status '{old_status}'")

            except Exception as exc:
                errors += 1
                details.append({
                    "file": str(filepath),
                    "domain": domain,
                    "old_status": None,
                    "new_status": None,
                    "action": "error",
                    "error": str(exc),
                })
                logger.error(f"migrate_statuses: error processing {filepath.name}: {exc}")

    report = {
        "status": "ok",
        "migrated": migrated,
        "skipped": skipped,
        "errors": errors,
        "unknown_statuses": unknown_statuses,
        "details": details,
    }
    logger.info(
        f"migrate_statuses: completed — migrated={migrated}, skipped={skipped}, "
        f"errors={errors}, unknown={unknown_statuses}"
    )
    return report
