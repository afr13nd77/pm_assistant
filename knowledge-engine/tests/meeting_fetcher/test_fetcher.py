"""Unit tests for meeting_fetcher.fetcher module."""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from app.meeting_fetcher.fetcher import (
    fetch_new_meetings,
    save_raw_fallback,
    _unique_filepath,
    _notify,
    _error_result,
    _is_daily,
)
from app.meeting_fetcher.imap_client import EmailAttachment, IMAPError

MSK = timezone(timedelta(hours=3))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def vault(tmp_path):
    """Return a temporary directory acting as the Obsidian vault root."""
    return tmp_path


@pytest.fixture
def sample_attachment():
    """Return a sample EmailAttachment for testing."""
    return EmailAttachment(
        message_id="<test-001@example.com>",
        subject="Daily standup",
        date=datetime(2026, 4, 25, 10, 0, 0, tzinfo=MSK),
        filename="standup.txt",
        content="Alice: did X\nBob: did Y\nDecision: do Z",
    )


@pytest.fixture
def sample_protocol_md():
    """Return a sample protocol markdown with frontmatter."""
    return (
        "---\n"
        "type: daily\n"
        "tags: [meeting, daily]\n"
        "date: 2026-04-25\n"
        "participants: [Alice, Bob]\n"
        "status: inbox\n"
        "---\n"
        "# Daily standup 2026-04-25\n\n"
        "## Participants\n- Alice\n- Bob\n\n"
        "## Decisions\n- Do Z\n\n"
        "## Action Items\n- [ ] Alice: complete X\n"
    )


def _make_attachment(msg_id: str, subject: str = "Meeting") -> EmailAttachment:
    """Helper to quickly create EmailAttachment instances."""
    return EmailAttachment(
        message_id=msg_id,
        subject=subject,
        date=datetime(2026, 4, 25, 10, 0, 0, tzinfo=MSK),
        filename="transcript.txt",
        content="Some transcript content",
    )


# ---------------------------------------------------------------------------
# _error_result
# ---------------------------------------------------------------------------


class TestErrorResult:
    def test_returns_error_status(self):
        result = _error_result("something went wrong")
        assert result["status"] == "error"
        assert result["errors"] == 1
        assert result["total_emails"] == 0
        assert result["newly_processed"] == 0
        assert result["already_processed"] == 0
        assert result["details"] == []
        assert result["message"] == "something went wrong"

    def test_all_keys_present(self):
        result = _error_result("test")
        expected_keys = {
            "status", "total_emails", "already_processed",
            "newly_processed", "skipped_failed", "errors", "details", "message",
        }
        assert set(result.keys()) == expected_keys


# ---------------------------------------------------------------------------
# _unique_filepath
# ---------------------------------------------------------------------------


class TestUniqueFilepath:
    def test_returns_original_when_no_collision(self, tmp_path):
        result = _unique_filepath(tmp_path, "2026-04-25-1000-daily.md")
        assert result == tmp_path / "2026-04-25-1000-daily.md"

    def test_appends_02_on_first_collision(self, tmp_path):
        (tmp_path / "2026-04-25-1000-daily.md").write_text("existing")
        result = _unique_filepath(tmp_path, "2026-04-25-1000-daily.md")
        assert result == tmp_path / "2026-04-25-1000-daily-02.md"

    def test_appends_03_on_second_collision(self, tmp_path):
        (tmp_path / "2026-04-25-1000-daily.md").write_text("existing")
        (tmp_path / "2026-04-25-1000-daily-02.md").write_text("existing")
        result = _unique_filepath(tmp_path, "2026-04-25-1000-daily.md")
        assert result == tmp_path / "2026-04-25-1000-daily-03.md"

    def test_preserves_extension(self, tmp_path):
        (tmp_path / "notes.md").write_text("existing")
        result = _unique_filepath(tmp_path, "notes.md")
        assert result.suffix == ".md"
        assert result.name == "notes-02.md"

    def test_handles_many_collisions(self, tmp_path):
        for i in range(10):
            suffix = f"-{i + 2:02d}" if i > 0 else ""
            name = f"file{suffix}.md" if i > 0 else "file.md"
            (tmp_path / name).write_text("x")
        result = _unique_filepath(tmp_path, "file.md")
        assert not result.exists()


# ---------------------------------------------------------------------------
# _is_daily
# ---------------------------------------------------------------------------


