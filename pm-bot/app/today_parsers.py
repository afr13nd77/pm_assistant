"""today_parsers.py — Parsers for the "Today" page data sources.

Provides functions for locating and parsing morning-digest files
from the Obsidian vault.  Additional parsers (TODOs, news) will be
added by subsequent tasks.
"""

import logging
import re
from datetime import date, timedelta
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# File lookup
# ---------------------------------------------------------------------------


def find_latest_file(
    directory: Path, prefix: str, today: date
) -> tuple[Path | None, bool]:
    """Find a vault file for *today*; fall back to the most recent one.

    Searches *directory* for a file whose name starts with
    ``{YYYY-MM-DD}-{prefix}``.  If a file matching today's date is found
    the function returns ``(path, True)``.  Otherwise it scans all
    ``*-{prefix}*.md`` files, sorts them by name descending, and returns
    the first match as ``(path, False)``.

    Returns ``(None, False)`` when no matching file exists at all.
    """
    logger.info(
        f"find_latest_file: directory={directory}, prefix={prefix}, today={today}"
    )

    today_prefix = f"{today.strftime('%Y-%m-%d')}-{prefix}"

    # 1. Try exact today match
    try:
        for f in directory.iterdir():
            if f.is_file() and f.name.startswith(today_prefix):
                logger.info(f"find_latest_file: found today's file {f.name}")
                return (f, True)
    except FileNotFoundError:
        logger.error(f"find_latest_file: directory does not exist: {directory}")
        return (None, False)
    except OSError as exc:
        logger.error(f"find_latest_file: OS error scanning {directory}: {exc}")
        return (None, False)

    # 2. Fallback — most recent file matching the prefix pattern
    pattern = f"*-{prefix}*.md"
    try:
        candidates = sorted(directory.glob(pattern), key=lambda p: p.name, reverse=True)
    except OSError as exc:
        logger.error(f"find_latest_file: glob error for {pattern}: {exc}")
        return (None, False)

    if candidates:
        chosen = candidates[0]
        logger.info(
            f"find_latest_file: no today file, falling back to {chosen.name}"
        )
        return (chosen, False)

    logger.info(f"find_latest_file: no files matching prefix '{prefix}' in {directory}")
    return (None, False)


# ---------------------------------------------------------------------------
# Wikilink extraction helper
# ---------------------------------------------------------------------------

_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def _extract_wikilinks(text: str) -> list[str]:
    """Return all ``[[wikilink]]`` targets found in *text*."""
    return _WIKILINK_RE.findall(text)


# ---------------------------------------------------------------------------
# Section key helper
# ---------------------------------------------------------------------------


def _label_to_key(label: str) -> str:
    """Convert a human-readable section label to a snake_case key.

    >>> _label_to_key("Идеи и бэклог")
    'идеи_бэклог'
    """
    return label.lower().replace(" ", "_").replace("_и_", "_")


# ---------------------------------------------------------------------------
# Morning-digest parser
# ---------------------------------------------------------------------------

_SECTION_RE = re.compile(r"^### ([^\n]+)\n(.*?)(?=^### |\Z)", re.MULTILINE | re.DOTALL)


def parse_digest(text: str) -> dict:
    """Parse a morning-digest markdown string into a structured dict.

    The input is plain markdown (no YAML frontmatter).  The function
    extracts ``### Фокус дня`` as the focus block and every other
    ``###``-level section into a list.

    Returns a dict with keys ``focus``, ``sections``, and
    ``full_markdown``.
    """
    logger.info("parse_digest: start parsing digest text")

    if not text or not text.strip():
        logger.info("parse_digest: empty input, returning empty result")
        return {"focus": None, "sections": [], "full_markdown": None}

    result: dict = {
        "focus": None,
        "sections": [],
        "full_markdown": text,
    }

    matches = _SECTION_RE.findall(text)
    if not matches:
        logger.info("parse_digest: no ### sections found")
        return result

    for label, body in matches:
        label = label.strip()
        body = body.strip()

        if label.lower() == "фокус дня":
            result["focus"] = _parse_focus(body)
        else:
            result["sections"].append(_parse_section(label, body))

    section_count = len(result["sections"])
    has_focus = result["focus"] is not None
    logger.info(
        f"parse_digest: done — focus={'yes' if has_focus else 'no'}, "
        f"sections={section_count}"
    )
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_focus(body: str) -> dict:
    """Parse the body of the 'Фокус дня' section."""
    lines = [ln for ln in body.splitlines() if ln.strip()]
    title = lines[0].strip() if lines else ""
    description = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
    wikilinks = _extract_wikilinks(body)
    return {"title": title, "description": description, "wikilinks": wikilinks}


