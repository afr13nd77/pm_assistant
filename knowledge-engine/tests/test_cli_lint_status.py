"""Tests for CLI lint and status subcommands."""

import importlib
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reload_modules(tmp_path: Path):
    """Reload vault_paths and domain_manager so VAULT_PATH points to tmp_path."""
    with patch.dict(os.environ, {"VAULT_PATH": str(tmp_path)}):
        from shared import vault_paths
        importlib.reload(vault_paths)
    from app import domain_manager
    importlib.reload(domain_manager)


def _run_main(argv: list, tmp_path: Path):
    """
    Invoke cli.main() with the given argv, capturing stdout.
    Sets VAULT_PATH env var and reloads modules.
    Returns (exit_code, stdout_text).
    """
    _reload_modules(tmp_path)

    import io
    captured = io.StringIO()

    with patch.dict(os.environ, {"VAULT_PATH": str(tmp_path)}):
        with patch.object(sys, "argv", ["knowledge_engine"] + argv):
            from app import cli
            importlib.reload(cli)
            with patch("sys.stdout", captured):
                try:
                    cli.main()
                    exit_code = 0
                except SystemExit as e:
                    exit_code = e.code if isinstance(e.code, int) else 0

    return exit_code, captured.getvalue()


def _create_minimal_domain(tmp_path: Path, domain: str = "test-domain"):
    """Create a minimal domain structure with an idea file."""
    ideas_dir = tmp_path / "wiki" / "domains" / domain / "ideas"
    ideas_dir.mkdir(parents=True, exist_ok=True)
    idea_file = ideas_dir / "idea-01.md"
    idea_file.write_text("---\nstatus: draft\n---\n\n# Test Idea\n", encoding="utf-8")
    return idea_file


# ---------------------------------------------------------------------------
# lint subcommand
# ---------------------------------------------------------------------------


class TestCliLint:
    def test_lint_clean_vault_exits_0(self, tmp_path):
        """lint on a clean vault exits 0."""
        _reload_modules(tmp_path)
        exit_code, output = _run_main(["lint", "--vault", str(tmp_path)], tmp_path)
        assert exit_code == 0

    def test_lint_returns_json_with_required_keys(self, tmp_path):
        """lint outputs JSON with status, broken_links, orphan_pages, stale_drafts,
        unsorted_misc, and summary keys."""
        _reload_modules(tmp_path)
        exit_code, output = _run_main(["lint", "--vault", str(tmp_path)], tmp_path)

        assert exit_code == 0
        data = json.loads(output.strip())
        assert "status" in data
        assert "broken_links" in data
        assert "orphan_pages" in data
        assert "stale_drafts" in data
        assert "unsorted_misc" in data
        assert "invalid_idea_statuses" in data
        assert "summary" in data

    def test_lint_summary_has_required_keys(self, tmp_path):
        """lint summary contains all count fields and total_issues."""
        _reload_modules(tmp_path)
        exit_code, output = _run_main(["lint", "--vault", str(tmp_path)], tmp_path)

        assert exit_code == 0
        data = json.loads(output.strip())
        summary = data["summary"]
        assert "broken_links_count" in summary
        assert "orphan_pages_count" in summary
        assert "stale_drafts_count" in summary
        assert "unsorted_misc_count" in summary
        assert "invalid_idea_statuses_count" in summary
        assert "total_issues" in summary

    def test_lint_clean_vault_zero_issues(self, tmp_path):
        """lint on an empty vault reports zero total issues."""
        _reload_modules(tmp_path)
        exit_code, output = _run_main(["lint", "--vault", str(tmp_path)], tmp_path)

        assert exit_code == 0
        data = json.loads(output.strip())
        assert data["summary"]["total_issues"] == 0

    def test_lint_detects_broken_link(self, tmp_path):
        """lint detects a broken wikilink and reports it in broken_links."""
        _reload_modules(tmp_path)
        md = tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "idea-01.md"
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text("# Idea\n\n[[nonexistent-page]]\n", encoding="utf-8")

        exit_code, output = _run_main(["lint", "--vault", str(tmp_path)], tmp_path)

        assert exit_code == 0
        data = json.loads(output.strip())
        assert data["summary"]["broken_links_count"] >= 1
        assert data["summary"]["total_issues"] >= 1

    def test_lint_detects_stale_draft(self, tmp_path):
        """lint detects a stale draft older than 30 days."""
        _reload_modules(tmp_path)
        md = tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "stale.md"
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text("---\nstatus: Новая\n---\n\n# Stale\n", encoding="utf-8")
        past = time.time() - 35 * 86400
        os.utime(str(md), (past, past))

        exit_code, output = _run_main(["lint", "--vault", str(tmp_path)], tmp_path)

        assert exit_code == 0
        data = json.loads(output.strip())
        assert data["summary"]["stale_drafts_count"] >= 1

    def test_lint_accepts_vault_flag(self, tmp_path):
        """lint accepts --vault flag and uses it as the vault root."""
        _reload_modules(tmp_path)
        exit_code, output = _run_main(["lint", "--vault", str(tmp_path)], tmp_path)
        assert exit_code == 0
        data = json.loads(output.strip())
        assert "status" in data

    def test_lint_status_is_ok(self, tmp_path):
        """lint always returns status=ok."""
        _reload_modules(tmp_path)
        exit_code, output = _run_main(["lint", "--vault", str(tmp_path)], tmp_path)
        assert exit_code == 0
        data = json.loads(output.strip())
        assert data["status"] == "ok"


