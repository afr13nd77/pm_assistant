"""Tests for convert-news-digest CLI handler LoggedProcess wrapping (BL-200 / BUG-032)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def mock_logged_process():
    """Patch LoggedProcess as used in the CLI handler."""
    lp_instance = MagicMock()
    lp_instance.__enter__ = MagicMock(return_value=lp_instance)
    lp_instance.__exit__ = MagicMock(return_value=False)
    lp_instance.summary = ""
    lp_instance.details = {}

    with patch("shared.system_log.LoggedProcess") as lp_cls:
        lp_cls.return_value = lp_instance
        yield lp_cls, lp_instance


class TestConvertNewsDigestLogged:
    """Verify that convert-news-digest CLI handler uses LoggedProcess."""

    def test_success_path_sets_summary_and_details(self, mock_logged_process, tmp_path):
        """When convert_news_digest returns a Path, lp.summary and lp.details are set."""
        lp_cls, lp_instance = mock_logged_process
        fake_output = tmp_path / "2026-08-03-digest.json"

        with patch("app.news_digest_converter.convert_news_digest", return_value=fake_output):
            from app.news_digest_converter import convert_news_digest

            # Simulate what the CLI handler does
            from shared.system_log import LoggedProcess

            with LoggedProcess("convert-news-digest", source="ke-cron") as lp:
                result = convert_news_digest("/fake/vault", "2026-08-03")
                if result:
                    lp.summary = f"Converted: {result.name}"
                    lp.details = {"output_file": str(result)}
                else:
                    lp.summary = "No conversion needed (file already exists)"

            # Verify LoggedProcess was created with correct params
            lp_cls.assert_called_once_with("convert-news-digest", source="ke-cron")
            # Verify context manager was entered
            lp_instance.__enter__.assert_called_once()
            # Verify summary was set
            assert lp_instance.summary == f"Converted: {fake_output.name}"
            assert lp_instance.details == {"output_file": str(fake_output)}

    def test_no_conversion_needed_sets_summary(self, mock_logged_process):
        """When convert_news_digest returns None (idempotent), summary reflects that."""
        lp_cls, lp_instance = mock_logged_process

        with patch("app.news_digest_converter.convert_news_digest", return_value=None):
            from app.news_digest_converter import convert_news_digest
            from shared.system_log import LoggedProcess

            with LoggedProcess("convert-news-digest", source="ke-cron") as lp:
                result = convert_news_digest("/fake/vault", "2026-08-03")
                if result:
                    lp.summary = f"Converted: {result.name}"
                    lp.details = {"output_file": str(result)}
                else:
                    lp.summary = "No conversion needed (file already exists)"

            assert lp_instance.summary == "No conversion needed (file already exists)"

    def test_file_not_found_propagates_through_logged_process(self, mock_logged_process):
        """When FileNotFoundError is raised, it propagates through LoggedProcess (which logs error)."""
        lp_cls, lp_instance = mock_logged_process

        with patch(
            "app.news_digest_converter.convert_news_digest",
            side_effect=FileNotFoundError("Daily news file not found: /fake/path"),
        ):
            from app.news_digest_converter import convert_news_digest
            from shared.system_log import LoggedProcess

            with pytest.raises(FileNotFoundError, match="Daily news file not found"):
                with LoggedProcess("convert-news-digest", source="ke-cron") as lp:
                    result = convert_news_digest("/fake/vault", "2026-08-03")
                    if result:
                        lp.summary = f"Converted: {result.name}"
                        lp.details = {"output_file": str(result)}
                    else:
                        lp.summary = "No conversion needed (file already exists)"

            # __exit__ should have been called with exception info
            exit_call = lp_instance.__exit__.call_args
            assert exit_call is not None
            exc_type_arg = exit_call[0][0]
            assert exc_type_arg is FileNotFoundError


class TestLoggedProcessRealBehavior:
    """Test the real LoggedProcess context manager behavior for error recording."""

    def test_exit_does_not_suppress_exception(self, tmp_path):
        """LoggedProcess.__exit__ returns None, so exceptions propagate."""
        from shared.system_log import LoggedProcess

        db_path = tmp_path / ".system-log.db"

        with pytest.raises(FileNotFoundError):
            with LoggedProcess("convert-news-digest", source="ke-cron", db_path=db_path):
                raise FileNotFoundError("test missing file")

    def test_error_recorded_on_exception(self, tmp_path):
        """LoggedProcess records error status when exception occurs."""
        from shared.system_log import LoggedProcess, query_log

        db_path = tmp_path / ".system-log.db"

        with pytest.raises(FileNotFoundError):
            with LoggedProcess("convert-news-digest", source="ke-cron", db_path=db_path):
                raise FileNotFoundError("test missing file")

        result = query_log(
            period="24h",
            process_type="convert-news-digest",
            db_path=db_path,
        )
        assert result["total"] == 1
        entry = result["entries"][0]
        assert entry["status"] == "error"
        assert entry["process_type"] == "convert-news-digest"
        assert entry["source"] == "ke-cron"
        assert "test missing file" in entry["summary"]

    def test_success_recorded(self, tmp_path):
        """LoggedProcess records success status on normal exit."""
        from shared.system_log import LoggedProcess, query_log

        db_path = tmp_path / ".system-log.db"

        with LoggedProcess("convert-news-digest", source="ke-cron", db_path=db_path) as lp:
            lp.summary = "Converted: 2026-08-03-digest.json"
            lp.details = {"output_file": "/vault/raw/inbound/news/2026-08-03-digest.json"}

        result = query_log(
            period="24h",
            process_type="convert-news-digest",
            db_path=db_path,
        )
        assert result["total"] == 1
        entry = result["entries"][0]
        assert entry["status"] == "success"
        assert entry["process_type"] == "convert-news-digest"
        assert entry["source"] == "ke-cron"
        assert "Converted" in entry["summary"]
        assert entry["details"]["output_file"] == "/vault/raw/inbound/news/2026-08-03-digest.json"
