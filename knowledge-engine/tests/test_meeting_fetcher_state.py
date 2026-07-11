"""Unit tests for meeting_fetcher.state module."""

import json
from unittest.mock import patch

import pytest

from app.meeting_fetcher.state import STATE_FILENAME, State, _empty_state

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def vault(tmp_path):
    """Return a temporary directory acting as the Obsidian vault root."""
    return tmp_path


@pytest.fixture
def state_path(vault):
    """Return the expected path of the state file inside the vault."""
    return vault / STATE_FILENAME


# ---------------------------------------------------------------------------
# __init__ — creation & loading
# ---------------------------------------------------------------------------

class TestStateInit:
    def test_creates_empty_state_when_file_missing(self, vault, state_path):
        """When the state file does not exist, State initialises with empty data."""
        s = State(str(vault))
        assert s._data["version"] == 1
        assert s._data["last_run"] is None
        assert s._data["processed"] == {}
        # File should NOT be written on init alone
        assert not state_path.exists()

    def test_loads_existing_state(self, vault, state_path):
        """When a valid state file exists, it is loaded correctly."""
        existing = {
            "version": 1,
            "last_run": "2026-04-25T10:00:00",
            "processed": {
                "<msg-1>": {
                    "subject": "Test meeting",
                    "date": "2026-04-25T09:00:00",
                    "attachment": "test.txt",
                    "output_file": "docs/test.md",
                    "type": "daily",
                    "processed_at": "2026-04-25T10:00:00",
                }
            },
        }
        state_path.write_text(json.dumps(existing), encoding="utf-8")

        s = State(str(vault))
        assert s._data["processed"]["<msg-1>"]["subject"] == "Test meeting"
        assert len(s._data["processed"]) == 1

    def test_recovers_from_corrupt_json(self, vault, state_path):
        """If the state file contains invalid JSON, it is replaced with empty state."""
        state_path.write_text("{not valid json!!!", encoding="utf-8")

        s = State(str(vault))
        assert s._data == _empty_state()

    def test_recovers_from_empty_file(self, vault, state_path):
        """An empty file should be treated as corrupt and replaced."""
        state_path.write_text("", encoding="utf-8")

        s = State(str(vault))
        assert s._data == _empty_state()


# ---------------------------------------------------------------------------
# is_processed
# ---------------------------------------------------------------------------

class TestIsProcessed:
    def test_returns_false_for_unknown_message(self, vault):
        s = State(str(vault))
        assert s.is_processed("<unknown@example.com>") is False

    def test_returns_true_for_known_message(self, vault, state_path):
        existing = {
            "version": 1,
            "last_run": "2026-04-25T10:00:00",
            "processed": {
                "<known@example.com>": {
                    "subject": "x",
                    "date": "2026-04-25",
                    "attachment": "a.txt",
                    "output_file": "docs/x.md",
                    "type": "daily",
                    "processed_at": "2026-04-25T10:00:00",
                }
            },
        }
        state_path.write_text(json.dumps(existing), encoding="utf-8")

        s = State(str(vault))
        assert s.is_processed("<known@example.com>") is True


# ---------------------------------------------------------------------------
# mark_processed
# ---------------------------------------------------------------------------

class TestMarkProcessed:
    def test_adds_entry_and_persists(self, vault, state_path):
        s = State(str(vault))
        s.mark_processed(
            message_id="<new@example.com>",
            subject="Daily standup",
            date="2026-04-25T09:00:00+03:00",
            attachment="standup.txt",
            output_file="docs/daily-protocols/2026-04-25-daily.md",
            protocol_type="daily",
        )

        # In-memory state
        assert s.is_processed("<new@example.com>") is True
        entry = s._data["processed"]["<new@example.com>"]
        assert entry["subject"] == "Daily standup"
        assert entry["date"] == "2026-04-25T09:00:00+03:00"
        assert entry["attachment"] == "standup.txt"
        assert entry["output_file"] == "docs/daily-protocols/2026-04-25-daily.md"
        assert entry["type"] == "daily"
        assert "processed_at" in entry

        # Persisted to disk
        assert state_path.exists()
        on_disk = json.loads(state_path.read_text(encoding="utf-8"))
        assert "<new@example.com>" in on_disk["processed"]
        assert on_disk["last_run"] is not None

    def test_multiple_entries_accumulate(self, vault):
        s = State(str(vault))
        for i in range(3):
            s.mark_processed(
                message_id=f"<msg-{i}@example.com>",
                subject=f"Meeting {i}",
                date=f"2026-04-2{i}T09:00:00",
                attachment=f"file{i}.txt",
                output_file=f"docs/meeting-{i}.md",
                protocol_type="weekly",
            )
        assert len(s._data["processed"]) == 3
        for i in range(3):
            assert s.is_processed(f"<msg-{i}@example.com>") is True

    def test_overwrite_existing_entry(self, vault):
        """Marking the same message-id again should overwrite the entry."""
        s = State(str(vault))
        s.mark_processed(
            message_id="<dup@example.com>",
            subject="First version",
            date="2026-04-25T09:00:00",
            attachment="v1.txt",
            output_file="docs/v1.md",
            protocol_type="daily",
        )
        s.mark_processed(
            message_id="<dup@example.com>",
            subject="Second version",
            date="2026-04-25T09:00:00",
            attachment="v2.txt",
            output_file="docs/v2.md",
            protocol_type="daily",
        )
        assert len(s._data["processed"]) == 1
        assert s._data["processed"]["<dup@example.com>"]["subject"] == "Second version"


