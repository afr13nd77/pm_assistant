import logging
import re
from datetime import date, datetime
from pathlib import Path

from .vault_paths import (
    VAULT_PATH,
    next_daily_filename,
    raw_daily_logs,
    raw_ideas,
    raw_meetings,
    raw_tasks,
    templates,
    wiki_daily_logs,
    wiki_domain_dir,
    wiki_log,
    wiki_meetings,
    wiki_reports,
)

logger = logging.getLogger(__name__)

_FALLBACK_TEMPLATE = """\
---
id: ""
type: idea
domain:
status: "Новая"
readiness: 0%
author:
created: ""
updated: ""
source:
epic_ref:
tags:
  -
---

# {title}

---

## Блок 1 — Паспорт идеи

### 1. Проблема / Боль


### 2. Решение


### 3. Ценность (USP)


### 4. Метрика


---

## Блок 2 — Посадочный талон

### 5. Сегмент (Кто)


### 6. Job Story


### 7. In scope


### 8. Out of scope


### 9. Ограничения


---

## Артефакт валидации гипотезы


---

## Контрольный вопрос


---

## Результат
"""


_BLOCK1_FIELD_MAP = [
    ("problem",  r"### 1\. Проблема / Боль"),
    ("solution", r"### 2\. Решение"),
    ("usp",      r"### 3\. Ценность \(USP\)"),
    ("metric",   r"### 4\. Метрика"),
]


def _parse_domain(content: str) -> str:
    """Extract domain from YAML frontmatter.

    Looks for a line like ``domain: some-domain`` between the opening
    and closing ``---`` markers.  Returns ``"general"`` when the
    frontmatter is absent, the ``domain`` key is missing, or the value
    is empty / literally ``"general"``.
    """
    m = re.search(
        r"^---\s*\n(.*?)\n---",
        content,
        re.DOTALL | re.MULTILINE,
    )
    if not m:
        return "general"
    frontmatter = m.group(1)
    dm = re.search(r"^domain:\s*(.+)$", frontmatter, re.MULTILINE)
    if not dm:
        return "general"
    value = dm.group(1).strip().strip("\"'")
    if not value or value.lower() == "general":
        return "general"
    return value


def _is_service_file(name: str) -> bool:
    """Return True for index/log files that should not appear in the index table."""
    return name in ("index.md", "log.md")


def _update_artifact_index(domain: str, artifact_type: str) -> None:
    """Rebuild index.md for wiki/domains/<domain>/<artifact_type>/.

    Scans all .md files in the directory (excluding index.md and log.md),
    reads frontmatter via regex, and writes a Markdown table to index.md.
    Errors are caught and logged so that index update failure never breaks
    the main write operation.
    """
    try:
        artifact_dir = VAULT_PATH / "wiki" / "domains" / domain / artifact_type
        if not artifact_dir.exists():
            logger.warning(
                "_update_artifact_index: directory does not exist: %s", artifact_dir
            )
            return

        files = sorted(
            f for f in artifact_dir.glob("*.md") if not _is_service_file(f.name)
        )

        rows: list[str] = []
        for f in files:
            try:
                raw = f.read_text(encoding="utf-8")
            except Exception as read_err:
                logger.warning(
                    "_update_artifact_index: cannot read %s: %s", f.name, read_err
                )
                rows.append(f"| [[{f.name}]] | — | — | — |")
                continue

            # Extract frontmatter block
            fm_match = re.search(
                r"^---\s*\n(.*?)\n---", raw, re.DOTALL | re.MULTILINE
            )
            frontmatter = fm_match.group(1) if fm_match else ""

            def _fm_value(key: str) -> str:
                m = re.search(rf"^{key}:\s*(.+)$", frontmatter, re.MULTILINE)
                if not m:
                    return "—"
                return m.group(1).strip().strip("\"'") or "—"

            title = _fm_value("title")
            status = _fm_value("status")
            created = _fm_value("created")
            rows.append(f"| [[{f.name}]] | {title} | {status} | {created} |")

        domain_title = domain.replace("-", " ").title()
        type_title = artifact_type.replace("-", " ").title()

        header_lines = [
            "---",
            "type: index",
            f"domain: {domain}",
            f"artifact_type: {artifact_type}",
            "---",
            "",
            f"# {domain_title} — {type_title}",
            "",
            "| File | Title | Status | Created |",
            "|------|-------|--------|---------|",
        ]
        content = "\n".join(header_lines + rows) + "\n"

        index_path = artifact_dir / "index.md"
        index_path.write_text(content, encoding="utf-8")
        logger.info(
            "_update_artifact_index: wrote index.md for %s/%s (%d entries)",
            domain,
            artifact_type,
            len(rows),
        )
    except Exception as e:
        logger.error(
            "_update_artifact_index: failed for %s/%s: %s", domain, artifact_type, e
        )