def _parse_section(label: str, body: str) -> dict:
    """Parse a generic ``### Label`` section into items.

    Supports two formats:
    1. Bullet lists (lines starting with ``- ``).
    2. Markdown tables (lines starting with ``|``).

    Bullets are tried first; if none are found, the function falls back
    to table parsing.
    """
    # --- attempt 1: bullet list ---
    raw_items = re.split(r"\n- ", "\n" + body)
    # First element is text before the first "- " — skip it.
    raw_items = [item.strip() for item in raw_items[1:] if item.strip()]

    items: list[dict] = []
    for raw in raw_items:
        # First line is the title; the rest is details
        item_lines = raw.splitlines()
        title = item_lines[0].strip() if item_lines else ""
        details = "\n".join(item_lines[1:]).strip() if len(item_lines) > 1 else ""
        wikilinks = _extract_wikilinks(raw)
        items.append({"title": title, "details": details, "wikilinks": wikilinks})

    # --- attempt 2: markdown table (only when no bullets found) ---
    if not items:
        items = _parse_table_rows(body)
        if items:
            logger.info(
                f"_parse_section: label='{label}' parsed as table, "
                f"rows={len(items)}"
            )

    return {
        "key": _label_to_key(label),
        "label": label,
        "count": len(items),
        "items": items,
    }


_TABLE_SEPARATOR_RE = re.compile(r"^\|[\s\-:|]+\|$")


def _parse_table_rows(body: str) -> list[dict]:
    """Extract data rows from a markdown table in *body*.

    Skips the header row and the separator row (``|---|---|``).
    Returns a list of item dicts with ``title``, ``details``, and
    ``wikilinks`` keys.
    """
    table_lines: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("|"):
            table_lines.append(stripped)

    if len(table_lines) < 3:
        # Need at least header + separator + 1 data row
        return []

    # Validate that the second line is a separator
    if not _TABLE_SEPARATOR_RE.match(table_lines[1]):
        logger.info("_parse_table_rows: second table line is not a separator, skipping")
        return []

    # Data rows start after header (index 0) and separator (index 1)
    items: list[dict] = []
    for row_line in table_lines[2:]:
        cells = [c.strip() for c in row_line.split("|")]
        # split("|") on "|a|b|c|" gives ['', 'a', 'b', 'c', '']
        # Remove empty edge cells from the leading/trailing pipes
        cells = [c for c in cells if c != ""]

        if not cells:
            continue

        # title = second column (index 1) if available, else first
        if len(cells) >= 2:
            title = cells[1]
            other_cells = [cells[0]] + cells[2:]
        else:
            title = cells[0]
            other_cells = []

        details = " · ".join(other_cells) if other_cells else ""
        wikilinks = _extract_wikilinks(row_line)
        items.append({"title": title, "details": details, "wikilinks": wikilinks})

    logger.info(f"_parse_table_rows: extracted {len(items)} data rows")
    return items


# ---------------------------------------------------------------------------
# TODO parser
# ---------------------------------------------------------------------------

_TODO_HEADER_RE = re.compile(r"^### \[TODO-(\d+)\] (.+)$", re.MULTILINE)
_FIELD_STATUS_RE = re.compile(r"\*\*Статус:\*\*\s*(.+)")
_FIELD_CREATED_RE = re.compile(r"\*\*Создано:\*\*\s*(.+)")
_FIELD_DUE_RE = re.compile(r"\*\*Срок:\*\*\s*(.+)")
_FIELD_CLOSED_RE = re.compile(r"\*\*Закрыто:\*\*\s*(.+)")
_FIELD_CONTEXT_RE = re.compile(r"\*\*Контекст:\*\*\s*(.+)")
_FIELD_JIRA_RE = re.compile(r"\*\*Jira:\*\*\s*(.+)")
_FIELD_RESULT_RE = re.compile(r"\*\*Результат:\*\*\s*(.+)")
_DATE_FULL_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
_DATE_SHORT_RE = re.compile(r"(\d{2})\.(\d{2})")


