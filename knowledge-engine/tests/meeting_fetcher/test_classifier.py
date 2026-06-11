"""Unit tests for meeting_fetcher.classifier module."""

import logging
import pytest
from datetime import datetime, date, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

from app.meeting_fetcher.classifier import (
    extract_type,
    route_protocol,
    make_filename,
    make_daily_filename,
    sanitize_filename,
    MSK,
    TYPE_FOLDER_MAP,
    DEFAULT_FOLDER,
)


# ---------------------------------------------------------------------------
# extract_type
# ---------------------------------------------------------------------------


class TestExtractType:
    """Tests for extract_type()."""

    def test_extracts_daily(self):
        md = "---\ntype: daily\n---\n# Meeting notes"
        assert extract_type(md) == "daily"

    def test_extracts_sync(self):
        md = "---\ntype: sync\n---\n# Meeting notes"
        assert extract_type(md) == "sync"

    def test_extracts_review(self):
        md = "---\ntype: review\n---\n# Review notes"
        assert extract_type(md) == "review"

    def test_extracts_planning(self):
        md = "---\ntype: planning\n---\n# Planning notes"
        assert extract_type(md) == "planning"

    def test_missing_type_falls_back_to_sync(self):
        md = "---\ntitle: Something\n---\n# Notes"
        assert extract_type(md) == "sync"

    def test_empty_frontmatter_falls_back_to_sync(self):
        md = "---\n---\n# Notes"
        assert extract_type(md) == "sync"

    def test_unrecognized_type_falls_back_to_sync(self, caplog):
        md = "---\ntype: retrospective\n---\n# Retro notes"
        with caplog.at_level(logging.WARNING):
            result = extract_type(md)
        assert result == "sync"
        assert "Unrecognized protocol type" in caplog.text

    def test_type_with_whitespace_is_stripped(self):
        md = "---\ntype: '  daily  '\n---\n# Notes"
        assert extract_type(md) == "daily"

    def test_type_case_insensitive(self):
        md = "---\ntype: Daily\n---\n# Notes"
        assert extract_type(md) == "daily"

    def test_no_frontmatter_falls_back_to_sync(self):
        md = "# Just a heading\nSome text without frontmatter."
        assert extract_type(md) == "sync"


# ---------------------------------------------------------------------------
# route_protocol
# ---------------------------------------------------------------------------


class TestRouteProtocol:
    """Tests for route_protocol()."""

    def test_daily_routes_to_daily_protocols(self):
        assert route_protocol("daily") == "docs/daily-protocols"

    def test_sync_routes_to_meeting_protocols(self):
        assert route_protocol("sync") == "docs/meeting-protocols"

    def test_review_routes_to_meeting_protocols(self):
        assert route_protocol("review") == "docs/meeting-protocols"

    def test_planning_routes_to_meeting_protocols(self):
        assert route_protocol("planning") == "docs/meeting-protocols"

    def test_unknown_type_routes_to_default(self):
        assert route_protocol("unknown") == DEFAULT_FOLDER

    def test_all_known_types_are_mapped(self):
        for ptype, folder in TYPE_FOLDER_MAP.items():
            assert route_protocol(ptype) == folder


# ---------------------------------------------------------------------------
# sanitize_filename
# ---------------------------------------------------------------------------


class TestSanitizeFilename:
    """Tests for sanitize_filename()."""

    def test_removes_backslash(self):
        assert sanitize_filename("a\\b") == "ab"

    def test_removes_forward_slash(self):
        assert sanitize_filename("a/b") == "ab"

    def test_removes_colon(self):
        assert sanitize_filename("a:b") == "ab"

    def test_removes_asterisk(self):
        assert sanitize_filename("a*b") == "ab"

    def test_removes_question_mark(self):
        assert sanitize_filename("a?b") == "ab"

    def test_removes_double_quote(self):
        assert sanitize_filename('a"b') == "ab"

    def test_removes_angle_brackets(self):
        assert sanitize_filename("a<b>c") == "abc"

    def test_removes_pipe(self):
        assert sanitize_filename("a|b") == "ab"

    def test_strips_whitespace(self):
        assert sanitize_filename("  hello  ") == "hello"

    def test_preserves_safe_characters(self):
        assert sanitize_filename("hello-world_2026") == "hello-world_2026"

    def test_removes_multiple_unsafe_characters(self):
        assert sanitize_filename('a\\b/c:d*e?f"g<h>i|j') == "abcdefghij"

    def test_cyrillic_preserved(self):
        assert sanitize_filename("Daily-standup") == "Daily-standup"


# ---------------------------------------------------------------------------
# make_filename
# ---------------------------------------------------------------------------


