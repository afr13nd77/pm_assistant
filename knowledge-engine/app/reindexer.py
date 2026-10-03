"""Переиндексация wiki/ -> LanceDB vector store (BL-237, T-08)."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable, Optional

from shared import vector_store
from shared.frontmatter_utils import read_frontmatter
from shared.system_log import LoggedProcess

from .digest.generator import _SKIP_FILENAMES, _generate_id, generate_digest
from .digest.templates import detect_type

logger = logging.getLogger(__name__)


def _collect_files(wiki_root: Path) -> list[Path]:
    """Собрать все .md файлы wiki/, кроме служебных."""
    files: list[Path] = []
    try:
        for md_file in sorted(wiki_root.rglob("*.md")):
            if md_file.name in _SKIP_FILENAMES or md_file.name.startswith("_"):
                continue
            files.append(md_file)
        logger.info("reindexer: collected %d files from %s", len(files), wiki_root)
    except Exception as e:
        logger.error("reindexer: failed to scan %s: %s", wiki_root, e)
    return files


def _has_vector(md_file: Path) -> bool:
    """True, если в LanceDB уже есть запись с непустым vector."""
    try:
        metadata, _ = read_frontmatter(md_file)
        digest_id = _generate_id(detect_type(md_file, metadata), md_file)
        record = vector_store.get_by_id(digest_id)
        return record is not None and record.get("vector") is not None
    except Exception as e:
        logger.warning("reindexer: has_vector check failed for %s: %s", md_file.name, e)
        return False


def reindex_vault(
    vault_path: str,
    full: bool = True,
    missing: bool = False,
    notify: bool = False,
    progress_cb: Optional[Callable[[int, int, int], None]] = None,
) -> dict:
    """Полная переиндексация wiki/ -> LanceDB.

    full=True: drop_and_recreate() перед началом.
    missing=True: только записи без vector (full при этом отключается).
    progress_cb(processed, total, errors_count) — для HTTP-статуса.
    """
    if missing:
        full = False
    t0 = time.monotonic()
    processed = 0
    skipped = 0
    errors = 0
    error_list: list[str] = []
    total = 0

    with LoggedProcess("reindex", source="ke-cron") as lp:
        try:
            if full:
                logger.info("reindexer: drop_and_recreate")
                vector_store.drop_and_recreate()

            wiki_root = Path(vault_path) / "wiki"
            files = _collect_files(wiki_root)
            total = len(files)
            if progress_cb:
                progress_cb(0, total, 0)

            for i, md_file in enumerate(files, 1):
                try:
                    if missing and _has_vector(md_file):
                        skipped += 1
                    else:
                        result = generate_digest(md_file, vault_path, force=True)
                        if result.get("status") == "error":
                            raise RuntimeError(result.get("error", "unknown error"))
                        processed += 1
                except Exception as e:
                    errors += 1
                    error_list.append(f"{md_file.name}: {e}")
                    logger.error("reindexer: failed %s: %s", md_file.name, e)
                logger.info("Reindexing: %d/%d (%d%%)", i, total, int(i * 100 / total))
                if progress_cb:
                    progress_cb(i, total, errors)

            report = {
                "status": "ok",
                "total": total,
                "processed": processed,
                "skipped": skipped,
                "errors": errors,
                "duration_sec": round(time.monotonic() - t0, 2),
            }
            lp.summary = f"Reindex: {processed}/{total}, errors={errors}"
            lp.details = {**report, "error_list": error_list[:20]}
            logger.info("reindexer: completed %s", report)
        except Exception as e:
            logger.error("reindexer: failed: %s", e, exc_info=True)
            report = {
                "status": "error",
                "error": str(e),
                "total": total,
                "processed": processed,
                "skipped": skipped,
                "errors": errors + 1,
                "duration_sec": round(time.monotonic() - t0, 2),
            }
            lp.status = "error"
            lp.summary = str(e)[:500]
            lp.details = dict(report)

    if notify:
        try:
            from .notifier import send_telegram

            send_telegram(
                f"Reindex {report['status']}: {report['processed']}/{report['total']}, "
                f"errors={report['errors']}, {report['duration_sec']}s"
            )
            logger.info("reindexer: telegram notification sent")
        except Exception as e:
            logger.error("reindexer: notify failed: %s", e)

    return report
