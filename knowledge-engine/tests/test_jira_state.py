"""Unit tests for jira_fetcher.state module."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.jira_fetcher.state import (
    STATE_FILENAME,
    diff,
    load,
    mark_closed,
    save,
    update_entry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_issue(key: str, updated: str = "2026-05-01T12:00:00.000+0300") -> dict:
    return {"key": key, "fields": {"updated": updated}}


def _write_state(vault: Path, state: dict) -> None:
    (vault / STATE_FILENAME).write_text(json.dumps(state), encoding="utf-8")


# ---------------------------------------------------------------------------
# load()
# ---------------------------------------------------------------------------

class TestLoad:
    def test_load_empty(self, tmp_path):
        """No file present → returns default state."""
        state = load(tmp_path)
        assert state["version"] == 1
        assert state["last_sync"] == ""
        assert state["issues"] == {}

    def test_load_existing(self, tmp_path):
        """Valid state file is parsed correctly."""
        data = {
            "version": 1,
            "last_sync": "2026-05-01T13:00:00",
            "issues": {
                "GO-187": {
                    "status": "todo",
                    "updated": "2026-05-01T12:00:00.000+0300",
                    "domain": "suggester",
                    "synced_at": "2026-05-01T13:00:00",
                }
            },
        }
        _write_state(tmp_path, data)

        state = load(tmp_path)
        assert state["last_sync"] == "2026-05-01T13:00:00"
        assert "GO-187" in state["issues"]
        assert state["issues"]["GO-187"]["status"] == "todo"
        assert state["issues"]["GO-187"]["domain"] == "suggester"

    def test_load_corrupt(self, tmp_path):
        """Invalid JSON → returns default state without raising."""
        (tmp_path / STATE_FILENAME).write_text("{not valid json!!!", encoding="utf-8")

        state = load(tmp_path)
        assert state["version"] == 1
        assert state["last_sync"] == ""
        assert state["issues"] == {}


# ---------------------------------------------------------------------------
# save()
# ---------------------------------------------------------------------------

class TestSave:
    def test_save_creates_file(self, tmp_path):
        """save() writes a file that can be read back."""
        state = {
            "version": 1,
            "last_sync": "",
            "issues": {
                "GO-1": {
                    "status": "todo",
                    "updated": "2026-05-01T10:00:00",
                    "domain": "core",
                    "synced_at": "2026-05-01T10:00:00",
                }
            },
        }
        path = save(tmp_path, state)

        assert path.exists()
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        assert "GO-1" in on_disk["issues"]
        assert on_disk["issues"]["GO-1"]["status"] == "todo"

    def test_save_updates_last_sync(self, tmp_path):
        """save() sets last_sync to a recent ISO timestamp."""
        state = {"version": 1, "last_sync": "", "issues": {}}
        before = datetime.now().isoformat()
        save(tmp_path, state)
        after = datetime.now().isoformat()

        assert state["last_sync"] != ""
        assert before <= state["last_sync"] <= after

        on_disk = json.loads((tmp_path / STATE_FILENAME).read_text(encoding="utf-8"))
        assert on_disk["last_sync"] != ""


# ---------------------------------------------------------------------------
# diff()
# ---------------------------------------------------------------------------

class TestDiff:
    def test_diff_all_new(self, tmp_path):
        """Empty state + 3 current issues → 3 new, 0 updated, 0 closed."""
        state = {"version": 1, "last_sync": "", "issues": {}}
        current = [
            _make_issue("GO-1"),
            _make_issue("GO-2"),
            _make_issue("GO-3"),
        ]
        new, updated, closed = diff(state, current)
        assert len(new) == 3
        assert len(updated) == 0
        assert len(closed) == 0

    def test_diff_all_existing_unchanged(self, tmp_path):
        """State has 3 issues with same updated → 0 new, 0 updated, 0 closed."""
        ts = "2026-05-01T12:00:00.000+0300"
        state = {
            "version": 1,
            "last_sync": "",
            "issues": {
                "GO-1": {"status": "todo", "updated": ts, "domain": "x", "synced_at": ts},
                "GO-2": {"status": "todo", "updated": ts, "domain": "x", "synced_at": ts},
                "GO-3": {"status": "todo", "updated": ts, "domain": "x", "synced_at": ts},
            },
        }
        current = [
            _make_issue("GO-1", ts),
            _make_issue("GO-2", ts),
            _make_issue("GO-3", ts),
        ]
        new, updated, closed = diff(state, current)
        assert len(new) == 0
        assert len(updated) == 0
        assert len(closed) == 0

    def test_diff_updated(self, tmp_path):
        """Issue with newer updated timestamp → 0 new, 1 updated, 0 closed."""
        old_ts = "2026-05-01T10:00:00.000+0300"
        new_ts = "2026-05-01T15:00:00.000+0300"
        state = {
            "version": 1,
            "last_sync": "",
            "issues": {
                "GO-1": {"status": "todo", "updated": old_ts, "domain": "x", "synced_at": old_ts},
            },
        }
        current = [_make_issue("GO-1", new_ts)]
        new, updated, closed = diff(state, current)
        assert len(new) == 0
        assert len(updated) == 1
        assert updated[0]["key"] == "GO-1"
        assert len(closed) == 0

    def test_diff_closed(self, tmp_path):
        """3 issues in state, only 2 in current → 0 new, 0 updated, 1 closed."""
        ts = "2026-05-01T12:00:00.000+0300"
        state = {
            "version": 1,
            "last_sync": "",
            "issues": {
                "GO-1": {"status": "todo", "updated": ts, "domain": "x", "synced_at": ts},
                "GO-2": {"status": "todo", "updated": ts, "domain": "x", "synced_at": ts},
                "GO-3": {"status": "todo", "updated": ts, "domain": "x", "synced_at": ts},
            },
        }
        current = [_make_issue("GO-1", ts), _make_issue("GO-2", ts)]
        new, updated, closed = diff(state, current)
        assert len(new) == 0
        assert len(updated) == 0
        assert len(closed) == 1
        assert "GO-3" in closed

    def test_diff_mixed(self, tmp_path):
        """1 new + 1 updated + 1 closed in one call."""
        ts_old = "2026-05-01T10:00:00.000+0300"
        ts_new = "2026-05-01T16:00:00.000+0300"
        state = {
            "version": 1,
            "last_sync": "",
            "issues": {
                # GO-existing: present in both, unchanged
                "GO-existing": {"status": "in_progress", "updated": ts_old, "domain": "x", "synced_at": ts_old},
                # GO-updated: present in both, but updated timestamp changed
                "GO-updated": {"status": "in_progress", "updated": ts_old, "domain": "x", "synced_at": ts_old},
                # GO-closed: present in state, absent from current
                "GO-closed": {"status": "in_progress", "updated": ts_old, "domain": "x", "synced_at": ts_old},
            },
        }
        current = [
            _make_issue("GO-existing", ts_old),   # unchanged
            _make_issue("GO-updated", ts_new),    # updated
            _make_issue("GO-new", ts_old),         # new
            # GO-closed is missing → closed
        ]
        new, updated, closed = diff(state, current)
        assert len(new) == 1
        assert new[0]["key"] == "GO-new"
        assert len(updated) == 1
        assert updated[0]["key"] == "GO-updated"
        assert len(closed) == 1
        assert "GO-closed" in closed


# ---------------------------------------------------------------------------
# update_entry()
# ---------------------------------------------------------------------------

class TestUpdateEntry:
    def test_update_entry_adds_new(self):
        """update_entry adds a new entry to an empty issues dict."""
        state = {"version": 1, "last_sync": "", "issues": {}}
        update_entry(state, "GO-100", "todo", "2026-05-01T10:00:00", "suggester")

        assert "GO-100" in state["issues"]
        entry = state["issues"]["GO-100"]
        assert entry["status"] == "todo"
        assert entry["updated"] == "2026-05-01T10:00:00"
        assert entry["domain"] == "suggester"
        assert "synced_at" in entry

    def test_update_entry_overwrites(self):
        """update_entry overwrites an existing entry."""
        ts = "2026-05-01T10:00:00"
        state = {
            "version": 1,
            "last_sync": "",
            "issues": {
                "GO-100": {
                    "status": "todo",
                    "updated": ts,
                    "domain": "old_domain",
                    "synced_at": ts,
                }
            },
        }
        update_entry(state, "GO-100", "in_progress", "2026-05-01T15:00:00", "new_domain")

        assert len(state["issues"]) == 1
        entry = state["issues"]["GO-100"]
        assert entry["status"] == "in_progress"
        assert entry["updated"] == "2026-05-01T15:00:00"
        assert entry["domain"] == "new_domain"


# ---------------------------------------------------------------------------
# mark_closed()
# ---------------------------------------------------------------------------

class TestMarkClosed:
    def test_mark_closed_sets_done(self):
        """mark_closed sets status to 'done' and updates synced_at."""
        ts = "2026-05-01T10:00:00"
        state = {
            "version": 1,
            "last_sync": "",
            "issues": {
                "GO-50": {
                    "status": "in_progress",
                    "updated": ts,
                    "domain": "core",
                    "synced_at": ts,
                }
            },
        }
        before = datetime.now().isoformat()
        mark_closed(state, "GO-50")
        after = datetime.now().isoformat()

        assert state["issues"]["GO-50"]["status"] == "done"
        synced_at = state["issues"]["GO-50"]["synced_at"]
        assert before <= synced_at <= after

    def test_mark_closed_missing_key(self, caplog):
        """mark_closed with unknown key logs a warning and does not raise."""
        import logging
        state = {"version": 1, "last_sync": "", "issues": {}}

        with caplog.at_level(logging.WARNING, logger="app.jira_fetcher.state"):
            mark_closed(state, "GO-999")

        assert "GO-999" in caplog.text
        # State is unchanged
        assert state["issues"] == {}
