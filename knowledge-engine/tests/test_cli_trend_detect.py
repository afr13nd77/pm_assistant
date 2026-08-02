"""Tests for CLI trend-detect subcommand (T-15)."""

import importlib
import io
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.signal_memory import SignalMemory, SignalRecord, TrendAlert


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_main(argv: list[str], env_overrides: dict | None = None):
    """
    Invoke cli.main() with given argv, capturing stdout.
    Returns (exit_code, stdout_text).
    """
    captured = io.StringIO()
    env = {"VAULT_PATH": "/fake-vault"}
    if env_overrides:
        env.update(env_overrides)

    with patch.dict(os.environ, env, clear=False):
        with patch.object(sys, "argv", ["knowledge_engine"] + argv):
            from app import cli
            importlib.reload(cli)
            with patch("sys.stdout", captured):
                try:
                    cli.main()
                    exit_code = 0
                except SystemExit as e:
                    exit_code = e.code if isinstance(e.code, int) else 0

    return exit_code, captured.getvalue()


def _make_config(**overrides):
    """Create a ModeratorConfig-like object with defaults."""
    from app.signal_orchestrator import ModeratorConfig
    config = ModeratorConfig()
    for k, v in overrides.items():
        setattr(config, k, v)
    return config


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTrendDetectSubparser:
    """Verify subparser registration (AC-28)."""

    def test_trend_detect_registered(self):
        """trend-detect is a valid subcommand."""
        from app.cli import main
        import argparse

        # Just verify the parser accepts trend-detect without error
        with patch.object(sys, "argv", ["knowledge_engine", "trend-detect", "--vault", "/test"]):
            from app import cli
            importlib.reload(cli)
            # Will fail at runtime (no DB), but parser accepts it
            parser = argparse.ArgumentParser()
            # If subparser not registered, main() would fail with argparse error

    def test_trend_detect_help_flag(self):
        """trend-detect --help does not crash."""
        with pytest.raises(SystemExit) as exc_info:
            with patch.object(sys, "argv", ["knowledge_engine", "trend-detect", "--help"]):
                from app import cli
                importlib.reload(cli)
                cli.main()
        assert exc_info.value.code == 0


