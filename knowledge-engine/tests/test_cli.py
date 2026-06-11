"""Tests for CLI domain/rebuild-index/jira-sync subcommands."""

import importlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reload_modules(tmp_path: Path):
    """Reload vault_paths and domain_manager so VAULT_PATH points to tmp_path."""
    with patch.dict(os.environ, {"VAULT_PATH": str(tmp_path)}):
        from app import vault_paths
        importlib.reload(vault_paths)
    from app import domain_manager
    importlib.reload(domain_manager)


def _run_main(argv: list[str], tmp_path: Path):
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


# ---------------------------------------------------------------------------
# domain create
# ---------------------------------------------------------------------------


class TestDomainCreate:
    def test_create_domain_ok(self, tmp_path):
        """domain create outputs JSON with status=ok and the domain path."""
        exit_code, output = _run_main(["domain", "--vault", str(tmp_path), "create", "test-domain"], tmp_path)

        assert exit_code == 0
        data = json.loads(output.strip())
        assert data["status"] == "ok"
        assert data["domain"] == "test-domain"
        assert "test-domain" in data["path"]
        # Verify the directory was actually created
        domain_dir = tmp_path / "wiki" / "domains" / "test-domain"
        assert domain_dir.is_dir()

    def test_create_domain_invalid_name_outputs_error_json(self, tmp_path):
        """domain create with an invalid name outputs JSON with status=error and exits 1."""
        exit_code, output = _run_main(
            ["domain", "--vault", str(tmp_path), "create", "Invalid_Name"], tmp_path
        )

        assert exit_code == 1
        data = json.loads(output.strip())
        assert data["status"] == "error"
        assert "message" in data
        assert len(data["message"]) > 0

    def test_create_domain_duplicate_outputs_error_json(self, tmp_path):
        """domain create on an existing domain outputs JSON with status=error and exits 1."""
        _reload_modules(tmp_path)
        # Pre-create the domain
        (tmp_path / "wiki" / "domains" / "existing-domain").mkdir(parents=True, exist_ok=True)

        exit_code, output = _run_main(
            ["domain", "--vault", str(tmp_path), "create", "existing-domain"], tmp_path
        )

        assert exit_code == 1
        data = json.loads(output.strip())
        assert data["status"] == "error"

    def test_create_domain_vault_flag(self, tmp_path):
        """domain create uses the --vault flag to set the vault root."""
        exit_code, output = _run_main(
            ["domain", "--vault", str(tmp_path), "create", "vault-flagged"], tmp_path
        )
        assert exit_code == 0
        domain_dir = tmp_path / "wiki" / "domains" / "vault-flagged"
        assert domain_dir.is_dir()


# ---------------------------------------------------------------------------
# domain list
# ---------------------------------------------------------------------------