# ---------------------------------------------------------------------------
# _save — last_run update and atomic write
# ---------------------------------------------------------------------------

class TestSave:
    def test_last_run_updated_on_save(self, vault):
        s = State(str(vault))
        assert s._data["last_run"] is None

        s.mark_processed(
            message_id="<ts@example.com>",
            subject="Test",
            date="2026-04-25",
            attachment="a.txt",
            output_file="docs/a.md",
            protocol_type="daily",
        )
        assert s._data["last_run"] is not None

    def test_state_survives_reload(self, vault, state_path):
        """State written by one instance is readable by another."""
        s1 = State(str(vault))
        s1.mark_processed(
            message_id="<persist@example.com>",
            subject="Persist test",
            date="2026-04-25",
            attachment="p.txt",
            output_file="docs/p.md",
            protocol_type="retro",
        )

        s2 = State(str(vault))
        assert s2.is_processed("<persist@example.com>") is True
        assert s2._data["processed"]["<persist@example.com>"]["type"] == "retro"

    def test_save_raises_on_write_failure(self, vault):
        """If atomic_write fails, mark_processed should propagate the exception."""
        s = State(str(vault))
        with patch("app.meeting_fetcher.state.atomic_write", side_effect=OSError("disk full")):
            with pytest.raises(OSError, match="disk full"):
                s.mark_processed(
                    message_id="<fail@example.com>",
                    subject="Fail",
                    date="2026-04-25",
                    attachment="f.txt",
                    output_file="docs/f.md",
                    protocol_type="daily",
                )


# ---------------------------------------------------------------------------
# Version field
# ---------------------------------------------------------------------------

class TestVersion:
    def test_state_has_version_1(self, vault):
        s = State(str(vault))
        s.mark_processed(
            message_id="<v@example.com>",
            subject="V",
            date="2026-04-25",
            attachment="v.txt",
            output_file="docs/v.md",
            protocol_type="daily",
        )
        on_disk = json.loads((vault / STATE_FILENAME).read_text(encoding="utf-8"))
        assert on_disk["version"] == 1


# ---------------------------------------------------------------------------
# UTF-8 / i18n
# ---------------------------------------------------------------------------

class TestUtf8:
    def test_cyrillic_subject_roundtrip(self, vault, state_path):
        """Cyrillic text in subject must survive save/load cycle."""
        s = State(str(vault))
        s.mark_processed(
            message_id="<cyr@example.com>",
            subject="Запись встречи: daily 25.04",
            date="2026-04-25T10:00:00+03:00",
            attachment="daily-25-04.txt",
            output_file="docs/daily-protocols/2026-04-25-daily.md",
            protocol_type="daily",
        )

        s2 = State(str(vault))
        entry = s2._data["processed"]["<cyr@example.com>"]
        assert entry["subject"] == "Запись встречи: daily 25.04"


# ---------------------------------------------------------------------------
# mark_failed
# ---------------------------------------------------------------------------

