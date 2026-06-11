"""
Unit tests for the IMAP client module.

Tests cover:
- imap_utf7_encode: encoding of ASCII, Cyrillic, and mixed strings
- decode_str: decoding of email headers (None, plain, encoded)
- select_folder: successful selection and failure with IMAPError
- _parse_date: valid dates, invalid dates, None
- _extract_txt_attachments: .txt extraction, non-txt skipping, empty payloads
- fetch_emails: full integration with mocked IMAP (success, auth failure,
  connection failure, empty folder, fetch errors)
"""

import email
import imaplib
import socket
from datetime import datetime, timedelta, timezone
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from app.meeting_fetcher.imap_client import (
    EmailAttachment,
    IMAPError,
    MSK,
    _extract_txt_attachments,
    _parse_date,
    decode_str,
    fetch_emails,
    imap_utf7_encode,
    select_folder,
)


# ---------------------------------------------------------------------------
# imap_utf7_encode
# ---------------------------------------------------------------------------

class TestImapUtf7Encode:
    def test_ascii_passthrough(self):
        """Pure ASCII strings are not modified."""
        assert imap_utf7_encode("INBOX") == "INBOX"

    def test_ampersand_encoding(self):
        """The '&' character is encoded as '&-' in IMAP modified UTF-7."""
        assert imap_utf7_encode("Tom & Jerry") == "Tom &- Jerry"

    def test_cyrillic_encoding(self):
        """Cyrillic folder names are encoded via modified UTF-7."""
        encoded = imap_utf7_encode("Протоколы встреч")
        # Must not contain any Cyrillic characters
        assert all(0x20 <= ord(c) <= 0x7E for c in encoded)
        # Must start with & (shift character for modified UTF-7)
        assert "&" in encoded

    def test_mixed_ascii_cyrillic(self):
        """Mixed ASCII and Cyrillic are encoded correctly."""
        encoded = imap_utf7_encode("Inbox/Протоколы")
        assert encoded.startswith("Inbox/")
        assert "&" in encoded

    def test_empty_string(self):
        """Empty string returns empty string."""
        assert imap_utf7_encode("") == ""

    def test_space_is_passthrough(self):
        """Space character (0x20) passes through as-is."""
        assert imap_utf7_encode("A B") == "A B"


# ---------------------------------------------------------------------------
# decode_str
# ---------------------------------------------------------------------------

class TestDecodeStr:
    def test_none_returns_empty(self):
        assert decode_str(None) == ""

    def test_plain_ascii(self):
        assert decode_str("Hello World") == "Hello World"

    def test_rfc2047_utf8(self):
        """RFC 2047 encoded UTF-8 header is decoded properly."""
        # Encode "Протокол" as RFC 2047
        encoded = "=?utf-8?b?0J/RgNC+0YLQvtC60L7Quw==?="
        result = decode_str(encoded)
        assert result == "Протокол"

    def test_rfc2047_multi_part(self):
        """Multi-part encoded headers are joined."""
        encoded = "=?utf-8?b?0J/RgNC+0YLQvtC60L7Quw==?= =?utf-8?b?INCy0YHRgtGA0LXRh9C4?="
        result = decode_str(encoded)
        assert "Протокол" in result

    def test_plain_cyrillic(self):
        """Already decoded Cyrillic strings pass through."""
        assert decode_str("Тест") == "Тест"


# ---------------------------------------------------------------------------
# select_folder
# ---------------------------------------------------------------------------

class TestSelectFolder:
    def test_success_first_try(self):
        """Folder is selected on the first attempt (quoted name)."""
        mock_imap = MagicMock()
        mock_imap.select.return_value = ("OK", [b"5"])

        result = select_folder(mock_imap, "INBOX")
        assert result == [b"5"]
        mock_imap.select.assert_called_once()

    def test_success_second_try(self):
        """Folder selection fails on quoted, succeeds on unquoted."""
        mock_imap = MagicMock()
        mock_imap.select.side_effect = [
            ("NO", [None]),  # quoted attempt fails
            ("OK", [b"3"]),  # unquoted attempt succeeds
        ]

        result = select_folder(mock_imap, "INBOX")
        assert result == [b"3"]
        assert mock_imap.select.call_count == 2

    def test_failure_raises_imap_error(self):
        """Both attempts fail, raises IMAPError and lists folders."""
        mock_imap = MagicMock()
        mock_imap.select.return_value = ("NO", [None])
        mock_imap.list.return_value = ("OK", [b'"." "INBOX"', b'"." "Sent"'])

        with pytest.raises(IMAPError, match="Failed to select folder"):
            select_folder(mock_imap, "NonExistent")

    def test_cyrillic_folder(self):
        """Cyrillic folder name is encoded before selection."""
        mock_imap = MagicMock()
        mock_imap.select.return_value = ("OK", [b"10"])

        select_folder(mock_imap, "Протоколы встреч")
        # The call should use an encoded name, not raw Cyrillic
        call_args = mock_imap.select.call_args[0][0]
        # Should not contain raw Cyrillic characters
        assert "Протоколы" not in call_args

    def test_select_raises_imap4_error_first_try(self):
        """imaplib.IMAP4.error on first select is caught, second try proceeds."""
        mock_imap = MagicMock()
        mock_imap.select.side_effect = [
            imaplib.IMAP4.error("mailbox not found"),
            ("OK", [b"1"]),
        ]

        result = select_folder(mock_imap, "Test")
        assert result == [b"1"]