# ---------------------------------------------------------------------------
# status subcommand
# ---------------------------------------------------------------------------


class TestCliStatus:
    def test_status_empty_vault_exits_0(self, tmp_path):
        """status on an empty vault exits 0."""
        _reload_modules(tmp_path)
        exit_code, output = _run_main(["status", "--vault", str(tmp_path)], tmp_path)
        assert exit_code == 0

    def test_status_returns_json_with_required_keys(self, tmp_path):
        """status outputs JSON with status, domains, domains_count, total_artifacts,
        raw_counts, and health keys."""
        _reload_modules(tmp_path)
        exit_code, output = _run_main(["status", "--vault", str(tmp_path)], tmp_path)

        assert exit_code == 0
        data = json.loads(output.strip())
        assert "status" in data
        assert "domains" in data
        assert "domains_count" in data
        assert "total_artifacts" in data
        assert "raw_counts" in data
        assert "health" in data

    def test_status_health_has_required_keys(self, tmp_path):
        """status health field contains all lint summary keys."""
        _reload_modules(tmp_path)
        exit_code, output = _run_main(["status", "--vault", str(tmp_path)], tmp_path)

        assert exit_code == 0
        data = json.loads(output.strip())
        health = data["health"]
        assert "broken_links_count" in health
        assert "orphan_pages_count" in health
        assert "stale_drafts_count" in health
        assert "unsorted_misc_count" in health
        assert "total_issues" in health

    def test_status_empty_vault_zero_domains(self, tmp_path):
        """status on an empty vault reports 0 domains and 0 total_artifacts."""
        _reload_modules(tmp_path)
        exit_code, output = _run_main(["status", "--vault", str(tmp_path)], tmp_path)

        assert exit_code == 0
        data = json.loads(output.strip())
        assert data["domains_count"] == 0
        assert data["total_artifacts"] == 0

    def test_status_counts_domains(self, tmp_path):
        """status reports correct domains_count when domains exist."""
        _reload_modules(tmp_path)
        (tmp_path / "wiki" / "domains" / "alpha" / "ideas").mkdir(parents=True, exist_ok=True)
        (tmp_path / "wiki" / "domains" / "beta" / "ideas").mkdir(parents=True, exist_ok=True)

        exit_code, output = _run_main(["status", "--vault", str(tmp_path)], tmp_path)

        assert exit_code == 0
        data = json.loads(output.strip())
        assert data["domains_count"] == 2

    def test_status_counts_artifacts(self, tmp_path):
        """status reports correct total_artifacts count."""
        _reload_modules(tmp_path)
        ideas_dir = tmp_path / "wiki" / "domains" / "test-domain" / "ideas"
        ideas_dir.mkdir(parents=True, exist_ok=True)
        (ideas_dir / "idea-01.md").write_text("# Idea 1", encoding="utf-8")
        (ideas_dir / "idea-02.md").write_text("# Idea 2", encoding="utf-8")

        exit_code, output = _run_main(["status", "--vault", str(tmp_path)], tmp_path)

        assert exit_code == 0
        data = json.loads(output.strip())
        assert data["total_artifacts"] == 2

    def test_status_raw_counts_populated(self, tmp_path):
        """status reports file counts in raw/inbound subdirectories."""
        _reload_modules(tmp_path)
        misc_dir = tmp_path / "raw" / "inbound" / "misc"
        misc_dir.mkdir(parents=True, exist_ok=True)
        (misc_dir / "file1.txt").write_text("data", encoding="utf-8")
        (misc_dir / "file2.txt").write_text("data", encoding="utf-8")

        exit_code, output = _run_main(["status", "--vault", str(tmp_path)], tmp_path)

        assert exit_code == 0
        data = json.loads(output.strip())
        assert data["raw_counts"].get("misc") == 2

    def test_status_raw_counts_empty_when_no_raw_dir(self, tmp_path):
        """status raw_counts is an empty dict when raw/inbound does not exist."""
        _reload_modules(tmp_path)
        exit_code, output = _run_main(["status", "--vault", str(tmp_path)], tmp_path)

        assert exit_code == 0
        data = json.loads(output.strip())
        assert data["raw_counts"] == {}

    def test_status_accepts_vault_flag(self, tmp_path):
        """status accepts --vault flag and uses it as the vault root."""
        _reload_modules(tmp_path)
        exit_code, output = _run_main(["status", "--vault", str(tmp_path)], tmp_path)
        assert exit_code == 0
        data = json.loads(output.strip())
        assert data["status"] == "ok"

    def test_status_domains_list_contains_domain_entries(self, tmp_path):
        """status domains list includes entries with name and total."""
        _reload_modules(tmp_path)
        ideas_dir = tmp_path / "wiki" / "domains" / "my-domain" / "ideas"
        ideas_dir.mkdir(parents=True, exist_ok=True)
        (ideas_dir / "idea-01.md").write_text("# Idea", encoding="utf-8")

        exit_code, output = _run_main(["status", "--vault", str(tmp_path)], tmp_path)

        assert exit_code == 0
        data = json.loads(output.strip())
        assert len(data["domains"]) == 1
        domain_entry = data["domains"][0]
        assert domain_entry["name"] == "my-domain"
        assert "total" in domain_entry