def _append_artifact_log(
    domain: str, artifact_type: str, action: str, filename: str
) -> None:
    """Append a timestamped entry to wiki/domains/<domain>/<artifact_type>/log.md.

    Creates the file with a header when it does not exist yet.
    Errors are caught and logged so that log failure never breaks the main
    write operation.
    """
    try:
        artifact_dir = VAULT_PATH / "wiki" / "domains" / domain / artifact_type
        if not artifact_dir.exists():
            logger.warning(
                "_append_artifact_log: directory does not exist: %s", artifact_dir
            )
            return

        log_path = artifact_dir / "log.md"
        timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        entry = f"[{timestamp}] {action} {filename} → ok\n"

        if not log_path.exists():
            header = (
                "---\ntype: log\n"
                f"domain: {domain}\n"
                f"artifact_type: {artifact_type}\n"
                "---\n\n"
                "# Change Log\n\n"
            )
            log_path.write_text(header + entry, encoding="utf-8")
            logger.info(
                "_append_artifact_log: created log.md for %s/%s", domain, artifact_type
            )
        else:
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(entry)
            logger.info(
                "_append_artifact_log: appended %s entry for %s to %s/%s log",
                action,
                filename,
                domain,
                artifact_type,
            )
    except Exception as e:
        logger.error(
            "_append_artifact_log: failed for %s/%s: %s", domain, artifact_type, e
        )


def _max_idea_number() -> int:
    """Scan both raw/ideas and all wiki/domains/*/ideas/ directories
    for the highest existing IDEA-NNNN number.
    """
    max_num = 0
    pattern = re.compile(r"IDEA-(\d{4})-")

    # 1. Scan raw/ideas
    raw_dir = raw_ideas()
    for f in raw_dir.glob("IDEA-*.md"):
        m = pattern.match(f.name)
        if m:
            max_num = max(max_num, int(m.group(1)))

    # 2. Scan wiki/domains/*/ideas/
    domains_dir = VAULT_PATH / "wiki" / "domains"
    if domains_dir.exists():
        for domain_entry in domains_dir.iterdir():
            if not domain_entry.is_dir():
                continue
            ideas_dir = domain_entry / "ideas"
            if ideas_dir.exists():
                for f in ideas_dir.glob("IDEA-*.md"):
                    m = pattern.match(f.name)
                    if m:
                        max_num = max(max_num, int(m.group(1)))

    return max_num


def _load_idea_template() -> str:
    """Load idea template from vault templates directory.
    Falls back to hardcoded template if file is missing.
    """
    template_path = templates() / "idea.md"
    try:
        content = template_path.read_text(encoding="utf-8")
        logger.info("_load_idea_template: loaded from %s", template_path)
        return content
    except FileNotFoundError:
        logger.error(
            "_load_idea_template: template not found at %s, using fallback",
            template_path,
        )
        return _FALLBACK_TEMPLATE
    except Exception as e:
        logger.error(
            "_load_idea_template: failed to read template at %s: %s, using fallback",
            template_path, e,
        )
        return _FALLBACK_TEMPLATE