class TestMarkFailed:
    def test_creates_new_failed_entry(self, vault, state_path):
        """First failure for a message creates a new entry with attempts=1."""
        s = State(str(vault))
        s.mark_failed("<fail@example.com>", "Bad meeting", "Claude timeout")

        entry = s._data["failed"]["<fail@example.com>"]
        assert entry["subject"] == "Bad meeting"
        assert entry["attempts"] == 1
        assert entry["last_error"] == "Claude timeout"
        assert "first_seen" in entry
        assert "last_seen" in entry

        # Persisted to disk
        assert state_path.exists()
        on_disk = json.loads(state_path.read_text(encoding="utf-8"))
        assert "<fail@example.com>" in on_disk["failed"]

    def test_increments_attempts_on_repeated_failure(self, vault):
        """Subsequent failures increment the attempts counter."""
        s = State(str(vault))
        s.mark_failed("<fail@example.com>", "Bad meeting", "Error 1")
        s.mark_failed("<fail@example.com>", "Bad meeting", "Error 2")
        s.mark_failed("<fail@example.com>", "Bad meeting", "Error 3")

        entry = s._data["failed"]["<fail@example.com>"]
        assert entry["attempts"] == 3
        assert entry["last_error"] == "Error 3"

    def test_preserves_first_seen(self, vault):
        """first_seen should not change on subsequent failures."""
        s = State(str(vault))
        s.mark_failed("<fail@example.com>", "Bad meeting", "Error 1")
        first_seen = s._data["failed"]["<fail@example.com>"]["first_seen"]

        s.mark_failed("<fail@example.com>", "Bad meeting", "Error 2")
        assert s._data["failed"]["<fail@example.com>"]["first_seen"] == first_seen

    def test_updates_last_seen(self, vault):
        """last_seen should update on each failure."""
        s = State(str(vault))
        s.mark_failed("<fail@example.com>", "Bad meeting", "Error 1")
        first_last_seen = s._data["failed"]["<fail@example.com>"]["last_seen"]

        s.mark_failed("<fail@example.com>", "Bad meeting", "Error 2")
        # last_seen should be >= first_last_seen (may be equal if very fast)
        assert s._data["failed"]["<fail@example.com>"]["last_seen"] >= first_last_seen

    def test_failed_survives_reload(self, vault):
        """Failed state written by one instance is readable by another."""
        s1 = State(str(vault))
        s1.mark_failed("<fail@example.com>", "Bad meeting", "Some error")
        s1.mark_failed("<fail@example.com>", "Bad meeting", "Another error")

        s2 = State(str(vault))
        entry = s2._data["failed"]["<fail@example.com>"]
        assert entry["attempts"] == 2
        assert entry["last_error"] == "Another error"

    def test_save_raises_on_write_failure(self, vault):
        """If atomic_write fails, mark_failed should propagate the exception."""
        s = State(str(vault))
        with patch("app.meeting_fetcher.state.atomic_write", side_effect=OSError("disk full")):
            with pytest.raises(OSError, match="disk full"):
                s.mark_failed("<fail@example.com>", "Fail", "err")


# ---------------------------------------------------------------------------
# is_max_retried
# ---------------------------------------------------------------------------

class TestIsMaxRetried:
    def test_returns_false_for_unknown_message(self, vault):
        """Unknown message ID should return False."""
        s = State(str(vault))
        assert s.is_max_retried("<unknown@example.com>") is False

    def test_returns_false_below_threshold(self, vault):
        """Message with fewer than 3 attempts should return False."""
        s = State(str(vault))
        s.mark_failed("<fail@example.com>", "Bad meeting", "Error 1")
        s.mark_failed("<fail@example.com>", "Bad meeting", "Error 2")
        assert s.is_max_retried("<fail@example.com>") is False

    def test_returns_true_at_threshold(self, vault):
        """Message with exactly 3 attempts should return True."""
        s = State(str(vault))
        s.mark_failed("<fail@example.com>", "Bad meeting", "Error 1")
        s.mark_failed("<fail@example.com>", "Bad meeting", "Error 2")
        s.mark_failed("<fail@example.com>", "Bad meeting", "Error 3")
        assert s.is_max_retried("<fail@example.com>") is True

    def test_returns_true_above_threshold(self, vault):
        """Message with more than 3 attempts should return True."""
        s = State(str(vault))
        for i in range(5):
            s.mark_failed("<fail@example.com>", "Bad meeting", f"Error {i+1}")
        assert s.is_max_retried("<fail@example.com>") is True

    def test_custom_max_retries(self, vault):
        """Custom max_retries parameter should work."""
        s = State(str(vault))
        s.mark_failed("<fail@example.com>", "Bad meeting", "Error 1")
        assert s.is_max_retried("<fail@example.com>", max_retries=1) is True
        assert s.is_max_retried("<fail@example.com>", max_retries=2) is False


# ---------------------------------------------------------------------------
# get_failed_count
# ---------------------------------------------------------------------------

class TestGetFailedCount:
    def test_returns_zero_when_no_failures(self, vault):
        s = State(str(vault))
        assert s.get_failed_count() == 0

    def test_returns_zero_when_below_threshold(self, vault):
        """Messages with < 3 attempts should not count."""
        s = State(str(vault))
        s.mark_failed("<fail1@example.com>", "Meeting 1", "Error")
        s.mark_failed("<fail2@example.com>", "Meeting 2", "Error")
        assert s.get_failed_count() == 0

    def test_counts_only_max_retried(self, vault):
        """Only messages with >= 3 attempts should count."""
        s = State(str(vault))
        # This one reaches max retries
        for i in range(3):
            s.mark_failed("<perm@example.com>", "Perm fail", f"Error {i+1}")
        # This one does not
        s.mark_failed("<temp@example.com>", "Temp fail", "Error 1")

        assert s.get_failed_count() == 1


