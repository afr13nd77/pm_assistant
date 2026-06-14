import logging
from datetime import datetime
from pathlib import Path

from shared import vault_paths
from shared.file_writer import append_section
from shared.frontmatter_utils import read_frontmatter, update_frontmatter

from . import claude_client
from .matcher import find_links
from .vault_index import build_index

logger = logging.getLogger(__name__)


def enrich(filepath: str | Path, vault_path: str = "", dry_run: bool = False) -> dict:
    if not vault_path:
        vault_path = str(vault_paths.vault_root())
    filepath = Path(filepath)
    logger.info(f"Starting enrichment: {filepath.name}")

    if not filepath.exists():
        logger.error(f"File not found: {filepath}")
        return {"status": "error", "message": f"File not found: {filepath}"}

    try:
        metadata, body = read_frontmatter(filepath)
    except Exception as e:
        logger.error(f"Failed to read frontmatter: {e}")
        return {"status": "error", "message": f"Failed to read file: {e}"}

    status = metadata.get("status", "inbox")
    if status in ("enriched", "processed"):
        logger.info(f"File already {status}, skipping: {filepath.name}")
        return {"status": "skip", "message": f"File already {status}"}

    logger.info("Building vault index")
    try:
        index = build_index(vault_path)
    except Exception as e:
        logger.error(f"Failed to build vault index: {e}")
        return {"status": "error", "message": f"Index build failed: {e}"}

    tags = metadata.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]

    logger.info("Finding matching entries")
    matches = find_links(body, tags, index)

    matched_entries = [
        {
            "path": entry.path,
            "title": entry.title,
            "snippet": snippet,
        }
        for entry, score, snippet in matches
    ]

    if dry_run:
        logger.info(f"Dry run: found {len(matched_entries)} matches")
        return {
            "status": "dry_run",
            "links_found": len(matched_entries),
            "matches": [e["path"] for e in matched_entries],
        }

    logger.info(f"Calling Claude API with {len(matched_entries)} matched entries")
    try:
        relations_section = claude_client.enrich(body, matched_entries)
    except Exception as e:
        logger.error(f"Claude API failed: {e}")
        return {"status": "error", "message": f"Claude API error: {e}"}

    logger.info("Appending relations section to file")
    try:
        append_section(filepath, relations_section)
    except Exception as e:
        logger.error(f"Failed to append section: {e}")
        return {"status": "error", "message": f"Write failed: {e}"}

    linked_paths = [e["path"] for e in matched_entries]
    logger.info("Updating frontmatter")
    try:
        update_frontmatter(filepath, {
            "status": "enriched",
            "enriched_at": datetime.now().isoformat(),
            "linked_to": linked_paths,
        })
    except Exception as e:
        logger.error(f"Failed to update frontmatter: {e}")
        return {"status": "error", "message": f"Frontmatter update failed: {e}"}

    logger.info(f"Enrichment complete: {filepath.name}, {len(linked_paths)} links")
    return {
        "status": "ok",
        "links_found": len(linked_paths),
        "filepath": str(filepath),
    }
