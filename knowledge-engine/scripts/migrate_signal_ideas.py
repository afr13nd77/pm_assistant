"""One-time migration: IDEA files with status 'Сигнал' -> 'Отсев' (BL-203, AC-13/AC-14).

Usage:
    python scripts/migrate_signal_ideas.py --dry-run   # preview changes
    python scripts/migrate_signal_ideas.py              # apply changes
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Add parent dirs to path for imports
# parent.parent = knowledge-engine/  (for app.* imports)
# parent.parent.parent = pm_assistant/  (monorepo root, for shared.* imports)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from shared.frontmatter_utils import read_frontmatter, update_frontmatter

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def migrate(vault_path: str, dry_run: bool = False) -> dict:
    """Scan wiki/domains/*/ideas/IDEA-*.md and migrate status 'Сигнал' -> 'Отсев'.

    Returns:
        dict with keys: scanned (int), migrated (int), errors (int), files (list[str])
    """
    logger.info(f"migrate: vault_path={vault_path}, dry_run={dry_run}")

    vault = Path(vault_path)

    stats: dict = {"scanned": 0, "migrated": 0, "errors": 0, "files": []}

    for md_path in sorted(vault.glob("wiki/domains/*/ideas/IDEA-*.md")):
        stats["scanned"] += 1
        logger.info(f"migrate: scanning {md_path.name}")

        try:
            fm, _body = read_frontmatter(md_path)
            if not fm:
                logger.info(f"migrate: {md_path.name} -- no frontmatter, skip")
                continue

            status = fm.get("status", "")
            if status != "Сигнал":
                continue

            logger.info(f"migrate: {md_path.name} -- status='Сигнал' -> will migrate")
            stats["files"].append(str(md_path.relative_to(vault)))

            if dry_run:
                logger.info(f"migrate: [DRY RUN] would change {md_path.name}: Сигнал -> Отсев")
                stats["migrated"] += 1
                continue

            update_frontmatter(md_path, {
                "status": "Отсев",
                "migrated_from": "Сигнал",
                "migrated_at": datetime.now().isoformat(),
            })
            stats["migrated"] += 1
            logger.info(f"migrate: {md_path.name} -- migrated: Сигнал -> Отсев")

        except Exception as e:
            logger.error(f"migrate: error processing {md_path.name}: {e}")
            stats["errors"] += 1

    logger.info(
        f"migrate: done -- scanned={stats['scanned']}, "
        f"migrated={stats['migrated']}, errors={stats['errors']}"
    )
    return stats


def main() -> None:
    """CLI entry point."""
    logger.info("main: starting migration script")

    parser = argparse.ArgumentParser(
        description="Migrate IDEA files with status 'Сигнал' -> 'Отсев'",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without applying",
    )
    parser.add_argument(
        "--vault-path",
        default=os.environ.get("VAULT_PATH", "/vault"),
        help="Path to vault (default: $VAULT_PATH or /vault)",
    )
    args = parser.parse_args()

    result = migrate(args.vault_path, args.dry_run)

    dry_label = "(DRY RUN) " if args.dry_run else ""
    print(f"\n{'=' * 50}")
    print(f"Migration {dry_label}complete:")
    print(f"  Scanned: {result['scanned']}")
    print(f"  Migrated: {result['migrated']}")
    print(f"  Errors: {result['errors']}")
    if result["files"]:
        print("\nAffected files:")
        for f in result["files"]:
            print(f"  - {f}")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