def _parse_dd_mm_yyyy(raw: str) -> str | None:
    """Convert DD.MM.YYYY string to ISO date YYYY-MM-DD, or None."""
    m = _DATE_FULL_RE.search(raw)
    if m:
        dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
        return f"{yyyy}-{mm}-{dd}"
    return None


def _parse_due_date(raw: str) -> str | None:
    """Extract a concrete date from a due_date_raw string.

    Supports full DD.MM.YYYY and short DD.MM (assumes current year).
    Returns ISO date string or None.
    """
    m_full = _DATE_FULL_RE.search(raw)
    if m_full:
        dd, mm, yyyy = m_full.group(1), m_full.group(2), m_full.group(3)
        return f"{yyyy}-{mm}-{dd}"
    m_short = _DATE_SHORT_RE.search(raw)
    if m_short:
        dd, mm = m_short.group(1), m_short.group(2)
        yyyy = str(date.today().year)
        return f"{yyyy}-{mm}-{dd}"
    return None


def _extract_field(pattern: re.Pattern[str], block: str) -> str | None:
    """Return the first capture group of *pattern* in *block*, or None."""
    m = pattern.search(block)
    return m.group(1).strip() if m else None


def _extract_multiline_text(block: str, field_name: str) -> str | None:
    """Extract multiline text for a ``**Field:**`` field in a TODO block.

    Finds ``**{field_name}:**`` and collects the inline text plus all
    subsequent lines until the next ``**...**:`` field or ``---`` separator.
    Returns the joined text stripped, or None if the field is absent.
    """
    pattern = re.compile(
        rf"\*\*{re.escape(field_name)}:\*\*\s*(.*)", re.IGNORECASE
    )
    lines = block.splitlines()
    found_idx: int | None = None
    first_line_text = ""

    for i, line in enumerate(lines):
        m = pattern.match(line.strip())
        if m:
            found_idx = i
            first_line_text = m.group(1).strip()
            break

    if found_idx is None:
        return None

    # Collect continuation lines
    continuation: list[str] = []
    for line in lines[found_idx + 1 :]:
        stripped = line.strip()
        # Stop at next field (e.g. **Срок:** ...) or separator
        if re.match(r"\*\*[^*]+:\*\*", stripped):
            break
        if stripped == "---":
            break
        if stripped:
            continuation.append(stripped)
        elif continuation:
            # Empty line after content — stop (but don't stop on leading empty lines)
            break

    parts = [first_line_text] + continuation if first_line_text else continuation
    result = "\n".join(parts).strip()
    logger.info(
        f"_extract_multiline_text: field='{field_name}', "
        f"lines_collected={len(parts)}"
    )
    return result if result else None


def _extract_multiline_field(block: str, field_name: str) -> list[str]:
    """Extract bullet items from a multiline ``**Field:**`` section.

    Finds ``**{field_name}:**`` and collects all subsequent ``- item`` lines
    until the next ``**...**:`` field, ``---`` separator, or a non-bullet
    non-empty line after bullets have started.

    Returns a list of bullet texts (without leading ``- ``), or [].
    """
    pattern = re.compile(
        rf"\*\*{re.escape(field_name)}:\*\*", re.IGNORECASE
    )
    lines = block.splitlines()
    found_idx: int | None = None

    for i, line in enumerate(lines):
        if pattern.match(line.strip()):
            found_idx = i
            break

    if found_idx is None:
        logger.info(f"_extract_multiline_field: field '{field_name}' not found")
        return []

    items: list[str] = []
    for line in lines[found_idx + 1 :]:
        stripped = line.strip()
        # Stop at next field or separator
        if stripped.startswith("**") and re.match(r"\*\*[^*]+\*\*:", stripped):
            break
        if stripped == "---":
            break
        if stripped.startswith("- "):
            items.append(stripped[2:].strip())
        elif not stripped and items:
            # Empty line after bullets — stop
            break
        elif stripped and items:
            # Non-bullet, non-empty line after we started collecting — stop
            break

    logger.info(
        f"_extract_multiline_field: field='{field_name}', items={len(items)}"
    )
    return items


