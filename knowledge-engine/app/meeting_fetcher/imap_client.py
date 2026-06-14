"""
IMAP client for fetching meeting protocol emails from Yandex Mail.

Connects to an IMAP mailbox, reads emails from a specified folder
(default: "Протоколы встреч"), and extracts .txt attachments containing
meeting transcripts.
"""

import base64
import email
import email.utils
import imaplib
import logging
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.header import decode_header
from typing import Optional

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))

_IMAP_TIMEOUT_SECONDS = 60


@dataclass
class EmailAttachment:
    """Represents a single .txt attachment extracted from an email."""

    message_id: str   # Message-ID header from email
    subject: str      # decoded email subject
    date: datetime    # parsed Date header (tz-aware, MSK)
    filename: str     # original attachment filename
    content: str      # decoded text content of the .txt attachment


class IMAPError(Exception):
    """Raised on IMAP connection or protocol errors."""
    pass


def imap_utf7_encode(s: str) -> str:
    """
    Encode a string using Modified UTF-7 for IMAP folder names (RFC 3501).

    IMAP requires folder names with non-ASCII characters to be encoded
    in a modified Base64 variant of UTF-7 where '&' is the shift character
    and '/' in base64 is replaced by ','.
    """
    logger.debug("imap_utf7_encode called for string of length %d", len(s))
    res: list[str] = []
    buf: list[str] = []
    for ch in s:
        if 0x20 <= ord(ch) <= 0x7E:
            if buf:
                b64 = base64.b64encode(
                    "".join(buf).encode("utf-16-be")
                ).decode("ascii")
                b64 = b64.rstrip("=").replace("/", ",")
                res.append("&" + b64 + "-")
                buf.clear()
            if ch == "&":
                res.append("&-")
            else:
                res.append(ch)
        else:
            buf.append(ch)
    if buf:
        b64 = base64.b64encode(
            "".join(buf).encode("utf-16-be")
        ).decode("ascii")
        b64 = b64.rstrip("=").replace("/", ",")
        res.append("&" + b64 + "-")
    encoded = "".join(res)
    logger.debug("imap_utf7_encode result: %s", encoded)
    return encoded


def decode_str(value: Optional[str]) -> str:
    """
    Decode an email header value that may contain RFC 2047 encoded words.

    Returns an empty string if value is None.
    """
    if value is None:
        logger.debug("decode_str called with None, returning empty string")
        return ""
    parts = decode_header(value)
    result: list[str] = []
    for part, enc in parts:
        if isinstance(part, bytes):
            result.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            result.append(part)
    decoded = "".join(result)
    logger.debug("decode_str decoded header: %d chars", len(decoded))
    return decoded


def select_folder(imap: imaplib.IMAP4_SSL, folder: str) -> list[bytes | None]:
    """
    Select an IMAP folder, encoding the name with Modified UTF-7 if needed.

    Tries both quoted and unquoted folder name variants.

    Raises:
        IMAPError: If the folder cannot be selected.
    """
    logger.info("Selecting IMAP folder: %s", folder)
    encoded = imap_utf7_encode(folder)
    logger.debug("Encoded folder name: %s", encoded)

    for name in (f'"{encoded}"', encoded):
        try:
            status, data = imap.select(name)
            if status == "OK":
                logger.info(
                    "Successfully selected folder '%s' (%s messages)",
                    folder,
                    data[0].decode() if data and data[0] else "unknown",
                )
                return data
        except imaplib.IMAP4.error as e:
            logger.debug("select_folder attempt with '%s' failed: %s", name, e)
            continue

    # Folder selection failed -- log available folders for diagnostics
    logger.warning("Failed to select folder '%s'. Listing available folders.", folder)
    try:
        _, folders = imap.list()
        if folders:
            for f in folders:
                if isinstance(f, bytes):
                    logger.warning("  Available folder: %s", f.decode(errors="replace"))
    except Exception as list_err:
        logger.warning("Could not list folders: %s", list_err)

    raise IMAPError(f"Failed to select folder '{folder}'")


def _parse_date(date_str: Optional[str]) -> datetime:
    """
    Parse an email Date header into a timezone-aware datetime.

    Falls back to current time in MSK if parsing fails.
    """
    if not date_str:
        logger.debug("No date header, using current MSK time as fallback")
        return datetime.now(MSK)
    try:
        dt = email.utils.parsedate_to_datetime(date_str)
        logger.debug("Parsed date: %s", dt.isoformat())
        return dt
    except Exception as e:
        logger.warning("Failed to parse date '%s': %s. Using current MSK time.", date_str, e)
        return datetime.now(MSK)


def _extract_txt_attachments(
    msg: email.message.Message,
    message_id: str,
    subject: str,
    date: datetime,
) -> list[EmailAttachment]:
    """
    Walk MIME parts of an email and extract all .txt attachments.

    Returns a list of EmailAttachment objects.
    """
    attachments: list[EmailAttachment] = []

    for part in msg.walk():
        content_disposition = str(part.get("Content-Disposition", ""))
        if "attachment" not in content_disposition:
            continue

        raw_filename = part.get_filename()
        filename = decode_str(raw_filename) if raw_filename else ""

        if not filename.lower().endswith(".txt"):
            logger.debug(
                "Skipping non-txt attachment: %s (message_id=%s)",
                filename,
                message_id,
            )
            continue

        payload = part.get_payload(decode=True)
        if payload is None:
            logger.warning(
                "Empty payload for attachment '%s' in message_id=%s, skipping",
                filename,
                message_id,
            )
            continue

        assert isinstance(payload, bytes)
        content = payload.decode("utf-8", errors="replace")
        logger.info(
            "Extracted .txt attachment: filename='%s', %d chars (message_id=%s)",
            filename,
            len(content),
            message_id,
        )

        attachments.append(
            EmailAttachment(
                message_id=message_id,
                subject=subject,
                date=date,
                filename=filename,
                content=content,
            )
        )

    return attachments