class TestDomainList:
    def test_list_domains_empty_json(self, tmp_path):
        """domain list on an empty vault outputs JSON with empty domains list."""
        exit_code, output = _run_main(
            ["domain", "--vault", str(tmp_path), "list"], tmp_path
        )

        assert exit_code == 0
        data = json.loads(output.strip())
        assert data["status"] == "ok"
        assert data["domains"] == []
        assert data["count"] == 0

    def test_list_domains_json_format(self, tmp_path):
        """domain list returns correct JSON structure with domain entries."""
        _reload_modules(tmp_path)
        # Create domains using domain_manager
        (tmp_path / "wiki" / "domains" / "alpha" / "ideas").mkdir(parents=True, exist_ok=True)
        (tmp_path / "wiki" / "domains" / "beta" / "ideas").mkdir(parents=True, exist_ok=True)

        exit_code, output = _run_main(
            ["domain", "--vault", str(tmp_path), "list"], tmp_path
        )

        assert exit_code == 0
        data = json.loads(output.strip())
        assert data["status"] == "ok"
        assert data["count"] == 2
        names = [d["name"] for d in data["domains"]]
        assert "alpha" in names
        assert "beta" in names
        # Verify each entry has required keys
        for domain_entry in data["domains"]:
            assert "name" in domain_entry
            assert "total" in domain_entry
            assert "last_updated" in domain_entry

    def test_list_domains_table_format_contains_names(self, tmp_path):
        """domain list --format table prints domain names in the output."""
        _reload_modules(tmp_path)
        (tmp_path / "wiki" / "domains" / "my-domain" / "ideas").mkdir(parents=True, exist_ok=True)

        exit_code, output = _run_main(
            ["domain", "--vault", str(tmp_path), "list", "--format", "table"], tmp_path
        )

        assert exit_code == 0
        assert "my-domain" in output

    def test_list_domains_table_format_has_header(self, tmp_path):
        """domain list --format table output contains column headers."""
        exit_code, output = _run_main(
            ["domain", "--vault", str(tmp_path), "list", "--format", "table"], tmp_path
        )

        assert exit_code == 0
        # Header must contain at least Name and Total columns
        assert "Name" in output
        assert "Total" in output

    def test_list_domains_with_artifacts_json(self, tmp_path):
        """domain list JSON includes artifact counts per type."""
        _reload_modules(tmp_path)
        ideas_dir = tmp_path / "wiki" / "domains" / "counted" / "ideas"
        ideas_dir.mkdir(parents=True, exist_ok=True)
        (ideas_dir / "idea-01.md").write_text("# Idea 1", encoding="utf-8")
        (ideas_dir / "idea-02.md").write_text("# Idea 2", encoding="utf-8")

        exit_code, output = _run_main(
            ["domain", "--vault", str(tmp_path), "list"], tmp_path
        )

        assert exit_code == 0
        data = json.loads(output.strip())
        entry = next(d for d in data["domains"] if d["name"] == "counted")
        assert entry["ideas"] == 2
        assert entry["total"] == 2


# ---------------------------------------------------------------------------
# rebuild-index
# ---------------------------------------------------------------------------


class TestRebuildIndex:
    def _create_domain_scaffolding(self, tmp_path: Path, domain: str):
        """Create minimal domain directory structure for rebuild-index tests."""
        for artifact_type in ("ideas", "prds", "epics", "userstories", "tasks", "bugs"):
            artifact_dir = tmp_path / "wiki" / "domains" / domain / artifact_type
            artifact_dir.mkdir(parents=True, exist_ok=True)
            (artifact_dir / "index.md").write_text(
                f"---\ntype: index\ndomain: {domain}\nartifact_type: {artifact_type}\n---\n\n# {domain} — {artifact_type}\n\n| File | Title | Status | Created |\n|------|-------|--------|---------|",
                encoding="utf-8",
            )
            (artifact_dir / "log.md").write_text(
                f"---\ntype: log\ndomain: {domain}\nartifact_type: {artifact_type}\n---\n",
                encoding="utf-8",
            )

    def test_rebuild_index_single_domain(self, tmp_path):
        """rebuild-index <domain> rebuilds index for all artifact types of that domain."""
        self._create_domain_scaffolding(tmp_path, "single-domain")

        exit_code, output = _run_main(
            ["rebuild-index", "single-domain", "--vault", str(tmp_path)], tmp_path
        )

        assert exit_code == 0
        data = json.loads(output.strip())
        assert data["status"] == "ok"
        assert data["total_indices"] == 7  # one per artifact type
        domains_in_result = [r["domain"] for r in data["rebuilt"]]
        assert all(d == "single-domain" for d in domains_in_result)
        artifact_types_rebuilt = {r["artifact_type"] for r in data["rebuilt"]}
        assert artifact_types_rebuilt == {"ideas", "prds", "epics", "userstories", "tasks", "bugs", "knowledge"}

    def test_rebuild_index_all_domains(self, tmp_path):
        """rebuild-index without domain argument rebuilds index for ALL domains."""
        self._create_domain_scaffolding(tmp_path, "domain-a")
        self._create_domain_scaffolding(tmp_path, "domain-b")

        exit_code, output = _run_main(
            ["rebuild-index", "--vault", str(tmp_path)], tmp_path
        )

        assert exit_code == 0
        data = json.loads(output.strip())
        assert data["status"] == "ok"
        assert data["total_indices"] == 14  # 2 domains x 7 artifact types
        domains_rebuilt = {r["domain"] for r in data["rebuilt"]}
        assert "domain-a" in domains_rebuilt
        assert "domain-b" in domains_rebuilt

    def test_rebuild_index_no_domains_returns_ok(self, tmp_path):
        """rebuild-index with no domains in vault returns ok with empty rebuilt list."""
        exit_code, output = _run_main(
            ["rebuild-index", "--vault", str(tmp_path)], tmp_path
        )

        assert exit_code == 0
        data = json.loads(output.strip())
        assert data["status"] == "ok"
        assert data["rebuilt"] == []
        assert data["total_indices"] == 0

    def test_rebuild_index_entries_count(self, tmp_path):
        """rebuild-index reports correct entries count per artifact type."""
        self._create_domain_scaffolding(tmp_path, "counted-domain")
        ideas_dir = tmp_path / "wiki" / "domains" / "counted-domain" / "ideas"
        (ideas_dir / "idea-01.md").write_text(
            "---\nstatus: draft\n---\n\n# Idea One\n", encoding="utf-8"
        )
        (ideas_dir / "idea-02.md").write_text(
            "---\nstatus: draft\n---\n\n# Idea Two\n", encoding="utf-8"
        )

        exit_code, output = _run_main(
            ["rebuild-index", "counted-domain", "--vault", str(tmp_path)], tmp_path
        )

        assert exit_code == 0
        data = json.loads(output.strip())
        ideas_entry = next(r for r in data["rebuilt"] if r["artifact_type"] == "ideas")
        assert ideas_entry["entries"] == 2

    def test_rebuild_index_output_structure(self, tmp_path):
        """rebuild-index JSON output contains status, rebuilt list, and total_indices."""
        self._create_domain_scaffolding(tmp_path, "structure-test")

        exit_code, output = _run_main(
            ["rebuild-index", "structure-test", "--vault", str(tmp_path)], tmp_path
        )

        assert exit_code == 0
        data = json.loads(output.strip())
        assert "status" in data
        assert "rebuilt" in data
        assert "total_indices" in data
        for entry in data["rebuilt"]:
            assert "domain" in entry
            assert "artifact_type" in entry
            assert "entries" in entry


