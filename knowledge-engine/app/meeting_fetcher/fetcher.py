"""
Fetcher orchestrator for Meeting Fetcher pipeline (BL-145 refactor).

After the meeting-processing-queue refactor (design §1.3, §3.1) the Fetch phase
is LLM-free: it only fills the file-based queue. The pipeline is now:

    IMAP fetch -> dedup gate (is_enqueued | is_processed) -> enqueue() to pending/

LLM processing (Claude), classification, wiki write, jira sync, enrichment and
per-protocol notifications moved to the Process phase (processor.py). The helper
functions below (``_inject_source_file``, ``_build_fetcher_log_entry``,
``_unique_filepath``, ``save_raw_fallback``) are kept here intentionally — they
are reused/migrated by the Process worker; only their CALLS were removed from
``fetch_new_meetings``.
"""

import logging
import os
import re
from datetime import datetime
from pathlib import Path

import requests

from shared.meeting_queue import enqueue

from .imap_client import EmailAttachment, IMAPError, fetch_emails
from .state import State

logger = logging.getLogger(__name__)


def _notify(message: str) -> bool:
    """Send plain-text Telegram notification (no parse_mode / no Markdown).

    Uses BOT_TOKEN and ALLOWED_CHAT_ID from environment variables.
    Returns True on success, False on failure (never raises).
    """

    bot_token = os.getenv("BOT_TOKEN")
    chat_id = os.getenv("ALLOWED_CHAT_ID")
    if not bot_token or not chat_id:
        logger.error("Cannot send notification: BOT_TOKEN or ALLOWED_CHAT_ID not set")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        logger.info("Notification sent OK")
        return True
    except Exception as e:
        logger.error("Notification failed: %s", e)
        return False


def _is_daily(attachment: EmailAttachment) -> bool:
    """Return True if the attachment belongs to a daily stand-up transcript.

    Detection is case-insensitive and checks both the email subject and
    the attachment filename so that either signal is sufficient.

    Args:
        attachment: The email attachment to inspect.

    Returns:
        True when "daily" appears in subject or filename, False otherwise.
    """
    subject_match = "daily" in attachment.subject.lower()
    filename_match = "daily" in attachment.filename.lower()
    is_daily = subject_match or filename_match
    logger.debug(
        "_is_daily: message_id=%s subject_match=%s filename_match=%s result=%s",
        attachment.message_id,
        subject_match,
        filename_match,
        is_daily,
    )
    return is_daily


def _build_fetcher_log_entry(
    filename: str,
    protocol_type: str,
    protocol_md: str,
    msg_date: datetime,
    target_folder: str,
) -> str:
    """Build a LOG.md entry string for a fetcher-processed protocol.

    Extracts date from the filename, domains from YAML frontmatter tags,
    and a brief summary from key sections.  Returns a single-line string
    formatted to match existing LOG.md entries.

    Args:
        filename: Vault filename (e.g. ``2026.05.25-135-Daily-summary.md``).
        protocol_type: Protocol classification (daily / sync / review / planning).
        protocol_md: Full markdown content of the protocol.
        msg_date: Email date as datetime (fallback for date extraction).
        target_folder: Vault-relative folder (e.g. ``wiki/daily-logs``).

    Returns:
        A single-line LOG.md entry string.
    """
    logger.info("_build_fetcher_log_entry: building entry for %s", filename)
    try:
        # --- Date extraction from filename -----------------------------------
        # Daily format: YYYY.MM.DD-NNN-Daily-summary.md
        daily_date = re.match(r"(\d{4})\.(\d{2})\.(\d{2})", filename)
        # Meeting format: YYYY-MM-DD-HHMM-slug.md
        meeting_date = re.match(r"(\d{4}-\d{2}-\d{2})", filename)

        if daily_date:
            entry_date = (
                f"{daily_date.group(1)}-{daily_date.group(2)}-"
                f"{daily_date.group(3)}"
            )
        elif meeting_date:
            entry_date = meeting_date.group(1)
        else:
            entry_date = msg_date.strftime("%Y-%m-%d")
            logger.debug(
                "_build_fetcher_log_entry: date fallback to msg_date=%s",
                entry_date,
            )

        # --- YAML frontmatter extraction -------------------------------------
        fm_match = re.search(
            r"^---\s*\n(.*?)\n---", protocol_md, re.DOTALL | re.MULTILINE
        )
        frontmatter = fm_match.group(1) if fm_match else ""

        # --- Domains from tags -----------------------------------------------
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

        # --- Summary from key sections ----------------------------------------
        summary = ""
        for section_title in ("Решения", "Ключевые решения", "Контекст", "Итоги"):
            sec_match = re.search(
                rf"^##\s+{section_title}\s*\n(.*?)(?=\n## |\Z)",
                protocol_md,
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
            f"[{entry_date}] CREATE {target_folder}/{filename}"
            f" ← source: email/telemost."
            f" Тип: {protocol_type}."
            f" Домены: {domains_str}."
        )
        if summary:
            entry += f" {summary}"

        logger.info(
            "_build_fetcher_log_entry: built entry, date=%s, type=%s, domains=%s",
            entry_date,
            protocol_type,
            domains_str,
        )
        return entry
    except Exception as e:
        logger.error("_build_fetcher_log_entry: failed to build entry: %s", e)
        raise