def _format_tag_yaml(tag: str) -> str:
    """Format a single tag as a YAML list item, quoting if needed."""
    if re.search(r'[^a-zA-Z0-9а-яА-ЯёЁ\-_]', tag):
        return f'  - "{tag}"'
    return f"  - {tag}"


def _fill_frontmatter(template: str, idea_id: str, idea_data: dict, today: str, readiness_pct: int) -> str:
    """Replace frontmatter field values in the template string."""
    fm_match = re.match(r"(---\s*\n)(.*?)(\n---)", template, re.DOTALL)
    if not fm_match:
        logger.error("_fill_frontmatter: no frontmatter block found in template")
        return template

    prefix = fm_match.group(1)
    fm_body = fm_match.group(2)
    suffix = fm_match.group(3)
    rest = template[fm_match.end():]

    domain = idea_data.get("domain", "general")
    tags = idea_data.get("tags", ["idea"])

    tags_yaml = "tags:\n" + "\n".join(_format_tag_yaml(t) for t in tags)

    replacements = [
        (r'^id:.*$',        f'id: "{idea_id}"'),
        (r'^domain:.*$',    f'domain: {domain}'),
        (r'^status:.*$',    'status: "Новая"'),
        (r'^readiness:.*$', f'readiness: {readiness_pct}%'),
        (r'^created:.*$',   f'created: "{today}"'),
        (r'^updated:.*$',   f'updated: "{today}"'),
        (r'^source:.*$',    'source: telegram-inbox'),
    ]

    for pattern, replacement in replacements:
        fm_body = re.sub(pattern, replacement, fm_body, count=1, flags=re.MULTILINE)

    fm_body = re.sub(
        r'^tags:.*?(?=\n[a-z]|\n---|\Z)',
        tags_yaml,
        fm_body,
        count=1,
        flags=re.MULTILINE | re.DOTALL,
    )

    result = prefix + fm_body + suffix + rest
    logger.info("_fill_frontmatter: filled id=%s, domain=%s, tags=%s", idea_id, domain, tags)
    return result


def _fill_title(content: str, title: str) -> str:
    """Replace the template H1 heading with the actual title."""
    match = re.search(r'^# .+$', content, re.MULTILINE)
    if match:
        content = content[:match.start()] + f"# {title}" + content[match.end():]
    logger.info("_fill_title: set title=%s", title[:40])
    return content


def _fill_block1(content: str, idea_data: dict) -> str:
    """Fill Block 1 sections with Claude-extracted content."""
    for field, heading_pattern in _BLOCK1_FIELD_MAP:
        value = idea_data.get(field, "").strip()
        if not value:
            logger.info("_fill_block1: field '%s' is empty, skipping", field)
            continue

        section_pattern = (
            rf"({heading_pattern}\s*\n)"
            rf"(<!-- .*?-->\s*\n)?"
        )
        match = re.search(section_pattern, content, re.DOTALL)
        if not match:
            logger.warning("_fill_block1: section '%s' not found in template", field)
            continue

        insert_pos = match.end()
        content = content[:insert_pos] + f"{value}\n" + content[insert_pos:]
        logger.info("_fill_block1: filled section '%s', len=%d", field, len(value))

    return content


