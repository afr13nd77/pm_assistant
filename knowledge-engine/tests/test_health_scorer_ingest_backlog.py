"""Tests for _check_ingest_backlog in health_scorer module."""
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


def _write_md(path: Path, content: str = "# Placeholder\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCheckIngestBacklog:

    def test_raw_idea_without_wiki_counterpart_is_backlog(self, tmp_path):
        scorer = _import_health_scorer(tmp_path)
        _write_md(tmp_path / "raw" / "inbound" / "ideas" / "IDEA-0044-slug.md")

        result = scorer._check_ingest_backlog(str(tmp_path))

        assert len(result) == 1
        assert result[0]["file"] == "raw/inbound/ideas/IDEA-0044-slug.md"
        assert result[0]["type"] == "ideas"

    def test_raw_task_without_wiki_counterpart_is_backlog(self, tmp_path):
        scorer = _import_health_scorer(tmp_path)
        _write_md(tmp_path / "raw" / "inbound" / "tasks" / "TASK-010-do-stuff.md")

        result = scorer._check_ingest_backlog(str(tmp_path))

        assert len(result) == 1
        assert result[0]["file"] == "raw/inbound/tasks/TASK-010-do-stuff.md"
        assert result[0]["type"] == "tasks"

    def test_raw_idea_with_wiki_counterpart_is_not_backlog(self, tmp_path):
        scorer = _import_health_scorer(tmp_path)
        _write_md(tmp_path / "raw" / "inbound" / "ideas" / "IDEA-0044-slug.md")
        _write_md(tmp_path / "wiki" / "domains" / "search-engine" / "ideas" / "IDEA-0044-slug.md")

        result = scorer._check_ingest_backlog(str(tmp_path))
        assert result == []

    def test_raw_task_with_wiki_counterpart_is_not_backlog(self, tmp_path):
        scorer = _import_health_scorer(tmp_path)
        _write_md(tmp_path / "raw" / "inbound" / "tasks" / "TASK-010-do-stuff.md")
        _write_md(tmp_path / "wiki" / "domains" / "payments" / "tasks" / "TASK-010-do-stuff.md")

        result = scorer._check_ingest_backlog(str(tmp_path))
        assert result == []

    def test_case_insensitive_stem_matching(self, tmp_path):
        scorer = _import_health_scorer(tmp_path)
        _write_md(tmp_path / "raw" / "inbound" / "ideas" / "idea-0044-slug.md")
        _write_md(tmp_path / "wiki" / "domains" / "crm" / "ideas" / "IDEA-0044-slug.md")

        result = scorer._check_ingest_backlog(str(tmp_path))
        assert result == []

    def test_wiki_counterpart_in_any_domain_counts(self, tmp_path):
        scorer = _import_health_scorer(tmp_path)
        _write_md(tmp_path / "raw" / "inbound" / "ideas" / "IDEA-0044-slug.md")
        # Wiki file exists in a different domain than one might expect
        _write_md(tmp_path / "wiki" / "domains" / "booking" / "ideas" / "IDEA-0044-slug.md")

        result = scorer._check_ingest_backlog(str(tmp_path))
        assert result == []

    def test_mixed_backlog_and_ingested(self, tmp_path):
        scorer = _import_health_scorer(tmp_path)
        # Two raw ideas: one has wiki counterpart, the other does not
        _write_md(tmp_path / "raw" / "inbound" / "ideas" / "IDEA-001-ingested.md")
        _write_md(tmp_path / "raw" / "inbound" / "ideas" / "IDEA-002-pending.md")
        _write_md(tmp_path / "wiki" / "domains" / "search-engine" / "ideas" / "IDEA-001-ingested.md")

        result = scorer._check_ingest_backlog(str(tmp_path))

        assert len(result) == 1
        assert result[0]["file"] == "raw/inbound/ideas/IDEA-002-pending.md"

    def test_both_ideas_and_tasks_scanned(self, tmp_path):
        scorer = _import_health_scorer(tmp_path)
        _write_md(tmp_path / "raw" / "inbound" / "ideas" / "IDEA-001.md")
        _write_md(tmp_path / "raw" / "inbound" / "tasks" / "TASK-001.md")

        result = scorer._check_ingest_backlog(str(tmp_path))

        assert len(result) == 2
        types = {r["type"] for r in result}
        assert types == {"ideas", "tasks"}

    def test_empty_vault_returns_empty(self, tmp_path):
        scorer = _import_health_scorer(tmp_path)

        result = scorer._check_ingest_backlog(str(tmp_path))
        assert result == []

    def test_raw_dirs_exist_but_empty(self, tmp_path):
        scorer = _import_health_scorer(tmp_path)
        (tmp_path / "raw" / "inbound" / "ideas").mkdir(parents=True)
        (tmp_path / "raw" / "inbound" / "tasks").mkdir(parents=True)

        result = scorer._check_ingest_backlog(str(tmp_path))
        assert result == []

    def test_non_md_files_in_raw_are_ignored(self, tmp_path):
        scorer = _import_health_scorer(tmp_path)
        raw_ideas = tmp_path / "raw" / "inbound" / "ideas"
        raw_ideas.mkdir(parents=True)
        (raw_ideas / "notes.txt").write_text("not markdown", encoding="utf-8")
        (raw_ideas / "data.json").write_text("{}", encoding="utf-8")

        result = scorer._check_ingest_backlog(str(tmp_path))
        assert result == []

    def test_paths_use_forward_slashes(self, tmp_path):
        scorer = _import_health_scorer(tmp_path)
        _write_md(tmp_path / "raw" / "inbound" / "ideas" / "IDEA-001.md")

        result = scorer._check_ingest_backlog(str(tmp_path))

        assert len(result) == 1
        assert "\\" not in result[0]["file"]
        assert "/" in result[0]["file"]

    def test_wiki_domains_dir_missing_does_not_crash(self, tmp_path):
        scorer = _import_health_scorer(tmp_path)
        # Raw files exist but wiki/domains/ doesn't
        _write_md(tmp_path / "raw" / "inbound" / "ideas" / "IDEA-001.md")

        result = scorer._check_ingest_backlog(str(tmp_path))

        assert len(result) == 1
        assert result[0]["file"] == "raw/inbound/ideas/IDEA-001.md"

    def test_multiple_domains_with_same_stem(self, tmp_path):
        """If the same stem exists in multiple domains, raw file is still matched."""
        scorer = _import_health_scorer(tmp_path)
        _write_md(tmp_path / "raw" / "inbound" / "ideas" / "IDEA-001.md")
        _write_md(tmp_path / "wiki" / "domains" / "search-engine" / "ideas" / "IDEA-001.md")
        _write_md(tmp_path / "wiki" / "domains" / "crm" / "ideas" / "IDEA-001.md")

        result = scorer._check_ingest_backlog(str(tmp_path))
        assert result == []

    def test_return_type_is_list_of_dicts(self, tmp_path):
        scorer = _import_health_scorer(tmp_path)
        _write_md(tmp_path / "raw" / "inbound" / "ideas" / "IDEA-001.md")
        _write_md(tmp_path / "raw" / "inbound" / "tasks" / "TASK-001.md")

        result = scorer._check_ingest_backlog(str(tmp_path))

        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, dict)
            assert "file" in item
            assert "type" in item
            assert item["type"] in ("ideas", "tasks")
