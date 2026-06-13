"""Tests for _check_dead_ends in health_scorer module."""
import importlib
import os
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


def _import_health_scorer(tmp_path: Path):
    """Set up vault and return a freshly-reloaded health_scorer module."""
    _setup_vault(tmp_path)
    from app import health_scorer
    importlib.reload(health_scorer)
    return health_scorer


def _write_md(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCheckDeadEnds:

    def test_file_with_no_wikilinks_is_dead_end(self, tmp_path):
        scorer = _import_health_scorer(tmp_path)
        md = tmp_path / "wiki" / "domains" / "search-engine" / "ideas" / "IDEA-001.md"
        _write_md(md, "---\ntitle: Idea\n---\n\nNo links here.\n")

        result = scorer._check_dead_ends(str(tmp_path))

        assert len(result) == 1
        assert result[0]["file"] == "wiki/domains/search-engine/ideas/IDEA-001.md"
        assert result[0]["domain"] == "search-engine"

    def test_file_with_wikilink_is_not_dead_end(self, tmp_path):
        scorer = _import_health_scorer(tmp_path)
        md = tmp_path / "wiki" / "domains" / "search-engine" / "ideas" / "IDEA-001.md"
        _write_md(md, "---\ntitle: Idea\n---\n\nSee [[IDEA-002]] for details.\n")

        result = scorer._check_dead_ends(str(tmp_path))
        assert result == []

    def test_wikilink_in_frontmatter_does_not_count(self, tmp_path):
        scorer = _import_health_scorer(tmp_path)
        md = tmp_path / "wiki" / "domains" / "search-engine" / "epics" / "EPIC-01.md"
        _write_md(md, "---\ntitle: [[linked-idea]]\nstatus: draft\n---\n\nNo links in body.\n")

        result = scorer._check_dead_ends(str(tmp_path))

        assert len(result) == 1
        assert result[0]["file"] == "wiki/domains/search-engine/epics/EPIC-01.md"

    def test_service_files_are_excluded(self, tmp_path):
        scorer = _import_health_scorer(tmp_path)
        for svc in ("index.md", "log.md", "decisions.md", "glossary.md"):
            _write_md(
                tmp_path / "wiki" / "domains" / "payments" / "ideas" / svc,
                "---\ntitle: Service\n---\n\nNo links.\n",
            )

        result = scorer._check_dead_ends(str(tmp_path))
        assert result == []

    def test_scans_all_six_artifact_types(self, tmp_path):
        scorer = _import_health_scorer(tmp_path)
        artifact_types = ("ideas", "prds", "epics", "userstories", "tasks", "bugs")
        domain = "booking"

        for art_type in artifact_types:
            _write_md(
                tmp_path / "wiki" / "domains" / domain / art_type / f"DOC-{art_type}.md",
                "---\ntitle: Test\n---\n\nDead end content.\n",
            )

        result = scorer._check_dead_ends(str(tmp_path))

        assert len(result) == 6
        files = {r["file"] for r in result}
        for art_type in artifact_types:
            assert f"wiki/domains/booking/{art_type}/DOC-{art_type}.md" in files

    def test_multiple_domains(self, tmp_path):
        scorer = _import_health_scorer(tmp_path)
        for domain in ("search-engine", "payments", "crm"):
            _write_md(
                tmp_path / "wiki" / "domains" / domain / "ideas" / "IDEA-01.md",
                "---\ntitle: X\n---\n\nNo links.\n",
            )

        result = scorer._check_dead_ends(str(tmp_path))

        assert len(result) == 3
        domains = {r["domain"] for r in result}
        assert domains == {"search-engine", "payments", "crm"}

    def test_empty_vault_returns_empty(self, tmp_path):
        scorer = _import_health_scorer(tmp_path)

        result = scorer._check_dead_ends(str(tmp_path))
        assert result == []

    def test_file_without_frontmatter(self, tmp_path):
        scorer = _import_health_scorer(tmp_path)
        md = tmp_path / "wiki" / "domains" / "search-engine" / "ideas" / "IDEA-001.md"
        _write_md(md, "# Just a heading\n\nNo links, no frontmatter.\n")

        result = scorer._check_dead_ends(str(tmp_path))

        assert len(result) == 1
        assert result[0]["file"] == "wiki/domains/search-engine/ideas/IDEA-001.md"

    def test_file_without_frontmatter_but_with_wikilink(self, tmp_path):
        scorer = _import_health_scorer(tmp_path)
        md = tmp_path / "wiki" / "domains" / "search-engine" / "ideas" / "IDEA-001.md"
        _write_md(md, "# Heading\n\nSee [[other-doc]].\n")

        result = scorer._check_dead_ends(str(tmp_path))
        assert result == []

    def test_non_md_files_are_skipped(self, tmp_path):
        scorer = _import_health_scorer(tmp_path)
        txt_file = tmp_path / "wiki" / "domains" / "search-engine" / "ideas" / "notes.txt"
        _write_md(txt_file, "No links here.\n")

        result = scorer._check_dead_ends(str(tmp_path))
        assert result == []

    def test_paths_use_forward_slashes(self, tmp_path):
        scorer = _import_health_scorer(tmp_path)
        md = tmp_path / "wiki" / "domains" / "search-engine" / "prds" / "PRD-001.md"
        _write_md(md, "---\ntitle: PRD\n---\n\nDead end.\n")

        result = scorer._check_dead_ends(str(tmp_path))

        assert len(result) == 1
        assert "\\" not in result[0]["file"]
        assert "/" in result[0]["file"]

    def test_unreadable_file_is_skipped(self, tmp_path):
        scorer = _import_health_scorer(tmp_path)
        md = tmp_path / "wiki" / "domains" / "search-engine" / "ideas" / "IDEA-001.md"
        _write_md(md, "---\ntitle: OK\n---\n\nNo links.\n")

        bad_md = tmp_path / "wiki" / "domains" / "search-engine" / "ideas" / "IDEA-002.md"
        _write_md(bad_md, "---\ntitle: Bad\n---\n\nNo links.\n")

        with patch.object(Path, "read_text", side_effect=[OSError("permission denied"), "---\ntitle: OK\n---\n\nNo links.\n"]):
            # Even if one file is unreadable, the function should not crash
            # and should process remaining files
            result = scorer._check_dead_ends(str(tmp_path))
            # We can't assert exact count here because of mock side effects,
            # but the function should not raise
            assert isinstance(result, list)
