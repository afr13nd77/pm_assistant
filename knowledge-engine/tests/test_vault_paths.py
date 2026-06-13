"""Tests for vault_paths module."""
import os
from datetime import date
import pytest
from pathlib import Path
from unittest.mock import patch


def _import_vault_paths(vault_path_str="/test/vault"):
    """Import vault_paths with a custom VAULT_PATH."""
    with patch.dict(os.environ, {"VAULT_PATH": vault_path_str}):
        # Reload module to pick up new env var
        import importlib
        from shared import vault_paths
        importlib.reload(vault_paths)
        return vault_paths


class TestVaultPathFunctions:
    def setup_method(self):
        self.vp = _import_vault_paths("/test/vault")

    def test_vault_root(self, tmp_path):
        vp = _import_vault_paths(str(tmp_path))
        result = vp.vault_root()
        assert result == tmp_path
        assert result.exists()

    def test_raw_ideas(self, tmp_path):
        vp = _import_vault_paths(str(tmp_path))
        result = vp.raw_ideas()
        assert result == tmp_path / "raw" / "inbound" / "ideas"
        assert result.exists()

    def test_raw_meetings(self, tmp_path):
        vp = _import_vault_paths(str(tmp_path))
        result = vp.raw_meetings()
        assert result == tmp_path / "raw" / "inbound" / "meeting-notes"
        assert result.exists()

    def test_wiki_domain_dir_valid(self, tmp_path):
        vp = _import_vault_paths(str(tmp_path))
        result = vp.wiki_domain_dir("search-engine", "ideas")
        assert result == tmp_path / "wiki" / "domains" / "search-engine" / "ideas"
        assert result.exists()

    def test_wiki_domain_dir_invalid_type(self, tmp_path):
        vp = _import_vault_paths(str(tmp_path))
        with pytest.raises(ValueError, match="Invalid artifact_type"):
            vp.wiki_domain_dir("search-engine", "invalid-type")

    def test_wiki_domain_dir_all_valid_types(self, tmp_path):
        vp = _import_vault_paths(str(tmp_path))
        for atype in ("ideas", "prds", "epics", "userstories", "tasks", "bugs", "knowledge"):
            result = vp.wiki_domain_dir("test-domain", atype)
            assert result.exists()
            assert atype in str(result)

    def test_wiki_meetings(self, tmp_path):
        vp = _import_vault_paths(str(tmp_path))
        result = vp.wiki_meetings()
        assert result == tmp_path / "wiki" / "meetings"
        assert result.exists()

    def test_wiki_daily_logs(self, tmp_path):
        vp = _import_vault_paths(str(tmp_path))
        result = vp.wiki_daily_logs()
        assert result == tmp_path / "wiki" / "daily-logs"
        assert result.exists()

    def test_wiki_reports(self, tmp_path):
        vp = _import_vault_paths(str(tmp_path))
        result = vp.wiki_reports()
        assert result == tmp_path / "wiki" / "reports"
        assert result.exists()

    def test_wiki_concepts(self, tmp_path):
        vp = _import_vault_paths(str(tmp_path))
        result = vp.wiki_concepts()
        assert result == tmp_path / "wiki" / "concepts"
        assert result.exists()

    def test_wiki_domain_knowledge(self, tmp_path):
        vp = _import_vault_paths(str(tmp_path))
        result = vp.wiki_domain_knowledge("search-engine")
        assert result == tmp_path / "wiki" / "domains" / "search-engine" / "knowledge"
        assert result.exists()

    def test_wiki_domain_knowledge_invalid_domain_chars(self, tmp_path):
        """wiki_domain_knowledge delegates to wiki_domain_dir which validates artifact_type,
        but domain is just a path segment — verify it works with hyphenated names."""
        vp = _import_vault_paths(str(tmp_path))
        result = vp.wiki_domain_knowledge("my-complex-domain")
        assert "my-complex-domain" in str(result)
        assert result.exists()

    def test_wiki_index(self, tmp_path):
        vp = _import_vault_paths(str(tmp_path))
        result = vp.wiki_index()
        assert result == tmp_path / "wiki" / "INDEX.md"

    def test_wiki_log(self, tmp_path):
        vp = _import_vault_paths(str(tmp_path))
        result = vp.wiki_log()
        assert result == tmp_path / "wiki" / "LOG.md"

    def test_all_domains_empty(self, tmp_path):
        vp = _import_vault_paths(str(tmp_path))
        assert vp.all_domains() == []

    def test_all_domains_with_domains(self, tmp_path):
        vp = _import_vault_paths(str(tmp_path))
        domains_dir = tmp_path / "wiki" / "domains"
        (domains_dir / "search-engine").mkdir(parents=True)
        (domains_dir / "booking").mkdir(parents=True)
        (domains_dir / "analytics").mkdir(parents=True)
        # Create a file to make sure it's ignored
        (domains_dir / "not-a-domain.txt").write_text("skip me")

        result = vp.all_domains()
        assert result == ["analytics", "booking", "search-engine"]

    def test_ensure_structure(self, tmp_path):
        vp = _import_vault_paths(str(tmp_path))
        vp.ensure_structure()
        assert (tmp_path / "raw" / "inbound" / "ideas").exists()
        assert (tmp_path / "raw" / "inbound" / "meeting-notes").exists()
        assert (tmp_path / "raw" / "inbound" / "daily-logs").exists()
        assert (tmp_path / "raw" / "inbound" / "tasks").exists()
        assert (tmp_path / "raw" / "inbound" / "clippings").exists()
        assert (tmp_path / "raw" / "inbound" / "misc").exists()
        assert (tmp_path / "raw" / "competitors").exists()
        assert (tmp_path / "raw" / "metrics").exists()