# ---------------------------------------------------------------------------
# Backwards compatibility — loading old state without "failed" key
# ---------------------------------------------------------------------------

class TestBackwardsCompat:
    def test_loads_old_state_without_failed_key(self, vault, state_path):
        """State files from before this change (no 'failed' key) should load fine."""
        old_state = {
            "version": 1,
            "last_run": "2026-04-25T10:00:00",
            "processed": {
                "<msg-1>": {
                    "subject": "Test meeting",
                    "date": "2026-04-25T09:00:00",
                    "attachment": "test.txt",
                    "output_file": "docs/test.md",
                    "type": "daily",
                    "processed_at": "2026-04-25T10:00:00",
                }
            },
        }
        state_path.write_text(json.dumps(old_state), encoding="utf-8")

        s = State(str(vault))
        # Processed data should load correctly
        assert s.is_processed("<msg-1>") is True
        # Failed dict should be initialized empty
        assert s._data["failed"] == {}
        # Should be able to use mark_failed
        s.mark_failed("<new-fail@example.com>", "New fail", "Error")
        assert s._data["failed"]["<new-fail@example.com>"]["attempts"] == 1

    def test_empty_state_includes_failed_key(self):
        """_empty_state() should always include 'failed' key."""
        state = _empty_state()
        assert "failed" in state
        assert state["failed"] == {}

    def test_loads_old_state_without_enqueued_key(self, vault, state_path):
        """State files from before this change (no 'enqueued' key) should load fine."""
        old_state = {
            "version": 1,
            "last_run": "2026-04-25T10:00:00",
            "processed": {
                "<msg-1>": {
                    "subject": "Test meeting",
                    "date": "2026-04-25T09:00:00",
                    "attachment": "test.txt",
                    "output_file": "docs/test.md",
                    "type": "daily",
                    "processed_at": "2026-04-25T10:00:00",
                }
            },
            "failed": {},
        }
        state_path.write_text(json.dumps(old_state), encoding="utf-8")

        s = State(str(vault))
        # Processed data should load correctly
        assert s.is_processed("<msg-1>") is True
        # Enqueued dict should be initialized empty (back-compat)
        assert s._data["enqueued"] == {}
        assert s.is_enqueued("<msg-1>") is False
        # Should be able to use mark_enqueued
        s.mark_enqueued("<msg-1>", "uid-1", "Test meeting", "2026-04-25")
        assert s.is_enqueued("<msg-1>") is True

    def test_empty_state_includes_enqueued_key(self):
        """_empty_state() should always include 'enqueued' key."""
        state = _empty_state()
        assert "enqueued" in state
        assert state["enqueued"] == {}


# ---------------------------------------------------------------------------
# mark_enqueued / is_enqueued
# ---------------------------------------------------------------------------

class TestMarkEnqueued:
    def test_adds_entry_and_persists(self, vault, state_path):
        s = State(str(vault))
        s.mark_enqueued(
            message_id="<enq@example.com>",
            unit_id="uid-1",
            subject="Daily standup",
            date="2026-06-30T09:00:00+03:00",
        )

        # In-memory state
        assert s.is_enqueued("<enq@example.com>") is True
        entry = s._data["enqueued"]["<enq@example.com>"]
        assert entry["unit_id"] == "uid-1"
        assert entry["subject"] == "Daily standup"
        assert entry["date"] == "2026-06-30T09:00:00+03:00"
        assert "enqueued_at" in entry

        # Persisted to disk
        assert state_path.exists()
        on_disk = json.loads(state_path.read_text(encoding="utf-8"))
        assert "<enq@example.com>" in on_disk["enqueued"]
        assert on_disk["last_run"] is not None

    def test_enqueued_survives_reload(self, vault):
        """Enqueued state written by one instance is readable by another."""
        s1 = State(str(vault))
        s1.mark_enqueued("<persist@example.com>", "uid-9", "Persist test", "2026-06-30")

        s2 = State(str(vault))
        assert s2.is_enqueued("<persist@example.com>") is True
        assert s2._data["enqueued"]["<persist@example.com>"]["unit_id"] == "uid-9"

    def test_is_enqueued_false_for_unknown(self, vault):
        s = State(str(vault))
        assert s.is_enqueued("<unknown@example.com>") is False

    def test_save_raises_on_write_failure(self, vault):
        """If atomic_write fails, mark_enqueued should propagate the exception."""
        s = State(str(vault))
        with patch("app.meeting_fetcher.state.atomic_write", side_effect=OSError("disk full")):
            with pytest.raises(OSError, match="disk full"):
                s.mark_enqueued("<fail@example.com>", "uid-x", "Fail", "2026-06-30")
