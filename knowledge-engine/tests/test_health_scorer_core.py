"""Tests for core functions: _compute_score, save_history, load_history."""
import importlib
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_vault(tmp_path: Path):
    """Reload vault_paths so VAULT_PATH points to tmp_path."""
    with patch.dict(os.environ, {"VAULT_PATH": str(tmp_path)}):
        from app import vault_paths
        importlib.reload(vault_paths)
    return tmp_path


def _import_health_scorer(tmp_path: Path):
    """Set up vault and return a freshly-reloaded health_scorer module."""
    _setup_vault(tmp_path)
    from app import health_scorer
    importlib.reload(health_scorer)
    return health_scorer


HISTORY_FILENAME = ".health-history.json"


def _read_history(vault_path: Path) -> dict:
    """Read .health-history.json and return parsed dict."""
    raw = (vault_path / HISTORY_FILENAME).read_text(encoding="utf-8")
    return json.loads(raw)


def _write_history(vault_path: Path, data: dict) -> None:
    """Write a .health-history.json file manually."""
    path = vault_path / HISTORY_FILENAME
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests: _compute_score
# ---------------------------------------------------------------------------

class TestComputeScore:

    def test_compute_score_perfect(self, tmp_path):
        """All counts=0, no penalties -> score=100, grade='healthy'."""
        scorer = _import_health_scorer(tmp_path)

        breakdown = {
            "broken_links": {"count": 0},
            "orphan_pages": {"count": 0},
            "dead_ends": {"count": 0},
            "stale_drafts": {"count": 0},
            "unsorted_misc": {"count": 0},
            "ingest_backlog": {"count": 0},
            "description_coverage": {"penalty": 0},
        }
        score, grade = scorer._compute_score(breakdown)

        assert score == 100
        assert grade == "healthy"

    def test_compute_score_formula(self, tmp_path):
        """5 broken_links + 2 orphans -> score=75, grade='warning'.

        100 - (5*3) - (2*5) = 100 - 15 - 10 = 75.
        """
        scorer = _import_health_scorer(tmp_path)

        breakdown = {
            "broken_links": {"count": 5},
            "orphan_pages": {"count": 2},
            "dead_ends": {"count": 0},
            "stale_drafts": {"count": 0},
            "unsorted_misc": {"count": 0},
            "ingest_backlog": {"count": 0},
            "description_coverage": {"penalty": 0},
        }
        score, grade = scorer._compute_score(breakdown)

        assert score == 75
        assert grade == "warning"

    def test_compute_score_clamp_zero(self, tmp_path):
        """Massive counts -> score=0, grade='critical' (no negative scores)."""
        scorer = _import_health_scorer(tmp_path)

        breakdown = {
            "broken_links": {"count": 100},
            "orphan_pages": {"count": 100},
            "dead_ends": {"count": 100},
            "stale_drafts": {"count": 100},
            "unsorted_misc": {"count": 100},
            "ingest_backlog": {"count": 100},
            "description_coverage": {"penalty": 10},
        }
        score, grade = scorer._compute_score(breakdown)

        assert score == 0
        assert grade == "critical"

    def test_compute_score_description_penalty_high(self, tmp_path):
        """coverage.penalty=10 contributes to score reduction.

        100 - 10 (description_coverage penalty) = 90.
        """
        scorer = _import_health_scorer(tmp_path)

        breakdown = {
            "broken_links": {"count": 0},
            "orphan_pages": {"count": 0},
            "dead_ends": {"count": 0},
            "stale_drafts": {"count": 0},
            "unsorted_misc": {"count": 0},
            "ingest_backlog": {"count": 0},
            "description_coverage": {"penalty": 10},
        }
        score, grade = scorer._compute_score(breakdown)

        assert score == 90
        assert grade == "healthy"

    def test_compute_score_grade_boundary_80(self, tmp_path):
        """Score exactly 80 -> grade='healthy'.

        To get score=80: 100 - 20 = 80. Use dead_ends=20 (weight=1).
        """
        scorer = _import_health_scorer(tmp_path)

        breakdown = {
            "broken_links": {"count": 0},
            "orphan_pages": {"count": 0},
            "dead_ends": {"count": 20},
            "stale_drafts": {"count": 0},
            "unsorted_misc": {"count": 0},
            "ingest_backlog": {"count": 0},
            "description_coverage": {"penalty": 0},
        }
        score, grade = scorer._compute_score(breakdown)

        assert score == 80
        assert grade == "healthy"

    def test_compute_score_grade_boundary_50(self, tmp_path):
        """Score exactly 50 -> grade='warning'.

        To get score=50: 100 - 50 = 50. Use dead_ends=50 (weight=1).
        """
        scorer = _import_health_scorer(tmp_path)

        breakdown = {
            "broken_links": {"count": 0},
            "orphan_pages": {"count": 0},
            "dead_ends": {"count": 50},
            "stale_drafts": {"count": 0},
            "unsorted_misc": {"count": 0},
            "ingest_backlog": {"count": 0},
            "description_coverage": {"penalty": 0},
        }
        score, grade = scorer._compute_score(breakdown)

        assert score == 50
        assert grade == "warning"

    def test_compute_score_grade_boundary_49(self, tmp_path):
        """Score 49 -> grade='critical'.

        To get score=49: 100 - 51 = 49. Use dead_ends=51 (weight=1).
        """
        scorer = _import_health_scorer(tmp_path)

        breakdown = {
            "broken_links": {"count": 0},
            "orphan_pages": {"count": 0},
            "dead_ends": {"count": 51},
            "stale_drafts": {"count": 0},
            "unsorted_misc": {"count": 0},
            "ingest_backlog": {"count": 0},
            "description_coverage": {"penalty": 0},
        }
        score, grade = scorer._compute_score(breakdown)

        assert score == 49
        assert grade == "critical"


