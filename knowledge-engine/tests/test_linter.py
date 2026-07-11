"""Tests for the linter module — vault health checks."""
import importlib
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_vault(tmp_path: Path):
    """Reload vault_paths so VAULT_PATH points to tmp_path."""
    with patch.dict(os.environ, {"VAULT_PATH": str(tmp_path)}):
        from shared import vault_paths
        importlib.reload(vault_paths)
    return tmp_path


def _import_linter(tmp_path: Path):
    """Set up vault and return a freshly-reloaded linter module."""
    _setup_vault(tmp_path)
    from app import linter
    importlib.reload(linter)
    return linter


def _write_md(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_md_with_frontmatter(path: Path, status: str, body: str = "") -> Path:
    content = f"---\nstatus: {status}\n---\n\n{body}"
    return _write_md(path, content)


def _set_mtime_days_ago(path: Path, days: int) -> None:
    """Set the mtime of a file to `days` days in the past."""
    past = time.time() - days * 86400
    os.utime(str(path), (past, past))


# ---------------------------------------------------------------------------
# check_broken_links
# ---------------------------------------------------------------------------

class TestCheckBrokenLinks:
    def test_broken_link_reported(self, tmp_path):
        linter = _import_linter(tmp_path)
        md = tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "idea-01.md"
        _write_md(md, "# Idea\n\n[[nonexistent]]\n")

        result = linter.check_broken_links(str(tmp_path))

        assert len(result) == 1
        item = result[0]
        assert item["link"] == "nonexistent"
        assert item["reason"] == "target not found"
        assert item["line"] == 3

    def test_valid_link_not_reported(self, tmp_path):
        linter = _import_linter(tmp_path)
        existing = tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "existing-file.md"
        _write_md(existing, "# Existing")

        md = tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "idea-01.md"
        _write_md(md, "# Idea\n\n[[existing-file]]\n")

        result = linter.check_broken_links(str(tmp_path))
        assert result == []

    def test_valid_link_with_extension_not_reported(self, tmp_path):
        linter = _import_linter(tmp_path)
        existing = tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "GO-153.md"
        _write_md(existing, "# GO-153")

        md = tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "idea-01.md"
        _write_md(md, "# Idea\n\n[[GO-153.md]]\n")

        result = linter.check_broken_links(str(tmp_path))
        assert result == []

    def test_pipe_syntax_target_resolved(self, tmp_path):
        linter = _import_linter(tmp_path)
        existing = tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "target-file.md"
        _write_md(existing, "# Target")

        md = tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "idea-01.md"
        _write_md(md, "# Idea\n\n[[target-file|display text]]\n")

        result = linter.check_broken_links(str(tmp_path))
        assert result == []

    def test_pipe_syntax_broken_target_reported(self, tmp_path):
        linter = _import_linter(tmp_path)
        md = tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "idea-01.md"
        _write_md(md, "# Idea\n\n[[missing-file|display]]\n")

        result = linter.check_broken_links(str(tmp_path))
        assert len(result) == 1
        assert result[0]["link"] == "missing-file|display"

    def test_multiple_broken_links_in_one_file(self, tmp_path):
        linter = _import_linter(tmp_path)
        md = tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "idea-01.md"
        _write_md(md, "# Idea\n\n[[missing-a]]\n\n[[missing-b]]\n")

        result = linter.check_broken_links(str(tmp_path))
        assert len(result) == 2
        links = {item["link"] for item in result}
        assert links == {"missing-a", "missing-b"}

    def test_no_wiki_dir_returns_empty(self, tmp_path):
        linter = _import_linter(tmp_path)
        result = linter.check_broken_links(str(tmp_path))
        assert result == []

    def test_result_contains_relative_file_path(self, tmp_path):
        linter = _import_linter(tmp_path)
        md = tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "idea-01.md"
        _write_md(md, "[[ghost]]\n")

        result = linter.check_broken_links(str(tmp_path))
        assert len(result) == 1
        assert result[0]["file"] == "wiki/domains/test-domain/ideas/idea-01.md"
        assert "\\" not in result[0]["file"]

    def test_link_on_correct_line_number(self, tmp_path):
        linter = _import_linter(tmp_path)
        md = tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "idea-01.md"
        _write_md(md, "line one\nline two\n[[ghost]]\n")

        result = linter.check_broken_links(str(tmp_path))
        assert result[0]["line"] == 3

    def test_cross_wiki_reference_is_valid(self, tmp_path):
        """A wikilink pointing to a file in another part of wiki/ is valid."""
        linter = _import_linter(tmp_path)
        meeting = tmp_path / "wiki" / "meetings" / "standup.md"
        _write_md(meeting, "# Standup")

        idea = tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "idea-01.md"
        _write_md(idea, "See [[standup]]\n")

        result = linter.check_broken_links(str(tmp_path))
        assert result == []


# ---------------------------------------------------------------------------
# check_orphan_pages
# ---------------------------------------------------------------------------

class TestCheckOrphanPages:
    """Tests for check_orphan_pages — checks raw/inbound/daily-logs and
    raw/inbound/meeting-notes for files without a wiki counterpart."""

    def test_empty_vault_returns_no_orphans(self, tmp_path):
        linter = _import_linter(tmp_path)
        result = linter.check_orphan_pages(str(tmp_path))
        assert result == []

    def test_no_raw_inbound_returns_empty(self, tmp_path):
        linter = _import_linter(tmp_path)
        # Only wiki exists, no raw/inbound at all
        _write_md(tmp_path / "wiki" / "daily-logs" / "2026-06-01.md", "# Day")
        result = linter.check_orphan_pages(str(tmp_path))
        assert result == []

    def test_daily_log_with_wiki_counterpart_not_orphan(self, tmp_path):
        linter = _import_linter(tmp_path)
        _write_md(tmp_path / "wiki" / "daily-logs" / "2026-06-01.md", "# Day")
        _write_md(
            tmp_path / "raw" / "inbound" / "daily-logs" / "2026-06-01 1004 (MSK) notes.txt",
            "raw content",
        )
        result = linter.check_orphan_pages(str(tmp_path))
        assert result == []

    def test_daily_log_without_wiki_counterpart_is_orphan(self, tmp_path):
        linter = _import_linter(tmp_path)
        # wiki has 2026-06-01 but raw has 2026-06-02
        _write_md(tmp_path / "wiki" / "daily-logs" / "2026-06-01.md", "# Day")
        _write_md(
            tmp_path / "raw" / "inbound" / "daily-logs" / "2026-06-02 notes.md",
            "raw content",
        )
        result = linter.check_orphan_pages(str(tmp_path))
        assert len(result) == 1
        assert result[0]["type"] == "daily-logs"
        assert "2026-06-02" in result[0]["file"]

    def test_meeting_note_with_wiki_counterpart_not_orphan(self, tmp_path):
        linter = _import_linter(tmp_path)
        _write_md(
            tmp_path / "wiki" / "meetings" / "2026-06-01-standup.md", "# Meeting"
        )
        _write_md(
            tmp_path / "raw" / "inbound" / "meeting-notes" / "2026-06-01 standup raw.txt",
            "raw content",
        )
        result = linter.check_orphan_pages(str(tmp_path))
        assert result == []

    def test_meeting_note_without_wiki_counterpart_is_orphan(self, tmp_path):
        linter = _import_linter(tmp_path)
        _write_md(
            tmp_path / "raw" / "inbound" / "meeting-notes" / "2026-06-03 planning.txt",
            "raw content",
        )
        result = linter.check_orphan_pages(str(tmp_path))
        assert len(result) == 1
        assert result[0]["type"] == "meeting-notes"
        assert "2026-06-03" in result[0]["file"]

    def test_ideas_and_tasks_are_ignored(self, tmp_path):
        """ideas and tasks are covered by _check_ingest_backlog, not here."""
        linter = _import_linter(tmp_path)
        _write_md(
            tmp_path / "raw" / "inbound" / "ideas" / "some-idea.md", "# Idea"
        )
        _write_md(
            tmp_path / "raw" / "inbound" / "tasks" / "GO-103.md", "# Task"
        )
        result = linter.check_orphan_pages(str(tmp_path))
        assert result == []

    def test_misc_and_clippings_are_ignored(self, tmp_path):
        """misc is covered by check_unsorted_misc; clippings need no transform."""
        linter = _import_linter(tmp_path)
        _write_md(
            tmp_path / "raw" / "inbound" / "misc" / "random.md", "# Misc"
        )
        _write_md(
            tmp_path / "raw" / "inbound" / "clippings" / "article.md", "# Clip"
        )
        result = linter.check_orphan_pages(str(tmp_path))
        assert result == []

    def test_raw_file_without_date_prefix_is_orphan(self, tmp_path):
        linter = _import_linter(tmp_path)
        _write_md(
            tmp_path / "raw" / "inbound" / "daily-logs" / "no-date-here.txt",
            "raw",
        )
        result = linter.check_orphan_pages(str(tmp_path))
        assert len(result) == 1
        assert result[0]["type"] == "daily-logs"

    def test_orphan_file_path_uses_forward_slashes(self, tmp_path):
        linter = _import_linter(tmp_path)
        _write_md(
            tmp_path / "raw" / "inbound" / "daily-logs" / "2026-06-05 notes.md",
            "raw",
        )
        result = linter.check_orphan_pages(str(tmp_path))
        assert len(result) == 1
        assert "\\" not in result[0]["file"]

    def test_multiple_raw_files_same_date_all_matched(self, tmp_path):
        """Multiple raw files sharing one date should all be non-orphan
        if the wiki counterpart exists."""
        linter = _import_linter(tmp_path)
        _write_md(tmp_path / "wiki" / "daily-logs" / "2026-06-01.md", "# Day")
        _write_md(
            tmp_path / "raw" / "inbound" / "daily-logs" / "2026-06-01 morning.txt",
            "a",
        )
        _write_md(
            tmp_path / "raw" / "inbound" / "daily-logs" / "2026-06-01 evening.txt",
            "b",
        )
        result = linter.check_orphan_pages(str(tmp_path))
        assert result == []

    def test_wiki_daily_log_with_dots_matches_raw_with_dashes(self, tmp_path):
        """wiki daily-log uses dots (2026.03.10-067-Daily-summary.md) but raw
        daily-log uses dashes (2026-03-10 0933 (MSK) notes.txt). They should
        match on the same date after normalization."""
        linter = _import_linter(tmp_path)
        _write_md(
            tmp_path / "wiki" / "daily-logs" / "2026.03.10-067-Daily-summary.md",
            "# Daily summary",
        )
        _write_md(
            tmp_path / "raw" / "inbound" / "daily-logs"
            / "2026-03-10 0933 (MSK) Konspekt dnya.txt",
            "raw content",
        )
        result = linter.check_orphan_pages(str(tmp_path))
        assert result == [], (
            "Raw daily-log with dashes should match wiki daily-log with dots"
        )

    def test_wiki_daily_log_with_dots_unmatched_date_is_orphan(self, tmp_path):
        """wiki daily-log with dots for one date should NOT match a raw file
        with a different date."""
        linter = _import_linter(tmp_path)
        _write_md(
            tmp_path / "wiki" / "daily-logs" / "2026.03.10-067-Daily-summary.md",
            "# Daily summary",
        )
        _write_md(
            tmp_path / "raw" / "inbound" / "daily-logs"
            / "2026-03-11 0933 (MSK) Konspekt dnya.txt",
            "raw content",
        )
        result = linter.check_orphan_pages(str(tmp_path))
        assert len(result) == 1
        assert result[0]["type"] == "daily-logs"

    def test_meeting_date_match_ignores_suffix(self, tmp_path):
        """wiki/meetings/2026-06-01-retro.md should match raw with date 2026-06-01."""
        linter = _import_linter(tmp_path)
        _write_md(
            tmp_path / "wiki" / "meetings" / "2026-06-01-retro.md", "# Retro"
        )
        _write_md(
            tmp_path / "raw" / "inbound" / "meeting-notes" / "2026-06-01 retro raw.txt",
            "raw",
        )
        result = linter.check_orphan_pages(str(tmp_path))
        assert result == []


# ---------------------------------------------------------------------------
# check_stale_drafts
# ---------------------------------------------------------------------------

class TestCheckStaleDrafts:
    def test_stale_draft_reported(self, tmp_path):
        linter = _import_linter(tmp_path)
        md = tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "old-idea.md"
        _write_md_with_frontmatter(md, status="Новая", body="# Old idea")
        _set_mtime_days_ago(md, 35)

        result = linter.check_stale_drafts(str(tmp_path))

        assert len(result) == 1
        item = result[0]
        assert item["domain"] == "test-domain"
        assert item["days_old"] >= 35
        assert item["status"] == "новая"

    def test_new_status_also_reported(self, tmp_path):
        linter = _import_linter(tmp_path)
        md = tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "new-idea.md"
        _write_md_with_frontmatter(md, status="Новая", body="# Old new idea")
        _set_mtime_days_ago(md, 31)

        result = linter.check_stale_drafts(str(tmp_path))

        assert len(result) == 1
        assert result[0]["status"] == "новая"

    def test_recent_draft_not_reported(self, tmp_path):
        linter = _import_linter(tmp_path)
        md = tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "new-idea.md"
        _write_md_with_frontmatter(md, status="Новая", body="# New idea")
        _set_mtime_days_ago(md, 5)

        result = linter.check_stale_drafts(str(tmp_path))
        assert result == []

    def test_non_draft_status_not_reported(self, tmp_path):
        linter = _import_linter(tmp_path)
        md = tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "active.md"
        _write_md_with_frontmatter(md, status="Проверка гипотезы", body="# Active idea")
        _set_mtime_days_ago(md, 60)

        result = linter.check_stale_drafts(str(tmp_path))
        assert result == []

    def test_exactly_30_days_old_is_stale(self, tmp_path):
        linter = _import_linter(tmp_path)
        md = tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "boundary.md"
        _write_md_with_frontmatter(md, status="Новая", body="# Boundary")
        _set_mtime_days_ago(md, 30)

        result = linter.check_stale_drafts(str(tmp_path))
        assert len(result) == 1

    def test_service_files_excluded_from_stale_check(self, tmp_path):
        linter = _import_linter(tmp_path)
        for service_name in ("index.md", "log.md"):
            f = tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / service_name
            _write_md_with_frontmatter(f, status="Новая", body="# Service")
            _set_mtime_days_ago(f, 60)

        result = linter.check_stale_drafts(str(tmp_path))
        assert result == []

    def test_stale_draft_file_path_is_relative(self, tmp_path):
        linter = _import_linter(tmp_path)
        md = tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "old.md"
        _write_md_with_frontmatter(md, status="Новая")
        _set_mtime_days_ago(md, 40)

        result = linter.check_stale_drafts(str(tmp_path))
        assert len(result) == 1
        assert result[0]["file"] == "wiki/domains/test-domain/ideas/old.md"
        assert "\\" not in result[0]["file"]

    def test_no_ideas_dirs_returns_empty(self, tmp_path):
        linter = _import_linter(tmp_path)
        result = linter.check_stale_drafts(str(tmp_path))
        assert result == []

    def test_only_ideas_dirs_are_scanned(self, tmp_path):
        """Stale draft check only looks in ideas/, not prds/ or tasks/."""
        linter = _import_linter(tmp_path)
        prd = tmp_path / "wiki" / "domains" / "test-domain" / "prds" / "old-prd.md"
        _write_md_with_frontmatter(prd, status="Новая")
        _set_mtime_days_ago(prd, 60)

        result = linter.check_stale_drafts(str(tmp_path))
        assert result == []


# ---------------------------------------------------------------------------
# check_unsorted_misc
# ---------------------------------------------------------------------------

class TestCheckUnsortedMisc:
    def test_unreferenced_misc_file_reported(self, tmp_path):
        """A misc file with no wikilink reference from wiki/ is reported."""
        linter = _import_linter(tmp_path)
        misc_dir = tmp_path / "raw" / "inbound" / "misc"
        misc_dir.mkdir(parents=True, exist_ok=True)
        old_file = misc_dir / "old-note.txt"
        old_file.write_text("hello", encoding="utf-8")

        result = linter.check_unsorted_misc(str(tmp_path))

        assert len(result) == 1
        assert "old-note.txt" in result[0]["file"]
        assert result[0]["name"] == "old-note.txt"
        assert "days_old" not in result[0]

    def test_referenced_misc_file_not_reported(self, tmp_path):
        """A misc file referenced via wikilink from wiki/ is NOT reported."""
        linter = _import_linter(tmp_path)
        misc_dir = tmp_path / "raw" / "inbound" / "misc"
        misc_dir.mkdir(parents=True, exist_ok=True)
        new_file = misc_dir / "new-note.txt"
        new_file.write_text("hello", encoding="utf-8")
        # Create a wiki file that references this misc file by stem
        wiki_file = tmp_path / "wiki" / "domains" / "test" / "ref.md"
        wiki_file.parent.mkdir(parents=True, exist_ok=True)
        wiki_file.write_text("See [[new-note]]", encoding="utf-8")

        result = linter.check_unsorted_misc(str(tmp_path))
        assert result == []

    def test_unreferenced_misc_file_always_reported(self, tmp_path):
        """Any misc file without a wikilink reference is reported regardless of age."""
        linter = _import_linter(tmp_path)
        misc_dir = tmp_path / "raw" / "inbound" / "misc"
        misc_dir.mkdir(parents=True, exist_ok=True)
        f = misc_dir / "boundary.txt"
        f.write_text("data", encoding="utf-8")

        result = linter.check_unsorted_misc(str(tmp_path))
        assert len(result) == 1

    def test_no_misc_dir_returns_empty(self, tmp_path):
        linter = _import_linter(tmp_path)
        result = linter.check_unsorted_misc(str(tmp_path))
        assert result == []

    def test_subdirectories_not_counted(self, tmp_path):
        linter = _import_linter(tmp_path)
        misc_dir = tmp_path / "raw" / "inbound" / "misc"
        subdir = misc_dir / "subfolder"
        subdir.mkdir(parents=True, exist_ok=True)
        _set_mtime_days_ago(subdir, 30)

        result = linter.check_unsorted_misc(str(tmp_path))
        assert result == []

    def test_misc_file_path_is_relative_with_forward_slashes(self, tmp_path):
        linter = _import_linter(tmp_path)
        misc_dir = tmp_path / "raw" / "inbound" / "misc"
        misc_dir.mkdir(parents=True, exist_ok=True)
        f = misc_dir / "note.md"
        f.write_text("content", encoding="utf-8")
        _set_mtime_days_ago(f, 8)

        result = linter.check_unsorted_misc(str(tmp_path))
        assert len(result) == 1
        assert result[0]["file"] == "raw/inbound/misc/note.md"
        assert "\\" not in result[0]["file"]


# ---------------------------------------------------------------------------
# check_invalid_idea_statuses
# ---------------------------------------------------------------------------

class TestCheckInvalidIdeaStatuses:
    def test_valid_status_not_reported(self, tmp_path):
        linter = _import_linter(tmp_path)
        md = tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "good.md"
        _write_md_with_frontmatter(md, status="Новая")

        result = linter.check_invalid_idea_statuses(str(tmp_path))
        assert result == []

    def test_unknown_status_reported(self, tmp_path):
        linter = _import_linter(tmp_path)
        md = tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "bad.md"
        _write_md_with_frontmatter(md, status="archived")

        result = linter.check_invalid_idea_statuses(str(tmp_path))
        assert len(result) == 1
        assert result[0]["status"] == "archived"
        assert result[0]["reason"] == "unknown_status"
        assert result[0]["domain"] == "test-domain"

    def test_missing_status_reported(self, tmp_path):
        linter = _import_linter(tmp_path)
        md = tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "no-status.md"
        _write_md(md, "---\ntitle: test\n---\n\nbody")

        result = linter.check_invalid_idea_statuses(str(tmp_path))
        assert len(result) == 1
        assert result[0]["reason"] == "missing_status"
        assert result[0]["status"] is None

    def test_empty_status_reported(self, tmp_path):
        linter = _import_linter(tmp_path)
        md = tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "empty.md"
        _write_md(md, "---\nstatus: \n---\n\nbody")

        result = linter.check_invalid_idea_statuses(str(tmp_path))
        assert len(result) == 1
        assert result[0]["reason"] == "missing_status"

    def test_service_files_excluded(self, tmp_path):
        linter = _import_linter(tmp_path)
        md = tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "index.md"
        _write_md_with_frontmatter(md, status="archived")

        result = linter.check_invalid_idea_statuses(str(tmp_path))
        assert result == []

    def test_no_domains_dir_returns_empty(self, tmp_path):
        linter = _import_linter(tmp_path)

        result = linter.check_invalid_idea_statuses(str(tmp_path))
        assert result == []

    def test_multiple_domains_scanned(self, tmp_path):
        linter = _import_linter(tmp_path)
        md1 = tmp_path / "wiki" / "domains" / "domain-a" / "ideas" / "a.md"
        _write_md_with_frontmatter(md1, status="bogus")
        md2 = tmp_path / "wiki" / "domains" / "domain-b" / "ideas" / "b.md"
        _write_md_with_frontmatter(md2, status="unknown")

        result = linter.check_invalid_idea_statuses(str(tmp_path))
        assert len(result) == 2
        domains = {r["domain"] for r in result}
        assert domains == {"domain-a", "domain-b"}

    def test_all_valid_statuses_accepted(self, tmp_path):
        linter = _import_linter(tmp_path)
        from app.status_migrator import VALID_STATUSES
        for i, status in enumerate(sorted(VALID_STATUSES)):
            md = tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / f"idea-{i}.md"
            _write_md_with_frontmatter(md, status=status)

        result = linter.check_invalid_idea_statuses(str(tmp_path))
        assert result == []

    def test_result_contains_file_path(self, tmp_path):
        linter = _import_linter(tmp_path)
        md = tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "bad.md"
        _write_md_with_frontmatter(md, status="old-status")

        result = linter.check_invalid_idea_statuses(str(tmp_path))
        assert len(result) == 1
        assert "bad.md" in result[0]["file"]

    def test_lint_includes_invalid_idea_statuses(self, tmp_path):
        linter = _import_linter(tmp_path)
        md = tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "bad.md"
        _write_md_with_frontmatter(md, status="obsolete")

        result = linter.lint(str(tmp_path))
        assert result["summary"]["invalid_idea_statuses_count"] == 1
        assert len(result["invalid_idea_statuses"]) == 1
        assert result["summary"]["total_issues"] >= 1


# ---------------------------------------------------------------------------
# lint() integration
# ---------------------------------------------------------------------------

class TestLintIntegration:
    def test_clean_vault_all_empty(self, tmp_path):
        linter = _import_linter(tmp_path)
        result = linter.lint(str(tmp_path))

        assert result["status"] == "ok"
        assert result["broken_links"] == []
        assert result["orphan_pages"] == []
        assert result["stale_drafts"] == []
        assert result["unsorted_misc"] == []
        assert result["summary"]["total_issues"] == 0

    def test_summary_counts_match_list_lengths(self, tmp_path):
        linter = _import_linter(tmp_path)

        # Create one of each issue type
        broken_md = tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "broken.md"
        _write_md(broken_md, "[[ghost-link]]\n")

        stale_md = tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "stale.md"
        _write_md_with_frontmatter(stale_md, status="draft")
        _set_mtime_days_ago(stale_md, 45)

        misc_dir = tmp_path / "raw" / "inbound" / "misc"
        misc_dir.mkdir(parents=True, exist_ok=True)
        old_misc = misc_dir / "old.txt"
        old_misc.write_text("data", encoding="utf-8")
        _set_mtime_days_ago(old_misc, 10)

        result = linter.lint(str(tmp_path))

        assert result["summary"]["broken_links_count"] == len(result["broken_links"])
        assert result["summary"]["orphan_pages_count"] == len(result["orphan_pages"])
        assert result["summary"]["stale_drafts_count"] == len(result["stale_drafts"])
        assert result["summary"]["unsorted_misc_count"] == len(result["unsorted_misc"])
        assert result["summary"]["invalid_idea_statuses_count"] == len(result["invalid_idea_statuses"])
        assert result["summary"]["total_issues"] == (
            result["summary"]["broken_links_count"]
            + result["summary"]["orphan_pages_count"]
            + result["summary"]["stale_drafts_count"]
            + result["summary"]["unsorted_misc_count"]
            + result["summary"]["invalid_idea_statuses_count"]
        )

    def test_result_has_all_required_keys(self, tmp_path):
        linter = _import_linter(tmp_path)
        result = linter.lint(str(tmp_path))

        assert "status" in result
        assert "broken_links" in result
        assert "orphan_pages" in result
        assert "stale_drafts" in result
        assert "unsorted_misc" in result
        assert "invalid_idea_statuses" in result
        assert "summary" in result

        summary = result["summary"]
        assert "broken_links_count" in summary
        assert "orphan_pages_count" in summary
        assert "stale_drafts_count" in summary
        assert "unsorted_misc_count" in summary
        assert "total_issues" in summary

    def test_status_is_ok(self, tmp_path):
        linter = _import_linter(tmp_path)
        result = linter.lint(str(tmp_path))
        assert result["status"] == "ok"

    def test_multiple_issues_counted_correctly(self, tmp_path):
        linter = _import_linter(tmp_path)

        # Two broken links in the same file
        md = tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "multi.md"
        _write_md(md, "[[ghost1]]\n[[ghost2]]\n")

        result = linter.lint(str(tmp_path))
        assert result["summary"]["broken_links_count"] == 2
        assert result["summary"]["total_issues"] >= 2

    def test_orphan_page_counted_in_summary(self, tmp_path):
        linter = _import_linter(tmp_path)
        # Create a raw daily-log with no wiki counterpart
        _write_md(
            tmp_path / "raw" / "inbound" / "daily-logs" / "2026-06-10 notes.md",
            "raw content",
        )

        result = linter.lint(str(tmp_path))
        assert result["summary"]["orphan_pages_count"] == 1
        assert result["summary"]["total_issues"] >= 1


# ---------------------------------------------------------------------------
# _build_file_index
# ---------------------------------------------------------------------------

class TestBuildFileIndex:
    def test_build_file_index_basic(self, tmp_path):
        """Three .md files in wiki/ produce 3 entries in each index dict."""
        linter = _import_linter(tmp_path)
        for name in ("alpha.md", "beta.md", "gamma.md"):
            _write_md(tmp_path / "wiki" / "docs" / name, f"# {name}")

        result = linter._build_file_index(tmp_path)

        assert len(result["by_name"]) == 3
        assert len(result["by_stem"]) == 3
        assert len(result["all_paths"]) == 3

    def test_build_file_index_duplicate_names(self, tmp_path):
        """Two files with same name in different dirs produce 2 paths under that name."""
        linter = _import_linter(tmp_path)
        _write_md(tmp_path / "wiki" / "ideas" / "note.md", "# Note A")
        _write_md(tmp_path / "wiki" / "prds" / "note.md", "# Note B")

        result = linter._build_file_index(tmp_path)

        assert len(result["by_name"]["note.md"]) == 2
        assert len(result["all_paths"]) == 2
        # stem is the same, so by_stem["note"] should also have 2 paths
        assert len(result["by_stem"]["note"]) == 2

    def test_build_file_index_empty_wiki(self, tmp_path):
        """Empty wiki/ directory produces empty index dicts."""
        linter = _import_linter(tmp_path)
        (tmp_path / "wiki").mkdir(parents=True, exist_ok=True)

        result = linter._build_file_index(tmp_path)

        assert result["by_name"] == {}
        assert result["by_stem"] == {}
        assert result["all_paths"] == []

    def test_build_file_index_no_wiki(self, tmp_path):
        """No wiki/ directory at all produces empty index dicts."""
        linter = _import_linter(tmp_path)

        result = linter._build_file_index(tmp_path)

        assert result["by_name"] == {}
        assert result["by_stem"] == {}
        assert result["all_paths"] == []


# ---------------------------------------------------------------------------
# _resolve_wikilink
# ---------------------------------------------------------------------------

class TestResolveWikilink:
    @pytest.fixture
    def file_index(self):
        """A pre-built file index for testing resolution without filesystem."""
        return {
            "by_name": {
                "file.md": ["wiki/ideas/file.md"],
                "note.md": ["wiki/ideas/note.md", "wiki/prds/note.md"],
            },
            "by_stem": {
                "file": ["wiki/ideas/file.md"],
                "note": ["wiki/ideas/note.md", "wiki/prds/note.md"],
            },
            "all_paths": [
                "wiki/ideas/file.md",
                "wiki/ideas/note.md",
                "wiki/prds/note.md",
            ],
        }

    def test_resolve_exact_name(self, tmp_path, file_index):
        """Level 1: exact filename match resolves True."""
        linter = _import_linter(tmp_path)
        assert linter._resolve_wikilink("file.md", file_index) is True

    def test_resolve_suffix_match(self, tmp_path, file_index):
        """Level 2: path suffix match resolves True."""
        linter = _import_linter(tmp_path)
        assert linter._resolve_wikilink("ideas/file.md", file_index) is True

    def test_resolve_stem_match(self, tmp_path, file_index):
        """Level 3: stem match (without .md extension) resolves True."""
        linter = _import_linter(tmp_path)
        assert linter._resolve_wikilink("file", file_index) is True

    def test_resolve_not_found(self, tmp_path, file_index):
        """Target that does not exist at any level returns False."""
        linter = _import_linter(tmp_path)
        assert linter._resolve_wikilink("nonexistent.md", file_index) is False

    def test_resolve_case_insensitive(self, tmp_path, file_index):
        """Resolution is case-insensitive: FILE.MD resolves to file.md."""
        linter = _import_linter(tmp_path)
        assert linter._resolve_wikilink("FILE.MD", file_index) is True

    def test_resolve_ambiguous_name_still_resolves(self, tmp_path, file_index):
        """Two files with the same name still resolves True (file exists somewhere)."""
        linter = _import_linter(tmp_path)
        assert linter._resolve_wikilink("note.md", file_index) is True


# ---------------------------------------------------------------------------
# check_broken_links with resolver (integration)
# ---------------------------------------------------------------------------

class TestCheckBrokenLinksWithResolver:
    def test_broken_link_with_stem_resolves(self, tmp_path):
        """Wikilink [[filename]] without .md resolves when target exists."""
        linter = _import_linter(tmp_path)
        _write_md(
            tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "target-doc.md",
            "# Target document",
        )
        md = tmp_path / "wiki" / "domains" / "test-domain" / "prds" / "referrer.md"
        _write_md(md, "See [[target-doc]]\n")

        result = linter.check_broken_links(str(tmp_path))
        assert result == []

    def test_broken_link_truly_broken(self, tmp_path):
        """Wikilink [[nonexistent-file]] is reported as broken."""
        linter = _import_linter(tmp_path)
        md = tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "referrer.md"
        _write_md(md, "See [[nonexistent-file]]\n")

        result = linter.check_broken_links(str(tmp_path))
        assert len(result) == 1
        assert result[0]["link"] == "nonexistent-file"
        assert result[0]["reason"] == "target not found"
