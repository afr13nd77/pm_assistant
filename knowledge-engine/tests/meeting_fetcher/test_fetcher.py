"""Unit tests for meeting_fetcher.fetcher module (BL-145 queue refactor).

After the meeting-processing-queue refactor, ``fetch_new_meetings`` is LLM-free:
it only enqueues new attachments into ``raw/meeting-queue/pending/`` via
``shared.meeting_queue.enqueue`` and records them in state (``mark_enqueued``).
These tests verify the new contract: enqueue + dedup gate + fast LLM-free return
+ NO wiki protocol written. The retained helper functions (``save_raw_fallback``,
``_unique_filepath``, ``_is_daily``, ``_notify``, ``_error_result``) are still
tested directly since they remain in the module for reuse by the Process worker.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.meeting_fetcher.fetcher import (
    _error_result,
    _is_daily,
    _notify,
    _unique_filepath,
    fetch_new_meetings,
    save_raw_fallback,
)
from app.meeting_fetcher.imap_client import EmailAttachment, IMAPError
from app.meeting_fetcher.state import State

MSK = timezone(timedelta(hours=3))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def vault(tmp_path):
    """Return a temporary directory acting as the Obsidian vault root."""
    return tmp_path


def _make_attachment(
    msg_id: str,
    subject: str = "Meeting",
    content: str = "Some transcript content",
) -> EmailAttachment:
    """Helper to quickly create EmailAttachment instances."""
    return EmailAttachment(
        message_id=msg_id,
        subject=subject,
        date=datetime(2026, 4, 25, 10, 0, 0, tzinfo=MSK),
        filename="transcript.txt",
        content=content,
    )


def _pending_units(vault) -> list:
    """Return list of *.txt unit files currently in the pending/ queue folder."""
    pending = vault / "raw" / "meeting-queue" / "pending"
    if not pending.exists():
        return []
    return sorted(pending.glob("*.txt"))


def _wiki_protocols(vault) -> list:
    """Return any markdown protocol files anywhere under wiki/."""
    wiki = vault / "wiki"
    if not wiki.exists():
        return []
    return list(wiki.rglob("*.md"))


# ---------------------------------------------------------------------------
# _error_result  (retained helper)
# ---------------------------------------------------------------------------


class TestErrorResult:
    EXPECTED_KEYS = {
        "status", "total_emails", "already_processed", "newly_processed",
        "enqueued", "skipped_failed", "errors", "details", "message",
    }

    def test_returns_error_status(self):
        result = _error_result("something went wrong")
        assert result["status"] == "error"
        assert result["errors"] == 1
        assert result["total_emails"] == 0
        assert result["newly_processed"] == 0
        assert result["enqueued"] == 0
        assert result["already_processed"] == 0
        assert result["details"] == []
        assert result["message"] == "something went wrong"

    def test_all_keys_present(self):
        result = _error_result("test")
        assert set(result.keys()) == self.EXPECTED_KEYS


# ---------------------------------------------------------------------------
# _unique_filepath  (retained helper, reused by processor)
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


# ---------------------------------------------------------------------------
# _is_daily  (retained helper)
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

    def test_no_daily_returns_false(self):
        att = self._make_att("Product review", "meeting-transcript.txt")
        assert _is_daily(att) is False

    def test_partial_word_does_not_false_positive(self):
        att = self._make_att("Not ideally a standup", "transcript.txt")
        assert _is_daily(att) is False


# ---------------------------------------------------------------------------
# save_raw_fallback  (retained helper, reused by processor)
# ---------------------------------------------------------------------------


class TestSaveRawFallback:
    def test_daily_routed_to_daily_logs(self, vault):
        att = _make_attachment("<d@ex.com>", "Daily standup")
        result = save_raw_fallback(str(vault), att)
        assert result.exists()
        assert result.parent == vault / "raw" / "inbound" / "daily-logs"
        assert result.read_text(encoding="utf-8") == att.content

    def test_non_daily_routed_to_meeting_notes(self, vault):
        att = _make_attachment("<m@ex.com>", "Product review")
        result = save_raw_fallback(str(vault), att)
        assert result.exists()
        assert result.parent == vault / "raw" / "inbound" / "meeting-notes"


# ---------------------------------------------------------------------------
# _notify  (retained helper)
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
        assert "parse_mode" not in payload

    @patch.dict("os.environ", {"BOT_TOKEN": "", "ALLOWED_CHAT_ID": ""})
    def test_returns_false_when_env_missing(self):
        assert _notify("Hello") is False


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
    @patch(
        "app.meeting_fetcher.fetcher.fetch_emails",
        side_effect=IMAPError("Connection refused"),
    )
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
        assert result["enqueued"] == 0
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
    def test_dry_run_returns_skip_without_enqueue(self, mock_fetch, vault):
        mock_fetch.return_value = [
            _make_attachment("<msg-1@ex.com>"),
            _make_attachment("<msg-2@ex.com>"),
        ]

        result = fetch_new_meetings(str(vault), dry_run=True)
        assert result["status"] == "skip"
        assert result["total_emails"] == 2
        assert result["newly_processed"] == 0
        assert result["enqueued"] == 0
        assert result["details"] == []
        assert "Dry run" in result["message"]
        # Nothing enqueued on disk
        assert _pending_units(vault) == []


# ---------------------------------------------------------------------------
# fetch_new_meetings — enqueue (core new behaviour)
# ---------------------------------------------------------------------------


class TestFetchNewMeetingsEnqueue:
    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    def test_enqueues_new_attachment(self, mock_fetch, vault):
        att = _make_attachment("<new@ex.com>", "Daily standup")
        mock_fetch.return_value = [att]

        result = fetch_new_meetings(str(vault))

        assert result["status"] == "ok"
        assert result["total_emails"] == 1
        assert result["newly_processed"] == 1
        assert result["enqueued"] == 1
        assert result["skipped_failed"] == 0
        assert result["errors"] == 0
        # One unit (.txt + .meta.json) landed in pending/
        units = _pending_units(vault)
        assert len(units) == 1
        meta = units[0].with_suffix(".meta.json")
        assert meta.exists()

    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    def test_detail_shape_matches_contract(self, mock_fetch, vault):
        att = _make_attachment("<new@ex.com>", "Sync meeting")
        mock_fetch.return_value = [att]

        result = fetch_new_meetings(str(vault))

        assert len(result["details"]) == 1
        detail = result["details"][0]
        assert set(detail.keys()) == {"unit_id", "subject", "source", "status"}
        assert detail["subject"] == "Sync meeting"
        assert detail["source"] == "email"
        assert detail["status"] == "pending"
        assert detail["unit_id"]

    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    def test_no_wiki_protocol_written(self, mock_fetch, vault):
        """AC-01: Fetch is LLM-free — it must NOT create wiki protocols."""
        att = _make_attachment("<new@ex.com>", "Daily standup")
        mock_fetch.return_value = [att]

        fetch_new_meetings(str(vault))

        assert _wiki_protocols(vault) == []

    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    def test_marks_enqueued_in_state(self, mock_fetch, vault):
        att = _make_attachment("<new@ex.com>", "Daily standup")
        mock_fetch.return_value = [att]

        fetch_new_meetings(str(vault))

        state = State(str(vault))
        assert state.is_enqueued("<new@ex.com>") is True

    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    def test_multiple_attachments_enqueued(self, mock_fetch, vault):
        mock_fetch.return_value = [
            _make_attachment("<m1@ex.com>", "Meeting one", content="aaa"),
            _make_attachment("<m2@ex.com>", "Meeting two", content="bbb"),
            _make_attachment("<m3@ex.com>", "Meeting three", content="ccc"),
        ]

        result = fetch_new_meetings(str(vault))

        assert result["newly_processed"] == 3
        assert result["enqueued"] == 3
        assert len(_pending_units(vault)) == 3

    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    def test_empty_transcript_skipped(self, mock_fetch, vault):
        """enqueue() returns None for empty content → not counted, not error."""
        att = _make_attachment("<empty@ex.com>", "Empty meeting", content="   ")
        mock_fetch.return_value = [att]

        result = fetch_new_meetings(str(vault))

        assert result["status"] == "ok"
        assert result["newly_processed"] == 0
        assert result["enqueued"] == 0
        assert result["errors"] == 0
        assert _pending_units(vault) == []


# ---------------------------------------------------------------------------
# fetch_new_meetings — dedup gate (AC-07)
# ---------------------------------------------------------------------------


class TestFetchNewMeetingsDedup:
    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    def test_skips_already_enqueued(self, mock_fetch, vault):
        """Second run with the same emails enqueues nothing (AC-07)."""
        mock_fetch.return_value = [
            _make_attachment("<a@ex.com>", "Meeting A"),
            _make_attachment("<b@ex.com>", "Meeting B"),
        ]

        r1 = fetch_new_meetings(str(vault))
        assert r1["newly_processed"] == 2

        r2 = fetch_new_meetings(str(vault))
        assert r2["newly_processed"] == 0
        assert r2["enqueued"] == 0
        assert r2["already_processed"] == 2
        # Still only 2 units in pending/ — no duplicates.
        assert len(_pending_units(vault)) == 2

    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    def test_skips_already_processed_backcompat(self, mock_fetch, vault):
        """Emails handled by the old monolith (in 'processed') are not re-enqueued."""
        att_old = _make_attachment("<old@ex.com>", "Old meeting")
        att_new = _make_attachment("<new@ex.com>", "New meeting")
        mock_fetch.return_value = [att_old, att_new]

        # Pre-seed state as if att_old was processed by the old pipeline.
        state = State(str(vault))
        state.mark_processed(
            "<old@ex.com>", "Old meeting", "2026-04-25", "t.txt",
            "wiki/old.md", "daily",
        )

        result = fetch_new_meetings(str(vault))

        assert result["already_processed"] == 1
        assert result["newly_processed"] == 1
        # Only the new email got enqueued.
        assert len(_pending_units(vault)) == 1


# ---------------------------------------------------------------------------
# fetch_new_meetings — no LLM / no IMAP side effects
# ---------------------------------------------------------------------------


class TestFetchNewMeetingsNoLLM:
    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    def test_status_ok_without_llm_keys(self, mock_fetch, vault):
        """No CLAUDE_API_KEY in env, yet status is 'ok' (LLM not in Fetch path)."""
        mock_fetch.return_value = [_make_attachment("<x@ex.com>", "Some meeting")]

        result = fetch_new_meetings(str(vault))

        assert result["status"] == "ok"
        assert result["enqueued"] == 1

    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    def test_uses_mocked_fetch_emails(self, mock_fetch, vault):
        """The real IMAP fetch_emails is mocked — confirm it is what's used."""
        mock_fetch.return_value = []
        fetch_new_meetings(str(vault))
        mock_fetch.assert_called_once()