# ---------------------------------------------------------------------------
# _parse_date
# ---------------------------------------------------------------------------

class TestParseDate:
    def test_valid_date(self):
        """Standard email date string is parsed correctly."""
        dt = _parse_date("Mon, 21 Apr 2025 10:30:00 +0300")
        assert dt.year == 2025
        assert dt.month == 4
        assert dt.day == 21
        assert dt.hour == 10
        assert dt.tzinfo is not None

    def test_none_returns_now_msk(self):
        """None date falls back to current MSK time."""
        before = datetime.now(MSK)
        dt = _parse_date(None)
        after = datetime.now(MSK)
        assert before <= dt <= after

    def test_invalid_date_returns_now_msk(self):
        """Garbage date string falls back to current MSK time."""
        before = datetime.now(MSK)
        dt = _parse_date("not-a-date-at-all")
        after = datetime.now(MSK)
        assert before <= dt <= after

    def test_empty_string_returns_now_msk(self):
        """Empty string falls back to current MSK time."""
        before = datetime.now(MSK)
        dt = _parse_date("")
        after = datetime.now(MSK)
        assert before <= dt <= after


# ---------------------------------------------------------------------------
# _extract_txt_attachments
# ---------------------------------------------------------------------------

def _make_email_with_txt(
    filename: str = "protocol.txt",
    content: str = "Meeting notes here",
    subject: str = "Test Subject",
) -> email.message.Message:
    """Helper to build a multipart email with a .txt attachment."""
    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["Message-ID"] = "<test@example.com>"
    msg["Date"] = "Mon, 21 Apr 2025 10:30:00 +0300"

    body = MIMEText("Email body text", "plain", "utf-8")
    msg.attach(body)

    attachment = MIMEBase("text", "plain")
    attachment.set_payload(content.encode("utf-8"))
    attachment.add_header(
        "Content-Disposition", "attachment", filename=filename
    )
    msg.attach(attachment)

    return msg