def _inject_source_file(protocol_md: str, raw_rel_path: str) -> str:
    """Inject source_file into frontmatter and update footer with wikilink."""
    logger.info(
        "_inject_source_file: injecting source_file=%s", raw_rel_path,
    )
    result = protocol_md

    # 1. Inject into frontmatter — find closing --- delimiter
    fm_match = re.match(r"(---\s*\n.*?\n)(---)", result, re.DOTALL)
    if fm_match:
        fm_body = fm_match.group(1)
        fm_close = fm_match.group(2)
        rest = result[fm_match.end():]
        # Quote path if it contains YAML-special characters
        if any(c in raw_rel_path for c in ':#[]{}'):
            quoted_path = f'"{raw_rel_path}"'
            logger.debug(
                "_inject_source_file: path quoted for YAML safety: %s -> %s",
                raw_rel_path, quoted_path,
            )
        else:
            quoted_path = raw_rel_path
        result = f"{fm_body}source_file: {quoted_path}\n{fm_close}{rest}"
        logger.info("_inject_source_file: frontmatter injected")
    else:
        logger.warning(
            "_inject_source_file: frontmatter not found, skipping injection"
        )

    # 2. Update footer line with wikilink
    old_footer = "*Источник: транскрипт Яндекс Телемост*"
    new_footer = (
        f"*Источник: транскрипт Яндекс Телемост "
        f"— [[{raw_rel_path}|исходный файл]]*"
    )
    if old_footer in result:
        result = result.replace(old_footer, new_footer, 1)
        logger.info("_inject_source_file: footer updated with wikilink")
    else:
        source_line = f"\n---\n*Источник: [[{raw_rel_path}|исходный файл]]*\n"
        result = result.rstrip() + source_line
        logger.info(
            "_inject_source_file: footer appended (pattern not found in LLM output)"
        )

    return result


def save_raw_fallback(vault_path: str, attachment: EmailAttachment) -> Path:
    """Save raw transcript as fallback when Claude processing fails.

    Routes the file to the correct subfolder based on transcript type:
    - Daily stand-up transcripts → ``{vault_path}/raw/inbound/daily-logs/``
    - Regular meeting transcripts → ``{vault_path}/raw/inbound/meeting-notes/``

    Nothing is lost even when the Claude API is unreachable.

    Args:
        vault_path: Absolute path to the Obsidian vault root.
        attachment: The email attachment that failed processing.

    Returns:
        Path to the saved raw file.
    """
    logger.info(
        "save_raw_fallback: saving raw transcript for message_id=%s, "
        "attachment=%s (%d chars)",
        attachment.message_id,
        attachment.filename,
        len(attachment.content),
    )
    try:
        if _is_daily(attachment):
            subfolder = "daily-logs"
            logger.info(
                "save_raw_fallback: routing to daily-logs/ "
                "(subject=%r, filename=%r)",
                attachment.subject,
                attachment.filename,
            )
        else:
            subfolder = "meeting-notes"
            logger.info(
                "save_raw_fallback: routing to meeting-notes/ "
                "(subject=%r, filename=%r)",
                attachment.subject,
                attachment.filename,
            )

        raw_dir = Path(vault_path) / "raw" / "inbound" / subfolder
        raw_dir.mkdir(parents=True, exist_ok=True)
        date_str = attachment.date.strftime("%Y-%m-%d-%H%M")
        filename = f"{date_str}-{attachment.filename}"
        filepath = raw_dir / filename
        filepath.write_text(attachment.content, encoding="utf-8")
        logger.info(
            "save_raw_fallback: saved raw fallback to %s/%s",
            subfolder,
            filepath.name,
        )
        return filepath
    except Exception as e:
        logger.error(
            "save_raw_fallback failed for message_id=%s: %s",
            attachment.message_id,
            e,
        )
        raise