class TestIsDaily:
    def _make_att(self, subject: str, filename: str) -> EmailAttachment:
        return EmailAttachment(
            message_id="<x@x.com>",
            subject=subject,
            date=datetime(2026, 4, 25, 10, 0, 0, tzinfo=MSK),
            filename=filename,
            content="content",
        )

    def test_daily_in_subject_returns_true(self):
        att = self._make_att("Daily standup", "transcript.txt")
        assert _is_daily(att) is True

    def test_daily_in_filename_returns_true(self):
        att = self._make_att("Team sync", "daily-2026-04-25.txt")
        assert _is_daily(att) is True

    def test_daily_uppercase_in_subject_returns_true(self):
        att = self._make_att("DAILY STANDUP", "transcript.txt")
        assert _is_daily(att) is True

    def test_daily_mixed_case_in_filename_returns_true(self):
        att = self._make_att("Team sync", "Daily-Notes.txt")
        assert _is_daily(att) is True

    def test_both_daily_returns_true(self):
        att = self._make_att("Daily standup", "daily-notes.txt")
        assert _is_daily(att) is True

    def test_no_daily_returns_false(self):
        att = self._make_att("Product review", "meeting-transcript.txt")
        assert _is_daily(att) is False

    def test_partial_word_does_not_false_positive(self):
        """'ideally' does not contain the substring 'daily' — no false positive."""
        att = self._make_att("Not ideally a standup", "transcript.txt")
        assert _is_daily(att) is False

    def test_empty_subject_and_filename_returns_false(self):
        att = self._make_att("", "transcript.txt")
        assert _is_daily(att) is False


# ---------------------------------------------------------------------------
# save_raw_fallback
# ---------------------------------------------------------------------------


class TestSaveRawFallback:
    def test_daily_routed_to_daily_logs(self, vault, sample_attachment):
        """subject='Daily standup' → raw/inbound/daily-logs/"""
        result = save_raw_fallback(str(vault), sample_attachment)
        assert result.exists()
        assert result.parent == vault / "raw" / "inbound" / "daily-logs"
        assert result.name == "2026-04-25-1000-standup.txt"
        assert result.read_text(encoding="utf-8") == sample_attachment.content

    def test_non_daily_routed_to_meeting_notes(self, vault):
        """Regular meeting → raw/inbound/meeting-notes/"""
        att = EmailAttachment(
            message_id="<test-002@example.com>",
            subject="Product review",
            date=datetime(2026, 4, 25, 10, 0, 0, tzinfo=MSK),
            filename="review.txt",
            content="Review content",
        )
        result = save_raw_fallback(str(vault), att)
        assert result.exists()
        assert result.parent == vault / "raw" / "inbound" / "meeting-notes"
        assert result.name == "2026-04-25-1000-review.txt"

    def test_daily_in_filename_routed_to_daily_logs(self, vault):
        """filename contains 'daily' → raw/inbound/daily-logs/ even if subject does not."""
        att = EmailAttachment(
            message_id="<test-003@example.com>",
            subject="Team sync",
            date=datetime(2026, 4, 25, 10, 0, 0, tzinfo=MSK),
            filename="daily-2026-04-25.txt",
            content="Stand-up content",
        )
        result = save_raw_fallback(str(vault), att)
        assert result.parent == vault / "raw" / "inbound" / "daily-logs"

    def test_file_content_matches_attachment(self, vault, sample_attachment):
        result = save_raw_fallback(str(vault), sample_attachment)
        assert result.read_text(encoding="utf-8") == sample_attachment.content

    def test_creates_nested_directories(self, vault, sample_attachment):
        """raw/inbound/daily-logs/ should be created even if raw/ doesn't exist."""
        assert not (vault / "raw").exists()
        save_raw_fallback(str(vault), sample_attachment)
        assert (vault / "raw" / "inbound" / "daily-logs").is_dir()

    def test_idempotent_directory_creation(self, vault, sample_attachment):
        """Calling twice should not fail on existing directory."""
        save_raw_fallback(str(vault), sample_attachment)
        att2 = EmailAttachment(
            message_id="<test-002@example.com>",
            subject="Another daily",
            date=datetime(2026, 4, 26, 10, 0, 0, tzinfo=MSK),
            filename="another.txt",
            content="Other content",
        )
        result = save_raw_fallback(str(vault), att2)
        assert result.exists()


# ---------------------------------------------------------------------------
# _notify
# ---------------------------------------------------------------------------