class TestExtractTxtAttachments:
    def test_single_txt_attachment(self):
        """One .txt attachment is extracted correctly."""
        msg = _make_email_with_txt(content="Meeting content 123")
        result = _extract_txt_attachments(
            msg, "<test@example.com>", "Test Subject",
            datetime(2025, 4, 21, 10, 30, tzinfo=MSK),
        )
        assert len(result) == 1
        assert result[0].filename == "protocol.txt"
        assert result[0].content == "Meeting content 123"
        assert result[0].message_id == "<test@example.com>"
        assert result[0].subject == "Test Subject"

    def test_no_attachments(self):
        """Email with no attachments returns empty list."""
        msg = MIMEText("Just a plain email", "plain", "utf-8")
        msg["Subject"] = "No attachment"
        result = _extract_txt_attachments(
            msg, "<no@att.com>", "No attachment",
            datetime.now(MSK),
        )
        assert result == []

    def test_non_txt_skipped(self):
        """Non-.txt attachments (e.g., .docx) are skipped."""
        msg = MIMEMultipart()
        msg["Subject"] = "With docx"

        attachment = MIMEBase("application", "vnd.openxmlformats-officedocument.wordprocessingml.document")
        attachment.set_payload(b"PK\x03\x04fake docx")
        attachment.add_header(
            "Content-Disposition", "attachment", filename="report.docx"
        )
        msg.attach(attachment)

        result = _extract_txt_attachments(
            msg, "<docx@test.com>", "With docx", datetime.now(MSK)
        )
        assert result == []

    def test_multiple_txt_attachments(self):
        """Multiple .txt attachments from one email are all extracted."""
        msg = MIMEMultipart()
        msg["Subject"] = "Multi attach"

        for i in range(3):
            att = MIMEBase("text", "plain")
            att.set_payload(f"Content {i}".encode("utf-8"))
            att.add_header(
                "Content-Disposition", "attachment", filename=f"file{i}.txt"
            )
            msg.attach(att)

        result = _extract_txt_attachments(
            msg, "<multi@test.com>", "Multi attach", datetime.now(MSK)
        )
        assert len(result) == 3
        assert {a.filename for a in result} == {"file0.txt", "file1.txt", "file2.txt"}

    def test_mixed_attachments(self):
        """Only .txt attachments are extracted, others ignored."""
        msg = MIMEMultipart()

        txt_att = MIMEBase("text", "plain")
        txt_att.set_payload(b"text content")
        txt_att.add_header("Content-Disposition", "attachment", filename="notes.txt")
        msg.attach(txt_att)

        pdf_att = MIMEBase("application", "pdf")
        pdf_att.set_payload(b"%PDF-1.4 fake")
        pdf_att.add_header("Content-Disposition", "attachment", filename="doc.pdf")
        msg.attach(pdf_att)

        result = _extract_txt_attachments(
            msg, "<mixed@test.com>", "Mixed", datetime.now(MSK)
        )
        assert len(result) == 1
        assert result[0].filename == "notes.txt"

    def test_txt_case_insensitive(self):
        """Filename extension matching is case-insensitive (.TXT works)."""
        msg = MIMEMultipart()
        att = MIMEBase("text", "plain")
        att.set_payload(b"upper case ext")
        att.add_header("Content-Disposition", "attachment", filename="PROTOCOL.TXT")
        msg.attach(att)

        result = _extract_txt_attachments(
            msg, "<case@test.com>", "Case test", datetime.now(MSK)
        )
        assert len(result) == 1
        assert result[0].filename == "PROTOCOL.TXT"


# ---------------------------------------------------------------------------
# fetch_emails — integration tests with mocked IMAP
# ---------------------------------------------------------------------------

def _build_raw_email(
    subject: str = "Протокол 2025-04-21",
    message_id: str = "<proto@yandex.ru>",
    date: str = "Mon, 21 Apr 2025 10:30:00 +0300",
    attachment_filename: str = "protocol.txt",
    attachment_content: str = "Meeting transcript here",
) -> bytes:
    """Build a raw RFC822 email message as bytes."""
    msg = _make_email_with_txt(
        filename=attachment_filename,
        content=attachment_content,
        subject=subject,
    )
    msg.replace_header("Message-ID", message_id) if "Message-ID" in msg else None
    if "Message-ID" not in msg:
        msg["Message-ID"] = message_id
    else:
        msg.replace_header("Message-ID", message_id)
    if "Date" not in msg:
        msg["Date"] = date
    else:
        msg.replace_header("Date", date)
    return msg.as_bytes()


