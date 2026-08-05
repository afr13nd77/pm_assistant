"""Tests for scripts/migrate_signal_ideas.py (BL-203, T-24)."""
from __future__ import annotations

from pathlib import Path

import frontmatter
import pytest

from scripts.migrate_signal_ideas import migrate


def _write_idea(filepath: Path, status: str | None, body: str = "some content") -> None:
    """Write a minimal .md file with frontmatter."""
    post = frontmatter.Post(body)
    if status is not None:
        post["status"] = status
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(frontmatter.dumps(post), encoding="utf-8")


class TestMigrateSignalIdeas:
    """Unit tests for the migrate() function."""

    def _setup_vault(self, tmp_path: Path, domain: str, files: dict[str, str | None]) -> Path:
        """Create domain/ideas/ dir and populate with IDEA-*.md files."""
        ideas_dir = tmp_path / "wiki" / "domains" / domain / "ideas"
        ideas_dir.mkdir(parents=True, exist_ok=True)
        for fname, status in files.items():
            fpath = ideas_dir / fname
            _write_idea(fpath, status=status)
        return ideas_dir

    def test_empty_vault(self, tmp_path: Path) -> None:
        """No files at all -- should return zeros."""
        result = migrate(str(tmp_path), dry_run=False)
        assert result["scanned"] == 0
        assert result["migrated"] == 0
        assert result["errors"] == 0
        assert result["files"] == []

    def test_no_signal_files(self, tmp_path: Path) -> None:
        """Files exist but none have status 'Сигнал'."""
        self._setup_vault(tmp_path, "hotels", {
            "IDEA-001.md": "Новая",
            "IDEA-002.md": "Отсев",
        })
        result = migrate(str(tmp_path), dry_run=False)
        assert result["scanned"] == 2
        assert result["migrated"] == 0
        assert result["files"] == []

    def test_migrate_signal_to_otsev(self, tmp_path: Path) -> None:
        """Files with status 'Сигнал' should be migrated to 'Отсев'."""
        self._setup_vault(tmp_path, "hotels", {
            "IDEA-001.md": "Сигнал",
            "IDEA-002.md": "Новая",
            "IDEA-003.md": "Сигнал",
        })
        result = migrate(str(tmp_path), dry_run=False)
        assert result["scanned"] == 3
        assert result["migrated"] == 2
        assert result["errors"] == 0
        assert len(result["files"]) == 2

        # Verify actual file contents
        post1 = frontmatter.load(
            str(tmp_path / "wiki/domains/hotels/ideas/IDEA-001.md")
        )
        assert post1["status"] == "Отсев"
        assert post1["migrated_from"] == "Сигнал"
        assert "migrated_at" in post1.metadata

        post2 = frontmatter.load(
            str(tmp_path / "wiki/domains/hotels/ideas/IDEA-002.md")
        )
        assert post2["status"] == "Новая"

        post3 = frontmatter.load(
            str(tmp_path / "wiki/domains/hotels/ideas/IDEA-003.md")
        )
        assert post3["status"] == "Отсев"
        assert post3["migrated_from"] == "Сигнал"

    def test_dry_run_does_not_modify(self, tmp_path: Path) -> None:
        """Dry run should count but not modify files."""
        self._setup_vault(tmp_path, "hotels", {
            "IDEA-001.md": "Сигнал",
        })
        result = migrate(str(tmp_path), dry_run=True)
        assert result["scanned"] == 1
        assert result["migrated"] == 1
        assert len(result["files"]) == 1

        # File should still have old status
        post = frontmatter.load(
            str(tmp_path / "wiki/domains/hotels/ideas/IDEA-001.md")
        )
        assert post["status"] == "Сигнал"
        assert "migrated_from" not in post.metadata

    def test_multiple_domains(self, tmp_path: Path) -> None:
        """Should scan across all domains."""
        self._setup_vault(tmp_path, "hotels", {"IDEA-001.md": "Сигнал"})
        self._setup_vault(tmp_path, "flights", {"IDEA-002.md": "Сигнал"})
        self._setup_vault(tmp_path, "payments", {"IDEA-003.md": "Новая"})

        result = migrate(str(tmp_path), dry_run=False)
        assert result["scanned"] == 3
        assert result["migrated"] == 2
        assert result["errors"] == 0

    def test_non_idea_files_ignored(self, tmp_path: Path) -> None:
        """Only IDEA-*.md files should be scanned, not other .md files."""
        ideas_dir = tmp_path / "wiki" / "domains" / "hotels" / "ideas"
        ideas_dir.mkdir(parents=True, exist_ok=True)
        _write_idea(ideas_dir / "IDEA-001.md", "Сигнал")
        _write_idea(ideas_dir / "index.md", "Сигнал")
        _write_idea(ideas_dir / "notes.md", "Сигнал")

        result = migrate(str(tmp_path), dry_run=False)
        assert result["scanned"] == 1
        assert result["migrated"] == 1

    def test_no_frontmatter_skipped(self, tmp_path: Path) -> None:
        """File with empty frontmatter should be skipped."""
        ideas_dir = tmp_path / "wiki" / "domains" / "hotels" / "ideas"
        ideas_dir.mkdir(parents=True, exist_ok=True)
        # Write file with no frontmatter at all
        (ideas_dir / "IDEA-001.md").write_text("just plain text", encoding="utf-8")

        result = migrate(str(tmp_path), dry_run=False)
        assert result["scanned"] == 1
        assert result["migrated"] == 0
        assert result["errors"] == 0

    def test_relative_paths_in_files_list(self, tmp_path: Path) -> None:
        """files list should contain paths relative to vault root."""
        self._setup_vault(tmp_path, "hotels", {"IDEA-001.md": "Сигнал"})
        result = migrate(str(tmp_path), dry_run=False)
        assert len(result["files"]) == 1
        rel_path = result["files"][0]
        # Should be relative (not absolute)
        assert not Path(rel_path).is_absolute()
        assert "IDEA-001.md" in rel_path

    def test_error_handling_continues(self, tmp_path: Path) -> None:
        """If one file errors, processing should continue with the rest."""
        self._setup_vault(tmp_path, "hotels", {
            "IDEA-001.md": "Сигнал",
            "IDEA-003.md": "Сигнал",
        })
        # Create a corrupted file
        bad_file = tmp_path / "wiki" / "domains" / "hotels" / "ideas" / "IDEA-002.md"
        bad_file.write_text("---\nstatus: 'Сигнал'\n---\n\x00\x01", encoding="utf-8")

        result = migrate(str(tmp_path), dry_run=False)
        # At minimum the two good files should be processed
        assert result["scanned"] == 3
        assert result["migrated"] >= 2