def parse_todos(text: str) -> list[dict]:
    """Parse a ``todo.md`` string (with YAML frontmatter) into TODO items.

    The file must have ``type: personal-todo`` in frontmatter.  Each TODO
    is delimited by a ``### [TODO-NNN] Title`` header.  Returns a list of
    dicts sorted by due_date ascending (items without a due_date come last).
    """
    logger.info("parse_todos: start parsing TODO text")

    if not text or not text.strip():
        logger.info("parse_todos: empty input")
        return []

    # --- frontmatter ---
    if not text.startswith("---"):
        logger.info("parse_todos: no frontmatter delimiter found")
        return []

    parts = text.split("---", 2)
    if len(parts) < 3:
        logger.info("parse_todos: incomplete frontmatter")
        return []

    try:
        meta = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        logger.error(f"parse_todos: YAML parse error: {exc}")
        return []

    if not isinstance(meta, dict) or meta.get("type") != "personal-todo":
        logger.info(
            f"parse_todos: frontmatter type is '{meta.get('type') if isinstance(meta, dict) else None}', "
            f"expected 'personal-todo'"
        )
        return []

    body = parts[2]

    # --- split by TODO headers ---
    headers = list(_TODO_HEADER_RE.finditer(body))
    if not headers:
        logger.info("parse_todos: no TODO headers found in body")
        return []

    today = date.today()
    urgent_threshold = today + timedelta(days=3)
    todos: list[dict] = []

    for idx, match in enumerate(headers):
        todo_num = match.group(1)
        title = match.group(2).strip()
        todo_id = f"TODO-{todo_num}"

        # Block text = from this header to next header (or end of body)
        block_start = match.end()
        block_end = headers[idx + 1].start() if idx + 1 < len(headers) else len(body)
        block = body[block_start:block_end]

        status = _extract_field(_FIELD_STATUS_RE, block)
        created_raw = _extract_field(_FIELD_CREATED_RE, block)
        due_date_raw = _extract_field(_FIELD_DUE_RE, block)
        closed_raw = _extract_field(_FIELD_CLOSED_RE, block)
        context = _extract_multiline_text(block, "Контекст")
        jira = _extract_field(_FIELD_JIRA_RE, block)
        result = _extract_field(_FIELD_RESULT_RE, block)
        questions = _extract_multiline_field(block, "Нужно ответить")

        created = _parse_dd_mm_yyyy(created_raw) if created_raw else None
        due_date = _parse_due_date(due_date_raw) if due_date_raw else None
        closed = _parse_dd_mm_yyyy(closed_raw) if closed_raw else None

        # Urgency: due_date exists and <= 3 days from today
        is_urgent = False
        if due_date:
            try:
                due_dt = date.fromisoformat(due_date)
                is_urgent = due_dt <= urgent_threshold
            except ValueError:
                logger.warning(f"parse_todos: invalid due_date ISO '{due_date}' for {todo_id}")

        wikilinks = _extract_wikilinks(block)

        todos.append(
            {
                "id": todo_id,
                "title": title,
                "status": status,
                "created": created,
                "due_date": due_date,
                "due_date_raw": due_date_raw,
                "closed": closed,
                "context": context,
                "jira": jira,
                "result": result,
                "questions": questions,
                "wikilinks": wikilinks,
                "is_urgent": is_urgent,
            }
        )

    # Sort: items with due_date first (ascending), then without
    todos.sort(key=lambda t: (t["due_date"] is None, t["due_date"] or ""))

    logger.info(f"parse_todos: parsed {len(todos)} TODO items")
    return todos


# ---------------------------------------------------------------------------
# TODO block formatter
# ---------------------------------------------------------------------------


