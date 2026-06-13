"""Tests for domain_manager module."""

import importlib
import os
import re
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_vault(tmp_path: Path):
    """Reload vault_paths and domain_manager so VAULT_PATH points to tmp_path."""
    with patch.dict(os.environ, {"VAULT_PATH": str(tmp_path)}):
        from shared import vault_paths
        importlib.reload(vault_paths)
    return tmp_path


def _import_dm(tmp_path: Path):
    """Set up vault and return a freshly-reloaded domain_manager module."""
    _setup_vault(tmp_path)
    from app import domain_manager
    importlib.reload(domain_manager)
    return domain_manager


_ARTIFACT_TYPES = ("ideas", "prds", "epics", "userstories", "tasks", "bugs")


# ---------------------------------------------------------------------------
# create_domain
# ---------------------------------------------------------------------------


class TestCreateDomainScaffolding:
    def test_create_domain_scaffolding(self, tmp_path):
        """All expected directories and files are created."""
        dm = _import_dm(tmp_path)
        domain_root = dm.create_domain("search-engine")

        assert domain_root == tmp_path / "wiki" / "domains" / "search-engine"
        assert domain_root.is_dir()

        for artifact_type in _ARTIFACT_TYPES:
            artifact_dir = domain_root / artifact_type
            assert artifact_dir.is_dir(), f"Missing dir: {artifact_type}"
            assert (artifact_dir / "index.md").exists(), f"Missing index.md in {artifact_type}"
            assert (artifact_dir / "log.md").exists(), f"Missing log.md in {artifact_type}"

        assert (domain_root / "decisions.md").exists()
        assert (domain_root / "glossary.md").exists()

    def test_create_domain_index_content(self, tmp_path):
        """index.md has correct frontmatter and table header."""
        dm = _import_dm(tmp_path)
        dm.create_domain("booking")

        for artifact_type in _ARTIFACT_TYPES:
            index_path = (
                tmp_path / "wiki" / "domains" / "booking" / artifact_type / "index.md"
            )
            content = index_path.read_text(encoding="utf-8")

            assert "type: index" in content
            assert "domain: booking" in content
            assert f"artifact_type: {artifact_type}" in content
            assert "| File | Title | Status | Created |" in content
            assert "|------|-------|--------|---------|" in content

    def test_create_domain_log_content(self, tmp_path):
        """log.md has correct frontmatter."""
        dm = _import_dm(tmp_path)
        dm.create_domain("analytics")

        for artifact_type in _ARTIFACT_TYPES:
            log_path = (
                tmp_path / "wiki" / "domains" / "analytics" / artifact_type / "log.md"
            )
            content = log_path.read_text(encoding="utf-8")

            assert "type: log" in content
            assert "domain: analytics" in content
            assert f"artifact_type: {artifact_type}" in content
            assert "Log" in content

    def test_create_domain_decisions_content(self, tmp_path):
        """decisions.md has correct frontmatter."""
        dm = _import_dm(tmp_path)
        dm.create_domain("my-domain")

        decisions_path = tmp_path / "wiki" / "domains" / "my-domain" / "decisions.md"
        content = decisions_path.read_text(encoding="utf-8")

        assert "type: decisions" in content
        assert "domain: my-domain" in content
        assert "Decisions" in content

    def test_create_domain_glossary_content(self, tmp_path):
        """glossary.md has correct frontmatter."""
        dm = _import_dm(tmp_path)
        dm.create_domain("my-domain")

        glossary_path = tmp_path / "wiki" / "domains" / "my-domain" / "glossary.md"
        content = glossary_path.read_text(encoding="utf-8")

        assert "type: glossary" in content
        assert "domain: my-domain" in content
        assert "Glossary" in content

    def test_create_domain_returns_root_path(self, tmp_path):
        """Return value is the domain root Path."""
        dm = _import_dm(tmp_path)
        result = dm.create_domain("payments")
        assert result == tmp_path / "wiki" / "domains" / "payments"

    def test_create_domain_already_exists(self, tmp_path):
        """Raises ValueError if domain already exists."""
        dm = _import_dm(tmp_path)
        dm.create_domain("search-engine")

        with pytest.raises(ValueError, match="already exists"):
            dm.create_domain("search-engine")

    def test_create_domain_invalid_name_uppercase(self, tmp_path):
        """Raises ValueError for names with uppercase letters."""
        dm = _import_dm(tmp_path)
        with pytest.raises(ValueError):
            dm.create_domain("Search-Engine")

    def test_create_domain_invalid_name_spaces(self, tmp_path):
        """Raises ValueError for names with spaces."""
        dm = _import_dm(tmp_path)
        with pytest.raises(ValueError):
            dm.create_domain("search engine")

    def test_create_domain_invalid_name_empty(self, tmp_path):
        """Raises ValueError for empty name."""
        dm = _import_dm(tmp_path)
        with pytest.raises(ValueError):
            dm.create_domain("")

    def test_create_domain_invalid_name_special_chars(self, tmp_path):
        """Raises ValueError for names with special characters."""
        dm = _import_dm(tmp_path)
        with pytest.raises(ValueError):
            dm.create_domain("search_engine")

    def test_create_domain_valid_name_single_word(self, tmp_path):
        """Single-word lowercase domain name is valid."""
        dm = _import_dm(tmp_path)
        result = dm.create_domain("payments")
        assert result.exists()

    def test_create_domain_valid_name_hyphenated(self, tmp_path):
        """Hyphenated lowercase domain name is valid."""
        dm = _import_dm(tmp_path)
        result = dm.create_domain("search-engine-v2")
        assert result.exists()