# ---------------------------------------------------------------------------
# jira-sync
# ---------------------------------------------------------------------------


def _run_jira_sync(argv: list[str], tmp_path: Path, sync_return: dict):
    """
    Invoke cli.main() with jira-sync args, mocking the sync() function.
    Returns (exit_code, stdout_text, mock_sync).
    """
    import io
    captured = io.StringIO()

    with patch.dict(os.environ, {"VAULT_PATH": str(tmp_path)}):
        with patch.object(sys, "argv", ["knowledge_engine"] + argv):
            with patch("app.jira_fetcher.fetcher.sync", return_value=sync_return) as mock_sync:
                from app import cli
                importlib.reload(cli)
                with patch("sys.stdout", captured):
                    try:
                        cli.main()
                        exit_code = 0
                    except SystemExit as e:
                        exit_code = e.code if isinstance(e.code, int) else 0

    return exit_code, captured.getvalue(), mock_sync


class TestJiraSync:
    def test_jira_sync_success(self, tmp_path):
        """jira-sync with ok result exits 0 and outputs JSON."""
        ok_result = {
            "status": "ok",
            "new": 3,
            "updated": 1,
            "closed": 0,
            "errors": 0,
            "details": [],
            "message": "Jira sync: 3 new, 1 updated, 0 closed",
        }
        exit_code, output, mock_sync = _run_jira_sync(
            ["jira-sync", "--vault", str(tmp_path)], tmp_path, ok_result
        )

        assert exit_code == 0
        data = json.loads(output.strip())
        assert data["status"] == "ok"
        assert data["new"] == 3
        assert data["updated"] == 1
        mock_sync.assert_called_once_with(str(tmp_path), notify=False, dry_run=False)

    def test_jira_sync_dry_run(self, tmp_path):
        """jira-sync --dry-run with skip result exits 0."""
        skip_result = {
            "status": "skip",
            "new": 2,
            "updated": 0,
            "closed": 1,
            "errors": 0,
            "details": [],
            "message": "Jira sync (dry-run): 2 new, 0 updated, 1 closed",
        }
        exit_code, output, mock_sync = _run_jira_sync(
            ["jira-sync", "--vault", str(tmp_path), "--dry-run"], tmp_path, skip_result
        )

        assert exit_code == 0
        data = json.loads(output.strip())
        assert data["status"] == "skip"
        mock_sync.assert_called_once_with(str(tmp_path), notify=False, dry_run=True)

    def test_jira_sync_error(self, tmp_path):
        """jira-sync with error result exits 1."""
        error_result = {
            "status": "error",
            "new": 0,
            "updated": 0,
            "closed": 0,
            "errors": 1,
            "details": [],
            "message": "Jira API error: connection refused",
        }
        exit_code, output, mock_sync = _run_jira_sync(
            ["jira-sync", "--vault", str(tmp_path)], tmp_path, error_result
        )

        assert exit_code == 1
        data = json.loads(output.strip())
        assert data["status"] == "error"
        assert data["errors"] == 1

    def test_jira_sync_passes_flags(self, tmp_path):
        """jira-sync forwards --notify and --dry-run to sync()."""
        ok_result = {
            "status": "ok",
            "new": 0,
            "updated": 0,
            "closed": 0,
            "errors": 0,
            "details": [],
            "message": "Jira sync: 0 new, 0 updated, 0 closed",
        }
        exit_code, output, mock_sync = _run_jira_sync(
            ["jira-sync", "--vault", str(tmp_path), "--notify", "--dry-run"],
            tmp_path,
            ok_result,
        )

        assert exit_code == 0
        mock_sync.assert_called_once_with(str(tmp_path), notify=True, dry_run=True)