def write_idea(idea_data: dict, raw_text: str) -> Path:
    """Save a structured idea to raw/ (immutable) and wiki/ (working copy).

    Takes a dict with keys: title, domain, problem, solution, usp, metric, tags.
    Reads template from vault, fills frontmatter + Block 1, saves both copies.
    Returns the wiki path.
    """
    logger.info("write_idea: saving idea, raw_text_len=%d", len(raw_text))
    try:
        domain = idea_data.get("domain", "general")
        title = idea_data.get("title", "Без названия")
        logger.info("write_idea: domain=%s, title=%s", domain, title[:40])

        today = date.today().isoformat()

        # 1. Load template
        template = _load_idea_template()

        # 2. Generate IDEA-NNNN id
        next_num = _max_idea_number() + 1
        idea_id = f"IDEA-{next_num:04d}"
        logger.info("write_idea: generated id=%s", idea_id)

        # 2.5. Calculate readiness
        filled_count = sum(1 for k in ("problem", "solution", "usp", "metric") if idea_data.get(k, "").strip())
        readiness_pct = int((filled_count / 9) * 100)
        logger.info("write_idea: readiness=%d%% (%d/9 fields filled)", readiness_pct, filled_count)

        # 3. Fill frontmatter
        content = _fill_frontmatter(template, idea_id, idea_data, today, readiness_pct)

        # 4. Fill title
        content = _fill_title(content, title)

        # 5. Fill Block 1 sections
        content = _fill_block1(content, idea_data)

        # 6. Build filename slug from raw_text
        slug = raw_text[:60].strip().replace(" ", "-").replace("/", "-")
        if len(slug) > 50:
            cut = slug[:50].rfind("-")
            slug = slug[:cut] if cut > 0 else slug[:50]
        slug = re.sub(r'[<>:"|?*\\]', '', slug)

        filename = f"IDEA-{next_num:04d}-{today}_{slug}.md"

        # 6.5. Fill source placeholders in body
        raw_rel = f"raw/inbound/ideas/{filename}"
        content = content.replace("{{source}}", "telegram-inbox")
        content = content.replace("{{raw_ref}}", raw_rel)
        logger.info("write_idea: filled source=telegram-inbox, raw_ref=%s", raw_rel)

        # 7. Save raw (immutable) copy
        raw_dir = raw_ideas()
        raw_path = raw_dir / filename
        raw_path.write_text(content, encoding="utf-8")
        logger.info("write_idea: saved raw copy to %s", raw_path)

        # 8. Save wiki (working) copy
        wiki_dir = wiki_domain_dir(domain, "ideas")
        wiki_path = wiki_dir / filename
        wiki_path.write_text(content, encoding="utf-8")
        logger.info("write_idea: saved wiki copy to %s", wiki_path)

    except Exception as e:
        logger.error("write_idea: failed to save idea: %s", e)
        raise

    # 9. Non-critical side effects: update index and log
    try:
        _update_artifact_index(domain, "ideas")
        _append_artifact_log(domain, "ideas", "CREATE", filename)
    except Exception as side_err:
        logger.error(
            "write_idea: side-effect update failed (index/log): %s", side_err
        )

    return wiki_path


def write_meeting(content: str, source_name: str) -> Path:
    """Save a meeting note to raw/ (original) and wiki/meetings/ (processed).

    Returns the wiki path.
    """
    logger.info("write_meeting: saving meeting note, source=%s", source_name)
    try:
        today = date.today().isoformat()
        base = Path(source_name).stem

        # 1. Save raw original
        raw_dir = raw_meetings()
        raw_path = raw_dir / source_name
        raw_path.write_text(content, encoding="utf-8")
        logger.info("write_meeting: saved raw copy to %s", raw_path)

        # 2. Save processed wiki copy
        wiki_dir = wiki_meetings()
        wiki_filename = f"{today}-{base}.md"
        wiki_path = wiki_dir / wiki_filename
        wiki_path.write_text(content, encoding="utf-8")
        logger.info("write_meeting: saved wiki copy to %s", wiki_path)

    except Exception as e:
        logger.error("write_meeting: failed to save meeting note: %s", e)
        raise

    # 3. Non-critical side effect: append entry to root LOG.md
    try:
        log_entry = _build_meeting_log_entry(wiki_filename, content)
        _append_wiki_root_log(log_entry)
    except Exception as side_err:
        logger.error("write_meeting: failed to append LOG.md entry: %s", side_err)

    return wiki_path