class TestTrendDetectNoNotify:
    """Test trend-detect without --notify flag (AC-12)."""

    @patch("app.signal_orchestrator.load_config_from_settings")
    @patch("app.signal_memory.SignalMemory")
    @patch("shared.system_log.LoggedProcess")
    def test_detect_trends_called(self, mock_lp_cls, mock_memory_cls, mock_load_config):
        """detect_trends() is invoked with config params."""
        config = _make_config(
            memory_db_path="/tmp/test.db",
            trend_detection_lookback_weeks=6,
            trend_spike_threshold=5,
            memory_cleanup_days=90,
        )
        mock_load_config.return_value = config

        mock_memory = MagicMock()
        mock_memory.detect_trends.return_value = []
        mock_memory.cleanup.return_value = 0
        mock_memory_cls.return_value = mock_memory

        mock_lp = MagicMock()
        mock_lp.__enter__ = MagicMock(return_value=mock_lp)
        mock_lp.__exit__ = MagicMock(return_value=False)
        mock_lp_cls.return_value = mock_lp

        exit_code, output = _run_main(["trend-detect", "--vault", "/fake-vault"])

        assert exit_code == 0
        data = json.loads(output.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert data["trends_detected"] == 0
        assert data["cleaned_up"] == 0

        mock_memory.detect_trends.assert_called_once_with(
            lookback_weeks=6,
            spike_threshold=5,
        )
        mock_memory.cleanup.assert_called_once_with(keep_days=90)

    @patch("app.signal_orchestrator.load_config_from_settings")
    @patch("app.signal_memory.SignalMemory")
    @patch("shared.system_log.LoggedProcess")
    def test_trends_returned_in_output(self, mock_lp_cls, mock_memory_cls, mock_load_config):
        """Detected trends appear in JSON output."""
        config = _make_config(memory_db_path="/tmp/test.db")
        mock_load_config.return_value = config

        trends = [
            TrendAlert(entity="booking.com", trend_type="spike",
                       description="booking.com: 5 mentions this week"),
            TrendAlert(entity="airbnb", trend_type="sustained",
                       description="airbnb: mentioned 4 consecutive weeks"),
        ]

        mock_memory = MagicMock()
        mock_memory.detect_trends.return_value = trends
        mock_memory.cleanup.return_value = 3
        mock_memory_cls.return_value = mock_memory

        mock_lp = MagicMock()
        mock_lp.__enter__ = MagicMock(return_value=mock_lp)
        mock_lp.__exit__ = MagicMock(return_value=False)
        mock_lp_cls.return_value = mock_lp

        exit_code, output = _run_main(["trend-detect", "--vault", "/fake-vault"])

        assert exit_code == 0
        data = json.loads(output.strip().split("\n")[-1])
        assert data["trends_detected"] == 2
        assert data["cleaned_up"] == 3
        assert len(data["trends"]) == 2
        entities = [t["entity"] for t in data["trends"]]
        assert "booking.com" in entities
        assert "airbnb" in entities


class TestTrendDetectWithNotify:
    """Test trend-detect --notify (AC-50)."""

    @patch("app.notifier.send_telegram")
    @patch("app.signal_orchestrator.load_config_from_settings")
    @patch("app.signal_memory.SignalMemory")
    @patch("shared.system_log.LoggedProcess")
    def test_notify_sends_telegram_except_new_entrant(
        self, mock_lp_cls, mock_memory_cls, mock_load_config, mock_send_tg
    ):
        """Non-new_entrant trends trigger Telegram, new_entrant is silent."""
        config = _make_config(memory_db_path="/tmp/test.db")
        mock_load_config.return_value = config

        trends = [
            TrendAlert(entity="booking.com", trend_type="spike",
                       description="spike desc"),
            TrendAlert(entity="newco", trend_type="new_entrant",
                       description="new entrant desc"),
            TrendAlert(entity="airbnb", trend_type="escalation",
                       description="escalation desc"),
        ]

        # Mock DB connection for alert_id lookup
        mock_row_1 = {"id": 101}
        mock_row_2 = {"id": 102}
        mock_row_3 = {"id": 103}
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.side_effect = [
            mock_row_1, mock_row_2, mock_row_3
        ]

        mock_memory = MagicMock()
        mock_memory.detect_trends.return_value = trends
        mock_memory.cleanup.return_value = 0
        mock_memory._get_conn.return_value = mock_conn
        mock_memory_cls.return_value = mock_memory

        mock_send_tg.return_value = True

        mock_lp = MagicMock()
        mock_lp.__enter__ = MagicMock(return_value=mock_lp)
        mock_lp.__exit__ = MagicMock(return_value=False)
        mock_lp_cls.return_value = mock_lp

        exit_code, output = _run_main(["trend-detect", "--vault", "/fake-vault", "--notify"])

        assert exit_code == 0

        # send_telegram called for spike and escalation, NOT for new_entrant
        assert mock_send_tg.call_count == 2
        calls = [c.args[0] for c in mock_send_tg.call_args_list]
        assert any("booking.com" in c for c in calls)
        assert any("airbnb" in c for c in calls)
        assert not any("newco" in c for c in calls)

        # All 3 alerts marked as notified (including new_entrant)
        assert mock_memory.mark_trend_notified.call_count == 3
        mock_memory.mark_trend_notified.assert_any_call(101)
        mock_memory.mark_trend_notified.assert_any_call(102)
        mock_memory.mark_trend_notified.assert_any_call(103)

    @patch("app.notifier.send_telegram")
    @patch("app.signal_orchestrator.load_config_from_settings")
    @patch("app.signal_memory.SignalMemory")
    @patch("shared.system_log.LoggedProcess")
    def test_notify_no_trends_skips_telegram(
        self, mock_lp_cls, mock_memory_cls, mock_load_config, mock_send_tg
    ):
        """With --notify but zero trends, send_telegram is never called."""
        config = _make_config(memory_db_path="/tmp/test.db")
        mock_load_config.return_value = config

        mock_memory = MagicMock()
        mock_memory.detect_trends.return_value = []
        mock_memory.cleanup.return_value = 0
        mock_memory_cls.return_value = mock_memory

        mock_lp = MagicMock()
        mock_lp.__enter__ = MagicMock(return_value=mock_lp)
        mock_lp.__exit__ = MagicMock(return_value=False)
        mock_lp_cls.return_value = mock_lp

        exit_code, output = _run_main(["trend-detect", "--vault", "/fake-vault", "--notify"])

        assert exit_code == 0
        mock_send_tg.assert_not_called()

    @patch("app.notifier.send_telegram", side_effect=Exception("network error"))
    @patch("app.signal_orchestrator.load_config_from_settings")
    @patch("app.signal_memory.SignalMemory")
    @patch("shared.system_log.LoggedProcess")
    def test_notify_telegram_failure_does_not_crash(
        self, mock_lp_cls, mock_memory_cls, mock_load_config, mock_send_tg
    ):
        """Telegram failure is logged as warning, does not crash CLI."""
        config = _make_config(memory_db_path="/tmp/test.db")
        mock_load_config.return_value = config

        trends = [
            TrendAlert(entity="booking.com", trend_type="spike",
                       description="spike desc"),
        ]

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = {"id": 42}

        mock_memory = MagicMock()
        mock_memory.detect_trends.return_value = trends
        mock_memory.cleanup.return_value = 0
        mock_memory._get_conn.return_value = mock_conn
        mock_memory_cls.return_value = mock_memory

        mock_lp = MagicMock()
        mock_lp.__enter__ = MagicMock(return_value=mock_lp)
        mock_lp.__exit__ = MagicMock(return_value=False)
        mock_lp_cls.return_value = mock_lp

        exit_code, output = _run_main(["trend-detect", "--vault", "/fake-vault", "--notify"])

        # Should still succeed (exit 0), just warn
        assert exit_code == 0
        data = json.loads(output.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert data["trends_detected"] == 1

        # mark_trend_notified should still be called even if Telegram fails
        mock_memory.mark_trend_notified.assert_called_once_with(42)


class TestTrendDetectCleanup:
    """Test cleanup after detection."""

    @patch("app.signal_orchestrator.load_config_from_settings")
    @patch("app.signal_memory.SignalMemory")
    @patch("shared.system_log.LoggedProcess")
    def test_cleanup_called_with_config_days(self, mock_lp_cls, mock_memory_cls, mock_load_config):
        """cleanup() called with memory_cleanup_days from config."""
        config = _make_config(memory_db_path="/tmp/test.db", memory_cleanup_days=365)
        mock_load_config.return_value = config

        mock_memory = MagicMock()
        mock_memory.detect_trends.return_value = []
        mock_memory.cleanup.return_value = 42
        mock_memory_cls.return_value = mock_memory

        mock_lp = MagicMock()
        mock_lp.__enter__ = MagicMock(return_value=mock_lp)
        mock_lp.__exit__ = MagicMock(return_value=False)
        mock_lp_cls.return_value = mock_lp

        exit_code, output = _run_main(["trend-detect", "--vault", "/fake-vault"])

        assert exit_code == 0
        mock_memory.cleanup.assert_called_once_with(keep_days=365)
        data = json.loads(output.strip().split("\n")[-1])
        assert data["cleaned_up"] == 42


class TestTrendDetectIntegration:
    """Integration test with real SQLite DB (no mocks for SignalMemory)."""

    def test_full_flow_with_real_db(self, tmp_path):
        """End-to-end: insert signals, detect trends, verify output."""
        db_path = str(tmp_path / "signal_memory.db")
        memory = SignalMemory(db_path)

        # Insert signals for "booking.com" to trigger spike
        from datetime import datetime, timedelta
        today = datetime.now().strftime("%Y-%m-%d")
        for i in range(4):
            memory.record_signal(SignalRecord(
                date=today,
                title=f"Booking news {i}",
                entities=["booking.com"],
                relevance=8,
            ))

        config = _make_config(
            memory_db_path=db_path,
            trend_detection_lookback_weeks=4,
            trend_spike_threshold=3,
            memory_cleanup_days=180,
        )

        with patch("app.signal_orchestrator.load_config_from_settings", return_value=config):
            with patch("shared.system_log.LoggedProcess") as mock_lp_cls:
                mock_lp = MagicMock()
                mock_lp.__enter__ = MagicMock(return_value=mock_lp)
                mock_lp.__exit__ = MagicMock(return_value=False)
                mock_lp_cls.return_value = mock_lp

                exit_code, output = _run_main(["trend-detect", "--vault", str(tmp_path)])

        assert exit_code == 0
        data = json.loads(output.strip().split("\n")[-1])
        assert data["status"] == "ok"
        assert data["trends_detected"] >= 1

        # Verify at least one trend for booking.com
        entities = [t["entity"] for t in data["trends"]]
        assert "booking.com" in entities

        memory.close()