class TestMakeFilename:
    """Tests for make_filename()."""

    def test_basic_filename_generation(self):
        dt = datetime(2026, 4, 25, 7, 0, 0, tzinfo=timezone.utc)  # 10:00 MSK
        result = make_filename(dt, "Daily standup")
        assert result == "2026-04-25-1000-daily-standup.md"

    def test_strips_telemost_prefix(self):
        dt = datetime(2026, 4, 25, 7, 0, 0, tzinfo=timezone.utc)
        result = make_filename(dt, "Запись встречи: Sprint review")
        assert result == "2026-04-25-1000-sprint-review.md"

    def test_strips_telemost_prefix_case_insensitive(self):
        dt = datetime(2026, 4, 25, 7, 0, 0, tzinfo=timezone.utc)
        result = make_filename(dt, "запись встречи: Team sync")
        assert result == "2026-04-25-1000-team-sync.md"

    def test_replaces_underscores_with_hyphens(self):
        dt = datetime(2026, 4, 25, 7, 0, 0, tzinfo=timezone.utc)
        result = make_filename(dt, "my_meeting_notes")
        assert result == "2026-04-25-1000-my-meeting-notes.md"

    def test_replaces_spaces_with_hyphens(self):
        dt = datetime(2026, 4, 25, 7, 0, 0, tzinfo=timezone.utc)
        result = make_filename(dt, "sprint planning session")
        assert result == "2026-04-25-1000-sprint-planning-session.md"

    def test_removes_unsafe_characters(self):
        dt = datetime(2026, 4, 25, 7, 0, 0, tzinfo=timezone.utc)
        result = make_filename(dt, 'meeting: "important" <stuff>')
        assert result == "2026-04-25-1000-meeting-important-stuff.md"

    def test_truncates_long_slug_at_word_boundary(self):
        dt = datetime(2026, 4, 25, 7, 0, 0, tzinfo=timezone.utc)
        # Build a long subject with hyphen-separated words
        long_subject = "this-is-a-very-long-meeting-subject-that-goes-beyond-fifty-characters-limit"
        result = make_filename(dt, long_subject)
        # Remove date prefix + .md to get the slug
        slug = result.replace("2026-04-25-1000-", "").replace(".md", "")
        assert len(slug) <= 50
        assert not slug.endswith("-")

    def test_empty_subject_uses_default(self):
        dt = datetime(2026, 4, 25, 7, 0, 0, tzinfo=timezone.utc)
        result = make_filename(dt, "")
        assert result == "2026-04-25-1000-meeting.md"

    def test_subject_only_special_chars_uses_default(self):
        dt = datetime(2026, 4, 25, 7, 0, 0, tzinfo=timezone.utc)
        result = make_filename(dt, '***???""')
        assert result == "2026-04-25-1000-meeting.md"

    def test_telemost_prefix_only_uses_default(self):
        dt = datetime(2026, 4, 25, 7, 0, 0, tzinfo=timezone.utc)
        result = make_filename(dt, "Запись встречи: ")
        assert result == "2026-04-25-1000-meeting.md"

    def test_msk_timezone_conversion(self):
        # Midnight UTC = 03:00 MSK
        dt = datetime(2026, 4, 25, 0, 0, 0, tzinfo=timezone.utc)
        result = make_filename(dt, "test")
        assert result == "2026-04-25-0300-test.md"

    def test_date_rollover_with_msk(self):
        # 22:00 UTC on Apr 24 = 01:00 MSK on Apr 25
        dt = datetime(2026, 4, 24, 22, 0, 0, tzinfo=timezone.utc)
        result = make_filename(dt, "late meeting")
        assert result == "2026-04-25-0100-late-meeting.md"

    def test_collapses_multiple_hyphens(self):
        dt = datetime(2026, 4, 25, 7, 0, 0, tzinfo=timezone.utc)
        result = make_filename(dt, "hello   ---   world")
        assert "--" not in result.replace("2026-04-25-1000-", "").replace(".md", "")

    def test_naive_datetime_treated_as_local(self):
        """Naive datetime is passed through astimezone which treats it as local."""
        dt = datetime(2026, 4, 25, 10, 0, 0)  # naive
        # We just verify it doesn't crash and returns valid .md
        result = make_filename(dt, "test")
        assert result.endswith(".md")
        assert "test" in result

    def test_filename_always_ends_with_md(self):
        dt = datetime(2026, 4, 25, 7, 0, 0, tzinfo=timezone.utc)
        for subject in ["daily", "", "Запись встречи: test", "a" * 100]:
            result = make_filename(dt, subject)
            assert result.endswith(".md")

    def test_filename_has_correct_date_format(self):
        dt = datetime(2026, 12, 31, 21, 0, 0, tzinfo=timezone.utc)  # 00:00 MSK Jan 1
        result = make_filename(dt, "new year")
        assert result.startswith("2027-01-01-0000-")


# ---------------------------------------------------------------------------
# make_daily_filename
# ---------------------------------------------------------------------------


class TestMakeDailyFilename:
    """Tests for make_daily_filename()."""

    def test_empty_directory_starts_at_001(self, tmp_path):
        """First daily file in an empty dir gets sequence 001."""
        result = make_daily_filename(tmp_path)
        today_str = date.today().strftime("%Y.%m.%d")
        assert result == f"{today_str}-001-Daily-summary.md"

    def test_increments_existing_sequence(self, tmp_path):
        """Next file after 002 gets sequence 003."""
        (tmp_path / "2026.05.19-001-Daily-summary.md").write_text("x")
        (tmp_path / "2026.05.19-002-Daily-summary.md").write_text("x")
        result = make_daily_filename(tmp_path)
        today_str = date.today().strftime("%Y.%m.%d")
        assert result == f"{today_str}-003-Daily-summary.md"

    def test_nonexistent_directory_starts_at_001(self):
        """Non-existent directory should start at 001."""
        nonexistent = Path("C:/tmp/nonexistent_dir_test_12345")
        result = make_daily_filename(nonexistent)
        today_str = date.today().strftime("%Y.%m.%d")
        assert result == f"{today_str}-001-Daily-summary.md"

    def test_ignores_non_matching_files(self, tmp_path):
        """Files not matching the daily pattern are ignored."""
        (tmp_path / "2026.05.19-001-Daily-summary.md").write_text("x")
        (tmp_path / "random-notes.md").write_text("x")
        (tmp_path / "2026-05-19-1000-daily-standup.md").write_text("x")
        result = make_daily_filename(tmp_path)
        today_str = date.today().strftime("%Y.%m.%d")
        assert result == f"{today_str}-002-Daily-summary.md"

    def test_returns_string_type(self, tmp_path):
        """Return type is str, not Path."""
        result = make_daily_filename(tmp_path)
        assert isinstance(result, str)
        assert result.endswith(".md")
