"""Tests for CLI migrate-statuses subcommand (T-02, BL-122)."""

import importlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

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


def _create_idea(tmp_path: Path, domain: str, filename: str, content: str):
    """Create an idea .md file in the given domain."""
    ideas_dir = tmp_path / "wiki" / "domains" / domain / "ideas"
    ideas_dir.mkdir(parents=True, exist_ok=True)
    filepath = ideas_dir / filename
    filepath.write_text(content, encoding="utf-8")
    return filepath


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCliMigrateStatuses:

    def test_empty_vault_exits_0(self, tmp_path):
        """migrate-statuses on an empty vault exits 0."""
        exit_code, output = _run_main(
            ["migrate-statuses", "--vault", str(tmp_path)], tmp_path
        )
        assert exit_code == 0

    def test_empty_vault_returns_json_with_required_keys(self, tmp_path):
        """migrate-statuses outputs JSON with status, migrated, skipped, errors."""
        exit_code, output = _run_main(
            ["migrate-statuses", "--vault", str(tmp_path)], tmp_path
        )
        assert exit_code == 0
        data = json.loads(output.strip())
        assert data["status"] == "ok"
        assert data["migrated"] == 0
        assert data["skipped"] == 0
        assert data["errors"] == 0

    def test_migrates_legacy_status(self, tmp_path):
        """migrate-statuses converts legacy 'draft' to canonical status."""
        _create_idea(tmp_path, "test-domain", "idea-01.md",
                     "---\nstatus: draft\n---\n\n# Test Idea\n")
        exit_code, output = _run_main(
            ["migrate-statuses", "--vault", str(tmp_path)], tmp_path
        )
        assert exit_code == 0
        data = json.loads(output.strip())
        assert data["migrated"] == 1
        assert data["skipped"] == 0

        # Verify the detail entry
        migrated = [d for d in data["details"] if d["action"] == "migrate"]
        assert len(migrated) == 1
        assert migrated[0]["old_status"] == "draft"

    def test_skips_valid_status(self, tmp_path):
        """migrate-statuses skips files that already have a canonical status."""
        _create_idea(tmp_path, "test-domain", "idea-01.md",
                     "---\nstatus: \"\\u041D\\u043E\\u0432\\u0430\\u044F\"\n---\n\n# Test\n")
        exit_code, output = _run_main(
            ["migrate-statuses", "--vault", str(tmp_path)], tmp_path
        )
        assert exit_code == 0
        data = json.loads(output.strip())
        assert data["skipped"] == 1
        assert data["migrated"] == 0

    def test_dry_run_does_not_modify_files(self, tmp_path):
        """migrate-statuses --dry-run reports changes but does not modify files."""
        filepath = _create_idea(tmp_path, "test-domain", "idea-01.md",
                                "---\nstatus: draft\n---\n\n# Test\n")
        original_content = filepath.read_text(encoding="utf-8")

        exit_code, output = _run_main(
            ["migrate-statuses", "--vault", str(tmp_path), "--dry-run"], tmp_path
        )
        assert exit_code == 0
        data = json.loads(output.strip())
        assert data["migrated"] == 1

        # File should be unchanged
        assert filepath.read_text(encoding="utf-8") == original_content

    def test_dry_run_flag_accepted(self, tmp_path):
        """migrate-statuses accepts --dry-run flag without error."""
        exit_code, output = _run_main(
            ["migrate-statuses", "--vault", str(tmp_path), "--dry-run"], tmp_path
        )
        assert exit_code == 0

    def test_vault_flag_accepted(self, tmp_path):
        """migrate-statuses accepts --vault flag."""
        exit_code, output = _run_main(
            ["migrate-statuses", "--vault", str(tmp_path)], tmp_path
        )
        assert exit_code == 0
        data = json.loads(output.strip())
        assert data["status"] == "ok"

    def test_multiple_domains(self, tmp_path):
        """migrate-statuses processes ideas across multiple domains."""
        _create_idea(tmp_path, "alpha", "idea-a.md",
                     "---\nstatus: inbox\n---\n\n# Alpha Idea\n")
        _create_idea(tmp_path, "beta", "idea-b.md",
                     "---\nstatus: processed\n---\n\n# Beta Idea\n")

        exit_code, output = _run_main(
            ["migrate-statuses", "--vault", str(tmp_path)], tmp_path
        )
        assert exit_code == 0
        data = json.loads(output.strip())
        assert data["migrated"] == 2
        assert data["skipped"] == 0

    def test_unknown_status_counted(self, tmp_path):
        """migrate-statuses reports unknown statuses."""
        _create_idea(tmp_path, "test-domain", "idea-01.md",
                     "---\nstatus: some-invalid-status\n---\n\n# Test\n")
        exit_code, output = _run_main(
            ["migrate-statuses", "--vault", str(tmp_path)], tmp_path
        )
        assert exit_code == 0
        data = json.loads(output.strip())
        assert data["unknown_statuses"] == 1
        assert data["migrated"] == 0