class TestNextDailyFilename:
    """Tests for next_daily_filename()."""

    def setup_method(self):
        self.vp = _import_vault_paths("/test/vault")

    def test_empty_directory_starts_from_001(self, tmp_path):
        """When no matching files exist, sequence starts at 001."""
        vp = _import_vault_paths(str(tmp_path))
        today_str = date.today().strftime("%Y.%m.%d")
        result = vp.next_daily_filename(tmp_path)
        assert result == f"{today_str}-001-Daily-summary.md"

    def test_nonexistent_directory_starts_from_001(self, tmp_path):
        """When the directory does not exist, sequence starts at 001."""
        vp = _import_vault_paths(str(tmp_path))
        nonexistent = tmp_path / "does-not-exist"
        today_str = date.today().strftime("%Y.%m.%d")
        result = vp.next_daily_filename(nonexistent)
        assert result == f"{today_str}-001-Daily-summary.md"

    def test_single_existing_file(self, tmp_path):
        """With one existing file numbered 005, next should be 006."""
        vp = _import_vault_paths(str(tmp_path))
        (tmp_path / "2026.05.20-005-Daily-summary.md").write_text("content")
        today_str = date.today().strftime("%Y.%m.%d")
        result = vp.next_daily_filename(tmp_path)
        assert result == f"{today_str}-006-Daily-summary.md"

    def test_multiple_existing_files_picks_max(self, tmp_path):
        """With multiple files, uses the maximum sequence number."""
        vp = _import_vault_paths(str(tmp_path))
        (tmp_path / "2026.05.18-010-Daily-summary.md").write_text("")
        (tmp_path / "2026.05.19-131-Daily-summary.md").write_text("")
        (tmp_path / "2026.05.20-050-Daily-summary.md").write_text("")
        today_str = date.today().strftime("%Y.%m.%d")
        result = vp.next_daily_filename(tmp_path)
        assert result == f"{today_str}-132-Daily-summary.md"

    def test_ignores_non_matching_files(self, tmp_path):
        """Files that don't match the pattern are ignored."""
        vp = _import_vault_paths(str(tmp_path))
        (tmp_path / "2026.05.20-003-Daily-summary.md").write_text("")
        (tmp_path / "random-notes.md").write_text("")
        (tmp_path / "2026.05.20-meeting-notes.md").write_text("")
        (tmp_path / "not-a-daily.txt").write_text("")
        today_str = date.today().strftime("%Y.%m.%d")
        result = vp.next_daily_filename(tmp_path)
        assert result == f"{today_str}-004-Daily-summary.md"

    def test_uses_today_date_not_file_date(self, tmp_path):
        """The returned filename uses today's date regardless of existing file dates."""
        vp = _import_vault_paths(str(tmp_path))
        (tmp_path / "2020.01.01-042-Daily-summary.md").write_text("")
        today_str = date.today().strftime("%Y.%m.%d")
        result = vp.next_daily_filename(tmp_path)
        assert result == f"{today_str}-043-Daily-summary.md"
        assert result.startswith(today_str)

    def test_three_digit_padding(self, tmp_path):
        """Sequence number is zero-padded to 3 digits."""
        vp = _import_vault_paths(str(tmp_path))
        today_str = date.today().strftime("%Y.%m.%d")
        result = vp.next_daily_filename(tmp_path)
        # First file: 001
        assert "-001-" in result

    def test_sequence_beyond_999(self, tmp_path):
        """Sequence numbers beyond 999 still work (no truncation)."""
        vp = _import_vault_paths(str(tmp_path))
        (tmp_path / "2026.05.20-999-Daily-summary.md").write_text("")
        today_str = date.today().strftime("%Y.%m.%d")
        result = vp.next_daily_filename(tmp_path)
        assert result == f"{today_str}-1000-Daily-summary.md"