# ---------------------------------------------------------------------------
# list_domains
# ---------------------------------------------------------------------------


class TestListDomains:
    def test_list_domains_empty(self, tmp_path):
        """Returns empty list when no domains exist."""
        dm = _import_dm(tmp_path)
        result = dm.list_domains()
        assert result == []

    def test_list_domains_with_no_artifacts(self, tmp_path):
        """Newly created domain has all-zero counts."""
        dm = _import_dm(tmp_path)
        dm.create_domain("booking")
        result = dm.list_domains()

        assert len(result) == 1
        entry = result[0]
        assert entry["name"] == "booking"
        for artifact_type in _ARTIFACT_TYPES:
            assert entry[artifact_type] == 0, f"Expected 0 for {artifact_type}"
        assert entry["total"] == 0

    def test_list_domains_with_files(self, tmp_path):
        """Artifact files are counted correctly per type."""
        dm = _import_dm(tmp_path)
        dm.create_domain("search-engine")

        # Add 2 ideas and 1 prd
        ideas_dir = tmp_path / "wiki" / "domains" / "search-engine" / "ideas"
        (ideas_dir / "idea-01.md").write_text("# Idea 1", encoding="utf-8")
        (ideas_dir / "idea-02.md").write_text("# Idea 2", encoding="utf-8")

        prds_dir = tmp_path / "wiki" / "domains" / "search-engine" / "prds"
        (prds_dir / "prd-01.md").write_text("# PRD 1", encoding="utf-8")

        result = dm.list_domains()
        assert len(result) == 1
        entry = result[0]
        assert entry["ideas"] == 2
        assert entry["prds"] == 1
        assert entry["epics"] == 0
        assert entry["total"] == 3

    def test_list_domains_excludes_service_files(self, tmp_path):
        """index.md and log.md are not counted as artifacts."""
        dm = _import_dm(tmp_path)
        dm.create_domain("analytics")

        # index.md and log.md already exist in each artifact dir (created by create_domain)
        result = dm.list_domains()
        entry = result[0]
        for artifact_type in _ARTIFACT_TYPES:
            assert entry[artifact_type] == 0, (
                f"Service files should not be counted for {artifact_type}"
            )
        assert entry["total"] == 0

    def test_list_domains_last_updated_empty_when_no_artifacts(self, tmp_path):
        """last_updated is empty string when no artifact files exist."""
        dm = _import_dm(tmp_path)
        dm.create_domain("new-domain")
        result = dm.list_domains()
        assert result[0]["last_updated"] == ""

    def test_list_domains_last_updated_set_when_artifacts_exist(self, tmp_path):
        """last_updated is an ISO timestamp when artifact files exist."""
        dm = _import_dm(tmp_path)
        dm.create_domain("search-engine")

        ideas_dir = tmp_path / "wiki" / "domains" / "search-engine" / "ideas"
        (ideas_dir / "idea-01.md").write_text("# Idea", encoding="utf-8")

        result = dm.list_domains()
        last_updated = result[0]["last_updated"]
        assert last_updated != ""
        # Should be a valid ISO timestamp
        assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", last_updated)

    def test_list_domains_multiple_domains(self, tmp_path):
        """Multiple domains are returned and sorted alphabetically."""
        dm = _import_dm(tmp_path)
        dm.create_domain("zeta-domain")
        dm.create_domain("alpha-domain")

        result = dm.list_domains()
        assert len(result) == 2
        assert result[0]["name"] == "alpha-domain"
        assert result[1]["name"] == "zeta-domain"


