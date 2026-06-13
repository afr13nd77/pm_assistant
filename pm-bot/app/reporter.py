import logging
import re
from datetime import date, timedelta
from pathlib import Path

import yaml

from shared import llm_client, vault_paths

logger = logging.getLogger(__name__)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter and body from a markdown file.

    Returns (metadata_dict, body_string). If no frontmatter found,
    returns ({}, full_text).
    """
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)", text, re.DOTALL)
    if not match:
        return {}, text

    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as e:
        logger.warning("Failed to parse YAML frontmatter: %s", e)
        meta = {}
    body = match.group(2).strip()
    return meta, body


def _extract_date_from_filename(filename: str) -> date | None:
    """Extract date from filename with YYYY-MM-DD prefix."""
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", filename)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def _extract_title(meta: dict, body: str, filename: str) -> str:
    """Extract title from frontmatter, first heading, or filename."""
    if meta.get("title"):
        return str(meta["title"])

    heading_match = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    if heading_match:
        return heading_match.group(1).strip()

    return Path(filename).stem


def scan_folder(folder_path: Path, start_date: date, end_date: date) -> list[dict]:
    """Read .md files from folder_path, filtered by date in filename.

    Files must have a YYYY-MM-DD prefix in their filename.
    Only files with dates between start_date and end_date (inclusive) are returned.
    """
    logger.info("scan_folder: scanning %s for dates %s..%s", folder_path, start_date, end_date)

    if not folder_path.exists():
        logger.warning("scan_folder: folder %s does not exist, returning empty list", folder_path)
        return []

    if not folder_path.is_dir():
        logger.warning("scan_folder: %s is not a directory, returning empty list", folder_path)
        return []

    all_files = list(folder_path.glob("*.md"))
    logger.info("scan_folder: found %d .md files in %s", len(all_files), folder_path)

    results = []
    for filepath in all_files:
        file_date = _extract_date_from_filename(filepath.name)
        if file_date is None:
            continue
        if not (start_date <= file_date <= end_date):
            continue

        try:
            text = filepath.read_text(encoding="utf-8")
        except Exception as e:
            logger.error("scan_folder: failed to read %s: %s", filepath, e)
            continue

        meta, body = _parse_frontmatter(text)
        title = _extract_title(meta, body, filepath.name)

        results.append({
            "filename": filepath.name,
            "date": file_date.isoformat(),
            "title": title,
            "body": body,
        })

    logger.info("scan_folder: %d files matched date filter in %s", len(results), folder_path)
    return results


def scan_all_domain_folders(
    artifact_type: str, start_date: date, end_date: date
) -> list[dict]:
    """Scan a given artifact_type folder across all domains.

    Iterates over every domain returned by vault_paths.all_domains(),
    calls scan_folder on each domain's artifact_type directory, and
    returns an aggregated list with a 'domain' field added to each entry.
    """
    domains = vault_paths.all_domains()
    logger.info(
        "scan_all_domain_folders: scanning '%s' across %d domains for dates %s..%s",
        artifact_type, len(domains), start_date, end_date,
    )

    aggregated: list[dict] = []
    for domain in domains:
        folder_path = vault_paths.wiki_domain_dir(domain, artifact_type)
        entries = scan_folder(folder_path, start_date, end_date)
        for entry in entries:
            entry["domain"] = domain
        aggregated.extend(entries)
        logger.info(
            "scan_all_domain_folders: domain '%s' yielded %d entries for '%s'",
            domain, len(entries), artifact_type,
        )

    logger.info(
        "scan_all_domain_folders: total %d entries for '%s' across all domains",
        len(aggregated), artifact_type,
    )
    return aggregated


def get_open_tasks() -> list[dict]:
    """Read .md files from all domain tasks/ folders, excluding those with status: done.

    Each returned dict includes a 'domain' field indicating which domain the task
    belongs to.
    """
    domains = vault_paths.all_domains()
    logger.info("get_open_tasks: scanning tasks across %d domains", len(domains))

    results = []
    for domain in domains:
        folder_path = vault_paths.wiki_domain_dir(domain, "tasks")

        if not folder_path.exists():
            logger.warning("get_open_tasks: folder %s does not exist, skipping", folder_path)
            continue

        if not folder_path.is_dir():
            logger.warning("get_open_tasks: %s is not a directory, skipping", folder_path)
            continue

        all_files = list(folder_path.glob("*.md"))
        logger.info("get_open_tasks: found %d .md files in domain '%s'", len(all_files), domain)

        for filepath in all_files:
            try:
                text = filepath.read_text(encoding="utf-8")
            except Exception as e:
                logger.error("get_open_tasks: failed to read %s: %s", filepath, e)
                continue

            meta, body = _parse_frontmatter(text)
            status = str(meta.get("status", "")).strip().lower()

            if status == "done":
                continue

            title = _extract_title(meta, body, filepath.name)
            file_date = _extract_date_from_filename(filepath.name)

            results.append({
                "filename": filepath.name,
                "title": title,
                "status": meta.get("status", "unknown"),
                "date": file_date.isoformat() if file_date else None,
                "domain": domain,
            })

    logger.info("get_open_tasks: %d open tasks found across all domains", len(results))
    return results


def build_context(
    meetings: list[dict],
    tasks: list[dict],
    ideas: list[dict],
    open_tasks: list[dict],
    upcoming_meetings: list[dict],
    daily_logs: list[dict] | None = None,
) -> str:
    """Build a structured text block to send to Claude as context for report generation."""
    if daily_logs is None:
        daily_logs = []

    logger.info(
        "build_context: meetings=%d, tasks=%d, ideas=%d, open_tasks=%d, upcoming=%d, daily_logs=%d",
        len(meetings), len(tasks), len(ideas), len(open_tasks), len(upcoming_meetings),
        len(daily_logs),
    )

    lines = []

    # Meetings last week
    lines.append(f"## Встречи за прошлую неделю ({len(meetings)})")
    for m in meetings:
        body_preview = m.get("body", "")[:200]
        lines.append(f"- {m['date']}: {m['title']}")
        if body_preview:
            lines.append(f"  {body_preview}")
    lines.append("")

    # Daily logs last week
    if daily_logs:
        lines.append(f"## Дневные логи за неделю ({len(daily_logs)})")
        for dl in daily_logs:
            body_preview = dl.get("body", "")[:200]
            lines.append(f"- {dl['date']}: {dl['title']}")
            if body_preview:
                lines.append(f"  {body_preview}")
        lines.append("")

    # New tasks/tickets last week
    lines.append(f"## Новые тикеты за неделю ({len(tasks)})")
    for t in tasks:
        domain_tag = f" [{t['domain']}]" if t.get("domain") else ""
        lines.append(f"- {t['date']}: {t['title']}{domain_tag}")
    lines.append("")

    # Ideas last week
    lines.append(f"## Идеи за неделю ({len(ideas)})")
    for i in ideas:
        domain_tag = f" [{i['domain']}]" if i.get("domain") else ""
        lines.append(f"- {i['date']}: {i['title']}{domain_tag}")
    lines.append("")

    # Open tasks
    lines.append(f"## Открытые задачи ({len(open_tasks)})")
    for ot in open_tasks:
        domain_tag = f" [{ot['domain']}]" if ot.get("domain") else ""
        lines.append(f"- {ot['title']} [{ot['status']}]{domain_tag}")
    lines.append("")

    # Upcoming meetings
    lines.append(f"## Предстоящие встречи ({len(upcoming_meetings)})")
    for um in upcoming_meetings:
        lines.append(f"- {um['date']}: {um['title']}")
    lines.append("")

    context_text = "\n".join(lines)
    logger.info("build_context: built context of %d characters", len(context_text))
    return context_text


def _load_prompt(name: str) -> str:
    """Load a prompt template from the prompts/ directory."""
    path = Path(__file__).parent / "prompts" / f"{name}.txt"
    logger.info("_load_prompt: loading %s", path)
    try:
        text = path.read_text(encoding="utf-8")
        logger.info("_load_prompt: loaded %d characters from %s", len(text), path)
        return text
    except Exception as e:
        logger.error("_load_prompt: failed to load prompt %s: %s", path, e)
        raise


def generate_weekly_report() -> str:
    """Generate a weekly report by scanning vault and calling Claude API.

    Algorithm:
    1. Calculate date ranges for last week (Mon-Fri) and current week
    2. Scan wiki/meetings/, daily-logs, and all domain ideas/tasks for last week
    3. Get open tasks across all domains
    4. Scan upcoming meetings for current week
    5. Build context and call Claude with the weekly_report prompt
    """
    logger.info("generate_weekly_report: starting report generation")

    # Step 1: Calculate date ranges
    today = date.today()
    # Monday of current week
    this_monday = today - timedelta(days=today.weekday())
    # Monday and Friday of previous week
    last_monday = this_monday - timedelta(days=7)
    last_friday = last_monday + timedelta(days=4)

    logger.info(
        "generate_weekly_report: date ranges — last_monday=%s, last_friday=%s, this_monday=%s",
        last_monday, last_friday, this_monday,
    )

    # Step 2: Scan folders for last week
    logger.info("generate_weekly_report: scanning meetings for last week")
    meetings = scan_folder(vault_paths.wiki_meetings(), last_monday, last_friday)

    logger.info("generate_weekly_report: scanning tasks across all domains for last week")
    tasks = scan_all_domain_folders("tasks", last_monday, last_friday)

    logger.info("generate_weekly_report: scanning ideas across all domains for last week")
    ideas = scan_all_domain_folders("ideas", last_monday, last_friday)

    logger.info("generate_weekly_report: scanning daily logs for last week")
    daily_logs = scan_folder(vault_paths.wiki_daily_logs(), last_monday, last_friday)

    # Step 3: Get open tasks
    logger.info("generate_weekly_report: getting open tasks")
    open_tasks = get_open_tasks()

    # Step 4: Scan upcoming meetings (current week)
    upcoming_end = this_monday + timedelta(days=6)
    logger.info("generate_weekly_report: scanning upcoming meetings %s..%s", this_monday, upcoming_end)
    upcoming_meetings = scan_folder(vault_paths.wiki_meetings(), this_monday, upcoming_end)

    # Step 5: Build context
    logger.info("generate_weekly_report: building context")
    context = build_context(
        meetings, tasks, ideas, open_tasks, upcoming_meetings,
        daily_logs=daily_logs,
    )
    logger.info("generate_weekly_report: context length = %d characters", len(context))

    # Step 6: Load prompt
    logger.info("generate_weekly_report: loading weekly_report prompt")
    prompt = _load_prompt("weekly_report")

    # Step 7: Call LLM
    logger.info("generate_weekly_report: calling LLM")
    try:
        result = llm_client.call_with_fallback(
            operation="weekly_report",
            messages=[{"role": "user", "content": f"{prompt}\n\n---\n{context}"}],
            max_tokens=2000,
        )
        logger.info("generate_weekly_report: LLM returned %d characters", len(result))
        return result
    except Exception as e:
        logger.error("generate_weekly_report: LLM call failed: %s", e)
        raise