def format_todo_block(
    todo_id: str,
    title: str,
    status: str,
    created: str,
    due_date: str | None,
    context: str | None,
    result: str | None,
    questions: list[str] | None = None,
) -> str:
    """Generate a markdown block for a new or updated TODO item.

    Used by POST/PATCH endpoints to produce the markdown that gets
    written into the vault ``todo.md`` file.
    """
    logger.info(f"format_todo_block: generating block for {todo_id}")
    lines = [f"\n### [{todo_id}] {title}\n"]
    lines.append(f"**Статус:** {status}")
    lines.append(f"**Создано:** {created}")
    if due_date:
        lines.append(f"**Срок:** {due_date}")
    if context:
        lines.append(f"**Контекст:** {context}")
    if questions:
        lines.append("**Нужно ответить:**")
        for q in questions:
            lines.append(f"- {q}")
    if result:
        lines.append(f"**Результат:** {result}")
    logger.info(f"format_todo_block: block for {todo_id} generated ({len(lines)} lines)")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Section extraction helper (## level)
# ---------------------------------------------------------------------------


def _extract_section(body: str, heading: str) -> str:
    """Извлечь текст секции ``## heading`` до следующей ``##`` или конца."""
    pattern = rf"^## {re.escape(heading)}\s*\n(.*?)(?=^## |\Z)"
    match = re.search(pattern, body, re.MULTILINE | re.DOTALL)
    return match.group(1).strip() if match else ""


# ---------------------------------------------------------------------------
# Daily-news parser
# ---------------------------------------------------------------------------

_NEWS_ITEM_RE = re.compile(
    r"- \*\*\[(.+?)\]\((.+?)\)\*\*\s*[—–\-]\s*(.+?)\n\s+(.+?)(?=\n- |\n## |\Z)",
    re.DOTALL,
)


def parse_news(text: str) -> dict:
    """Parse a daily-news markdown file (with YAML frontmatter) into a structured dict.

    Returns a dict with ``categories`` containing ``competitors`` and ``ai_llm``
    lists.  Each item has ``title``, ``url``, ``source``, and ``summary`` keys.
    """
    logger.info("parse_news: start parsing daily-news text")

    empty: dict = {"categories": {"competitors": [], "ai_llm": []}}

    if not text or not text.strip():
        logger.info("parse_news: empty input, returning empty result")
        return empty

    # --- frontmatter extraction ---
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                meta = yaml.safe_load(parts[1])
            except yaml.YAMLError as e:
                logger.warning(f"parse_news: YAML frontmatter parse error: {e}, attempting fallback")
                if "type: daily-news" in parts[1]:
                    meta = {"type": "daily-news"}
                else:
                    return empty
        else:
            meta = {}
        body = parts[2] if len(parts) >= 3 else text
    else:
        logger.info("parse_news: no frontmatter found, returning empty result")
        return empty

    if not isinstance(meta, dict):
        logger.error(f"parse_news: frontmatter is not a dict: {type(meta)}")
        return empty

    if meta.get("type") != "daily-news":
        logger.info(
            f"parse_news: type is '{meta.get('type')}', expected 'daily-news'; "
            f"returning empty result"
        )
        return empty

    # --- extract sections ---
    competitors_raw = _extract_section(body, "Конкуренты")
    ai_llm_raw = _extract_section(body, "AI / LLM")

    competitors = _parse_news_items(competitors_raw, "competitors")
    ai_llm = _parse_news_items(ai_llm_raw, "ai_llm")

    logger.info(
        f"parse_news: done — competitors={len(competitors)}, ai_llm={len(ai_llm)}"
    )
    return {"categories": {"competitors": competitors, "ai_llm": ai_llm}}


def _parse_news_items(section_text: str, category: str) -> list[dict]:
    """Parse bullet items from a news section into a list of dicts."""
    if not section_text:
        logger.info(f"_parse_news_items: section '{category}' is empty")
        return []

    items: list[dict] = []
    for match in _NEWS_ITEM_RE.finditer(section_text):
        title = match.group(1).strip()
        url = match.group(2).strip()
        source = match.group(3).strip()
        summary = match.group(4).strip()
        items.append(
            {"title": title, "url": url, "source": source, "summary": summary}
        )

    logger.info(f"_parse_news_items: parsed {len(items)} items from '{category}'")
    return items