def _unique_filepath(target_dir: Path, filename: str) -> Path:
    """Return a unique filepath, appending -02, -03, etc. on collision.

    Args:
        target_dir: Directory where the file will be written.
        filename: Desired filename (e.g. ``2026-04-25-1000-daily.md``).

    Returns:
        A Path that does not yet exist on disk.
    """
    filepath = target_dir / filename
    if not filepath.exists():
        logger.debug("_unique_filepath: no collision, using %s", filepath.name)
        return filepath

    stem = filepath.stem
    suffix = filepath.suffix
    counter = 2
    while True:
        new_name = f"{stem}-{counter:02d}{suffix}"
        new_path = target_dir / new_name
        if not new_path.exists():
            logger.info(
                "_unique_filepath: collision resolved, using %s (original: %s)",
                new_name,
                filename,
            )
            return new_path
        counter += 1


def fetch_new_meetings(
    vault_path: str,
    notify: bool = False,
    dry_run: bool = False,
) -> dict:
    """Fetch new meeting emails and enqueue them for processing (BL-145).

    This is now an LLM-free Fetch phase (design §1.3, §3.1): it only fills the
    file-based queue ``raw/meeting-queue/pending/``. The actual transcript ->
    protocol conversion is performed by the separate Process worker
    (``processor.py``), triggered by the queue watchdog / cron.

    Steps:
      1. Load IMAP credentials from environment.
      2. Fetch emails via IMAP.
      3. Dedup gate: drop attachments already enqueued OR already processed
         (back-compat with the old monolith) — AC-07.
      4. (dry_run) Return counts without enqueueing.
      5. For each new attachment: ``shared.meeting_queue.enqueue`` + mark
         enqueued in state.
      6. Send a summary notification if requested.

    Args:
        vault_path: Absolute path to the Obsidian vault root.
        notify: Whether to send a Telegram summary notification.
        dry_run: If True, only report counts without enqueueing.

    Returns:
        A compatible dict (AC-09) with keys: status, total_emails,
        already_processed, newly_processed (= enqueued), enqueued,
        skipped_failed (= 0), errors, details, message.
    """
    logger.info(
        "fetch_new_meetings started: vault_path=%s, notify=%s, dry_run=%s",
        vault_path,
        notify,
        dry_run,
    )

    # ------------------------------------------------------------------ #
    # Step 1: Load IMAP credentials
    # ------------------------------------------------------------------ #
    login = os.getenv("YANDEX_LOGIN")
    password = os.getenv("YANDEX_APP_PASSWORD")

    if not login or not password:
        msg = "YANDEX_LOGIN or YANDEX_APP_PASSWORD not set in environment"
        logger.error("fetch_new_meetings: %s", msg)
        return _error_result(msg)

    logger.info("fetch_new_meetings: IMAP credentials loaded for user=%s", login)

    # ------------------------------------------------------------------ #
    # Step 2: Fetch emails from IMAP
    # ------------------------------------------------------------------ #
    try:
        logger.info("fetch_new_meetings: calling imap_client.fetch_emails")
        attachments = fetch_emails(login, password)
        logger.info(
            "fetch_new_meetings: fetched %d attachment(s) from IMAP",
            len(attachments),
        )
    except IMAPError as e:
        error_msg = f"IMAP error: {e}"
        logger.error("fetch_new_meetings: %s", error_msg)
        if notify:
            _notify(
                "Meeting Fetcher: ошибка подключения\n\n"
                f"Ошибка: {e}\n"
                "Следующая попытка через 1 час (по расписанию cron)"
            )
        return _error_result(error_msg)

    total_emails = len(attachments)

    # ------------------------------------------------------------------ #
    # Step 3: Dedup gate (AC-07): skip already-enqueued OR already-processed.
    #         is_processed keeps back-compat with emails handled by the old
    #         monolith (design §2.5, §7).
    # ------------------------------------------------------------------ #
    logger.info("fetch_new_meetings: loading state from vault")
    state = State(vault_path)

    new_attachments = [
        a
        for a in attachments
        if not (
            state.is_enqueued(a.message_id) or state.is_processed(a.message_id)
        )
    ]
    already_processed = total_emails - len(new_attachments)

    logger.info(
        "fetch_new_meetings: %d total, %d already enqueued/processed, %d new",
        total_emails,
        already_processed,
        len(new_attachments),
    )

    # ------------------------------------------------------------------ #
    # Step 4: Dry-run — return counts only
    # ------------------------------------------------------------------ #
    if dry_run:
        msg = (
            f"Dry run: {total_emails} email(s), "
            f"{len(new_attachments)} new, "
            f"{already_processed} already enqueued/processed"
        )
        logger.info("fetch_new_meetings: %s", msg)
        return {
            "status": "skip",
            "total_emails": total_emails,
            "already_processed": already_processed,
            "newly_processed": 0,
            "enqueued": 0,
            "skipped_failed": 0,
            "errors": 0,
            "details": [],
            "message": msg,
        }

    # ------------------------------------------------------------------ #
    # Step 5: Enqueue each new attachment (NO LLM — AC-01)
    # ------------------------------------------------------------------ #
    newly_processed = 0
    errors = 0
    details: list[dict] = []

    for attachment in new_attachments:
        logger.info(
            "fetch_new_meetings: enqueueing attachment message_id=%s, "
            "filename=%s (%d chars)",
            attachment.message_id,
            attachment.filename,
            len(attachment.content),
        )
        try:
            unit = enqueue(
                vault_path,
                raw_text=attachment.content,
                source="email",
                subject=attachment.subject,
                date=attachment.date,
                message_id=attachment.message_id,
                source_filename=attachment.filename,
            )

            # enqueue returns None for an empty transcript — nothing to process.
            if unit is None:
                logger.warning(
                    "fetch_new_meetings: empty transcript skipped, "
                    "message_id=%s, subject='%s'",
                    attachment.message_id,
                    attachment.subject,
                )
                continue

            state.mark_enqueued(
                attachment.message_id,
                unit.unit_id,
                attachment.subject,
                attachment.date.isoformat(),
            )

            newly_processed += 1
            details.append(
                {
                    "unit_id": unit.unit_id,
                    "subject": attachment.subject,
                    "source": "email",
                    "status": "pending",
                }
            )
            logger.info(
                "fetch_new_meetings: enqueued message_id=%s as unit_id=%s",
                attachment.message_id,
                unit.unit_id,
            )
        except Exception as enq_err:
            logger.error(
                "fetch_new_meetings: enqueue failed for message_id=%s: %s",
                attachment.message_id,
                enq_err,
            )
            errors += 1

    # ------------------------------------------------------------------ #
    # Step 6: Summary notification
    # ------------------------------------------------------------------ #
    summary_msg = (
        f"Meeting Fetcher: {newly_processed} писем поставлено в очередь\n\n"
        f"Всего писем: {total_emails}\n"
        f"Поставлено в очередь: {newly_processed}\n"
        f"Пропущено (уже в очереди/обработаны): {already_processed}\n"
        f"Ошибок: {errors}"
    )

    if notify:
        logger.info("fetch_new_meetings: sending summary notification")
        _notify(summary_msg)

    # ------------------------------------------------------------------ #
    # Step 7: Return result
    # ------------------------------------------------------------------ #
    # status stays 'ok' when there are no enqueue errors — LLM is NOT called
    # here, so LLM unavailability never turns this into an error (AC-01).
    status = "ok" if errors == 0 else "error"
    logger.info(
        "fetch_new_meetings completed: status=%s, total=%d, enqueued=%d, "
        "already=%d, errors=%d",
        status,
        total_emails,
        newly_processed,
        already_processed,
        errors,
    )

    return {
        "status": status,
        "total_emails": total_emails,
        "already_processed": already_processed,
        "newly_processed": newly_processed,
        "enqueued": newly_processed,
        "skipped_failed": 0,
        "errors": errors,
        "details": details,
        "message": summary_msg,
    }


def _error_result(message: str) -> dict:
    """Build a standardised error result dict.

    Args:
        message: Human-readable error description.

    Returns:
        FetchResult dict with status="error" and zero counts (AC-09 keys).
    """
    logger.debug("_error_result: %s", message)
    return {
        "status": "error",
        "total_emails": 0,
        "already_processed": 0,
        "newly_processed": 0,
        "enqueued": 0,
        "skipped_failed": 0,
        "errors": 1,
        "details": [],
        "message": message,
    }