def write_jira_draft(content: str) -> Path:
    """Save a Jira ticket draft to raw/ and wiki/domains/<domain>/tasks/.

    Returns the wiki path.
    """
    logger.info("write_jira_draft: saving Jira draft")
    try:
        domain = _parse_domain(content)
        logger.info("write_jira_draft: parsed domain=%s", domain)

        today = date.today().isoformat()

        # Count existing drafts across raw and wiki to determine index
        raw_dir = raw_tasks()
        wiki_dir = wiki_domain_dir(domain, "tasks")

        existing_raw = list(raw_dir.glob(f"{today}-jira-*.md"))
        existing_wiki = list(wiki_dir.glob(f"{today}-jira-*.md"))
        idx = max(len(existing_raw), len(existing_wiki)) + 1

        filename = f"{today}-jira-{idx:02d}.md"

        # 1. Save raw copy
        raw_path = raw_dir / filename
        raw_path.write_text(content, encoding="utf-8")
        logger.info("write_jira_draft: saved raw copy to %s", raw_path)

        # 2. Save wiki copy
        wiki_path = wiki_dir / filename
        wiki_path.write_text(content, encoding="utf-8")
        logger.info("write_jira_draft: saved wiki copy to %s", wiki_path)

    except Exception as e:
        logger.error("write_jira_draft: failed to save Jira draft: %s", e)
        raise

    # 3. Non-critical side effects: update index and log.
    # These run only when the main write succeeded (no exception above).
    # Wrapped in try/except so any unexpected failure never reaches the caller.
    try:
        _update_artifact_index(domain, "tasks")
        _append_artifact_log(domain, "tasks", "CREATE", filename)
    except Exception as side_err:
        logger.error(
            "write_jira_draft: side-effect update failed (index/log): %s", side_err
        )

    return wiki_path


def write_report(content: str) -> Path:
    """Save a weekly report to wiki/reports/.

    Reports are generated artifacts -- no raw copy is needed.
    Returns the path.
    """
    logger.info("write_report: saving weekly report")
    try:
        folder = wiki_reports()
        today = date.today().isoformat()
        week = date.today().isocalendar()[1]
        filepath = folder / f"{today}-week-{week:02d}.md"
        filepath.write_text(content, encoding="utf-8")
        logger.info("write_report: saved to %s", filepath)
        return filepath
    except Exception as e:
        logger.error("write_report: failed to save report: %s", e)
        raise


def _daily_filename(directory: Path) -> str:
    """Generate the next daily-log filename using global sequence numbering."""
    return next_daily_filename(directory)