class TestFetchEmails:
    """Tests for the main fetch_emails function with a fully mocked IMAP server."""

    def _setup_mock_imap(
        self,
        mock_imap4_ssl_class,
        messages: list[bytes] | None = None,
        login_error: bool = False,
        select_status: str = "OK",
    ):
        """Configure the mock IMAP4_SSL instance.

        Note: we do NOT use spec=imaplib.IMAP4_SSL here because when
        @patch is active, imaplib.IMAP4_SSL is already a MagicMock and
        Python 3.13 raises InvalidSpecError when using a mock as spec.
        """
        mock_conn = MagicMock()
        mock_imap4_ssl_class.return_value = mock_conn

        if login_error:
            mock_conn.login.side_effect = imaplib.IMAP4.error("LOGIN failed")
            return mock_conn

        mock_conn.select.return_value = (select_status, [b"1"])

        if messages is None:
            messages = [_build_raw_email()]

        # search returns sequence numbers
        seq_nums = " ".join(str(i + 1) for i in range(len(messages)))
        mock_conn.search.return_value = ("OK", [seq_nums.encode()])

        def fetch_side_effect(seq_num, parts):
            idx = int(seq_num if isinstance(seq_num, str) else seq_num.decode()) - 1
            if 0 <= idx < len(messages):
                return ("OK", [(b"1 (RFC822 {1234})", messages[idx])])
            return ("NO", None)

        mock_conn.fetch.side_effect = fetch_side_effect
        return mock_conn

    @patch("app.meeting_fetcher.imap_client.imaplib.IMAP4_SSL")
    def test_successful_fetch_single_message(self, mock_ssl_class):
        """Single message with .txt attachment is fetched successfully."""
        self._setup_mock_imap(mock_ssl_class)

        results = fetch_emails("user@yandex.ru", "password123")

        assert len(results) == 1
        assert results[0].filename == "protocol.txt"
        assert results[0].content == "Meeting transcript here"
        assert results[0].message_id == "<proto@yandex.ru>"

    @patch("app.meeting_fetcher.imap_client.imaplib.IMAP4_SSL")
    def test_successful_fetch_multiple_messages(self, mock_ssl_class):
        """Multiple messages yield multiple attachments."""
        messages = [
            _build_raw_email(
                subject=f"Protocol {i}",
                message_id=f"<msg{i}@yandex.ru>",
                attachment_content=f"Content {i}",
            )
            for i in range(3)
        ]
        self._setup_mock_imap(mock_ssl_class, messages=messages)

        results = fetch_emails("user@yandex.ru", "pass")

        assert len(results) == 3

    @patch("app.meeting_fetcher.imap_client.imaplib.IMAP4_SSL")
    def test_empty_folder(self, mock_ssl_class):
        """Empty folder returns empty list."""
        mock_conn = MagicMock()
        mock_ssl_class.return_value = mock_conn
        mock_conn.select.return_value = ("OK", [b"0"])
        mock_conn.search.return_value = ("OK", [b""])

        results = fetch_emails("user@yandex.ru", "pass")

        assert results == []

    @patch("app.meeting_fetcher.imap_client.imaplib.IMAP4_SSL")
    def test_auth_failure_raises_imap_error(self, mock_ssl_class):
        """Authentication failure raises IMAPError."""
        self._setup_mock_imap(mock_ssl_class, login_error=True)

        with pytest.raises(IMAPError, match="Authentication failed"):
            fetch_emails("bad@yandex.ru", "wrongpass")

    @patch("app.meeting_fetcher.imap_client.imaplib.IMAP4_SSL")
    def test_connection_failure_raises_imap_error(self, mock_ssl_class):
        """Socket/connection error raises IMAPError."""
        mock_ssl_class.side_effect = socket.timeout("Connection timed out")

        with pytest.raises(IMAPError, match="Connection failed"):
            fetch_emails("user@yandex.ru", "pass")

    @patch("app.meeting_fetcher.imap_client.imaplib.IMAP4_SSL")
    def test_connection_gaierror_raises_imap_error(self, mock_ssl_class):
        """DNS resolution error raises IMAPError."""
        mock_ssl_class.side_effect = socket.gaierror("Name resolution failed")

        with pytest.raises(IMAPError, match="Connection failed"):
            fetch_emails("user@yandex.ru", "pass")

    @patch("app.meeting_fetcher.imap_client.imaplib.IMAP4_SSL")
    def test_folder_not_found_raises_imap_error(self, mock_ssl_class):
        """Non-existent folder raises IMAPError."""
        mock_conn = MagicMock()
        mock_ssl_class.return_value = mock_conn
        mock_conn.select.return_value = ("NO", [None])
        mock_conn.list.return_value = ("OK", [b'"." "INBOX"'])

        with pytest.raises(IMAPError, match="Failed to select folder"):
            fetch_emails("user@yandex.ru", "pass", folder="NonExistent")

    @patch("app.meeting_fetcher.imap_client.imaplib.IMAP4_SSL")
    def test_fetch_error_skips_message_continues(self, mock_ssl_class):
        """If one message fetch fails, it is skipped and others continue."""
        good_msg = _build_raw_email(
            subject="Good", message_id="<good@test.com>",
            attachment_content="Good content",
        )

        mock_conn = MagicMock()
        mock_ssl_class.return_value = mock_conn
        mock_conn.select.return_value = ("OK", [b"2"])
        mock_conn.search.return_value = ("OK", [b"1 2"])

        def fetch_side_effect(seq_num, parts):
            num = int(seq_num if isinstance(seq_num, str) else seq_num.decode())
            if num == 1:
                raise imaplib.IMAP4.error("fetch failed")
            return ("OK", [(b"2 (RFC822 {1234})", good_msg)])

        mock_conn.fetch.side_effect = fetch_side_effect

        results = fetch_emails("user@yandex.ru", "pass")

        assert len(results) == 1
        assert results[0].message_id == "<good@test.com>"

    @patch("app.meeting_fetcher.imap_client.imaplib.IMAP4_SSL")
    def test_cleanup_called_on_success(self, mock_ssl_class):
        """close() and logout() are called after successful fetch."""
        mock_conn = self._setup_mock_imap(mock_ssl_class)

        fetch_emails("user@yandex.ru", "pass")

        mock_conn.close.assert_called_once()
        mock_conn.logout.assert_called_once()

    @patch("app.meeting_fetcher.imap_client.imaplib.IMAP4_SSL")
    def test_cleanup_called_on_error(self, mock_ssl_class):
        """close() and logout() are attempted even after errors."""
        mock_conn = MagicMock()
        mock_ssl_class.return_value = mock_conn
        mock_conn.login.side_effect = imaplib.IMAP4.error("LOGIN failed")

        with pytest.raises(IMAPError):
            fetch_emails("user@yandex.ru", "pass")

        # logout should still be attempted (close might fail since no folder was selected)
        mock_conn.logout.assert_called_once()

    @patch("app.meeting_fetcher.imap_client.imaplib.IMAP4_SSL")
    def test_search_failure_raises_imap_error(self, mock_ssl_class):
        """IMAP search returning non-OK status raises IMAPError."""
        mock_conn = MagicMock()
        mock_ssl_class.return_value = mock_conn
        mock_conn.select.return_value = ("OK", [b"5"])
        mock_conn.search.return_value = ("BAD", [None])

        with pytest.raises(IMAPError, match="search failed"):
            fetch_emails("user@yandex.ru", "pass")

    @patch("app.meeting_fetcher.imap_client.imaplib.IMAP4_SSL")
    def test_message_without_txt_returns_empty(self, mock_ssl_class):
        """Message with no .txt attachment returns empty list."""
        msg = MIMEMultipart()
        msg["Subject"] = "No TXT"
        msg["Message-ID"] = "<notxt@test.com>"
        msg["Date"] = "Mon, 21 Apr 2025 10:30:00 +0300"
        body = MIMEText("Just text body", "plain", "utf-8")
        msg.attach(body)

        mock_conn = MagicMock()
        mock_ssl_class.return_value = mock_conn
        mock_conn.select.return_value = ("OK", [b"1"])
        mock_conn.search.return_value = ("OK", [b"1"])
        mock_conn.fetch.return_value = ("OK", [(b"1 (RFC822 {500})", msg.as_bytes())])

        results = fetch_emails("user@yandex.ru", "pass")
        assert results == []

    @patch("app.meeting_fetcher.imap_client.imaplib.IMAP4_SSL")
    def test_custom_folder_and_host(self, mock_ssl_class):
        """Custom folder, host and port parameters are passed correctly."""
        mock_conn = self._setup_mock_imap(mock_ssl_class)

        fetch_emails(
            "user@yandex.ru", "pass",
            folder="TestFolder",
            host="imap.custom.com",
            port=994,
        )

        mock_ssl_class.assert_called_once_with("imap.custom.com", 994, timeout=60)

    @patch("app.meeting_fetcher.imap_client.imaplib.IMAP4_SSL")
    def test_password_not_in_logs(self, mock_ssl_class, caplog):
        """Password must never appear in log output."""
        self._setup_mock_imap(mock_ssl_class)

        secret = "MySuper$ecretP@ss!"
        import logging
        with caplog.at_level(logging.DEBUG, logger="app.meeting_fetcher.imap_client"):
            fetch_emails("user@yandex.ru", secret)

        full_log = caplog.text
        assert secret not in full_log


# ---------------------------------------------------------------------------
# EmailAttachment dataclass
# ---------------------------------------------------------------------------

class TestEmailAttachment:
    def test_creation(self):
        """EmailAttachment can be created with all fields."""
        att = EmailAttachment(
            message_id="<test@example.com>",
            subject="Test",
            date=datetime(2025, 4, 21, 10, 0, tzinfo=MSK),
            filename="test.txt",
            content="Hello world",
        )
        assert att.message_id == "<test@example.com>"
        assert att.subject == "Test"
        assert att.filename == "test.txt"
        assert att.content == "Hello world"

    def test_equality(self):
        """Two EmailAttachments with same fields are equal (dataclass)."""
        dt = datetime(2025, 4, 21, 10, 0, tzinfo=MSK)
        a = EmailAttachment("<id>", "Sub", dt, "f.txt", "content")
        b = EmailAttachment("<id>", "Sub", dt, "f.txt", "content")
        assert a == b


class TestIMAPError:
    def test_is_exception(self):
        assert issubclass(IMAPError, Exception)

    def test_message(self):
        err = IMAPError("test error")
        assert str(err) == "test error"
