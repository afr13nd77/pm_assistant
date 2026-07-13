"""Unit tests for BUG-023: Jira sync fallback for custom-named vault files.

Tests that the sync orchestrator correctly finds and updates vault files
whose names differ from the Jira key (e.g. E-15-retry-logic.md with
jira_key: TMPL-16260 in frontmatter).
"""

from unittest.mock import patch

import pytest

from app.jira_fetcher.fetcher import (
    _find_vault_file_by_jira_key,
    import_single_issue,
    sync,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_issue(
    key: str = "TMPL-16260",
    summary: str = "Retry logic import phases",
    status: str = "Ready for development",
    updated: str = "2026-07-13T12:00:00",
    issue_type: str = "Epic",
    project: str = "TMPL",
) -> dict:
    return {
        "key": key,
        "fields": {
            "summary": summary,
            "status": {"name": status},
            "assignee": {"displayName": "Test User"},
            "priority": {"name": "Medium"},
            "labels": ["r6"],
            "project": {"key": project},
            "description": "Test description",
            "created": "2026-06-01T10:00:00",
            "updated": updated,
            "issuetype": {"name": issue_type},
        },
    }


def _empty_state() -> dict:
    return {"version": 1, "last_sync": "", "issues": {}}


def _state_with_issues(*entries) -> dict:
    state = _empty_state()
    for key, status, updated, domain in entries:
        state["issues"][key] = {
            "status": status,
            "updated": updated,
            "domain": domain,
            "synced_at": "2026-07-12T10:00:00",
        }
    return state


def _write_custom_file(directory, filename, jira_key, status="todo"):
    """Write a custom-named .md file with jira_key in frontmatter."""
    directory.mkdir(parents=True, exist_ok=True)
    filepath = directory / filename
    content = (
        f"---\n"
        f"title: Test Epic\n"
        f"jira_key: {jira_key}\n"
        f"status: {status}\n"
        f"---\n"
        f"# Test Epic\n\n"
        f"## Goals\n\nUser-written content that must be preserved.\n"
    )
    filepath.write_text(content, encoding="utf-8")
    return filepath


@pytest.fixture
def jira_env(monkeypatch):
    monkeypatch.setenv("JIRA_URL", "https://jira.example.com")
    monkeypatch.setenv("JIRA_TOKEN", "test-token")


# ---------------------------------------------------------------------------
# T-01: _find_vault_file_by_jira_key
# ---------------------------------------------------------------------------

class TestFindVaultFileByJiraKey:

    @patch("app.jira_fetcher.fetcher.vault_paths")
    def test_find_by_jira_key_found(self, mock_vault_paths, tmp_path):
        """File with matching jira_key in frontmatter is found."""
        epics_dir = tmp_path / "wiki" / "domains" / "hotels" / "epics"
        custom_file = _write_custom_file(epics_dir, "E-15-retry-logic.md", "TMPL-16260")

        mock_vault_paths.wiki_domain_dir.return_value = epics_dir

        result = _find_vault_file_by_jira_key("hotels", "TMPL-16260", ("epics",))

        assert result is not None
        assert result == custom_file

    @patch("app.jira_fetcher.fetcher.vault_paths")
    def test_find_by_jira_key_not_found(self, mock_vault_paths, tmp_path):
        """No file has matching jira_key -> None."""
        epics_dir = tmp_path / "wiki" / "domains" / "hotels" / "epics"
        _write_custom_file(epics_dir, "E-15-retry-logic.md", "TMPL-99999")

        mock_vault_paths.wiki_domain_dir.return_value = epics_dir

        result = _find_vault_file_by_jira_key("hotels", "TMPL-16260", ("epics",))

        assert result is None

    @patch("app.jira_fetcher.fetcher.vault_paths")
    def test_find_by_jira_key_no_frontmatter(self, mock_vault_paths, tmp_path):
        """File without valid frontmatter is skipped without error."""
        epics_dir = tmp_path / "wiki" / "domains" / "hotels" / "epics"
        epics_dir.mkdir(parents=True)
        bad_file = epics_dir / "broken.md"
        bad_file.write_text("no frontmatter here", encoding="utf-8")

        mock_vault_paths.wiki_domain_dir.return_value = epics_dir

        result = _find_vault_file_by_jira_key("hotels", "TMPL-16260", ("epics",))

        assert result is None

    @patch("app.jira_fetcher.fetcher.vault_paths")
    def test_find_by_jira_key_empty_dir(self, mock_vault_paths, tmp_path):
        """Empty directory returns None."""
        epics_dir = tmp_path / "wiki" / "domains" / "hotels" / "epics"
        epics_dir.mkdir(parents=True)

        mock_vault_paths.wiki_domain_dir.return_value = epics_dir

        result = _find_vault_file_by_jira_key("hotels", "TMPL-16260", ("epics",))

        assert result is None

    @patch("app.jira_fetcher.fetcher.vault_paths")
    def test_find_by_jira_key_dir_not_exists(self, mock_vault_paths, tmp_path):
        """Non-existent directory is skipped."""
        nonexistent = tmp_path / "wiki" / "domains" / "hotels" / "epics"
        mock_vault_paths.wiki_domain_dir.return_value = nonexistent

        result = _find_vault_file_by_jira_key("hotels", "TMPL-16260", ("epics",))

        assert result is None

    @patch("app.jira_fetcher.fetcher.vault_paths")
    def test_find_scans_multiple_artifact_types(self, mock_vault_paths, tmp_path):
        """Search across multiple artifact types, find in second one."""
        tasks_dir = tmp_path / "wiki" / "domains" / "hotels" / "tasks"
        tasks_dir.mkdir(parents=True)

        epics_dir = tmp_path / "wiki" / "domains" / "hotels" / "epics"
        custom_file = _write_custom_file(epics_dir, "E-15-retry-logic.md", "TMPL-16260")

        def _wiki_domain_dir(domain, art_type):
            return tmp_path / "wiki" / "domains" / domain / art_type

        mock_vault_paths.wiki_domain_dir.side_effect = _wiki_domain_dir

        result = _find_vault_file_by_jira_key("hotels", "TMPL-16260", ("tasks", "epics"))

        assert result is not None
        assert result == custom_file


# ---------------------------------------------------------------------------
# T-02: UPDATED issues fallback (section 6)
# ---------------------------------------------------------------------------

class TestSyncUpdatedFallback:

    @patch("app.jira_fetcher.fetcher.send_telegram")
    @patch("app.jira_fetcher.fetcher.append_domain_log")
    @patch("app.jira_fetcher.fetcher.update_domain_index")
    @patch("app.jira_fetcher.fetcher.atomic_write")
    @patch("app.jira_fetcher.fetcher.vault_paths")
    @patch("app.jira_fetcher.fetcher.sync_state")
    @patch("app.jira_fetcher.fetcher.search")
    def test_updated_flow_fallback_custom_file(
        self,
        mock_search,
        mock_sync_state,
        mock_vault_paths,
        mock_atomic_write,
        mock_update_index,
        mock_append_log,
        mock_telegram,
        tmp_path,
        jira_env,
    ):
        """UPDATED issue: {KEY}.md does not exist, custom file found -> partial update."""
        issue = _make_issue(key="TMPL-16260", status="In Progress")
        mock_search.return_value = [issue]

        state = _state_with_issues(
            ("TMPL-16260", "todo", "2026-07-12T10:00:00", "general"),
        )
        state["issues"]["TMPL-16260"]["artifact_type"] = "epics"
        mock_sync_state.load.return_value = state
        mock_sync_state.diff.return_value = ([], [issue], [])

        def _wiki_domain_dir(domain, art_type):
            d = tmp_path / "wiki" / "domains" / domain / art_type
            d.mkdir(parents=True, exist_ok=True)
            return d

        mock_vault_paths.wiki_domain_dir.side_effect = _wiki_domain_dir

        epics_dir = _wiki_domain_dir("general", "epics")
        custom_file = _write_custom_file(
            epics_dir, "E-15-retry-logic.md", "TMPL-16260", status="todo",
        )

        result = sync(str(tmp_path))

        assert result["status"] == "ok"
        assert result["updated"] == 1
        assert result["errors"] == 0

        updated_content = custom_file.read_text(encoding="utf-8")
        assert "User-written content that must be preserved" in updated_content
        assert "status: in-progress" in updated_content or "status: todo" in updated_content.replace("in-progress", "")

        assert not (epics_dir / "TMPL-16260.md").exists()

    @patch("app.jira_fetcher.fetcher.send_telegram")
    @patch("app.jira_fetcher.fetcher.append_domain_log")
    @patch("app.jira_fetcher.fetcher.update_domain_index")
    @patch("app.jira_fetcher.fetcher.atomic_write")
    @patch("app.jira_fetcher.fetcher.vault_paths")
    @patch("app.jira_fetcher.fetcher.sync_state")
    @patch("app.jira_fetcher.fetcher.search")
    def test_updated_flow_standard_no_regression(
        self,
        mock_search,
        mock_sync_state,
        mock_vault_paths,
        mock_atomic_write,
        mock_update_index,
        mock_append_log,
        mock_telegram,
        tmp_path,
        jira_env,
    ):
        """UPDATED issue: {KEY}.md exists -> standard behavior (no fallback scan)."""
        issue = _make_issue(key="GO-200", status="In Progress", issue_type="Task", project="GO")
        mock_search.return_value = [issue]

        state = _state_with_issues(
            ("GO-200", "todo", "2026-07-12T10:00:00", "general"),
        )
        mock_sync_state.load.return_value = state
        mock_sync_state.diff.return_value = ([], [issue], [])

        wiki_dir = tmp_path / "wiki" / "domains" / "general" / "tasks"
        wiki_dir.mkdir(parents=True)
        mock_vault_paths.wiki_domain_dir.return_value = wiki_dir

        wiki_file = wiki_dir / "GO-200.md"
        wiki_file.write_text("---\nstatus: todo\n---\n# GO-200\n", encoding="utf-8")

        result = sync(str(tmp_path))

        assert result["status"] == "ok"
        assert result["updated"] == 1
        assert result["errors"] == 0

        assert mock_atomic_write.call_count == 1


# ---------------------------------------------------------------------------
# T-03: CLOSED issues fallback (section 7)
# ---------------------------------------------------------------------------

class TestSyncClosedFallback:

    @patch("app.jira_fetcher.fetcher.send_telegram")
    @patch("app.jira_fetcher.fetcher.append_domain_log")
    @patch("app.jira_fetcher.fetcher.update_domain_index")
    @patch("app.jira_fetcher.fetcher.atomic_write")
    @patch("app.jira_fetcher.fetcher.vault_paths")
    @patch("app.jira_fetcher.fetcher.sync_state")
    @patch("app.jira_fetcher.fetcher.search")
    def test_closed_flow_fallback_custom_file(
        self,
        mock_search,
        mock_sync_state,
        mock_vault_paths,
        mock_atomic_write,
        mock_update_index,
        mock_append_log,
        mock_telegram,
        tmp_path,
        jira_env,
    ):
        """CLOSED issue: {KEY}.md does not exist, custom file found -> status updated."""
        mock_search.return_value = []

        state = _empty_state()
        state["issues"]["TMPL-16260"] = {
            "status": "todo",
            "updated": "2026-07-12T10:00:00",
            "domain": "general",
            "synced_at": "2026-07-12T10:00:00",
            "artifact_type": "epics",
        }
        mock_sync_state.load.return_value = state
        mock_sync_state.diff.return_value = ([], [], ["TMPL-16260"])

        def _wiki_domain_dir(domain, art_type):
            d = tmp_path / "wiki" / "domains" / domain / art_type
            d.mkdir(parents=True, exist_ok=True)
            return d

        mock_vault_paths.wiki_domain_dir.side_effect = _wiki_domain_dir

        epics_dir = _wiki_domain_dir("general", "epics")
        custom_file = _write_custom_file(
            epics_dir, "E-15-retry-logic.md", "TMPL-16260", status="todo",
        )

        result = sync(str(tmp_path))

        assert result["status"] == "ok"
        assert result["closed"] == 1
        assert result["errors"] == 0

        assert mock_atomic_write.call_count >= 1
        written_content = mock_atomic_write.call_args[0][1]
        assert "status: done" in written_content


# ---------------------------------------------------------------------------
# T-04: import_single_issue fallback
# ---------------------------------------------------------------------------

class TestImportSingleIssueFallback:

    @patch("app.jira_fetcher.fetcher.send_telegram", create=True)
    @patch("app.jira_fetcher.fetcher.sync_state")
    @patch("app.jira_fetcher.fetcher.append_domain_log")
    @patch("app.jira_fetcher.fetcher.update_domain_index")
    @patch("app.jira_fetcher.fetcher.atomic_write")
    @patch("app.jira_fetcher.fetcher.vault_paths")
    @patch("app.jira_fetcher.fetcher.get_issue")
    def test_import_fallback_custom_file(
        self,
        mock_get_issue,
        mock_vault_paths,
        mock_atomic_write,
        mock_update_index,
        mock_append_log,
        mock_sync_state,
        mock_telegram,
        tmp_path,
        jira_env,
    ):
        """import_single_issue: custom file found -> update, no duplicate created."""
        issue = _make_issue(key="TMPL-16260", status="In Progress")
        mock_get_issue.return_value = issue

        raw_dir = tmp_path / "raw" / "inbound" / "tasks"
        raw_dir.mkdir(parents=True)
        mock_vault_paths.raw_tasks.return_value = raw_dir

        def _wiki_domain_dir(domain, art_type):
            d = tmp_path / "wiki" / "domains" / domain / art_type
            d.mkdir(parents=True, exist_ok=True)
            return d

        mock_vault_paths.wiki_domain_dir.side_effect = _wiki_domain_dir

        epics_dir = _wiki_domain_dir("general", "epics")
        custom_file = _write_custom_file(
            epics_dir, "E-15-retry-logic.md", "TMPL-16260", status="todo",
        )

        st = _empty_state()
        mock_sync_state.load.return_value = st

        result = import_single_issue("TMPL-16260", str(tmp_path))

        assert result["status"] == "ok"
        assert result["action"] == "update"

        updated_content = custom_file.read_text(encoding="utf-8")
        assert "User-written content that must be preserved" in updated_content

        assert not (epics_dir / "TMPL-16260.md").exists()

    @patch("app.jira_fetcher.fetcher.send_telegram", create=True)
    @patch("app.jira_fetcher.fetcher.sync_state")
    @patch("app.jira_fetcher.fetcher.append_domain_log")
    @patch("app.jira_fetcher.fetcher.update_domain_index")
    @patch("app.jira_fetcher.fetcher.atomic_write")
    @patch("app.jira_fetcher.fetcher.vault_paths")
    @patch("app.jira_fetcher.fetcher.get_issue")
    def test_import_standard_no_regression(
        self,
        mock_get_issue,
        mock_vault_paths,
        mock_atomic_write,
        mock_update_index,
        mock_append_log,
        mock_sync_state,
        mock_telegram,
        tmp_path,
        jira_env,
    ):
        """import_single_issue: {KEY}.md exists -> standard flow, no fallback."""
        issue = _make_issue(key="GO-123", status="To Do", issue_type="Task", project="GO")
        mock_get_issue.return_value = issue

        raw_dir = tmp_path / "raw" / "inbound" / "tasks"
        raw_dir.mkdir(parents=True)
        mock_vault_paths.raw_tasks.return_value = raw_dir

        wiki_dir = tmp_path / "wiki" / "domains" / "general" / "tasks"
        wiki_dir.mkdir(parents=True)
        mock_vault_paths.wiki_domain_dir.return_value = wiki_dir

        wiki_file = wiki_dir / "GO-123.md"
        wiki_file.write_text("---\nstatus: todo\n---\n# GO-123\n", encoding="utf-8")

        st = _empty_state()
        mock_sync_state.load.return_value = st

        result = import_single_issue("GO-123", str(tmp_path))

        assert result["status"] == "ok"
        assert result["action"] == "update"
        assert mock_atomic_write.call_count == 1
