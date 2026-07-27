"""Unit tests for scheduler.py: start_scheduler with enrichment and daily alert jobs."""

from unittest.mock import MagicMock, patch

import pytest


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
        # enrichment_reminder + daily_alert = 2 jobs (no weekly_report)
        assert mock_sched_instance.add_job.call_count == 2
        mock_sched_instance.start.assert_called_once()
        assert result is mock_sched_instance

    @patch("app.scheduler.BackgroundScheduler")
    def test_start_scheduler_registers_enrichment_and_daily_alert(self, MockSchedulerClass):
        from app.scheduler import start_scheduler

        mock_sched_instance = MagicMock()
        MockSchedulerClass.return_value = mock_sched_instance

        bot = MagicMock()
        start_scheduler(bot, chat_id=99)

        job_ids = [
            call[1]["id"]
            for call in mock_sched_instance.add_job.call_args_list
        ]
        assert "enrichment_reminder" in job_ids
        assert "daily_alert" in job_ids
        assert "weekly_report" not in job_ids

    @patch("app.scheduler.BackgroundScheduler")
    def test_start_scheduler_replace_existing(self, MockSchedulerClass):
        """Calling start_scheduler twice should use replace_existing=True."""
        from app.scheduler import start_scheduler

        mock_sched_instance = MagicMock()
        MockSchedulerClass.return_value = mock_sched_instance

        bot = MagicMock()
        start_scheduler(bot, chat_id=1)
        start_scheduler(bot, chat_id=1)

        for call in mock_sched_instance.add_job.call_args_list:
            assert call[1]["replace_existing"] is True