# ---------------------------------------------------------------------------
# Tests: save_history
# ---------------------------------------------------------------------------

class TestSaveHistory:

    def test_save_history_creates_file(self, tmp_path):
        """Save to non-existent file -> file created with 1 entry."""
        scorer = _import_health_scorer(tmp_path)

        entry = {"date": "2026-06-10", "score": 85, "grade": "healthy"}
        scorer.save_history(str(tmp_path), entry)

        history_file = tmp_path / HISTORY_FILENAME
        assert history_file.exists()

        data = _read_history(tmp_path)
        assert data["version"] == 1
        assert len(data["entries"]) == 1
        assert data["entries"][0]["date"] == "2026-06-10"
        assert data["entries"][0]["score"] == 85

    def test_save_history_appends(self, tmp_path):
        """Save twice with different dates -> 2 entries."""
        scorer = _import_health_scorer(tmp_path)

        entry1 = {"date": "2026-06-09", "score": 80, "grade": "healthy"}
        entry2 = {"date": "2026-06-10", "score": 85, "grade": "healthy"}
        scorer.save_history(str(tmp_path), entry1)
        scorer.save_history(str(tmp_path), entry2)

        data = _read_history(tmp_path)
        assert len(data["entries"]) == 2

        dates = {e["date"] for e in data["entries"]}
        assert dates == {"2026-06-09", "2026-06-10"}

    def test_save_history_overwrites_same_day(self, tmp_path):
        """Save twice with same date -> 1 entry (latest values)."""
        scorer = _import_health_scorer(tmp_path)

        entry1 = {"date": "2026-06-10", "score": 70, "grade": "warning"}
        entry2 = {"date": "2026-06-10", "score": 90, "grade": "healthy"}
        scorer.save_history(str(tmp_path), entry1)
        scorer.save_history(str(tmp_path), entry2)

        data = _read_history(tmp_path)
        assert len(data["entries"]) == 1
        assert data["entries"][0]["score"] == 90

    def test_save_history_ttl_cleanup(self, tmp_path):
        """Entry older than 90 days is removed after save."""
        scorer = _import_health_scorer(tmp_path)

        today = datetime.now(timezone.utc).date()
        old_date = (today - timedelta(days=91)).isoformat()
        recent_date = (today - timedelta(days=10)).isoformat()

        # Pre-populate history with an old entry and a recent entry
        initial_data = {
            "version": 1,
            "entries": [
                {"date": old_date, "score": 60, "grade": "warning"},
                {"date": recent_date, "score": 80, "grade": "healthy"},
            ],
        }
        _write_history(tmp_path, initial_data)

        # Save a new entry, which triggers TTL cleanup
        new_entry = {"date": today.isoformat(), "score": 85, "grade": "healthy"}
        scorer.save_history(str(tmp_path), new_entry)

        data = _read_history(tmp_path)
        dates = [e["date"] for e in data["entries"]]

        # Old entry (91 days ago) must be gone
        assert old_date not in dates
        # Recent entry and new entry must remain
        assert recent_date in dates
        assert today.isoformat() in dates
        assert len(data["entries"]) == 2


# ---------------------------------------------------------------------------
# Tests: load_history
# ---------------------------------------------------------------------------

class TestLoadHistory:

    def test_load_history_missing_file(self, tmp_path):
        """No history file -> empty list."""
        scorer = _import_health_scorer(tmp_path)

        result = scorer.load_history(str(tmp_path))

        assert result == []

    def test_load_history_corrupt_json(self, tmp_path):
        """Bad JSON -> empty list."""
        scorer = _import_health_scorer(tmp_path)

        history_file = tmp_path / HISTORY_FILENAME
        history_file.write_text("{corrupt json!!!", encoding="utf-8")

        result = scorer.load_history(str(tmp_path))

        assert result == []

    def test_load_history_filters_by_days(self, tmp_path):
        """Entries outside the `days` window are filtered out."""
        scorer = _import_health_scorer(tmp_path)

        today = datetime.now(timezone.utc).date()
        within_window = (today - timedelta(days=5)).isoformat()
        outside_window = (today - timedelta(days=40)).isoformat()

        data = {
            "version": 1,
            "entries": [
                {"date": within_window, "score": 80, "grade": "healthy"},
                {"date": outside_window, "score": 60, "grade": "warning"},
            ],
        }
        _write_history(tmp_path, data)

        # Request only last 30 days
        result = scorer.load_history(str(tmp_path), days=30)

        assert len(result) == 1
        assert result[0]["date"] == within_window

    def test_load_history_sorted_ascending(self, tmp_path):
        """Entries are returned in ascending order by date."""
        scorer = _import_health_scorer(tmp_path)

        today = datetime.now(timezone.utc).date()
        date_a = (today - timedelta(days=3)).isoformat()
        date_b = (today - timedelta(days=1)).isoformat()
        date_c = (today - timedelta(days=2)).isoformat()

        # Store in non-sorted order
        data = {
            "version": 1,
            "entries": [
                {"date": date_b, "score": 85},
                {"date": date_a, "score": 75},
                {"date": date_c, "score": 80},
            ],
        }
        _write_history(tmp_path, data)

        result = scorer.load_history(str(tmp_path), days=90)

        returned_dates = [e["date"] for e in result]
        assert returned_dates == sorted(returned_dates)
        assert returned_dates == [date_a, date_c, date_b]