def _build_daily_log_entry(filename: str, content: str) -> str:
    """Parse daily-log content and build a LOG.md entry string.

    Extracts date, source, domains (from tags or section headings),
    and a brief summary from key sections.  Returns a single-line
    string formatted to match existing LOG.md entries.
    """
    logger.info("_build_daily_log_entry: building log entry for %s", filename)
    try:
        # --- Extract YAML frontmatter ----------------------------------------
        fm_match = re.search(
            r"^---\s*\n(.*?)\n---", content, re.DOTALL | re.MULTILINE
        )
        frontmatter = fm_match.group(1) if fm_match else ""

        # date: filename is authoritative (YYYY.MM.DD-NNN-...), frontmatter may be hallucinated
        fn_date = re.match(r"(\d{4})\.(\d{2})\.(\d{2})", filename)
        if fn_date:
            entry_date = f"{fn_date.group(1)}-{fn_date.group(2)}-{fn_date.group(3)}"
        else:
            dm = re.search(r"^date:\s*(.+)$", frontmatter, re.MULTILINE)
            entry_date = dm.group(1).strip().strip("\"'") if dm else date.today().isoformat()

        # source
        sm = re.search(r"^source:\s*(.+)$", frontmatter, re.MULTILINE)
        source = sm.group(1).strip().strip("\"'") if sm else "unknown"

        # domains from tags (supports both inline [a, b] and multiline - a\n- b)
        _SKIP_TAGS = ("daily", "daily-log", "meeting", "протокол")
        domains: list[str] = []
        inline_tags = re.search(
            r"^tags:\s*\[([^\]]+)\]", frontmatter, re.MULTILINE
        )
        multiline_tags = re.search(
            r"^tags:\s*\n((?:\s+-\s+.+\n?)+)", frontmatter, re.MULTILINE
        )
        if inline_tags:
            for raw_tag in inline_tags.group(1).split(","):
                tag_val = raw_tag.strip().strip("\"'")
                if tag_val and tag_val not in _SKIP_TAGS:
                    domains.append(tag_val)
        elif multiline_tags:
            for tag_m in re.finditer(r"-\s+(.+)", multiline_tags.group(1)):
                tag_val = tag_m.group(1).strip().strip("\"'")
                if tag_val and tag_val not in _SKIP_TAGS:
                    domains.append(tag_val)

        # Fallback: scan ## headings for domain-like keywords if no tags found
        if not domains:
            for heading_m in re.finditer(r"^##\s+(.+)$", content, re.MULTILINE):
                heading = heading_m.group(1).strip()
                if heading.lower() not in (
                    "контекст", "решения", "блокеры", "следующие шаги",
                    "участники", "итоги",
                ):
                    domains.append(heading.lower().replace(" ", "-"))
            if not domains:
                domains = ["general"]

        domains_str = ", ".join(domains)

        # --- Extract summary from ## Решения or ## Контекст -------------------
        summary = ""
        for section_title in ("Решения", "Контекст", "Итоги"):
            sec_match = re.search(
                rf"^##\s+{section_title}\s*\n(.*?)(?=\n## |\Z)",
                content,
                re.MULTILINE | re.DOTALL,
            )
            if sec_match:
                raw_text = sec_match.group(1).strip()
                # Take first meaningful lines, collapse whitespace
                lines = [
                    ln.strip().lstrip("-").lstrip("*").strip()
                    for ln in raw_text.split("\n")
                    if ln.strip() and not ln.strip().startswith("#")
                ]
                summary = " ".join(lines)
                break

        if len(summary) > 200:
            cut = summary[:200].rfind(" ")
            summary = summary[: cut if cut > 0 else 200] + "..."

        entry = (
            f"[{entry_date}] CREATE wiki/daily-logs/{filename}"
            f" ← source: {source}."
            f" Домены: {domains_str}."
            f" {summary}"
        )
        logger.info(
            "_build_daily_log_entry: built entry, date=%s, source=%s, domains=%s",
            entry_date, source, domains_str,
        )
        return entry
    except Exception as e:
        logger.error("_build_daily_log_entry: failed to build entry: %s", e)
        raise


