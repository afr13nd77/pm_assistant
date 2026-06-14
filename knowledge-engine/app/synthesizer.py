import logging
from datetime import date
from pathlib import Path

from shared import vault_paths
from shared.file_writer import atomic_write
from shared.frontmatter_utils import read_frontmatter, update_frontmatter

from . import claude_client
from .notifier import send_telegram

logger = logging.getLogger(__name__)


def synthesize(
    vault_path: str,
    notify: bool = False,
    min_ideas: int = 1,
    dry_run: bool = False,
) -> dict:
    vault = Path(vault_path)

    logger.info(f"Starting synthesis, vault={vault}, min_ideas={min_ideas}, notify={notify}")

    ideas = _collect_ideas()
    logger.info(f"Found {len(ideas)} ideas for synthesis across all domains")

    if len(ideas) < min_ideas:
        msg = f"Not enough ideas for synthesis (found {len(ideas)}, minimum {min_ideas})"
        logger.info(msg)
        return {"status": "skip", "message": msg}

    if dry_run:
        logger.info(f"Dry run: would synthesize {len(ideas)} ideas")
        return {
            "status": "dry_run",
            "count": len(ideas),
            "ideas": [i["filename"] for i in ideas],
        }

    logger.info(f"Calling Claude API to synthesize {len(ideas)} ideas")
    try:
        synthesis_md = claude_client.synthesize(ideas)
    except Exception as e:
        logger.error(f"Claude API error during synthesis: {e}")
        return {"status": "error", "message": str(e)}

    reports_dir = vault_paths.wiki_reports()
    logger.info(f"Writing synthesis to reports directory: {reports_dir}")

    today = date.today().isoformat()
    filename = _unique_filename(reports_dir, f"synthesis-{today}")
    filepath = reports_dir / filename

    logger.info(f"Writing synthesis to {filepath}")
    atomic_write(filepath, synthesis_md)

    for idea in ideas:
        idea_path = Path(idea["filepath"])
        logger.info(f"Marking as processed: {idea['filename']}")
        try:
            update_frontmatter(idea_path, {"status": "processed"})
        except Exception as e:
            logger.warning(f"Failed to update status for {idea['filename']}: {e}")

    summary = synthesis_md[:500]

    if notify:
        notify_msg = f"Synthesis complete: `{filename}`\n\n{summary[:300]}..."
        send_telegram(notify_msg)

    logger.info(f"Synthesis complete: {filename}, {len(ideas)} ideas processed")
    return {
        "status": "ok",
        "file": filename,
        "summary": summary,
        "count": len(ideas),
    }


def _collect_ideas() -> list[dict]:
    """Collect ideas from all wiki/domains/*/ideas/ directories."""
    ideas = []
    domains = vault_paths.all_domains()
    logger.info(f"Collecting ideas from {len(domains)} domains: {domains}")

    for domain in domains:
        ideas_dir = vault_paths.wiki_domain_dir(domain, "ideas")
        if not ideas_dir.exists():
            logger.info(f"Ideas dir does not exist for domain '{domain}', skipping")
            continue

        for md_file in sorted(ideas_dir.glob("*.md")):
            try:
                metadata, body = read_frontmatter(md_file)
                status = metadata.get("status", "inbox")

                if status in ("inbox", "enriched"):
                    title = _extract_title(body, md_file)
                    ideas.append({
                        "filename": md_file.name,
                        "filepath": str(md_file),
                        "domain": domain,
                        "title": title,
                        "date": str(metadata.get("date", "")),
                        "tags": metadata.get("tags", []),
                        "body": body,
                        "links": metadata.get("linked_to", []),
                        "status": status,
                    })
            except Exception as e:
                logger.warning(f"Failed to read {md_file.name}: {e}")

    return ideas


def _extract_title(body: str, filepath: Path) -> str:
    for line in body.split("\n"):
        line = line.strip()
        if line.startswith("# ") and not line.startswith("## "):
            return line[2:].strip()
    return filepath.stem


def _unique_filename(directory: Path, base: str) -> str:
    filename = f"{base}.md"
    if not (directory / filename).exists():
        return filename

    idx = 2
    while True:
        filename = f"{base}-{idx:02d}.md"
        if not (directory / filename).exists():
            return filename
        idx += 1