# ---------------------------------------------------------------------------
# update_domain_index
# ---------------------------------------------------------------------------


class TestUpdateDomainIndex:
    def test_update_domain_index_empty(self, tmp_path):
        """No artifact files → table contains only the header row."""
        dm = _import_dm(tmp_path)
        dm.create_domain("search-engine")

        index_path = dm.update_domain_index("search-engine", "ideas")
        content = index_path.read_text(encoding="utf-8")

        assert "| File | Title | Status | Created |" in content
        assert "|------|-------|--------|---------|" in content
        # No data rows beyond header
        lines = [l for l in content.splitlines() if l.startswith("| [[")]
        assert len(lines) == 0

    def test_update_domain_index_with_files(self, tmp_path):
        """Artifact files appear as table rows with correct wiki-link format."""
        dm = _import_dm(tmp_path)
        dm.create_domain("search-engine")

        ideas_dir = tmp_path / "wiki" / "domains" / "search-engine" / "ideas"
        (ideas_dir / "idea-01.md").write_text(
            "---\nstatus: draft\ndate: 2026-05-01\n---\n\n# Better Search\n",
            encoding="utf-8",
        )

        index_path = dm.update_domain_index("search-engine", "ideas")
        content = index_path.read_text(encoding="utf-8")

        assert "[[idea-01.md]]" in content
        assert "Better Search" in content
        assert "draft" in content
        assert "2026-05-01" in content

    def test_update_domain_index_excludes_service_files(self, tmp_path):
        """index.md and log.md do not appear in the rebuilt index table."""
        dm = _import_dm(tmp_path)
        dm.create_domain("booking")

        index_path = dm.update_domain_index("booking", "prds")
        content = index_path.read_text(encoding="utf-8")

        assert "[[index.md]]" not in content
        assert "[[log.md]]" not in content

    def test_update_domain_index_multiple_files(self, tmp_path):
        """Multiple artifact files all appear as rows."""
        dm = _import_dm(tmp_path)
        dm.create_domain("analytics")

        tasks_dir = tmp_path / "wiki" / "domains" / "analytics" / "tasks"
        for i in range(3):
            (tasks_dir / f"task-0{i+1}.md").write_text(
                f"---\nstatus: inbox\n---\n\n# Task {i+1}\n",
                encoding="utf-8",
            )

        index_path = dm.update_domain_index("analytics", "tasks")
        content = index_path.read_text(encoding="utf-8")

        for i in range(3):
            assert f"[[task-0{i+1}.md]]" in content

    def test_update_domain_index_preserves_frontmatter(self, tmp_path):
        """Existing index.md frontmatter keys are preserved after rebuild."""
        dm = _import_dm(tmp_path)
        dm.create_domain("my-domain")

        # Manually add an extra frontmatter field to index.md
        index_path = tmp_path / "wiki" / "domains" / "my-domain" / "ideas" / "index.md"
        original = index_path.read_text(encoding="utf-8")
        modified = original.replace("---\n\n#", "custom_key: custom_value\n---\n\n#")
        index_path.write_text(modified, encoding="utf-8")

        dm.update_domain_index("my-domain", "ideas")
        new_content = index_path.read_text(encoding="utf-8")

        assert "custom_key: custom_value" in new_content

    def test_update_domain_index_returns_index_path(self, tmp_path):
        """Return value is the path to index.md."""
        dm = _import_dm(tmp_path)
        dm.create_domain("search-engine")

        result = dm.update_domain_index("search-engine", "bugs")
        assert result == (
            tmp_path / "wiki" / "domains" / "search-engine" / "bugs" / "index.md"
        )

    def test_update_domain_index_title_from_heading(self, tmp_path):
        """Title is extracted from the first # heading if available."""
        dm = _import_dm(tmp_path)
        dm.create_domain("search-engine")

        ideas_dir = tmp_path / "wiki" / "domains" / "search-engine" / "ideas"
        (ideas_dir / "idea-special.md").write_text(
            "---\nstatus: open\n---\n\n# My Special Title\n\nBody text.\n",
            encoding="utf-8",
        )

        index_path = dm.update_domain_index("search-engine", "ideas")
        content = index_path.read_text(encoding="utf-8")
        assert "My Special Title" in content

    def test_update_domain_index_title_falls_back_to_stem(self, tmp_path):
        """Title falls back to filename stem if no # heading exists."""
        dm = _import_dm(tmp_path)
        dm.create_domain("search-engine")

        ideas_dir = tmp_path / "wiki" / "domains" / "search-engine" / "ideas"
        (ideas_dir / "idea-no-heading.md").write_text(
            "---\nstatus: open\n---\n\nNo heading here.\n",
            encoding="utf-8",
        )

        index_path = dm.update_domain_index("search-engine", "ideas")
        content = index_path.read_text(encoding="utf-8")
        assert "idea-no-heading" in content