def fetch_emails(
    login: str,
    password: str,
    folder: str = "Протоколы встреч",
    host: str = "imap.yandex.ru",
    port: int = 993,
) -> list[EmailAttachment]:
    """
    Connect to IMAP, fetch all emails from the specified folder,
    extract .txt attachments, return as list of EmailAttachment.

    Args:
        login: Email address / IMAP login.
        password: IMAP password or app-specific password.
        folder: Mailbox folder to read from (default: "Протоколы встреч").
        host: IMAP server hostname.
        port: IMAP server port (SSL).

    Returns:
        List of EmailAttachment objects extracted from emails in the folder.

    Raises:
        IMAPError: On connection, authentication, or protocol failures.
    """
    logger.info(
        "fetch_emails started: login=%s, host=%s, port=%d, folder='%s'",
        login,
        host,
        port,
        folder,
    )

    imap: Optional[imaplib.IMAP4_SSL] = None
    results: list[EmailAttachment] = []

    try:
        # --- Connect ---
        logger.info("Connecting to %s:%d with timeout=%ds", host, port, _IMAP_TIMEOUT_SECONDS)
        try:
            imap = imaplib.IMAP4_SSL(host, port, timeout=_IMAP_TIMEOUT_SECONDS)
            logger.info("IMAP SSL connection established to %s:%d", host, port)
        except (socket.timeout, socket.gaierror, OSError) as e:
            logger.error("IMAP connection failed to %s:%d: %s", host, port, e)
            raise IMAPError(f"Connection failed to {host}:{port}: {e}") from e

        # --- Authenticate ---
        try:
            imap.login(login, password)
            logger.info("IMAP login successful for user=%s", login)
        except imaplib.IMAP4.error as e:
            logger.error("IMAP authentication failed for user=%s: %s", login, e)
            raise IMAPError("Authentication failed") from e

        # --- Select folder ---
        select_folder(imap, folder)

        # --- Search for all messages ---
        logger.info("Searching for all messages in folder '%s'", folder)
        try:
            status, search_data = imap.search(None, "ALL")
            if status != "OK":
                logger.error("IMAP search failed with status=%s", status)
                raise IMAPError(f"IMAP search failed: status={status}")
        except imaplib.IMAP4.error as e:
            logger.error("IMAP search error: %s", e)
            raise IMAPError(f"IMAP search error: {e}") from e

        message_ids_raw = search_data[0].split() if search_data[0] else []
        logger.info("Found %d messages in folder '%s'", len(message_ids_raw), folder)

        if not message_ids_raw:
            logger.info("No messages found, returning empty list")
            return results

        # --- Fetch each message ---
        for seq_num in message_ids_raw:
            seq_str = seq_num.decode() if isinstance(seq_num, bytes) else str(seq_num)
            logger.debug("Fetching message seq=%s", seq_str)

            try:
                status, msg_data = imap.fetch(seq_num, "(RFC822)")
                if status != "OK" or not msg_data or msg_data[0] is None:
                    logger.warning("Failed to fetch message seq=%s, status=%s, skipping", seq_str, status)
                    continue
            except imaplib.IMAP4.error as e:
                logger.warning("IMAP fetch error for seq=%s: %s, skipping", seq_str, e)
                continue

            raw_email = msg_data[0][1]
            assert isinstance(raw_email, bytes)
            msg = email.message_from_bytes(raw_email)

            message_id = msg.get("Message-ID", "").strip()
            subject = decode_str(msg.get("Subject", "Без темы"))
            date = _parse_date(msg.get("Date"))

            logger.info(
                "Processing message: seq=%s, message_id=%s, subject='%s', date=%s",
                seq_str,
                message_id,
                subject,
                date.isoformat(),
            )

            attachments = _extract_txt_attachments(msg, message_id, subject, date)
            if attachments:
                logger.info(
                    "Found %d .txt attachment(s) in message seq=%s",
                    len(attachments),
                    seq_str,
                )
                results.extend(attachments)
            else:
                logger.debug("No .txt attachments in message seq=%s", seq_str)

        logger.info(
            "fetch_emails completed: %d attachment(s) extracted from %d messages",
            len(results),
            len(message_ids_raw),
        )
        return results

    except IMAPError:
        # Re-raise our own errors without wrapping
        raise

    except Exception as e:
        logger.error("Unexpected error in fetch_emails: %s", e, exc_info=True)
        raise IMAPError(f"Unexpected error: {e}") from e

    finally:
        if imap is not None:
            try:
                imap.close()
                logger.debug("IMAP folder closed")
            except Exception as e:
                logger.debug("IMAP close failed (may be expected): %s", e)
            try:
                imap.logout()
                logger.info("IMAP logout completed")
            except Exception as e:
                logger.debug("IMAP logout failed: %s", e)
