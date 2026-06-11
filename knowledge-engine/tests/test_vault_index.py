"""Tests for vault_index module with domain-based vault structure."""
import os
import importlib
import pytest
from pathlib import Path
from unittest.mock import patch


def _setup_vault_paths(tmp_path):
    """Set up vault_paths module to use tmp_path."""
    with patch.dict(os.environ, {"VAULT_PATH": str(tmp_path)}):
        from app import vault_paths
        importlib.reload(vault_paths)
    return tmp_path


def _create_md_file(path: Path, title: str, tags: list[str] = None, status: str = "inbox"):
    """Create a .md file with frontmatter."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fm_lines = ["---"]
    if tags:
        fm_lines.append(f"tags: [{', '.join(tags)}]")
    fm_lines.append(f"status: {status}")
    fm_lines.append("---")
    fm_lines.append(f"# {title}")
    fm_lines.append("")
    fm_lines.append("Some body content about this topic.")
    path.write_text("\n".join(fm_lines), encoding="utf-8")


class TestBuildIndex:
    def test_empty_vault(self, tmp_path):
        _setup_vault_paths(tmp_path)
        from app.vault_index import build_index
        index = build_index(str(tmp_path))
        assert len(index.entries) == 0
        assert index.vault_path == str(tmp_path)

    def test_single_domain_ideas(self, tmp_path):
        _setup_vault_paths(tmp_path)
        ideas_dir = tmp_path / "wiki" / "domains" / "search-engine" / "ideas"
        _create_md_file(ideas_dir / "idea-01.md", "Search Improvements", ["search", "ux"])

        from app.vault_index import build_index
        index = build_index(str(tmp_path))
        assert len(index.entries) == 1
        entry = index.entries[0]
        assert entry.category == "idea"
        assert entry.domain == "search-engine"
        assert entry.title == "Search Improvements"
        assert "search" in entry.tags

    def test_multiple_domains(self, tmp_path):
        _setup_vault_paths(tmp_path)

        # Domain 1: search-engine
        ideas1 = tmp_path / "wiki" / "domains" / "search-engine" / "ideas"
        _create_md_file(ideas1 / "idea-01.md", "Better Search")

        # Domain 2: booking
        ideas2 = tmp_path / "wiki" / "domains" / "booking" / "ideas"
        _create_md_file(ideas2 / "idea-01.md", "Booking Flow")

        prds = tmp_path / "wiki" / "domains" / "booking" / "prds"
        _create_md_file(prds / "prd-01.md", "Booking PRD")

        from app.vault_index import build_index
        index = build_index(str(tmp_path))

        assert len(index.entries) == 3
        domains = {e.domain for e in index.entries}
        assert domains == {"search-engine", "booking"}
        categories = {e.category for e in index.entries}
        assert categories == {"idea", "prd"}

    def test_all_artifact_types(self, tmp_path):
        _setup_vault_paths(tmp_path)
        domain = "test-domain"
        artifact_map = {
            "ideas": "idea",
            "prds": "prd",
            "epics": "epic",
            "userstories": "userstory",
            "tasks": "task",
            "bugs": "bug",
        }
        for artifact_type, expected_category in artifact_map.items():
            d = tmp_path / "wiki" / "domains" / domain / artifact_type
            _create_md_file(d / f"{artifact_type}-01.md", f"Test {artifact_type}")

        from app.vault_index import build_index
        index = build_index(str(tmp_path))

        assert len(index.entries) == 6
        categories = {e.category for e in index.entries}
        assert categories == set(artifact_map.values())

    def test_cross_domain_meetings(self, tmp_path):
        _setup_vault_paths(tmp_path)
        meetings = tmp_path / "wiki" / "meetings"
        _create_md_file(meetings / "2026-04-28-standup.md", "Daily Standup")

        from app.vault_index import build_index
        index = build_index(str(tmp_path))

        assert len(index.entries) == 1
        entry = index.entries[0]
        assert entry.category == "meeting"
        assert entry.domain == "cross-domain"

    def test_cross_domain_daily_logs(self, tmp_path):
        _setup_vault_paths(tmp_path)
        logs = tmp_path / "wiki" / "daily-logs"
        _create_md_file(logs / "2026-04-28.md", "Daily Log")

        from app.vault_index import build_index
        index = build_index(str(tmp_path))

        assert len(index.entries) == 1
        entry = index.entries[0]
        assert entry.category == "daily-log"
        assert entry.domain == "cross-domain"

    def test_cross_domain_reports(self, tmp_path):
        _setup_vault_paths(tmp_path)
        reports = tmp_path / "wiki" / "reports"
        _create_md_file(reports / "synthesis-2026-04-28.md", "Synthesis Report")

        from app.vault_index import build_index
        index = build_index(str(tmp_path))

        assert len(index.entries) == 1
        entry = index.entries[0]
        assert entry.category == "report"
        assert entry.domain == "cross-domain"

    def test_relative_path_format(self, tmp_path):
        _setup_vault_paths(tmp_path)
        ideas_dir = tmp_path / "wiki" / "domains" / "search" / "ideas"
        _create_md_file(ideas_dir / "test.md", "Test Idea")

        from app.vault_index import build_index
        index = build_index(str(tmp_path))

        entry = index.entries[0]
        assert entry.path == "wiki/domains/search/ideas/test.md"
        assert "\\" not in entry.path  # forward slashes only

    def test_domain_field_in_vault_entry(self, tmp_path):
        _setup_vault_paths(tmp_path)
        from app.vault_index import VaultEntry
        entry = VaultEntry(path="test.md", title="Test", domain="search-engine")
        assert entry.domain == "search-engine"

    def test_domain_field_default_empty(self, tmp_path):
        _setup_vault_paths(tmp_path)
        from app.vault_index import VaultEntry
        entry = VaultEntry(path="test.md", title="Test")
        assert entry.domain == ""


class TestVaultIndexSearch:
    def test_search_by_keyword(self, tmp_path):
        _setup_vault_paths(tmp_path)
        ideas = tmp_path / "wiki" / "domains" / "search" / "ideas"
        _create_md_file(ideas / "search-idea.md", "Improve Search Algorithm", ["search"])

        from app.vault_index import build_index
        index = build_index(str(tmp_path))

        results = index.search(["search"], [])
        assert len(results) > 0
        assert results[0][0].title == "Improve Search Algorithm"

    def test_search_by_tag(self, tmp_path):
        _setup_vault_paths(tmp_path)
        ideas = tmp_path / "wiki" / "domains" / "booking" / "ideas"
        _create_md_file(ideas / "booking-idea.md", "Booking Feature", ["booking", "ux"])

        from app.vault_index import build_index
        index = build_index(str(tmp_path))

        results = index.search([], ["booking"])
        assert len(results) > 0
        assert results[0][0].domain == "booking"

    def test_search_returns_max_10(self, tmp_path):
        _setup_vault_paths(tmp_path)
        ideas = tmp_path / "wiki" / "domains" / "test" / "ideas"
        for i in range(15):
            _create_md_file(ideas / f"idea-{i:02d}.md", f"Test Idea {i}", ["common"])

        from app.vault_index import build_index
        index = build_index(str(tmp_path))

        results = index.search([], ["common"])
        assert len(results) <= 10