# ---------------------------------------------------------------------------
# jira-issue-types
# ---------------------------------------------------------------------------


def _run_jira_issue_types(argv: list[str], tmp_path: Path, issue_types_return: list[dict] | Exception):
    """
    Invoke cli.main() with jira-issue-types args, mocking client.get_project_issue_types.
    Returns (exit_code, stdout_text, mock_func).
    """
    import io
    captured = io.StringIO()

    with patch.dict(os.environ, {"VAULT_PATH": str(tmp_path)}):
        with patch.object(sys, "argv", ["knowledge_engine"] + argv):
            if isinstance(issue_types_return, Exception):
                mock_fn = MagicMock(side_effect=issue_types_return)
            else:
                mock_fn = MagicMock(return_value=issue_types_return)
            with patch("app.jira_fetcher.client.get_project_issue_types", mock_fn):
                from app import cli
                importlib.reload(cli)
                with patch("sys.stdout", captured):
                    try:
                        cli.main()
                        exit_code = 0
                    except SystemExit as e:
                        exit_code = e.code if isinstance(e.code, int) else 0

    return exit_code, captured.getvalue(), mock_fn


class TestJiraIssueTypes:
    def test_jira_issue_types_success(self, tmp_path):
        """jira-issue-types with ok result exits 0 and outputs JSON."""
        types = [
            {"id": "10001", "name": "Task", "subtask": False},
            {"id": "10002", "name": "Bug", "subtask": False},
        ]
        exit_code, output, mock_fn = _run_jira_issue_types(
            ["jira-issue-types", "--project", "GO"], tmp_path, types
        )

        assert exit_code == 0
        data = json.loads(output.strip())
        assert data["status"] == "ok"
        assert len(data["issue_types"]) == 2
        assert data["issue_types"][0]["name"] == "Task"
        mock_fn.assert_called_once_with("GO")

    def test_jira_issue_types_empty(self, tmp_path):
        """jira-issue-types with no types returns empty list."""
        exit_code, output, mock_fn = _run_jira_issue_types(
            ["jira-issue-types", "--project", "EMPTY"], tmp_path, []
        )

        assert exit_code == 0
        data = json.loads(output.strip())
        assert data["status"] == "ok"
        assert data["issue_types"] == []
        mock_fn.assert_called_once_with("EMPTY")

    def test_jira_issue_types_error(self, tmp_path):
        """jira-issue-types on error exits 1 and outputs error JSON."""
        from app.jira_fetcher.client import JiraClientError
        exit_code, output, mock_fn = _run_jira_issue_types(
            ["jira-issue-types", "--project", "BAD"], tmp_path,
            JiraClientError("Jira resource not found: /rest/api/2/project/BAD")
        )

        assert exit_code == 1
        data = json.loads(output.strip())
        assert data["status"] == "error"
        assert "not found" in data["message"]
