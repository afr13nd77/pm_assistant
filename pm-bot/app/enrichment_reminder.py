"""Core logic for guided enrichment reminders.

Scans all idea notes across domains, identifies ideas with active statuses
and incomplete sections, then sends Telegram reminders with deep links
to the ideas dashboard.
"""

import asyncio
import logging
import os
import re
from pathlib import Path

from .rate_limiter import TelegramRateLimiter

logger = logging.getLogger(__name__)

_rate_limiter = TelegramRateLimiter()

ACTIVE_STATUSES = frozenset({"Новая", "Проверка гипотезы"})

SECTION_DISPLAY_NAMES = {
    r"### 1\.": "Проблема / Боль",
    r"### 2\.": "Решение",
    r"### 3\.": "Ценность (USP)",
    r"### 4\.": "Метрика",
    r"### 5\.": "Сегмент (Кто)",
    r"### 6\.": "Job Story",
    r"### 7\.": "In scope",
    r"### 8\.": "Out of scope",
    r"### 9\.": "Ограничения",
}

REMINDER_TEMPLATE = (
    "\U0001f4cb *{idea_id}* — {title}\n"
    "\n"
    "Readiness: *{readiness}%* → нужно "
    "заполнить {count} "
    "{field_word}:\n"
    "{sections_list}\n"
    "\n"
    "\U0001f517 [Открыть на ideas.html]({link_url})"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pluralize_field(n: int) -> str:
    """Russian pluralization for the word 'поле' (field).

    Rules:
    - 11-19 -> 'полей'
    - last digit 1 -> 'поле'
    - last digit 2-4 -> 'поля'
    - else -> 'полей'
    """
    if 11 <= (n % 100) <= 19:
        return "полей"
    last = n % 10
    if last == 1:
        return "поле"
    if 2 <= last <= 4:
        return "поля"
    return "полей"


def _get_empty_sections(body: str) -> list[str]:
    """Return display names for sections that are empty or missing.

    Uses the same logic as ``_calculate_readiness()`` in vault_api.py but
    collects the *empty* section names instead of counting filled ones.
    """
    empty: list[str] = []

    for heading_pat, display_name in SECTION_DISPLAY_NAMES.items():
        match = re.search(heading_pat, body)
        if not match:
            empty.append(display_name)
            continue

        rest = body[match.end():]

        # Find the end boundary: next ### or ## or --- or end of string
        boundary = re.search(r"^(?:###\s|##\s|---)", rest, re.MULTILINE)
        section_text = rest[: boundary.start()] if boundary else rest

        # Strip HTML comments (possibly multi-line)
        section_text = re.sub(r"<!--.*?-->", "", section_text, flags=re.DOTALL)

        # Strip the remainder of the heading line itself
        section_text = re.sub(r"^[^\n]*\n?", "", section_text, count=1)

        section_text = section_text.strip()

        if not section_text:
            empty.append(display_name)

    logger.info("_get_empty_sections: %d empty sections found", len(empty))
    return empty


def _build_reminder_message(idea: dict, host_url: str) -> str:
    """Build a Markdown-formatted Telegram reminder for an idea.

    Args:
        idea: dict with keys: id, title, readiness, empty_sections.
        host_url: base URL for the ideas dashboard.

    Returns:
        Formatted reminder string.
    """
    sections_list = "\n".join("• " + name for name in idea["empty_sections"])
    link_url = f"{host_url}/ideas.html?highlight={idea['id']}"
    count = len(idea["empty_sections"])
    field_word = _pluralize_field(count)

    message = REMINDER_TEMPLATE.format(
        idea_id=idea["id"],
        title=idea["title"],
        readiness=idea["readiness"],
        count=count,
        field_word=field_word,
        sections_list=sections_list,
        link_url=link_url,
    )
    logger.info("_build_reminder_message: built message for %s, length=%d", idea["id"], len(message))
    return message


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


def _scan_all_ideas() -> list[dict]:
    """Scan all domain idea files and return enrichment metadata.

    Returns:
        List of dicts with keys: path, filename, id, title, status,
        readiness, empty_sections, domain.
    """
    from shared.vault_paths import all_domains, wiki_domain_dir

    from .vault_parsers import _calculate_readiness, parse_note

    results: list[dict] = []
    domains = all_domains()
    logger.info("_scan_all_ideas: found %d domains", len(domains))

    for domain in domains:
        ideas_dir = wiki_domain_dir(domain, "ideas")
        md_files = sorted(ideas_dir.glob("*.md"))
        logger.info("_scan_all_ideas: domain=%s, %d idea files", domain, len(md_files))

        for md_path in md_files:
            try:
                note = parse_note(md_path)
                body = note.get("body", "")
                status = note.get("status", "")
                title = note.get("title", md_path.stem)
                readiness = _calculate_readiness(body)
                empty_sections = _get_empty_sections(body)

                # Extract IDEA-NNNN from filename
                id_match = re.search(r"(IDEA-\d{4})", md_path.name)
                idea_id = id_match.group(1) if id_match else md_path.stem

                results.append({
                    "path": str(md_path),
                    "filename": md_path.name,
                    "id": idea_id,
                    "title": title,
                    "status": status,
                    "readiness": readiness,
                    "empty_sections": empty_sections,
                    "domain": domain,
                })
            except Exception as exc:
                logger.error("_scan_all_ideas: failed to process %s: %s", md_path, exc)
                continue

    logger.info("_scan_all_ideas: total %d ideas scanned", len(results))
    return results


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


async def run_enrichment_check(bot, chat_id: int) -> None:
    """Scan all ideas and send enrichment reminders for incomplete ones.

    Args:
        bot: Telegram bot instance (must support ``send_message``).
        chat_id: Telegram chat to send reminders to.
    """
    logger.info("run_enrichment_check: start")
    try:
        from shared.system_log import LoggedProcess
        from shared.vault_paths import VAULT_PATH

        from .enrichment_db import get_reminded_today, init_db, record_reminder

        with LoggedProcess(process_type="enrichment-reminder", source="pm-bot") as lp:
            db_path = Path(os.getenv("PM_BOT_DATA_PATH", str(VAULT_PATH))) / ".enrichment-reminders.db"
            init_db(db_path)

            reminded_today = get_reminded_today(db_path)
            ideas = _scan_all_ideas()
            host_url = os.getenv("ENRICHMENT_HOST_URL", "http://localhost:8080")
            sent_count = 0
            skipped_cooldown = 0

            for idea in ideas:
                idea_id = idea["id"]

                if idea["status"] not in ACTIVE_STATUSES:
                    logger.info(
                        "run_enrichment_check: %s status=%s, skip (not active)",
                        idea_id, idea["status"],
                    )
                    continue

                if idea["readiness"] >= 100:
                    logger.info("run_enrichment_check: %s readiness=100%%, skip", idea_id)
                    continue

                if idea_id in reminded_today:
                    logger.info("run_enrichment_check: %s already sent today, skip", idea_id)
                    skipped_cooldown += 1
                    continue

                if not idea["empty_sections"]:
                    logger.info("run_enrichment_check: %s no empty sections, skip", idea_id)
                    continue

                try:
                    message = _build_reminder_message(idea, host_url)
                    await _rate_limiter.acquire()
                    try:
                        await bot.send_message(
                            chat_id=chat_id, text=message, parse_mode="Markdown",
                        )
                    except Exception as send_err:
                        # Handle Telegram 429 RetryAfter
                        from telegram.error import RetryAfter
                        if isinstance(send_err, RetryAfter):
                            _rate_limiter.on_retry_after(send_err.retry_after)
                            await asyncio.sleep(send_err.retry_after)
                            await bot.send_message(
                                chat_id=chat_id, text=message, parse_mode="Markdown",
                            )
                        else:
                            raise
                    logger.info(
                        "run_enrichment_check: sent reminder for %s to chat_id=%s",
                        idea_id, chat_id,
                    )

                    record_reminder(
                        db_path, idea_id, idea["filename"],
                        idea["readiness"], idea["empty_sections"],
                    )
                    sent_count += 1
                except Exception as send_err:
                    logger.error(
                        "run_enrichment_check: failed to send reminder for %s: %s",
                        idea_id, send_err,
                    )
                    continue

            lp.summary = f"{sent_count} напоминаний отправлено из {len(ideas)} идей"
            lp.details = {
                "ideas_scanned": len(ideas),
                "reminders_sent": sent_count,
                "skipped_cooldown": skipped_cooldown,
            }

            logger.info(
                "run_enrichment_check: complete — %d ideas scanned, %d reminders sent",
                len(ideas), sent_count,
            )
    except Exception as e:
        logger.error("run_enrichment_check: failed: %s", e, exc_info=True)


def run_enrichment_check_sync(bot, chat_id: int) -> None:
    """Sync wrapper for ``run_enrichment_check``.

    Follows the same async dispatch pattern used by ``_run_weekly_report``
    in scheduler.py.
    """
    logger.info("enrichment_reminder: cron triggered")
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(run_enrichment_check(bot, chat_id))
        else:
            loop.run_until_complete(run_enrichment_check(bot, chat_id))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_enrichment_check(bot, chat_id))
    logger.info("enrichment_reminder: cron execution dispatched")
