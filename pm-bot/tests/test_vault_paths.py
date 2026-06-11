"""Unit tests for vault_paths.next_daily_filename."""

from pathlib import Path
from unittest.mock import patch

import pytest

from app.vault_paths import next_daily_filename


@pytest.fixture
def daily_dir(tmp_path: Path) -> Path:
    """Return a temporary directory to act as the daily-logs dir."""
    d = tmp_path / "daily-logs"
    d.mkdir()
    return d


class TestNextDailyFilename:
    """Tests for next_daily_filename()."""

    def test_empty_dir_returns_001(self, daily_dir: Path) -> None:
        """When no matching files exist, sequence starts at 001."""
        with patch("app.vault_paths.date") as mock_date:
            mock_date.today.return_value.strftime.return_value = "2026.05.20"
            result = next_daily_filename(daily_dir)

        assert result == "2026.05.20-001-Daily-summary.md"

    def test_nonexistent_dir_returns_001(self, tmp_path: Path) -> None:
        """When the directory does not exist, sequence starts at 001."""
        missing = tmp_path / "no-such-dir"
        with patch("app.vault_paths.date") as mock_date:
            mock_date.today.return_value.strftime.return_value = "2026.05.20"
            result = next_daily_filename(missing)

        assert result == "2026.05.20-001-Daily-summary.md"

    def test_single_existing_file(self, daily_dir: Path) -> None:
        """Finds the max number from a single existing file."""
        (daily_dir / "2026.05.19-005-Daily-summary.md").touch()
        with patch("app.vault_paths.date") as mock_date:
            mock_date.today.return_value.strftime.return_value = "2026.05.20"
            result = next_daily_filename(daily_dir)

        assert result == "2026.05.20-006-Daily-summary.md"

    def test_multiple_files_picks_max(self, daily_dir: Path) -> None:
        """When multiple matching files exist, picks the highest number."""
        (daily_dir / "2026.05.18-010-Daily-summary.md").touch()
        (daily_dir / "2026.05.19-131-Daily-summary.md").touch()
        (daily_dir / "2026.05.20-050-Daily-summary.md").touch()
        with patch("app.vault_paths.date") as mock_date:
            mock_date.today.return_value.strftime.return_value = "2026.05.21"
            result = next_daily_filename(daily_dir)

        assert result == "2026.05.21-132-Daily-summary.md"

    def test_ignores_non_matching_files(self, daily_dir: Path) -> None:
        """Files that don't match the pattern are ignored."""
        (daily_dir / "2026.05.19-003-Daily-summary.md").touch()
        (daily_dir / "random-notes.md").touch()
        (daily_dir / "2026.05.19-meeting.md").touch()
        (daily_dir / "not-a-daily.txt").touch()
        with patch("app.vault_paths.date") as mock_date:
            mock_date.today.return_value.strftime.return_value = "2026.05.20"
            result = next_daily_filename(daily_dir)

        assert result == "2026.05.20-004-Daily-summary.md"

    def test_three_digit_padding(self, daily_dir: Path) -> None:
        """Result is zero-padded to 3 digits."""
        (daily_dir / "2026.05.19-001-Daily-summary.md").touch()
        with patch("app.vault_paths.date") as mock_date:
            mock_date.today.return_value.strftime.return_value = "2026.05.20"
            result = next_daily_filename(daily_dir)

        assert result == "2026.05.20-002-Daily-summary.md"

    def test_example_from_spec(self, daily_dir: Path) -> None:
        """Matches the exact example given in the task spec."""
        (daily_dir / "2026.05.20-131-Daily-summary.md").touch()
        with patch("app.vault_paths.date") as mock_date:
            mock_date.today.return_value.strftime.return_value = "2026.05.21"
            result = next_daily_filename(daily_dir)

        assert result == "2026.05.21-132-Daily-summary.md"