class TestNotify:
    @patch.dict("os.environ", {"BOT_TOKEN": "fake-token", "ALLOWED_CHAT_ID": "12345"})
    @patch("app.meeting_fetcher.fetcher.requests.post")
    def test_sends_plain_text_notification(self, mock_post):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = _notify("Hello test")
        assert result is True

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["text"] == "Hello test"
        assert payload["chat_id"] == "12345"
        # Must NOT have parse_mode key
        assert "parse_mode" not in payload

    @patch.dict("os.environ", {"BOT_TOKEN": "", "ALLOWED_CHAT_ID": ""})
    def test_returns_false_when_env_missing(self):
        result = _notify("Hello")
        assert result is False

    @patch.dict("os.environ", {"BOT_TOKEN": "tok", "ALLOWED_CHAT_ID": "123"})
    @patch("app.meeting_fetcher.fetcher.requests.post", side_effect=Exception("network error"))
    def test_returns_false_on_request_failure(self, mock_post):
        result = _notify("Hello")
        assert result is False


# ---------------------------------------------------------------------------
# fetch_new_meetings — credentials missing
# ---------------------------------------------------------------------------


class TestFetchNewMeetingsCredentials:
    @patch.dict("os.environ", {}, clear=True)
    def test_returns_error_when_login_missing(self, vault):
        result = fetch_new_meetings(str(vault))
        assert result["status"] == "error"
        assert "YANDEX_LOGIN" in result["message"]

    @patch.dict("os.environ", {"YANDEX_LOGIN": "user@ya.ru"}, clear=True)
    def test_returns_error_when_password_missing(self, vault):
        result = fetch_new_meetings(str(vault))
        assert result["status"] == "error"
        assert "YANDEX_APP_PASSWORD" in result["message"]


# ---------------------------------------------------------------------------
# fetch_new_meetings — IMAP error
# ---------------------------------------------------------------------------


