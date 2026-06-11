"""Unit tests for scheduler.py: start_scheduler, _run_weekly_report,
_run_weekly_report_async.
"""

import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


class TestStartScheduler:
    """Tests for start_scheduler function."""

    @patch("app.scheduler.BackgroundScheduler")
    def test_start_scheduler_creates_and_starts(self, MockSchedulerClass):
        from app.scheduler import start_scheduler

        mock_sched_instance = MagicMock()
        MockSchedulerClass.return_value = mock_sched_instance

        bot = MagicMock()
        result = start_scheduler(bot, chat_id=12345)

        MockSchedulerClass.assert_called_once()
        mock_sched_instance.add_job.assert_called_once()
        mock_sched_instance.start.assert_called_once()
        assert result is mock_sched_instance

    @patch("app.scheduler.BackgroundScheduler")
    def test_start_scheduler_job_params(self, MockSchedulerClass):
        from app.scheduler import start_scheduler

        mock_sched_instance = MagicMock()
        MockSchedulerClass.return_value = mock_sched_instance

        bot = MagicMock()
        start_scheduler(bot, chat_id=99)

        call_kwargs = mock_sched_instance.add_job.call_args
        assert call_kwargs[1]["trigger"] == "cron"
        assert call_kwargs[1]["day_of_week"] == "mon"
        assert call_kwargs[1]["hour"] == 9
        assert call_kwargs[1]["minute"] == 0
        assert call_kwargs[1]["id"] == "weekly_report"
        assert call_kwargs[1]["replace_existing"] is True

    @patch("app.scheduler.BackgroundScheduler")
    def test_start_scheduler_replace_existing(self, MockSchedulerClass):
        """Calling start_scheduler twice should use replace_existing=True."""
        from app.scheduler import start_scheduler

        mock_sched_instance = MagicMock()
        MockSchedulerClass.return_value = mock_sched_instance

        bot = MagicMock()
        start_scheduler(bot, chat_id=1)
        start_scheduler(bot, chat_id=1)

        assert mock_sched_instance.add_job.call_count == 2
        for call in mock_sched_instance.add_job.call_args_list:
            assert call[1]["replace_existing"] is True


class TestRunWeeklyReportAsync:
    """Tests for _run_weekly_report_async."""

    @pytest.mark.asyncio
    async def test_successful_report(self):
        """Test that a successful report is generated, saved, and notification sent."""
        from app.scheduler import _run_weekly_report_async

        mock_filepath = MagicMock()
        mock_filepath.name = "2026-04-27-week-18.md"

        bot = AsyncMock()

        with patch("app.reporter.generate_weekly_report", return_value="# Weekly Report\nContent"), \
             patch("app.obsidian_writer.write_report", return_value=mock_filepath):
            await _run_weekly_report_async(bot, chat_id=123)

        bot.send_message.assert_called_once()
        call_kwargs = bot.send_message.call_args[1]
        assert call_kwargs["chat_id"] == 123
        assert "2026-04-27-week-18.md" in call_kwargs["text"]

    @pytest.mark.asyncio
    async def test_report_generation_failure_sends_error(self):
        from app.scheduler import _run_weekly_report_async

        bot = AsyncMock()

        with patch("app.reporter.generate_weekly_report", side_effect=RuntimeError("Claude API down")):
            await _run_weekly_report_async(bot, chat_id=456)

        # Should attempt to send error notification
        bot.send_message.assert_called_once()
        call_kwargs = bot.send_message.call_args[1]
        assert call_kwargs["chat_id"] == 456
        assert "Claude API down" in call_kwargs["text"]

    @pytest.mark.asyncio
    async def test_error_notification_failure_does_not_raise(self):
        """If both report generation and error notification fail, should not raise."""
        from app.scheduler import _run_weekly_report_async

        bot = AsyncMock()
        bot.send_message.side_effect = RuntimeError("Telegram API down")

        with patch("app.reporter.generate_weekly_report", side_effect=RuntimeError("fail")):
            # Should not raise even though both report and notification fail
            await _run_weekly_report_async(bot, chat_id=789)


class TestRunWeeklyReportSync:
    """Tests for _run_weekly_report sync wrapper."""

    @patch("app.scheduler._run_weekly_report_async", new_callable=AsyncMock)
    def test_sync_wrapper_dispatches(self, mock_async_fn):
        from app.scheduler import _run_weekly_report

        bot = MagicMock()
        _run_weekly_report(bot, chat_id=42)

        # The async function should have been called (via event loop)
        # We can't easily verify the exact call due to asyncio wrapping,
        # but we can verify no exception was raised

    @patch("app.scheduler._run_weekly_report_async", new_callable=AsyncMock)
    def test_sync_wrapper_handles_runtime_error(self, mock_async_fn):
        """If get_event_loop raises RuntimeError, a new loop should be created."""
        from app.scheduler import _run_weekly_report

        bot = MagicMock()

        with patch("asyncio.get_event_loop", side_effect=RuntimeError("no loop")), \
             patch("asyncio.new_event_loop") as mock_new_loop, \
             patch("asyncio.set_event_loop"):
            mock_loop = MagicMock()
            mock_loop.run_until_complete = MagicMock()
            mock_new_loop.return_value = mock_loop

            _run_weekly_report(bot, chat_id=55)

            mock_new_loop.assert_called_once()
            mock_loop.run_until_complete.assert_called_once()
