"""Tests for CLI meeting-queue subcommands: process-queue / queue-watch / queue-status (T-10, BL-145)."""

import importlib
import io
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _run_main(argv: list[str], tmp_path: Path):
    """Invoke cli.main() with argv, capturing stdout. Returns (exit_code, stdout_text)."""
    captured = io.StringIO()
    with patch.dict(os.environ, {"VAULT_PATH": str(tmp_path)}):
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


# ---------------------------------------------------------------------------
# process-queue
# ---------------------------------------------------------------------------


class TestProcessQueue:
    def test_process_queue_calls_process_pending(self, tmp_path):
        """process-queue invokes processor.process_pending and outputs the summary JSON."""
        summary = {
            "status": "ok",
            "reclaimed": 0,
            "processed": 2,
            "failed": 1,
            "requeued": 0,
            "details": [],
        }
        captured = io.StringIO()
        with patch.dict(os.environ, {"VAULT_PATH": str(tmp_path)}):
            with patch.object(sys, "argv", ["knowledge_engine", "process-queue", "--limit", "5"]):
                with patch(
                    "app.meeting_fetcher.processor.process_pending", return_value=summary
                ) as mock_pp:
                    from app import cli
                    importlib.reload(cli)
                    with patch("sys.stdout", captured):
                        with pytest.raises(SystemExit) as exc:
                            cli.main()
        assert exc.value.code == 0
        mock_pp.assert_called_once_with(str(tmp_path), limit=5, notify=False)
        data = json.loads(captured.getvalue().strip())
        assert data["processed"] == 2
        assert data["failed"] == 1

    def test_process_queue_default_limit_none_and_notify_flag(self, tmp_path):
        """Without --limit, limit=None is passed; --notify forwards notify=True."""
        summary = {"status": "ok", "reclaimed": 0, "processed": 0,
                   "failed": 0, "requeued": 0, "details": []}
        with patch.dict(os.environ, {"VAULT_PATH": str(tmp_path)}):
            with patch.object(sys, "argv", ["knowledge_engine", "process-queue", "--notify"]):
                with patch(
                    "app.meeting_fetcher.processor.process_pending", return_value=summary
                ) as mock_pp:
                    from app import cli
                    importlib.reload(cli)
                    with patch("sys.stdout", io.StringIO()):
                        with pytest.raises(SystemExit):
                            cli.main()
        mock_pp.assert_called_once_with(str(tmp_path), limit=None, notify=True)

    def test_process_queue_error_exits_1(self, tmp_path):
        """process-queue with status=error exits 1."""
        summary = {"status": "error", "reclaimed": 0, "processed": 0,
                   "failed": 0, "requeued": 0, "details": [], "message": "boom"}
        with patch.dict(os.environ, {"VAULT_PATH": str(tmp_path)}):
            with patch.object(sys, "argv", ["knowledge_engine", "process-queue"]):
                with patch(
                    "app.meeting_fetcher.processor.process_pending", return_value=summary
                ):
                    from app import cli
                    importlib.reload(cli)
                    with patch("sys.stdout", io.StringIO()):
                        with pytest.raises(SystemExit) as exc:
                            cli.main()
        assert exc.value.code == 1

    def test_process_queue_live_empty_vault(self, tmp_path):
        """process-queue on a real empty vault returns processed=0 without error."""
        exit_code, output = _run_main(["process-queue", "--limit", "1"], tmp_path)
        assert exit_code == 0
        data = json.loads(output.strip())
        assert data["status"] == "ok"
        assert data["processed"] == 0


# ---------------------------------------------------------------------------
# queue-status
# ---------------------------------------------------------------------------


class TestQueueStatus:
    def test_queue_status_table_empty(self, tmp_path):
        """queue-status --format table on empty queue prints zero counters."""
        exit_code, output = _run_main(["queue-status", "--format", "table"], tmp_path)
        assert exit_code == 0
        assert "Meeting queue status" in output
        assert "pending:" in output
        assert "No units in queue." in output

    def test_queue_status_json_empty(self, tmp_path):
        """queue-status --format json on empty queue outputs zero counts and empty units."""
        exit_code, output = _run_main(["queue-status", "--format", "json"], tmp_path)
        assert exit_code == 0
        data = json.loads(output.strip())
        assert data["status"] == "ok"
        assert data["counts"] == {"pending": 0, "processing": 0, "done": 0, "failed": 0}
        assert data["units"] == []

    def test_queue_status_calls_status_counts(self, tmp_path):
        """queue-status invokes MeetingQueue.status_counts()."""
        counts = {"pending": 3, "processing": 1, "done": 5, "failed": 2}
        with patch.dict(os.environ, {"VAULT_PATH": str(tmp_path)}):
            with patch.object(sys, "argv", ["knowledge_engine", "queue-status", "--format", "json"]):
                with patch(
                    "app.meeting_fetcher.queue.MeetingQueue.status_counts", return_value=counts
                ) as mock_sc:
                    captured = io.StringIO()
                    from app import cli
                    importlib.reload(cli)
                    with patch("sys.stdout", captured):
                        with pytest.raises(SystemExit) as exc:
                            cli.main()
        assert exc.value.code == 0
        mock_sc.assert_called_once()
        data = json.loads(captured.getvalue().strip())
        assert data["counts"] == counts

    def test_queue_status_lists_pending_unit(self, tmp_path):
        """A pending unit (via enqueue) shows up in queue-status json output."""
        import datetime

        from shared.meeting_queue import enqueue
        enqueue(str(tmp_path), raw_text="тест", source="local",
                subject="t", date=datetime.datetime.now(), source_filename="a.txt")
        exit_code, output = _run_main(["queue-status", "--format", "json"], tmp_path)
        assert exit_code == 0
        data = json.loads(output.strip())
        assert data["counts"]["pending"] == 1
        assert len(data["units"]) == 1
        assert data["units"][0]["source"] == "local"
        assert data["units"][0]["status"] == "pending"


# ---------------------------------------------------------------------------
# queue-watch
# ---------------------------------------------------------------------------


class TestQueueWatch:
    def test_queue_watch_calls_start_queue_watch_and_joins(self, tmp_path):
        """queue-watch invokes start_queue_watch and blocks on observer.join()."""
        fake_observer = MagicMock()
        with patch.dict(os.environ, {"VAULT_PATH": str(tmp_path)}):
            with patch.object(sys, "argv", ["knowledge_engine", "queue-watch", "--notify"]):
                with patch(
                    "app.meeting_fetcher.queue_watcher.start_queue_watch",
                    return_value=fake_observer,
                ) as mock_start:
                    from app import cli
                    importlib.reload(cli)
                    cli.main()
        mock_start.assert_called_once_with(str(tmp_path), notify=True)
        fake_observer.join.assert_called_once()

    def test_queue_watch_keyboard_interrupt_stops_observer(self, tmp_path):
        """KeyboardInterrupt during join() triggers observer.stop() + join()."""
        fake_observer = MagicMock()
        fake_observer.join.side_effect = [KeyboardInterrupt(), None]
        with patch.dict(os.environ, {"VAULT_PATH": str(tmp_path)}):
            with patch.object(sys, "argv", ["knowledge_engine", "queue-watch"]):
                with patch(
                    "app.meeting_fetcher.queue_watcher.start_queue_watch",
                    return_value=fake_observer,
                ):
                    from app import cli
                    importlib.reload(cli)
                    cli.main()
        fake_observer.stop.assert_called_once()
        assert fake_observer.join.call_count == 2