def _build_meeting_log_entry(wiki_filename: str, content: str) -> str:
    """Parse meeting content and build a LOG.md entry string.

    Extracts date, source, domains (from tags), title (first H1),
    and a brief summary from key sections (Решения / Ключевые решения / Итоги).
    Returns a single-line string formatted to match existing LOG.md entries.
    """
    logger.info("_build_meeting_log_entry: building log entry for %s", wiki_filename)
    try:
        # --- Extract YAML frontmatter ----------------------------------------
        fm_match = re.search(
            r"^---\s*\n(.*?)\n---", content, re.DOTALL | re.MULTILINE
        )
        frontmatter = fm_match.group(1) if fm_match else ""

        # date: filename is authoritative (YYYY-MM-DD-slug.md), frontmatter may be hallucinated
        fn_date = re.match(r"(\d{4}-\d{2}-\d{2})", wiki_filename)
        if fn_date:
            entry_date = fn_date.group(1)
        else:
            dm = re.search(r"^date:\s*(.+)$", frontmatter, re.MULTILINE)
            entry_date = dm.group(1).strip().strip("\"'") if dm else date.today().isoformat()

        # source
        sm = re.search(r"^source:\s*(.+)$", frontmatter, re.MULTILINE)
        source = sm.group(1).strip().strip("\"'") if sm else "unknown"

        # domains from tags (supports both inline [a, b] and multiline - a\n- b)
        _SKIP_TAGS = ("daily", "daily-log", "meeting", "протокол")
        domains: list[str] = []
        inline_tags = re.search(
            r"^tags:\s*\[([^\]]+)\]", frontmatter, re.MULTILINE
        )
        multiline_tags = re.search(
            r"^tags:\s*\n((?:\s+-\s+.+\n?)+)", frontmatter, re.MULTILINE
        )
        if inline_tags:
            for raw_tag in inline_tags.group(1).split(","):
                tag_val = raw_tag.strip().strip("\"'")
                if tag_val and tag_val not in _SKIP_TAGS:
                    domains.append(tag_val)
        elif multiline_tags:
            for tag_m in re.finditer(r"-\s+(.+)", multiline_tags.group(1)):
                tag_val = tag_m.group(1).strip().strip("\"'")
                if tag_val and tag_val not in _SKIP_TAGS:
                    domains.append(tag_val)

        if not domains:
            domains = ["general"]

        domains_str = ", ".join(domains)

        # --- Extract title from first H1 heading -----------------------------
        title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else ""

        # --- Extract summary from key sections --------------------------------
        summary = ""
        for section_title in ("Решения", "Ключевые решения", "Итоги"):
            sec_match = re.search(
                rf"^##\s+{section_title}\s*\n(.*?)(?=\n## |\Z)",
                content,
                re.MULTILINE | re.DOTALL,
            )
            if sec_match:
                raw_text = sec_match.group(1).strip()
                lines = [
                    ln.strip().lstrip("-").lstrip("*").strip()
                    for ln in raw_text.split("\n")
                    if ln.strip() and not ln.strip().startswith("#")
                ]
                summary = " ".join(lines)
                break

        if len(summary) > 200:
            cut = summary[:200].rfind(" ")
            summary = summary[: cut if cut > 0 else 200] + "..."

        # --- Build entry string -----------------------------------------------
        entry = (
            f"[{entry_date}] CREATE wiki/meetings/{wiki_filename}"
            f" ← source: {source}."
            f" Домен: {domains_str}."
        )
        if title:
            entry += f" {title}."
        if summary:
            entry += f" {summary}"

        logger.info(
            "_build_meeting_log_entry: built entry, date=%s, source=%s, domains=%s",
            entry_date, source, domains_str,
        )
        return entry
    except Exception as e:
        logger.error("_build_meeting_log_entry: failed to build entry: %s", e)
        raise


def _append_wiki_root_log(entry: str) -> None:
    """Append a single line to wiki/LOG.md.

    The LOG.md file is expected to always exist in the vault.  If the
    file is missing for any reason, the function logs an error and
    returns without raising.
    """
    log_path = wiki_log()
    try:
        if not log_path.exists():
            logger.error(
                "_append_wiki_root_log: LOG.md does not exist at %s, skipping",
                log_path,
            )
            return

        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(entry + "\n")
        logger.info("_append_wiki_root_log: appended entry to %s", log_path)
    except Exception as e:
        logger.error("_append_wiki_root_log: failed to write to %s: %s", log_path, e)
        raise


def write_daily(content: str) -> Path:
    """Save a daily log to raw/ (immutable) and wiki/daily-logs/ (working copy).

    Returns the wiki path.
    """
    logger.info("write_daily: saving daily log, content_len=%d", len(content))
    try:
        # Generate filename from wiki dir (source of truth for numbering)
        wiki_dir = wiki_daily_logs()
        filename = _daily_filename(wiki_dir)

        # 1. Save raw (immutable) copy
        raw_dir = raw_daily_logs()
        raw_path = raw_dir / filename
        raw_path.write_text(content, encoding="utf-8")
        logger.info("write_daily: saved raw copy to %s", raw_path)

        # 2. Save wiki (working) copy
        wiki_path = wiki_dir / filename
        wiki_path.write_text(content, encoding="utf-8")
        logger.info("write_daily: saved wiki copy to %s", wiki_path)

    except Exception as e:
        logger.error("write_daily: failed to save daily log: %s", e)
        raise

    # 3. Non-critical side effect: append entry to root LOG.md
    try:
        log_entry = _build_daily_log_entry(filename, content)
        _append_wiki_root_log(log_entry)
    except Exception as side_err:
        logger.error(
            "write_daily: failed to append LOG.md entry: %s", side_err
        )

    return wiki_path
