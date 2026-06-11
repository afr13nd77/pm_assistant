"""
Fetcher orchestrator for Meeting Fetcher pipeline.

Ties together the entire meeting fetch pipeline:
IMAP fetch -> filter by state -> Claude processing -> classification
-> file write -> enrichment -> notification.
"""

import logging
import os
import re
from datetime import datetime
from pathlib import Path

import requests

from .imap_client import fetch_emails, IMAPError, EmailAttachment
from .state import State
from .classifier import extract_type, route_protocol, make_filename, make_daily_filename
from ..file_writer import atomic_write
from ..enricher import enrich
from .. import claude_client

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
    """Run the full meeting-fetch pipeline.

    Steps:
      1. Load IMAP credentials from environment.
      2. Fetch emails via IMAP.
      3. Filter out already-processed emails using state tracker.
      4. (dry_run) Return counts without processing.
      5. For each new attachment: Claude -> classify -> write -> enrich -> state.
      6. Send notifications if requested.

    Args:
        vault_path: Absolute path to the Obsidian vault root.
        notify: Whether to send Telegram notifications.
        dry_run: If True, only report counts without downloading or processing.

    Returns:
        A dict with keys: status, total_emails, already_processed,
        newly_processed, errors, details, message.
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
    # Step 3: Filter by state (dedup)
    # ------------------------------------------------------------------ #
    logger.info("fetch_new_meetings: loading state from vault")
    state = State(vault_path)

    new_attachments = [
        a for a in attachments if not state.is_processed(a.message_id)
    ]
    already_processed = total_emails - len(new_attachments)

    logger.info(
        "fetch_new_meetings: %d total, %d already processed, %d new",
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
            f"{already_processed} already processed"
        )
        logger.info("fetch_new_meetings: %s", msg)
        return {
            "status": "skip",
            "total_emails": total_emails,
            "already_processed": already_processed,
            "newly_processed": 0,
            "skipped_failed": 0,
            "errors": 0,
            "details": [],
            "message": msg,
        }

    # ------------------------------------------------------------------ #
    # Step 5: Process each new attachment
    # ------------------------------------------------------------------ #
    newly_processed = 0
    errors = 0
    skipped_failed = 0
    details: list[dict] = []

    for attachment in new_attachments:
        # Skip emails that have permanently failed (max retries exceeded)
        if state.is_max_retried(attachment.message_id):
            skipped_failed += 1
            logger.warning(
                "fetch_new_meetings: skipping permanently failed email "
                "message_id=%s, subject='%s'",
                attachment.message_id,
                attachment.subject,
            )
            continue

        logger.info(
            "fetch_new_meetings: processing attachment message_id=%s, "
            "filename=%s (%d chars)",
            attachment.message_id,
            attachment.filename,
            len(attachment.content),
        )
        raw_saved = False
        try:
            # 5a. Save raw transcript (always, before Claude processing)
            raw_path = save_raw_fallback(vault_path, attachment)
            raw_saved = True
            logger.info(
                "fetch_new_meetings: raw transcript saved to %s", raw_path
            )

            # 5b. Claude processing
            logger.info(
                "fetch_new_meetings: calling Claude API for transcript "
                "(%d chars)",
                len(attachment.content),
            )
            protocol_md = claude_client.process_meeting_transcript(
                attachment.content
            )
            logger.info(
                "fetch_new_meetings: Claude returned protocol (%d chars)",
                len(protocol_md),
            )

            # 5c. Classification
            protocol_type = extract_type(protocol_md)
            logger.info(
                "fetch_new_meetings: classified as type='%s'", protocol_type
            )

            target_folder = route_protocol(protocol_type)
            logger.info(
                "fetch_new_meetings: routed to folder='%s'", target_folder
            )

            # 5d. Ensure target directory exists (before filename generation,
            #     because make_daily_filename needs to scan the directory)
            target_dir = Path(vault_path) / target_folder
            target_dir.mkdir(parents=True, exist_ok=True)
            logger.info(
                "fetch_new_meetings: target directory ensured: %s", target_dir
            )

            if protocol_type == "daily":
                filename = make_daily_filename(target_dir)
            else:
                filename = make_filename(attachment.date, attachment.subject)
            logger.info(
                "fetch_new_meetings: generated filename='%s'", filename
            )

            # 5e. Handle filename collision
            target_path = _unique_filepath(target_dir, filename)
            logger.info(
                "fetch_new_meetings: target path resolved: %s", target_path
            )

            # 5f. Write protocol file
            atomic_write(str(target_path), protocol_md)
            logger.info(
                "fetch_new_meetings: protocol written to %s", target_path.name
            )

            # 5f-bis. Jira key sync — only for daily protocols (non-fatal)
            jira_sync_detail = {}
            if protocol_type == "daily":
                try:
                    from ..jira_key_sync import sync_daily_jira_keys, patch_daily_links
                    jira_sync_detail = sync_daily_jira_keys(
                        protocol_md, vault_path
                    )
                    logger.info(
                        "fetch_new_meetings: jira_key_sync keys=%d missing=%d "
                        "imported=%d failed=%d",
                        len(jira_sync_detail.get("keys", [])),
                        len(jira_sync_detail.get("missing", [])),
                        len(jira_sync_detail.get("imported", [])),
                        len(jira_sync_detail.get("failed", [])),
                    )
                    patch_daily_links(
                        str(target_path),
                        jira_sync_detail.get("keys_map", {}),
                    )
                except Exception as jira_err:
                    logger.warning(
                        "fetch_new_meetings: jira_key_sync failed for %s "
                        "(non-fatal): %s",
                        target_path.name,
                        jira_err,
                    )

            # 5g. Enrichment (non-fatal)
            links_found = 0
            try:
                logger.info(
                    "fetch_new_meetings: starting enrichment for %s",
                    target_path.name,
                )
                enrich_result = enrich(str(target_path), vault_path)
                links_found = enrich_result.get("links_found", 0)
                logger.info(
                    "fetch_new_meetings: enrichment complete, "
                    "links_found=%d, status=%s",
                    links_found,
                    enrich_result.get("status", "unknown"),
                )
            except Exception as enrich_err:
                logger.warning(
                    "fetch_new_meetings: enrichment failed for %s "
                    "(non-fatal): %s",
                    target_path.name,
                    enrich_err,
                )

            # 5h. Mark as processed in state
            relative_output = str(
                target_path.relative_to(Path(vault_path))
            )
            date_iso = attachment.date.isoformat()

            state.mark_processed(
                message_id=attachment.message_id,
                subject=attachment.subject,
                date=date_iso,
                attachment=attachment.filename,
                output_file=relative_output,
                protocol_type=protocol_type,
            )
            logger.info(
                "fetch_new_meetings: marked as processed, message_id=%s",
                attachment.message_id,
            )

            newly_processed += 1
            detail = {
                "file": str(target_path),
                "type": protocol_type,
                "links_found": links_found,
                "jira_sync": jira_sync_detail if protocol_type == "daily" else {},
            }
            details.append(detail)

            # 5h-bis. Non-critical: append entry to root LOG.md
            try:
                log_entry = _build_fetcher_log_entry(
                    filename=target_path.name,
                    protocol_type=protocol_type,
                    protocol_md=protocol_md,
                    msg_date=attachment.date,
                    target_folder=target_folder,
                )
                from ..ingest import _append_root_log
                _append_root_log(log_entry)
                logger.info(
                    "fetch_new_meetings: LOG.md entry appended for %s",
                    target_path.name,
                )
            except Exception as log_err:
                logger.warning(
                    "fetch_new_meetings: failed to append LOG.md entry for %s "
                    "(non-fatal): %s",
                    target_path.name,
                    log_err,
                )

            # 5i. Per-protocol notification
            if notify:
                notify_text = (
                    "Протокол встречи готов\n\n"
                    f"Файл: {target_path.name}\n"
                    f"Тип: {protocol_type}\n"
                    f"Папка: {target_folder}/\n"
                    f"Связей найдено: {links_found}"
                )
                if protocol_type == "daily" and jira_sync_detail.get("keys"):
                    keys_str = ", ".join(jira_sync_detail["keys"])
                    notify_text += f"\n📋 Задачи: {keys_str}"
                    imported = jira_sync_detail.get("imported", [])
                    if imported:
                        imp_str = ", ".join(
                            f"{i['key']}→{i['domain']}" for i in imported
                        )
                        notify_text += f"\n⬇️ Импортировано: {imp_str}"
                    failed = jira_sync_detail.get("failed", [])
                    if failed:
                        fail_str = ", ".join(f["key"] for f in failed)
                        notify_text += f"\n⚠️ Ошибка импорта: {fail_str}"
                _notify(notify_text)

        except Exception as proc_err:
            logger.error(
                "fetch_new_meetings: processing failed for message_id=%s: %s",
                attachment.message_id,
                proc_err,
            )
            if not raw_saved:
                try:
                    fallback_path = save_raw_fallback(vault_path, attachment)
                    logger.info(
                        "fetch_new_meetings: raw fallback saved at %s",
                        fallback_path,
                    )
                except Exception as fallback_err:
                    logger.error(
                        "fetch_new_meetings: raw fallback also failed for "
                        "message_id=%s: %s",
                        attachment.message_id,
                        fallback_err,
                    )

            # Track failure in state for retry limiting
            state.mark_failed(
                attachment.message_id, attachment.subject, str(proc_err)
            )

            # Send one-time notification when email becomes permanently failed
            if state.is_max_retried(attachment.message_id):
                logger.warning(
                    "fetch_new_meetings: message_id=%s has reached max retries, "
                    "marked as permanently failed",
                    attachment.message_id,
                )
                if notify:
                    _notify(
                        "Meeting Fetcher: письмо помечено как необработаемое\n\n"
                        f"Тема: {attachment.subject}\n"
                        f"Ошибка: {proc_err}\n"
                        f"Попытки: 3/3\n"
                        f"Транскрипт сохранён в raw/inbound/"
                    )

            errors += 1

    # ------------------------------------------------------------------ #
    # Step 6: Summary notification
    # ------------------------------------------------------------------ #
    summary_msg = (
        f"Meeting Fetcher: обработка завершена\n\n"
        f"Всего писем: {total_emails}\n"
        f"Новых обработано: {newly_processed}\n"
        f"Пропущено (уже обработаны): {already_processed}\n"
        f"Ошибок: {errors}"
    )
    if skipped_failed > 0:
        summary_msg += f"\nПропущено (неисправимые ошибки): {skipped_failed}"

    if notify:
        logger.info("fetch_new_meetings: sending summary notification")
        _notify(summary_msg)

    # ------------------------------------------------------------------ #
    # Step 7: Return result
    # ------------------------------------------------------------------ #
    status = "ok" if errors == 0 else "error"
    logger.info(
        "fetch_new_meetings completed: status=%s, total=%d, new=%d, "
        "skipped=%d, skipped_failed=%d, errors=%d",
        status,
        total_emails,
        newly_processed,
        already_processed,
        skipped_failed,
        errors,
    )

    return {
        "status": status,
        "total_emails": total_emails,
        "already_processed": already_processed,
        "newly_processed": newly_processed,
        "skipped_failed": skipped_failed,
        "errors": errors,
        "details": details,
        "message": summary_msg,
    }


def _error_result(message: str) -> dict:
    """Build a standardised error result dict.

    Args:
        message: Human-readable error description.

    Returns:
        FetchResult dict with status="error" and zero counts.
    """
    logger.debug("_error_result: %s", message)
    return {
        "status": "error",
        "total_emails": 0,
        "already_processed": 0,
        "newly_processed": 0,
        "skipped_failed": 0,
        "errors": 1,
        "details": [],
        "message": message,
    }
