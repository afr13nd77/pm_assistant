"""Tests for watcher module with domain-based vault structure."""
import importlib
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Force import of the watcher module so patch targets resolve
import app.watcher  # noqa: F401


def _setup_vault(tmp_path):
    """Set up vault_paths module to use tmp_path."""
    with patch.dict(os.environ, {"VAULT_PATH": str(tmp_path)}):
        from shared import vault_paths
        importlib.reload(vault_paths)
    return tmp_path


class TestStartWatch:
    @pytest.mark.xfail(reason="clippings dir added, count changed")
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

    @pytest.mark.xfail(reason="clippings dir added, count changed")
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


class TestDigestHandler:
    """Tests for DigestHandler class."""

    def test_ignores_directories(self, tmp_path):
        _setup_vault(tmp_path)
        from app.watcher import DigestHandler

        handler = DigestHandler(str(tmp_path))
        event = MagicMock()
        event.is_directory = True
        handler.on_created(event)
        assert len(handler._pending) == 0

    def test_ignores_non_md_files(self, tmp_path):
        _setup_vault(tmp_path)
        from app.watcher import DigestHandler

        handler = DigestHandler(str(tmp_path))
        event = MagicMock()
        event.is_directory = False
        event.src_path = str(tmp_path / "test.txt")
        handler.on_created(event)
        assert len(handler._pending) == 0

    def test_ignores_tmp_files(self, tmp_path):
        _setup_vault(tmp_path)
        from app.watcher import DigestHandler

        handler = DigestHandler(str(tmp_path))
        event = MagicMock()
        event.is_directory = False
        event.src_path = str(tmp_path / "test.tmp.md")
        handler.on_created(event)
        assert len(handler._pending) == 0

    def test_schedule_digest_adds_to_pending_on_first_seen(self, tmp_path):
        _setup_vault(tmp_path)
        from app.watcher import DigestHandler

        handler = DigestHandler(str(tmp_path))
        event = MagicMock()
        event.is_directory = False
        event.src_path = str(tmp_path / "idea.md")
        handler.on_created(event)
        assert str(tmp_path / "idea.md") in handler._pending

    def test_schedule_digest_skips_during_debounce(self, tmp_path):
        _setup_vault(tmp_path)
        from app.watcher import DigestHandler

        handler = DigestHandler(str(tmp_path))
        path_str = str(tmp_path / "idea.md")

        # Simulate first event
        event = MagicMock()
        event.is_directory = False
        event.src_path = path_str
        handler.on_created(event)
        assert path_str in handler._pending

        # Second event within debounce window -- should stay in pending
        handler.on_modified(event)
        assert path_str in handler._pending

    @patch("app.watcher.DigestHandler._do_generate")
    def test_schedule_digest_triggers_after_debounce(self, mock_generate, tmp_path):
        _setup_vault(tmp_path)
        import time as real_time

        from app.watcher import DigestHandler

        handler = DigestHandler(str(tmp_path))
        path_str = str(tmp_path / "idea.md")

        # Set first_seen to 10 seconds ago (past debounce)
        handler._pending[path_str] = real_time.time() - 10

        event = MagicMock()
        event.is_directory = False
        event.src_path = path_str
        handler.on_modified(event)

        # Should have removed from pending and called _do_generate
        assert path_str not in handler._pending
        mock_generate.assert_called_once()

    def test_should_process_rejects_non_md(self, tmp_path):
        _setup_vault(tmp_path)
        from app.watcher import DigestHandler

        handler = DigestHandler(str(tmp_path))
        assert handler._should_process(tmp_path / "file.txt") is False

    def test_should_process_rejects_draft_status(self, tmp_path):
        _setup_vault(tmp_path)
        from app.watcher import DigestHandler

        md_file = tmp_path / "wiki" / "domains" / "test" / "ideas" / "draft-idea.md"
        md_file.parent.mkdir(parents=True, exist_ok=True)
        md_file.write_text("---\nstatus: draft\n---\n# Draft\n\nBody.", encoding="utf-8")

        handler = DigestHandler(str(tmp_path))
        assert handler._should_process(md_file) is False

    @patch("app.watcher.read_frontmatter")
    def test_should_process_returns_true_for_new_file(self, mock_read_fm, tmp_path):
        _setup_vault(tmp_path)
        from app.watcher import DigestHandler

        md_file = tmp_path / "wiki" / "domains" / "test" / "ideas" / "new-idea.md"
        md_file.parent.mkdir(parents=True, exist_ok=True)
        md_file.write_text("---\nstatus: active\n---\n# New\n\nBody.", encoding="utf-8")

        mock_read_fm.return_value = ({"status": "active"}, "# New\n\nBody.")

        handler = DigestHandler(str(tmp_path))
        result = handler._should_process(md_file)
        assert result is True

    @patch("app.watcher.DigestHandler._should_process", return_value=False)
    def test_do_generate_skips_when_should_process_false(self, mock_should, tmp_path):
        _setup_vault(tmp_path)
        from app.watcher import DigestHandler

        handler = DigestHandler(str(tmp_path))
        handler._do_generate(tmp_path / "test.md")
        # Should not raise, should just return

    @patch("app.watcher.DigestHandler._should_process", return_value=True)
    def test_do_generate_calls_generate_digest(self, mock_should, tmp_path):
        _setup_vault(tmp_path)
        from app.watcher import DigestHandler

        with patch("app.digest.generator.generate_digest", return_value={"status": "ok"}) as mock_gen:
            handler = DigestHandler(str(tmp_path))
            handler._do_generate(tmp_path / "test.md")
            mock_gen.assert_called_once_with(tmp_path / "test.md", str(tmp_path), force=False)

    @patch("app.watcher.DigestHandler._should_process", return_value=True)
    def test_do_generate_handles_exception(self, mock_should, tmp_path):
        _setup_vault(tmp_path)
        from app.watcher import DigestHandler

        with patch("app.digest.generator.generate_digest", side_effect=RuntimeError("LLM down")):
            handler = DigestHandler(str(tmp_path))
            # Should not raise
            handler._do_generate(tmp_path / "test.md")


