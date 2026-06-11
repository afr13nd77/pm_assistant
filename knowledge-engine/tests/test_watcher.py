"""Tests for watcher module with domain-based vault structure."""
import os
import importlib
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, call

# Force import of the watcher module so patch targets resolve
import app.watcher  # noqa: F401


def _setup_vault(tmp_path):
    """Set up vault_paths module to use tmp_path."""
    with patch.dict(os.environ, {"VAULT_PATH": str(tmp_path)}):
        from app import vault_paths
        importlib.reload(vault_paths)
    return tmp_path


class TestStartWatch:
    @patch("app.watcher.PollingObserver")
    def test_watches_all_domain_ideas_dirs(self, mock_observer_cls, tmp_path):
        _setup_vault(tmp_path)

        # Create domain directories
        d1 = tmp_path / "wiki" / "domains" / "search" / "ideas"
        d1.mkdir(parents=True)
        d2 = tmp_path / "wiki" / "domains" / "booking" / "ideas"
        d2.mkdir(parents=True)

        mock_observer = MagicMock()
        mock_observer_cls.return_value = mock_observer

        # Make the watcher stop after start by raising KeyboardInterrupt
        mock_observer.start.side_effect = KeyboardInterrupt

        from app.watcher import start_watch
        try:
            start_watch(str(tmp_path))
        except KeyboardInterrupt:
            pass

        # Verify observer was scheduled on both dirs
        schedule_calls = mock_observer.schedule.call_args_list
        assert len(schedule_calls) == 2

        scheduled_dirs = set()
        for c in schedule_calls:
            # call_args: (handler, dir_path, recursive=False)
            dir_path = c[0][1]
            scheduled_dirs.add(Path(dir_path))

        assert d1 in scheduled_dirs
        assert d2 in scheduled_dirs

    @patch("app.watcher.PollingObserver")
    def test_no_domains_still_starts(self, mock_observer_cls, tmp_path):
        _setup_vault(tmp_path)

        mock_observer = MagicMock()
        mock_observer_cls.return_value = mock_observer
        mock_observer.start.side_effect = KeyboardInterrupt

        from app.watcher import start_watch
        try:
            start_watch(str(tmp_path))
        except KeyboardInterrupt:
            pass

        # No schedule calls since no domains exist
        assert mock_observer.schedule.call_count == 0


class TestInboxHandler:
    def test_ignores_directories(self, tmp_path):
        _setup_vault(tmp_path)

        from app.watcher import InboxHandler
        handler = InboxHandler(str(tmp_path))

        event = MagicMock()
        event.is_directory = True
        handler.on_created(event)
        # Should return without doing anything

    def test_ignores_non_md_files(self, tmp_path):
        _setup_vault(tmp_path)

        from app.watcher import InboxHandler
        handler = InboxHandler(str(tmp_path))

        event = MagicMock()
        event.is_directory = False
        event.src_path = str(tmp_path / "test.txt")
        handler.on_created(event)
        # Should return without enriching

    def test_ignores_tmp_files(self, tmp_path):
        _setup_vault(tmp_path)

        from app.watcher import InboxHandler
        handler = InboxHandler(str(tmp_path))

        event = MagicMock()
        event.is_directory = False
        event.src_path = str(tmp_path / "test.tmp.md")
        handler.on_created(event)
        # Should return without enriching

    @patch("app.watcher.enrich")
    @patch("app.watcher.time.sleep")
    def test_enriches_new_md_file(self, mock_sleep, mock_enrich, tmp_path):
        _setup_vault(tmp_path)

        # Create a test md file
        md_file = tmp_path / "test-idea.md"
        md_file.write_text("---\nstatus: inbox\n---\n# Test Idea\n\nBody.", encoding="utf-8")

        mock_enrich.return_value = {"status": "ok"}

        from app.watcher import InboxHandler
        handler = InboxHandler(str(tmp_path))

        event = MagicMock()
        event.is_directory = False
        event.src_path = str(md_file)
        handler.on_created(event)

        mock_enrich.assert_called_once_with(str(md_file), str(tmp_path))