class TestFetchNewMeetingsIMAPError:
    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails", side_effect=IMAPError("Connection refused"))
    def test_returns_error_on_imap_failure(self, mock_fetch, vault):
        result = fetch_new_meetings(str(vault))
        assert result["status"] == "error"
        assert "IMAP error" in result["message"]
        assert "Connection refused" in result["message"]

    @patch.dict(
        "os.environ",
        {
            "YANDEX_LOGIN": "user@ya.ru",
            "YANDEX_APP_PASSWORD": "secret",
            "BOT_TOKEN": "tok",
            "ALLOWED_CHAT_ID": "123",
        },
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails", side_effect=IMAPError("timeout"))
    @patch("app.meeting_fetcher.fetcher._notify")
    def test_sends_error_notification_on_imap_failure(
        self, mock_notify, mock_fetch, vault
    ):
        fetch_new_meetings(str(vault), notify=True)
        mock_notify.assert_called_once()
        msg = mock_notify.call_args[0][0]
        assert "ошибка подключения" in msg
        assert "timeout" in msg


# ---------------------------------------------------------------------------
# fetch_new_meetings — empty inbox
# ---------------------------------------------------------------------------


class TestFetchNewMeetingsEmpty:
    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails", return_value=[])
    def test_returns_ok_with_zero_counts(self, mock_fetch, vault):
        result = fetch_new_meetings(str(vault))
        assert result["status"] == "ok"
        assert result["total_emails"] == 0
        assert result["newly_processed"] == 0
        assert result["already_processed"] == 0
        assert result["errors"] == 0


# ---------------------------------------------------------------------------
# fetch_new_meetings — dry run
# ---------------------------------------------------------------------------


class TestFetchNewMeetingsDryRun:
    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    def test_dry_run_returns_skip_without_processing(self, mock_fetch, vault):
        mock_fetch.return_value = [
            _make_attachment("<msg-1@ex.com>"),
            _make_attachment("<msg-2@ex.com>"),
        ]

        result = fetch_new_meetings(str(vault), dry_run=True)
        assert result["status"] == "skip"
        assert result["total_emails"] == 2
        assert result["newly_processed"] == 0
        assert result["already_processed"] == 0
        assert result["details"] == []
        assert "Dry run" in result["message"]

    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    @patch("app.meeting_fetcher.fetcher.claude_client")
    def test_dry_run_does_not_call_claude(
        self, mock_claude, mock_fetch, vault
    ):
        mock_fetch.return_value = [_make_attachment("<msg-1@ex.com>")]
        fetch_new_meetings(str(vault), dry_run=True)
        mock_claude.process_meeting_transcript.assert_not_called()


# ---------------------------------------------------------------------------
# fetch_new_meetings — dedup (state filtering)
# ---------------------------------------------------------------------------


class TestFetchNewMeetingsDedup:
    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    @patch("app.meeting_fetcher.fetcher.claude_client")
    @patch("app.meeting_fetcher.fetcher.enrich", return_value={"status": "ok", "links_found": 0})
    def test_skips_already_processed_emails(
        self, mock_enrich, mock_claude, mock_fetch, vault, sample_protocol_md
    ):
        att1 = _make_attachment("<old@ex.com>", "Old meeting")
        att2 = _make_attachment("<new@ex.com>", "New meeting")
        mock_fetch.return_value = [att1, att2]
        mock_claude.process_meeting_transcript.return_value = sample_protocol_md

        # Pre-seed state with att1
        from app.meeting_fetcher.state import State

        state = State(str(vault))
        state.mark_processed(
            "<old@ex.com>", "Old meeting", "2026-04-25", "t.txt",
            "docs/old.md", "daily",
        )

        result = fetch_new_meetings(str(vault))
        assert result["already_processed"] == 1
        assert result["newly_processed"] == 1
        # Claude should only be called once (for the new attachment)
        assert mock_claude.process_meeting_transcript.call_count == 1


# ---------------------------------------------------------------------------
# fetch_new_meetings — successful processing
# ---------------------------------------------------------------------------


class TestFetchNewMeetingsSuccess:
    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    @patch("app.meeting_fetcher.fetcher.claude_client")
    @patch("app.meeting_fetcher.fetcher.enrich", return_value={"status": "ok", "links_found": 3})
    def test_full_pipeline_success(
        self, mock_enrich, mock_claude, mock_fetch, vault, sample_protocol_md
    ):
        att = _make_attachment("<new@ex.com>", "Daily standup")
        mock_fetch.return_value = [att]
        mock_claude.process_meeting_transcript.return_value = sample_protocol_md

        result = fetch_new_meetings(str(vault))

        assert result["status"] == "ok"
        assert result["total_emails"] == 1
        assert result["newly_processed"] == 1
        assert result["errors"] == 0
        assert len(result["details"]) == 1
        assert result["details"][0]["type"] == "daily"
        assert result["details"][0]["links_found"] == 3

    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    @patch("app.meeting_fetcher.fetcher.claude_client")
    @patch("app.meeting_fetcher.fetcher.enrich", return_value={"status": "ok", "links_found": 0})
    def test_creates_protocol_file_in_correct_folder(
        self, mock_enrich, mock_claude, mock_fetch, vault, sample_protocol_md
    ):
        att = _make_attachment("<new@ex.com>", "Daily standup")
        mock_fetch.return_value = [att]
        mock_claude.process_meeting_transcript.return_value = sample_protocol_md

        fetch_new_meetings(str(vault))

        daily_dir = vault / "wiki" / "daily-logs"
        assert daily_dir.exists()
        md_files = list(daily_dir.glob("*.md"))
        assert len(md_files) == 1
        content = md_files[0].read_text(encoding="utf-8")
        assert "Daily standup" in content

    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    @patch("app.meeting_fetcher.fetcher.claude_client")
    @patch("app.meeting_fetcher.fetcher.enrich", return_value={"status": "ok", "links_found": 0})
    def test_marks_processed_in_state(
        self, mock_enrich, mock_claude, mock_fetch, vault, sample_protocol_md
    ):
        att = _make_attachment("<new@ex.com>", "Daily standup")
        mock_fetch.return_value = [att]
        mock_claude.process_meeting_transcript.return_value = sample_protocol_md

        fetch_new_meetings(str(vault))

        from app.meeting_fetcher.state import State

        state = State(str(vault))
        assert state.is_processed("<new@ex.com>") is True

    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    @patch("app.meeting_fetcher.fetcher.claude_client")
    @patch("app.meeting_fetcher.fetcher.enrich", return_value={"status": "ok", "links_found": 0})
    def test_idempotent_second_run(
        self, mock_enrich, mock_claude, mock_fetch, vault, sample_protocol_md
    ):
        att = _make_attachment("<new@ex.com>", "Daily standup")
        mock_fetch.return_value = [att]
        mock_claude.process_meeting_transcript.return_value = sample_protocol_md

        r1 = fetch_new_meetings(str(vault))
        assert r1["newly_processed"] == 1

        r2 = fetch_new_meetings(str(vault))
        assert r2["newly_processed"] == 0
        assert r2["already_processed"] == 1


# ---------------------------------------------------------------------------
# fetch_new_meetings — Claude failure with raw fallback
# ---------------------------------------------------------------------------


class TestFetchNewMeetingsClaudeFailure:
    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    @patch(
        "app.meeting_fetcher.fetcher.claude_client"
    )
    def test_saves_raw_fallback_on_claude_error(
        self, mock_claude, mock_fetch, vault
    ):
        att = _make_attachment("<fail@ex.com>", "Broken meeting")
        mock_fetch.return_value = [att]
        mock_claude.process_meeting_transcript.side_effect = Exception(
            "Claude API unavailable"
        )

        result = fetch_new_meetings(str(vault))

        assert result["status"] == "error"
        assert result["errors"] == 1
        assert result["newly_processed"] == 0

        # Raw fallback should exist — "Broken meeting" is not daily, goes to meeting-notes
        raw_files = list((vault / "raw" / "inbound" / "meeting-notes").glob("*.txt"))
        assert len(raw_files) == 1

    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    @patch("app.meeting_fetcher.fetcher.claude_client")
    def test_does_not_mark_processed_on_claude_error(
        self, mock_claude, mock_fetch, vault
    ):
        att = _make_attachment("<fail@ex.com>", "Broken meeting")
        mock_fetch.return_value = [att]
        mock_claude.process_meeting_transcript.side_effect = Exception("fail")

        fetch_new_meetings(str(vault))

        from app.meeting_fetcher.state import State

        state = State(str(vault))
        assert state.is_processed("<fail@ex.com>") is False


# ---------------------------------------------------------------------------
# fetch_new_meetings — enrichment failure (non-fatal)
# ---------------------------------------------------------------------------


class TestFetchNewMeetingsEnrichmentFailure:
    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    @patch("app.meeting_fetcher.fetcher.claude_client")
    @patch("app.meeting_fetcher.fetcher.enrich", side_effect=Exception("enrichment boom"))
    def test_enrichment_failure_is_non_fatal(
        self, mock_enrich, mock_claude, mock_fetch, vault, sample_protocol_md
    ):
        att = _make_attachment("<new@ex.com>", "Daily standup")
        mock_fetch.return_value = [att]
        mock_claude.process_meeting_transcript.return_value = sample_protocol_md

        result = fetch_new_meetings(str(vault))

        # Processing should still succeed
        assert result["status"] == "ok"
        assert result["newly_processed"] == 1
        assert result["errors"] == 0
        # links_found defaults to 0 when enrichment fails
        assert result["details"][0]["links_found"] == 0

    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    @patch("app.meeting_fetcher.fetcher.claude_client")
    @patch("app.meeting_fetcher.fetcher.enrich", side_effect=Exception("enrichment boom"))
    def test_state_marked_even_when_enrichment_fails(
        self, mock_enrich, mock_claude, mock_fetch, vault, sample_protocol_md
    ):
        att = _make_attachment("<new@ex.com>", "Daily standup")
        mock_fetch.return_value = [att]
        mock_claude.process_meeting_transcript.return_value = sample_protocol_md

        fetch_new_meetings(str(vault))

        from app.meeting_fetcher.state import State

        state = State(str(vault))
        assert state.is_processed("<new@ex.com>") is True


# ---------------------------------------------------------------------------
# fetch_new_meetings — notifications
# ---------------------------------------------------------------------------


class TestFetchNewMeetingsNotifications:
    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    @patch("app.meeting_fetcher.fetcher.claude_client")
    @patch("app.meeting_fetcher.fetcher.enrich", return_value={"status": "ok", "links_found": 2})
    @patch("app.meeting_fetcher.fetcher._notify")
    def test_sends_per_protocol_and_summary_notifications(
        self, mock_notify, mock_enrich, mock_claude, mock_fetch,
        vault, sample_protocol_md,
    ):
        att = _make_attachment("<new@ex.com>", "Daily standup")
        mock_fetch.return_value = [att]
        mock_claude.process_meeting_transcript.return_value = sample_protocol_md

        fetch_new_meetings(str(vault), notify=True)

        # 2 notifications: per-protocol + summary
        assert mock_notify.call_count == 2

        # First call: per-protocol notification
        per_protocol_msg = mock_notify.call_args_list[0][0][0]
        assert "Протокол встречи готов" in per_protocol_msg
        assert "daily" in per_protocol_msg

        # Second call: summary notification
        summary_msg = mock_notify.call_args_list[1][0][0]
        assert "обработка завершена" in summary_msg

    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    @patch("app.meeting_fetcher.fetcher.claude_client")
    @patch("app.meeting_fetcher.fetcher.enrich", return_value={"status": "ok", "links_found": 0})
    @patch("app.meeting_fetcher.fetcher._notify")
    def test_no_notifications_when_notify_false(
        self, mock_notify, mock_enrich, mock_claude, mock_fetch,
        vault, sample_protocol_md,
    ):
        att = _make_attachment("<new@ex.com>", "Daily standup")
        mock_fetch.return_value = [att]
        mock_claude.process_meeting_transcript.return_value = sample_protocol_md

        fetch_new_meetings(str(vault), notify=False)

        mock_notify.assert_not_called()


# ---------------------------------------------------------------------------
# fetch_new_meetings — multiple attachments, mixed results
# ---------------------------------------------------------------------------


class TestFetchNewMeetingsMixed:
    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    @patch("app.meeting_fetcher.fetcher.claude_client")
    @patch("app.meeting_fetcher.fetcher.enrich", return_value={"status": "ok", "links_found": 0})
    def test_partial_failure_counts(
        self, mock_enrich, mock_claude, mock_fetch, vault, sample_protocol_md
    ):
        att1 = _make_attachment("<ok@ex.com>", "Good meeting")
        att2 = _make_attachment("<fail@ex.com>", "Bad meeting")
        att3 = _make_attachment("<ok2@ex.com>", "Another good meeting")
        mock_fetch.return_value = [att1, att2, att3]

        # att2 will fail on Claude call
        mock_claude.process_meeting_transcript.side_effect = [
            sample_protocol_md,
            Exception("Claude down"),
            sample_protocol_md,
        ]

        result = fetch_new_meetings(str(vault))

        assert result["status"] == "error"  # has errors
        assert result["total_emails"] == 3
        assert result["newly_processed"] == 2
        assert result["errors"] == 1
        assert len(result["details"]) == 2

    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    @patch("app.meeting_fetcher.fetcher.claude_client")
    @patch("app.meeting_fetcher.fetcher.enrich", return_value={"status": "ok", "links_found": 0})
    def test_multiple_success_creates_multiple_files(
        self, mock_enrich, mock_claude, mock_fetch, vault, sample_protocol_md
    ):
        att1 = _make_attachment("<m1@ex.com>", "Meeting one")
        att2 = _make_attachment("<m2@ex.com>", "Meeting two")
        mock_fetch.return_value = [att1, att2]
        mock_claude.process_meeting_transcript.return_value = sample_protocol_md

        result = fetch_new_meetings(str(vault))

        assert result["newly_processed"] == 2
        daily_dir = vault / "wiki" / "daily-logs"
        md_files = list(daily_dir.glob("*.md"))
        assert len(md_files) == 2


# ---------------------------------------------------------------------------
# fetch_new_meetings — result dict structure
# ---------------------------------------------------------------------------


class TestFetchResultStructure:
    """Verify that returned dicts always have the expected keys."""

    EXPECTED_KEYS = {
        "status", "total_emails", "already_processed",
        "newly_processed", "skipped_failed", "errors", "details", "message",
    }

    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails", return_value=[])
    def test_ok_result_has_all_keys(self, mock_fetch, vault):
        result = fetch_new_meetings(str(vault))
        assert set(result.keys()) == self.EXPECTED_KEYS

    @patch.dict("os.environ", {}, clear=True)
    def test_error_result_has_all_keys(self, vault):
        result = fetch_new_meetings(str(vault))
        assert set(result.keys()) == self.EXPECTED_KEYS

    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    def test_dry_run_result_has_all_keys(self, mock_fetch, vault):
        mock_fetch.return_value = [_make_attachment("<m@ex.com>")]
        result = fetch_new_meetings(str(vault), dry_run=True)
        assert set(result.keys()) == self.EXPECTED_KEYS


# ---------------------------------------------------------------------------
# fetch_new_meetings — failed retry limiting
# ---------------------------------------------------------------------------


class TestFetchNewMeetingsFailedRetryLimiting:
    """Tests for the max-retry skip behavior (Bug 1 fix)."""

    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    @patch("app.meeting_fetcher.fetcher.claude_client")
    def test_marks_failed_on_processing_error(
        self, mock_claude, mock_fetch, vault
    ):
        """When processing fails, the email is tracked in failed state."""
        att = _make_attachment("<fail@ex.com>", "Broken meeting")
        mock_fetch.return_value = [att]
        mock_claude.process_meeting_transcript.side_effect = Exception("API error")

        fetch_new_meetings(str(vault))

        from app.meeting_fetcher.state import State

        state = State(str(vault))
        assert state._data["failed"]["<fail@ex.com>"]["attempts"] == 1

    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    @patch("app.meeting_fetcher.fetcher.claude_client")
    def test_increments_failed_on_repeated_errors(
        self, mock_claude, mock_fetch, vault
    ):
        """Each failed run increments the attempt counter."""
        att = _make_attachment("<fail@ex.com>", "Broken meeting")
        mock_fetch.return_value = [att]
        mock_claude.process_meeting_transcript.side_effect = Exception("API error")

        fetch_new_meetings(str(vault))
        fetch_new_meetings(str(vault))

        from app.meeting_fetcher.state import State

        state = State(str(vault))
        assert state._data["failed"]["<fail@ex.com>"]["attempts"] == 2

    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    @patch("app.meeting_fetcher.fetcher.claude_client")
    def test_skips_max_retried_emails(
        self, mock_claude, mock_fetch, vault
    ):
        """After 3 failures, the email is skipped on subsequent runs."""
        att = _make_attachment("<fail@ex.com>", "Broken meeting")
        mock_fetch.return_value = [att]
        mock_claude.process_meeting_transcript.side_effect = Exception("API error")

        # Fail 3 times
        for _ in range(3):
            fetch_new_meetings(str(vault))

        # Reset mock to track calls on 4th run
        mock_claude.process_meeting_transcript.reset_mock()
        mock_claude.process_meeting_transcript.side_effect = Exception("API error")

        result = fetch_new_meetings(str(vault))

        # Claude should NOT be called (email was skipped)
        mock_claude.process_meeting_transcript.assert_not_called()
        assert result["skipped_failed"] == 1
        assert result["errors"] == 0

    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    @patch("app.meeting_fetcher.fetcher.claude_client")
    @patch("app.meeting_fetcher.fetcher._notify")
    def test_sends_permanently_failed_notification(
        self, mock_notify, mock_claude, mock_fetch, vault
    ):
        """One-time notification when email hits max retries."""
        att = _make_attachment("<fail@ex.com>", "Broken meeting")
        mock_fetch.return_value = [att]
        mock_claude.process_meeting_transcript.side_effect = Exception("Claude timeout")

        # First 2 runs: no permanent-fail notification
        fetch_new_meetings(str(vault), notify=True)
        fetch_new_meetings(str(vault), notify=True)

        # Check that "необработаемое" was NOT sent yet
        for call in mock_notify.call_args_list:
            assert "необработаемое" not in call[0][0]

        mock_notify.reset_mock()

        # 3rd run: should trigger permanent-fail notification
        fetch_new_meetings(str(vault), notify=True)

        # Find the permanent-fail notification
        perm_fail_msgs = [
            call[0][0]
            for call in mock_notify.call_args_list
            if "необработаемое" in call[0][0]
        ]
        assert len(perm_fail_msgs) == 1
        assert "Broken meeting" in perm_fail_msgs[0]
        assert "3/3" in perm_fail_msgs[0]

    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    @patch("app.meeting_fetcher.fetcher.claude_client")
    @patch("app.meeting_fetcher.fetcher._notify")
    def test_skipped_failed_in_summary_notification(
        self, mock_notify, mock_claude, mock_fetch, vault
    ):
        """Summary notification includes skipped_failed count when > 0."""
        att = _make_attachment("<fail@ex.com>", "Broken meeting")
        mock_fetch.return_value = [att]
        mock_claude.process_meeting_transcript.side_effect = Exception("error")

        # Fail 3 times to max-retry
        for _ in range(3):
            fetch_new_meetings(str(vault))

        mock_notify.reset_mock()

        # 4th run: email is skipped
        fetch_new_meetings(str(vault), notify=True)

        # Find the summary notification
        summary_msgs = [
            call[0][0]
            for call in mock_notify.call_args_list
            if "обработка завершена" in call[0][0]
        ]
        assert len(summary_msgs) == 1
        assert "неисправимые ошибки" in summary_msgs[0]

    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    @patch("app.meeting_fetcher.fetcher.claude_client")
    @patch("app.meeting_fetcher.fetcher.enrich", return_value={"status": "ok", "links_found": 0})
    def test_mix_of_skipped_and_processed(
        self, mock_enrich, mock_claude, mock_fetch, vault, sample_protocol_md
    ):
        """Mix of permanently failed (skipped) and new (processable) emails."""
        att_fail = _make_attachment("<fail@ex.com>", "Broken meeting")
        att_new = _make_attachment("<new@ex.com>", "Good meeting")

        # First: fail att_fail 3 times
        mock_fetch.return_value = [att_fail]
        mock_claude.process_meeting_transcript.side_effect = Exception("error")
        for _ in range(3):
            fetch_new_meetings(str(vault))

        # Now: both emails in inbox
        mock_fetch.return_value = [att_fail, att_new]
        mock_claude.process_meeting_transcript.side_effect = None
        mock_claude.process_meeting_transcript.return_value = sample_protocol_md

        result = fetch_new_meetings(str(vault))

        assert result["skipped_failed"] == 1
        assert result["newly_processed"] == 1
        assert result["errors"] == 0


# ---------------------------------------------------------------------------
# fetch_new_meetings — raw transcript saved before Claude processing
# ---------------------------------------------------------------------------


class TestRawTranscriptAlwaysSaved:
    """Tests for BUG-008: raw transcript must be saved before Claude call."""

    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    @patch("app.meeting_fetcher.fetcher.claude_client")
    @patch("app.meeting_fetcher.fetcher.enrich", return_value={"status": "ok", "links_found": 0})
    def test_raw_file_exists_when_claude_succeeds(
        self, mock_enrich, mock_claude, mock_fetch, vault, sample_protocol_md
    ):
        """AC-01: When Claude succeeds, raw file AND protocol must both exist."""
        att = _make_attachment("<ok@ex.com>", "Daily standup")
        mock_fetch.return_value = [att]
        mock_claude.process_meeting_transcript.return_value = sample_protocol_md

        result = fetch_new_meetings(str(vault))

        assert result["status"] == "ok"
        assert result["newly_processed"] == 1

        # Raw file must exist in raw/inbound/daily-logs/
        raw_files = list((vault / "raw" / "inbound" / "daily-logs").glob("*.txt"))
        assert len(raw_files) == 1

        # Protocol file must exist in wiki folder
        daily_dir = vault / "wiki" / "daily-logs"
        md_files = list(daily_dir.glob("*.md"))
        assert len(md_files) == 1

    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    @patch("app.meeting_fetcher.fetcher.claude_client")
    def test_raw_file_saved_once_when_claude_fails(
        self, mock_claude, mock_fetch, vault
    ):
        """AC-02: When Claude fails, raw file is saved once (not duplicated)."""
        att = _make_attachment("<fail@ex.com>", "Broken meeting")
        mock_fetch.return_value = [att]
        mock_claude.process_meeting_transcript.side_effect = Exception(
            "Claude API unavailable"
        )

        result = fetch_new_meetings(str(vault))

        assert result["status"] == "error"
        assert result["errors"] == 1

        # Raw file in meeting-notes (non-daily), exactly one file
        raw_files = list((vault / "raw" / "inbound" / "meeting-notes").glob("*.txt"))
        assert len(raw_files) == 1

    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    @patch("app.meeting_fetcher.fetcher.claude_client")
    @patch("app.meeting_fetcher.fetcher.save_raw_fallback", side_effect=Exception("disk full"))
    def test_raw_save_failure_caught_and_logged(
        self, mock_save_raw, mock_claude, mock_fetch, vault, caplog
    ):
        """AC-03: If raw saving itself fails before Claude call, error is caught and logged."""
        att = _make_attachment("<fail@ex.com>", "Some meeting")
        mock_fetch.return_value = [att]

        with caplog.at_level(logging.ERROR):
            result = fetch_new_meetings(str(vault))

        assert result["errors"] == 1
        # Claude should NOT have been called since raw save failed first
        mock_claude.process_meeting_transcript.assert_not_called()
        # The error should be logged
        assert any("disk full" in record.message for record in caplog.records)

    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    @patch("app.meeting_fetcher.fetcher.claude_client")
    def test_mark_failed_called_when_claude_fails(
        self, mock_claude, mock_fetch, vault
    ):
        """AC-02: mark_failed is called when Claude fails."""
        att = _make_attachment("<fail@ex.com>", "Broken meeting")
        mock_fetch.return_value = [att]
        mock_claude.process_meeting_transcript.side_effect = Exception("Claude down")

        fetch_new_meetings(str(vault))

        from app.meeting_fetcher.state import State

        state = State(str(vault))
        assert "<fail@ex.com>" in state._data["failed"]
        assert state._data["failed"]["<fail@ex.com>"]["attempts"] == 1