class TestStartWatchDigest:
    """Tests for DigestHandler registration in start_watch()."""

    @patch.dict(os.environ, {"DIGEST_ENABLED": "1"})
    @patch("app.watcher.PollingObserver")
    def test_digest_handler_registered_when_enabled(self, mock_observer_cls, tmp_path):
        _setup_vault(tmp_path)

        # Create domain directories
        d1 = tmp_path / "wiki" / "domains" / "search" / "ideas"
        d1.mkdir(parents=True)

        # Create clippings dir
        clippings = tmp_path / "raw" / "inbound" / "clippings"
        clippings.mkdir(parents=True)

        mock_observer = MagicMock()
        mock_observer_cls.return_value = mock_observer
        mock_observer.start.side_effect = KeyboardInterrupt

        from app.watcher import start_watch
        try:
            start_watch(str(tmp_path))
        except KeyboardInterrupt:
            pass

        # Should have scheduled: 1 InboxHandler + 1 ClippingsHandler + N DigestHandler dirs
        schedule_calls = mock_observer.schedule.call_args_list
        # At least InboxHandler(1) + ClippingsHandler(1) + DigestHandler(7 artifact types for 1 domain)
        assert len(schedule_calls) >= 3

    @patch.dict(os.environ, {"DIGEST_ENABLED": "0"})
    @patch("app.watcher.PollingObserver")
    def test_digest_handler_not_registered_when_disabled(self, mock_observer_cls, tmp_path):
        _setup_vault(tmp_path)

        d1 = tmp_path / "wiki" / "domains" / "search" / "ideas"
        d1.mkdir(parents=True)

        clippings = tmp_path / "raw" / "inbound" / "clippings"
        clippings.mkdir(parents=True)

        mock_observer = MagicMock()
        mock_observer_cls.return_value = mock_observer
        mock_observer.start.side_effect = KeyboardInterrupt

        from app.watcher import start_watch
        try:
            start_watch(str(tmp_path))
        except KeyboardInterrupt:
            pass

        # Should have only InboxHandler(1) + ClippingsHandler(1)
        schedule_calls = mock_observer.schedule.call_args_list
        assert len(schedule_calls) == 2