# ---------------------------------------------------------------------------
# append_domain_log
# ---------------------------------------------------------------------------


class TestAppendDomainLog:
    def test_append_domain_log_format(self, tmp_path):
        """Entry follows [TIMESTAMP] ACTION target → result format."""
        dm = _import_dm(tmp_path)
        dm.create_domain("search-engine")

        log_path = dm.append_domain_log(
            "search-engine", "ideas", "CREATE", "idea-01.md", "ok"
        )
        content = log_path.read_text(encoding="utf-8")

        # Verify timestamp format and arrow
        assert re.search(
            r"\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\] CREATE idea-01\.md → ok",
            content,
        )

    def test_append_domain_log_returns_log_path(self, tmp_path):
        """Return value is the path to log.md."""
        dm = _import_dm(tmp_path)
        dm.create_domain("booking")

        result = dm.append_domain_log("booking", "prds", "UPDATE", "prd-01.md", "success")
        assert result == (
            tmp_path / "wiki" / "domains" / "booking" / "prds" / "log.md"
        )

    def test_append_domain_log_multiple_entries(self, tmp_path):
        """Multiple append calls accumulate entries in order."""
        dm = _import_dm(tmp_path)
        dm.create_domain("analytics")

        dm.append_domain_log("analytics", "tasks", "CREATE", "task-01.md", "created")
        dm.append_domain_log("analytics", "tasks", "UPDATE", "task-01.md", "updated")
        dm.append_domain_log("analytics", "tasks", "DELETE", "task-01.md", "deleted")

        log_path = tmp_path / "wiki" / "domains" / "analytics" / "tasks" / "log.md"
        content = log_path.read_text(encoding="utf-8")

        assert "CREATE" in content
        assert "UPDATE" in content
        assert "DELETE" in content

        # Verify order: CREATE appears before UPDATE, UPDATE before DELETE
        create_pos = content.index("CREATE")
        update_pos = content.index("UPDATE")
        delete_pos = content.index("DELETE")
        assert create_pos < update_pos < delete_pos

    def test_append_domain_log_creates_log_if_missing(self, tmp_path):
        """log.md is created with default header when it doesn't exist."""
        dm = _import_dm(tmp_path)
        dm.create_domain("my-domain")

        # Remove the log.md file
        log_path = tmp_path / "wiki" / "domains" / "my-domain" / "epics" / "log.md"
        log_path.unlink()
        assert not log_path.exists()

        dm.append_domain_log("my-domain", "epics", "CREATE", "epic-01.md", "ok")

        assert log_path.exists()
        content = log_path.read_text(encoding="utf-8")
        # Default header should be present
        assert "type: log" in content
        # Entry should also be present
        assert "CREATE" in content

    def test_append_domain_log_does_not_overwrite_existing_entries(self, tmp_path):
        """Existing log content is preserved when appending a new entry."""
        dm = _import_dm(tmp_path)
        dm.create_domain("search-engine")

        dm.append_domain_log(
            "search-engine", "bugs", "CREATE", "bug-01.md", "filed"
        )
        first_content = (
            tmp_path / "wiki" / "domains" / "search-engine" / "bugs" / "log.md"
        ).read_text(encoding="utf-8")

        dm.append_domain_log(
            "search-engine", "bugs", "CLOSE", "bug-01.md", "resolved"
        )
        second_content = (
            tmp_path / "wiki" / "domains" / "search-engine" / "bugs" / "log.md"
        ).read_text(encoding="utf-8")

        # Both entries should be present
        assert "CREATE" in second_content
        assert "CLOSE" in second_content
        # First entry text is still there
        assert "filed" in second_content
