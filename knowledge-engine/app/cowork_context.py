"""Генерация _cowork-session.md — компактный срез vault для Claude Cowork.

Модуль детерминированно собирает контекстный файл из wiki-артефактов:
daily-логи, открытые задачи, активные эпики, решения из протоколов,
лог активности. Без LLM-вызовов.

BL-151: llm_wiki как контекст для Claude Cowork.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from shared import vault_paths
from shared.file_writer import atomic_write
from shared.frontmatter_utils import read_frontmatter

logger = logging.getLogger(__name__)

# Статусы, при которых задача считается закрытой
_CLOSED_STATUSES = frozenset({"done", "cancelled", "closed", "resolved"})

# Статусы, при которых эпик считается активным
_ACTIVE_EPIC_STATUSES = frozenset({"in-progress", "todo", "planned"})

# Файлы, которые пропускаем при сканировании директорий
_SKIP_FILES = frozenset({"index.md", "log.md"})

# Лимит задач для секции (AC-10: файл < 1000 строк)
_MAX_TASKS = 200

# Regex для извлечения Jira-ключей
_JIRA_KEY_RE = re.compile(r"[A-Z][A-Z0-9]+-\d+")

# Regex для извлечения даты из имени daily-log файла
_DAILY_DATE_RE = re.compile(r"^(\d{4})\.(\d{2})\.(\d{2})")


def generate_cowork_session(vault_path: str = "") -> dict:
    """Генерирует llm_wiki/_cowork-session.md — компактный срез vault для Cowork.

    Args:
        vault_path: путь к vault root (по умолчанию VAULT_PATH из env).

    Returns:
        dict с ключами status, session_sections, generated_at (и message при ошибке).
    """
    vault_root = Path(vault_path) if vault_path else vault_paths.VAULT_PATH

    # Guard: vault доступен?
    if not vault_root.exists():
        logger.error(f"generate_cowork_session: vault not accessible at {vault_root}")
        return {"status": "error", "message": "vault not accessible"}

    logger.info(f"generate_cowork_session: starting, vault={vault_root}")

    # Собираем секции
    daily_md, daily_count = _collect_daily_logs(vault_root)
    tasks_md, tasks_count = _collect_open_tasks(vault_root)
    epics_md, epics_count = _collect_active_epics(vault_root)
    decisions_md, decisions_count = _collect_recent_decisions(vault_root)
    activity_md, activity_count = _collect_activity_log(vault_root)

    # Vault stats для frontmatter
    now = datetime.now().isoformat(timespec="seconds")
    vault_stats = {
        "daily_logs": daily_count,
        "open_tasks": tasks_count,
        "active_epics": epics_count,
        "recent_decisions": decisions_count,
        "activity_entries": activity_count,
    }

    # Формируем frontmatter (ручная сборка, не через python-frontmatter)
    frontmatter_str = (
        "---\n"
        f'generated: "{now}"\n'
        "vault_stats:\n"
        f"  daily_logs: {daily_count}\n"
        f"  open_tasks: {tasks_count}\n"
        f"  active_epics: {epics_count}\n"
        f"  recent_decisions: {decisions_count}\n"
        f"  activity_entries: {activity_count}\n"
        "---\n\n"
    )

    # Собираем файл
    content = (
        frontmatter_str
        + "# Cowork Session Context\n\n"
        + daily_md + "\n"
        + tasks_md + "\n"
        + epics_md + "\n"
        + decisions_md + "\n"
        + activity_md + "\n"
    )

    # Записываем атомарно
    output_path = vault_root / "llm_wiki" / "_cowork-session.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(output_path, content)

    logger.info(
        f"generate_cowork_session: completed — daily={daily_count} tasks={tasks_count} "
        f"epics={epics_count} decisions={decisions_count} activity={activity_count}"
    )

    return {
        "status": "ok",
        "session_sections": vault_stats,
        "generated_at": now,
    }


# ---------------------------------------------------------------------------
# Приватные коллекторы
# ---------------------------------------------------------------------------


def _collect_daily_logs(vault_root: Path, limit: int = 5) -> tuple[str, int]:
    """Собирает секцию 'Последние дейли' из wiki/daily-logs/*.md.

    Парсит frontmatter (date) и body (bullets, Jira-ключи).
    Сортирует по дате (от новых к старым), берёт первые limit файлов.
    """
    daily_dir = vault_root / "wiki" / "daily-logs"

    if not daily_dir.exists():
        logger.info(f"_collect_daily_logs: directory not found: {daily_dir}")
        return "## Последние дейли\n\n*нет данных*\n", 0

    md_files = [f for f in daily_dir.glob("*.md") if f.name.lower() not in _SKIP_FILES]
    if not md_files:
        logger.info("_collect_daily_logs: no .md files found")
        return "## Последние дейли\n\n*нет данных*\n", 0

    # Парсим файлы, собираем (date_str, bullets, jira_keys, path)
    entries: list[tuple[str, list[str], list[str]]] = []
    for path in md_files:
        try:
            meta, body = read_frontmatter(path)
        except Exception as e:
            logger.warning(f"cowork_context: skipping {path.name}: {e}")
            continue

        # Дата: frontmatter или имя файла
        date_str = _extract_date(meta, path)

        # Bullets: строки начинающиеся с "- "
        bullets = [line.strip() for line in body.splitlines() if line.strip().startswith("- ")]
        bullets = bullets[:5]  # максимум 5 пунктов на файл

        # Jira-ключи
        jira_keys = sorted(set(_JIRA_KEY_RE.findall(body)))

        entries.append((date_str, bullets, jira_keys))

    if not entries:
        logger.info("_collect_daily_logs: no valid entries after parsing")
        return "## Последние дейли\n\n*нет данных*\n", 0

    # Сортировка по дате — от новых к старым
    entries.sort(key=lambda e: e[0], reverse=True)
    entries = entries[:limit]

    # Формируем markdown
    lines = ["## Последние дейли\n"]
    for date_str, bullets, jira_keys in entries:
        lines.append(f"### {date_str}")
        for b in bullets:
            lines.append(b)
        if jira_keys:
            lines.append(f"- Jira: {', '.join(jira_keys)}")
        lines.append("")  # пустая строка между записями

    count = len(entries)
    logger.info(f"_collect_daily_logs: collected {count} entries")
    return "\n".join(lines) + "\n", count


def _collect_open_tasks(vault_root: Path) -> tuple[str, int]:
    """Собирает секцию 'Открытые задачи' из wiki/domains/*/tasks/*.md.

    Фильтрует по status NOT IN (done, cancelled, closed, resolved).
    Группирует по домену, формирует Markdown-таблицу.
    При >200 задач усекает с пометкой.
    """
    domains_dir = vault_root / "wiki" / "domains"

    if not domains_dir.exists():
        logger.info(f"_collect_open_tasks: domains directory not found: {domains_dir}")
        return "## Открытые задачи\n\n*нет данных*\n", 0

    # Собираем домены
    domain_dirs = sorted(
        d.name for d in domains_dir.iterdir() if d.is_dir()
    )

    # {domain: [(jira_key, title, status, priority), ...]}
    grouped: dict[str, list[tuple[str, str, str, str]]] = {}
    total_count = 0

    for domain in domain_dirs:
        tasks_dir = domains_dir / domain / "tasks"
        if not tasks_dir.exists():
            continue

        tasks_in_domain: list[tuple[str, str, str, str]] = []
        for path in tasks_dir.glob("*.md"):
            if path.name.lower() in _SKIP_FILES:
                continue
            try:
                meta, _body = read_frontmatter(path)
            except Exception as e:
                logger.warning(f"cowork_context: skipping {path.name}: {e}")
                continue

            status = meta.get("status", "").lower().strip() if isinstance(meta.get("status"), str) else str(meta.get("status", "")).lower().strip()
            if status in _CLOSED_STATUSES:
                continue

            jira_key = meta.get("jira_key", "") or "—"
            title = meta.get("title", path.stem)
            display_status = meta.get("status", "unknown")
            priority = meta.get("priority", "") or "—"

            tasks_in_domain.append((str(jira_key), str(title), str(display_status), str(priority)))

        if tasks_in_domain:
            grouped[domain] = tasks_in_domain
            total_count += len(tasks_in_domain)

    if total_count == 0:
        logger.info("_collect_open_tasks: no open tasks found")
        return "## Открытые задачи\n\n*нет данных*\n", 0

    # Формируем markdown
    lines = ["## Открытые задачи\n"]
    shown_count = 0
    truncated = False

    for domain in sorted(grouped.keys()):
        tasks = grouped[domain]
        lines.append(f"### {domain} ({len(tasks)})")
        lines.append("| Jira | Title | Status | Priority |")
        lines.append("|---|---|---|---|")
        for jira_key, title, status, priority in tasks:
            if shown_count >= _MAX_TASKS:
                truncated = True
                break
            lines.append(f"| {jira_key} | {title} | {status} | {priority} |")
            shown_count += 1
        lines.append("")
        if truncated:
            break

    if truncated:
        remaining = total_count - _MAX_TASKS
        lines.append(f"*... и ещё {remaining} задач*\n")

    logger.info(f"_collect_open_tasks: collected {total_count} open tasks across {len(grouped)} domains")
    return "\n".join(lines) + "\n", total_count


def _collect_active_epics(vault_root: Path) -> tuple[str, int]:
    """Собирает секцию 'Активные эпики' из wiki/domains/*/epics/*.md.

    Фильтрует по status IN (in-progress, todo, planned).
    Вычисляет progress % из tickets.
    """
    domains_dir = vault_root / "wiki" / "domains"

    if not domains_dir.exists():
        logger.info(f"_collect_active_epics: domains directory not found: {domains_dir}")
        return "## Активные эпики\n\n*нет данных*\n", 0

    domain_dirs = sorted(
        d.name for d in domains_dir.iterdir() if d.is_dir()
    )

    # [(domain, title, status, progress_str), ...]
    epics: list[tuple[str, str, str, str]] = []

    for domain in domain_dirs:
        epics_dir = domains_dir / domain / "epics"
        if not epics_dir.exists():
            continue

        for path in epics_dir.glob("*.md"):
            if path.name.lower() in _SKIP_FILES:
                continue
            try:
                meta, _body = read_frontmatter(path)
            except Exception as e:
                logger.warning(f"cowork_context: skipping {path.name}: {e}")
                continue

            status = meta.get("status", "").lower().strip() if isinstance(meta.get("status"), str) else str(meta.get("status", "")).lower().strip()
            if status not in _ACTIVE_EPIC_STATUSES:
                continue

            title = str(meta.get("title", path.stem))
            display_status = str(meta.get("status", "unknown"))

            # Progress из tickets
            tickets = meta.get("tickets", [])
            if isinstance(tickets, list) and len(tickets) > 0:
                done_count = sum(
                    1 for t in tickets
                    if isinstance(t, dict) and t.get("status", "").lower() in {"done", "closed", "resolved"}
                )
                total = len(tickets)
                pct = int(done_count / total * 100)
                progress_str = f"{pct}% ({done_count}/{total})"
            else:
                progress_str = "—"

            epics.append((domain, title, display_status, progress_str))

    if not epics:
        logger.info("_collect_active_epics: no active epics found")
        return "## Активные эпики\n\n*нет данных*\n", 0

    # Формируем markdown таблицу
    lines = ["## Активные эпики\n"]
    lines.append("| Domain | Title | Status | Progress |")
    lines.append("|---|---|---|---|")
    for domain, title, status, progress in epics:
        lines.append(f"| {domain} | {title} | {status} | {progress} |")
    lines.append("")

    count = len(epics)
    logger.info(f"_collect_active_epics: collected {count} active epics")
    return "\n".join(lines) + "\n", count


def _collect_recent_decisions(vault_root: Path, limit: int = 10) -> tuple[str, int]:
    """Собирает секцию 'Последние решения' из wiki/meetings/*.md.

    Извлекает секцию '## Решения' из каждого протокола.
    Берёт до limit решений суммарно (не файлов — решений).
    Сортирует по дате от новых к старым.
    """
    meetings_dir = vault_root / "wiki" / "meetings"

    if not meetings_dir.exists():
        logger.info(f"_collect_recent_decisions: meetings directory not found: {meetings_dir}")
        return "## Последние решения\n\n*нет данных*\n", 0

    md_files = [f for f in meetings_dir.glob("*.md") if f.name.lower() not in _SKIP_FILES]
    if not md_files:
        logger.info("_collect_recent_decisions: no .md files found")
        return "## Последние решения\n\n*нет данных*\n", 0

    # Парсим файлы: (date_str, title, decisions_bullets)
    meeting_entries: list[tuple[str, str, list[str]]] = []
    for path in md_files:
        try:
            meta, body = read_frontmatter(path)
        except Exception as e:
            logger.warning(f"cowork_context: skipping {path.name}: {e}")
            continue

        # Извлекаем секцию "Решения"
        section_lines = _extract_section_lines(body, "Решения")
        decisions = [line.strip() for line in section_lines if line.strip().startswith("- ")]
        if not decisions:
            continue

        date_str = _extract_date(meta, path)
        title = str(meta.get("title", path.stem))
        meeting_entries.append((date_str, title, decisions))

    if not meeting_entries:
        logger.info("_collect_recent_decisions: no meetings with decisions found")
        return "## Последние решения\n\n*нет данных*\n", 0

    # Сортировка по дате — от новых к старым
    meeting_entries.sort(key=lambda e: e[0], reverse=True)

    # Берём до limit решений суммарно
    lines = ["## Последние решения\n"]
    total_decisions = 0
    for date_str, title, decisions in meeting_entries:
        if total_decisions >= limit:
            break

        remaining_slots = limit - total_decisions
        decisions_to_show = decisions[:remaining_slots]

        lines.append(f"### {date_str} — {title}")
        for d in decisions_to_show:
            lines.append(d)
        lines.append("")

        total_decisions += len(decisions_to_show)

    logger.info(f"_collect_recent_decisions: collected {total_decisions} decisions")
    return "\n".join(lines) + "\n", total_decisions


def _collect_activity_log(vault_root: Path, limit: int = 10) -> tuple[str, int]:
    """Собирает секцию 'Последняя активность' из wiki/LOG.md.

    Читает plain text (без frontmatter), берёт последние limit bullet-строк.
    """
    log_path = vault_root / "wiki" / "LOG.md"

    if not log_path.exists():
        logger.info(f"_collect_activity_log: LOG.md not found: {log_path}")
        return "## Последняя активность\n\n*нет данных*\n", 0

    try:
        text = log_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"cowork_context: failed to read LOG.md: {e}")
        return "## Последняя активность\n\n*нет данных*\n", 0

    # Ищем bullet-строки
    bullets = [line for line in text.splitlines() if line.strip().startswith("- ")]

    if not bullets:
        logger.info("_collect_activity_log: no bullet entries in LOG.md")
        return "## Последняя активность\n\n*нет данных*\n", 0

    # Берём последние limit
    last_bullets = bullets[-limit:]

    lines = ["## Последняя активность\n"]
    for b in last_bullets:
        lines.append(b)
    lines.append("")

    count = len(last_bullets)
    logger.info(f"_collect_activity_log: collected {count} entries")
    return "\n".join(lines) + "\n", count


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def _extract_section_lines(body: str, header: str) -> list[str]:
    """Извлекает строки между ## header и следующим ## (или концом текста).

    Args:
        body: тело markdown-файла (без frontmatter).
        header: заголовок секции (без ##), например "Решения".

    Returns:
        Список строк секции (без заголовка). Пустой список если секция не найдена.
    """
    lines = body.splitlines()
    collecting = False
    result: list[str] = []

    for line in lines:
        stripped = line.strip()
        # Проверяем начало целевой секции
        if stripped.lower().startswith("## ") and header.lower() in stripped.lower():
            collecting = True
            continue
        # Проверяем конец секции (следующий ##)
        if collecting and stripped.startswith("## "):
            break
        if collecting:
            result.append(line)

    return result


def _extract_date(meta: dict, path: Path) -> str:
    """Извлекает дату из frontmatter или имени файла.

    Приоритет: meta["date"] -> meta["created"] -> имя файла (YYYY.MM.DD-...).
    Возвращает строку в формате YYYY-MM-DD.
    """
    for key in ("date", "created"):
        val = meta.get(key)
        if val is not None:
            # Может быть datetime, date или str
            date_str = str(val)
            # Берём только дату (первые 10 символов YYYY-MM-DD)
            if len(date_str) >= 10:
                return date_str[:10]
            return date_str

    # Fallback: из имени файла
    m = _DAILY_DATE_RE.match(path.name)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    return "unknown"