# ---------------------------------------------------------------------------
# fetch_new_meetings — notifications
# ---------------------------------------------------------------------------


class TestFetchNewMeetingsNotifications:
    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    @patch("app.meeting_fetcher.fetcher._notify")
    def test_summary_notification_says_enqueued(self, mock_notify, mock_fetch, vault):
        mock_fetch.return_value = [
            _make_attachment("<m1@ex.com>", "Meeting one", content="aaa"),
            _make_attachment("<m2@ex.com>", "Meeting two", content="bbb"),
        ]

        fetch_new_meetings(str(vault), notify=True)

        # Exactly one summary notification (no per-protocol notifications now).
        assert mock_notify.call_count == 1
        summary = mock_notify.call_args_list[0][0][0]
        assert "поставлено в очередь" in summary

    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    @patch("app.meeting_fetcher.fetcher._notify")
    def test_no_notifications_when_notify_false(self, mock_notify, mock_fetch, vault):
        mock_fetch.return_value = [_make_attachment("<m1@ex.com>", "Meeting one")]
        fetch_new_meetings(str(vault), notify=False)
        mock_notify.assert_not_called()


# ---------------------------------------------------------------------------
# fetch_new_meetings — result dict structure (AC-09)
# ---------------------------------------------------------------------------


class TestFetchResultStructure:
    """Returned dicts always have the AC-09-compatible keys (incl. 'enqueued')."""

    EXPECTED_KEYS = {
        "status", "total_emails", "already_processed", "newly_processed",
        "enqueued", "skipped_failed", "errors", "details", "message",
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

    @patch.dict(
        "os.environ",
        {"YANDEX_LOGIN": "user@ya.ru", "YANDEX_APP_PASSWORD": "secret"},
    )
    @patch("app.meeting_fetcher.fetcher.fetch_emails")
    def test_enqueue_result_has_all_keys(self, mock_fetch, vault):
        mock_fetch.return_value = [_make_attachment("<m@ex.com>")]
        result = fetch_new_meetings(str(vault))
        assert set(result.keys()) == self.EXPECTED_KEYS
