import gc
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from app.enrichment_db import (
    cleanup_old_records,
    get_reminded_today,
    init_db,
    record_reminder,
    was_reminded_recently,
)


@pytest.fixture()
def db_path():
    """Yield a temporary DB path; force-close SQLite handles before cleanup."""
    tmp_dir = tempfile.TemporaryDirectory()
    path = Path(tmp_dir.name) / "test.db"
    yield path
    # Force garbage-collection so that any lingering sqlite3 connection objects
    # are finalized and release their file handles (Windows-specific issue).
    gc.collect()
    tmp_dir.cleanup()


def test_init_db_creates_table(db_path: Path):
    """init_db creates the DB file and the enrichment_reminders table."""
    assert not db_path.exists()

    init_db(db_path)

    assert db_path.exists()
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='enrichment_reminders'"
        )
        assert cursor.fetchone() is not None
    finally:
        conn.close()


def test_record_and_was_reminded_recently(db_path: Path):
    """After recording a reminder, was_reminded_recently returns True."""
    init_db(db_path)

    record_reminder(db_path, "idea-1", "idea-1.md", 40, ["risks", "market"])
    assert was_reminded_recently(db_path, "idea-1") is True


def test_was_reminded_recently_no_record(db_path: Path):
    """was_reminded_recently returns False for an unknown idea_id."""
    init_db(db_path)

    assert was_reminded_recently(db_path, "nonexistent-idea") is False


def test_get_reminded_today(db_path: Path):
    """Recording 2 ideas makes both appear in get_reminded_today."""
    init_db(db_path)

    record_reminder(db_path, "idea-a", "idea-a.md", 30, [])
    record_reminder(db_path, "idea-b", "idea-b.md", 50, ["risks"])

    result = get_reminded_today(db_path)
    assert result == {"idea-a", "idea-b"}


def test_get_reminded_today_empty(db_path: Path):
    """get_reminded_today returns an empty set when there are no records."""
    init_db(db_path)

    result = get_reminded_today(db_path)
    assert result == set()


def test_record_reminder_stores_empty_sections(db_path: Path):
    """empty_sections list is stored as valid JSON in the DB."""
    init_db(db_path)

    sections = ["risks", "market", "competitors"]
    record_reminder(db_path, "idea-x", "idea-x.md", 25, sections)

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute(
            "SELECT empty_sections FROM enrichment_reminders WHERE idea_id = ?",
            ("idea-x",),
        )
        row = cursor.fetchone()
        assert row is not None
        stored = json.loads(row[0])
        assert stored == sections
    finally:
        conn.close()


def test_cleanup_old_records(db_path: Path):
    """cleanup_old_records removes records with sent_at in the past beyond keep_days."""
    init_db(db_path)

    # Insert an old record manually with sent_at 100 days ago
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO enrichment_reminders "
            "(idea_id, idea_filename, readiness_at_send, empty_sections, sent_at) "
            "VALUES (?, ?, ?, ?, datetime('now', '-100 days'))",
            ("old-idea", "old-idea.md", 20, "[]"),
        )
        conn.commit()
    finally:
        conn.close()

    # Insert a recent record
    record_reminder(db_path, "new-idea", "new-idea.md", 60, [])

    # Cleanup with default 90-day retention
    deleted = cleanup_old_records(db_path, keep_days=90)
    assert deleted == 1

    # Verify old record is gone and new record remains
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute("SELECT idea_id FROM enrichment_reminders")
        remaining = [row[0] for row in cursor.fetchall()]
        assert "old-idea" not in remaining
        assert "new-idea" in remaining
    finally:
        conn.close()
