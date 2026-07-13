"""Unit tests for app.jira_fetcher.fetcher (sync orchestrator)."""

from unittest.mock import patch

import pytest

from app.jira_fetcher.client import JiraClientError
from app.jira_fetcher.fetcher import _error_result, import_single_issue, sync

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_issue(
    key: str = "GO-123",
    summary: str = "Test task",
    status: str = "To Do",
    assignee: str = "Тестов Тест",
    labels: list | None = None,
    updated: str = "2026-05-01T12:00:00",
    project: str = "GO",
    description: str = "Test description",
    created: str = "2026-04-20T10:00:00",
    priority: str = "Medium",
    issue_type: str = "Task",
) -> dict:
    """Build a realistic Jira issue dict for testing."""
    return {
        "key": key,
        "fields": {
            "summary": summary,
            "status": {"name": status},
            "assignee": {"displayName": assignee},
            "priority": {"name": priority},
            "labels": labels if labels is not None else ["r6"],
            "project": {"key": project},
            "description": description,
            "created": created,
            "updated": updated,
            "issuetype": {"name": issue_type},
        },
    }


def _empty_state() -> dict:
    """Return a fresh empty state dict."""
    return {"version": 1, "last_sync": "", "issues": {}}


def _state_with_issues(*entries) -> dict:
    """Build a state dict with pre-populated issues.

    Each entry is a tuple (key, status, updated, domain).
    """
    state = _empty_state()
    for key, status, updated, domain in entries:
        state["issues"][key] = {
            "status": status,
            "updated": updated,
            "domain": domain,
            "synced_at": "2026-04-30T10:00:00",
        }
    return state


@pytest.fixture
def jira_env(monkeypatch):
    """Set JIRA_URL (and JIRA_TOKEN for completeness) in the environment."""
    monkeypatch.setenv("JIRA_URL", "https://jira.example.com")
    monkeypatch.setenv("JIRA_TOKEN", "test-token")


# ---------------------------------------------------------------------------
# _error_result
# ---------------------------------------------------------------------------

class TestErrorResult:
    def test_returns_error_dict(self):
        result = _error_result("something broke")
        assert result["status"] == "error"
        assert result["errors"] == 1
        assert result["new"] == 0
        assert result["updated"] == 0
        assert result["closed"] == 0
        assert result["details"] == []
        assert "something broke" in result["message"]


# ---------------------------------------------------------------------------
# sync() tests
# ---------------------------------------------------------------------------

class TestSyncNewIssues:
    """test_sync_new_issues: search returns 2 issues not in state."""

    @patch("app.jira_fetcher.fetcher.send_telegram")
    @patch("app.jira_fetcher.fetcher.append_domain_log")
    @patch("app.jira_fetcher.fetcher.update_domain_index")
    @patch("app.jira_fetcher.fetcher.atomic_write")
    @patch("app.jira_fetcher.fetcher.vault_paths")
    @patch("app.jira_fetcher.fetcher.sync_state")
    @patch("app.jira_fetcher.fetcher.search")
    def test_sync_new_issues(
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
        issue1 = _make_issue(key="GO-101", summary="First task", labels=["r6"])
        issue2 = _make_issue(key="GO-102", summary="Second task", labels=["r6", "suggester"])

        mock_search.return_value = [issue1, issue2]
        mock_sync_state.load.return_value = _empty_state()
        mock_sync_state.diff.return_value = ([issue1, issue2], [], [])

        raw_dir = tmp_path / "raw" / "inbound" / "tasks"
        raw_dir.mkdir(parents=True)
        mock_vault_paths.raw_tasks.return_value = raw_dir

        wiki_dir = tmp_path / "wiki" / "domains" / "general" / "tasks"
        wiki_dir.mkdir(parents=True)
        mock_vault_paths.wiki_domain_dir.return_value = wiki_dir

        result = sync(str(tmp_path))

        assert result["status"] == "ok"
        assert result["new"] == 2
        assert result["updated"] == 0
        assert result["closed"] == 0
        assert result["errors"] == 0
        assert len(result["details"]) == 2

        # Each new issue writes to raw/ AND wiki/ = 2 writes per issue = 4 total
        assert mock_atomic_write.call_count == 4

        # State updated for both issues
        assert mock_sync_state.update_entry.call_count == 2

        # State saved once at the end
        mock_sync_state.save.assert_called_once()

        # Domain index/log updated for each issue
        assert mock_update_index.call_count == 2
        assert mock_append_log.call_count == 2


class TestSyncUpdatedIssues:
    """test_sync_updated_issues: issues in state with different updated timestamp."""

    @patch("app.jira_fetcher.fetcher.send_telegram")
    @patch("app.jira_fetcher.fetcher.append_domain_log")
    @patch("app.jira_fetcher.fetcher.update_domain_index")
    @patch("app.jira_fetcher.fetcher.atomic_write")
    @patch("app.jira_fetcher.fetcher.vault_paths")
    @patch("app.jira_fetcher.fetcher.sync_state")
    @patch("app.jira_fetcher.fetcher.search")
    def test_sync_updated_issues(
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
        issue = _make_issue(
            key="GO-200",
            summary="Updated task",
            status="In Progress",
            updated="2026-05-01T14:00:00",
        )
        mock_search.return_value = [issue]

        state = _state_with_issues(
            ("GO-200", "todo", "2026-05-01T12:00:00", "general"),
        )
        mock_sync_state.load.return_value = state
        mock_sync_state.diff.return_value = ([], [issue], [])

        wiki_dir = tmp_path / "wiki" / "domains" / "general" / "tasks"
        wiki_dir.mkdir(parents=True)
        mock_vault_paths.wiki_domain_dir.return_value = wiki_dir

        # Simulate existing wiki file
        wiki_file = wiki_dir / "GO-200.md"
        wiki_file.write_text("---\nstatus: todo\n---\n# GO-200\n", encoding="utf-8")

        result = sync(str(tmp_path))

        assert result["status"] == "ok"
        assert result["new"] == 0
        assert result["updated"] == 1
        assert result["closed"] == 0
        assert result["errors"] == 0

        # Updated issue writes to wiki/ only (NOT raw/) = 1 write
        assert mock_atomic_write.call_count == 1

        # State updated
        mock_sync_state.update_entry.assert_called_once()

        # State saved
        mock_sync_state.save.assert_called_once()


class TestSyncClosedIssues:
    """test_sync_closed_issues: issues in state but not in search results."""

    @patch("app.jira_fetcher.fetcher.send_telegram")
    @patch("app.jira_fetcher.fetcher.append_domain_log")
    @patch("app.jira_fetcher.fetcher.update_domain_index")
    @patch("app.jira_fetcher.fetcher.atomic_write")
    @patch("app.jira_fetcher.fetcher.vault_paths")
    @patch("app.jira_fetcher.fetcher.sync_state")
    @patch("app.jira_fetcher.fetcher.search")
    def test_sync_closed_issues(
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
        # No issues returned from Jira
        mock_search.return_value = []

        state = _state_with_issues(
            ("GO-300", "in-progress", "2026-04-28T10:00:00", "suggester"),
        )
        mock_sync_state.load.return_value = state
        mock_sync_state.diff.return_value = ([], [], ["GO-300"])

        # Build distinct directories per artifact_type so only "tasks" has the file
        def _wiki_domain_dir(domain, art):
            d = tmp_path / "wiki" / "domains" / domain / art
            d.mkdir(parents=True, exist_ok=True)
            return d

        mock_vault_paths.wiki_domain_dir.side_effect = _wiki_domain_dir

        wiki_dir = _wiki_domain_dir("suggester", "tasks")

        # Create existing wiki file with status: in-progress
        wiki_file = wiki_dir / "GO-300.md"
        wiki_file.write_text(
            "---\nstatus: in-progress\n---\n# GO-300: Some task\n",
            encoding="utf-8",
        )

        result = sync(str(tmp_path))

        assert result["status"] == "ok"
        assert result["new"] == 0
        assert result["updated"] == 0
        assert result["closed"] == 1
        assert result["errors"] == 0

        # mark_closed called for the key
        mock_sync_state.mark_closed.assert_called_once_with(state, "GO-300")

        # Wiki file rewritten with status: done (only in tasks/ where the file exists)
        assert mock_atomic_write.call_count == 1
        written_content = mock_atomic_write.call_args[0][1]
        assert "status: done" in written_content
        assert "status: in-progress" not in written_content

        # State saved
        mock_sync_state.save.assert_called_once()


class TestSyncDryRun:
    """test_sync_dry_run: dry_run=True, no files written, counts returned."""

    @patch("app.jira_fetcher.fetcher.send_telegram")
    @patch("app.jira_fetcher.fetcher.atomic_write")
    @patch("app.jira_fetcher.fetcher.sync_state")
    @patch("app.jira_fetcher.fetcher.search")
    def test_sync_dry_run(
        self,
        mock_search,
        mock_sync_state,
        mock_atomic_write,
        mock_telegram,
        tmp_path,
        jira_env,
    ):
        issue = _make_issue(key="GO-400")
        mock_search.return_value = [issue]
        mock_sync_state.load.return_value = _empty_state()
        mock_sync_state.diff.return_value = ([issue], [], [])

        result = sync(str(tmp_path), dry_run=True)

        assert result["status"] == "skip"
        assert result["new"] == 1
        assert result["updated"] == 0
        assert result["closed"] == 0
        assert result["errors"] == 0

        # No files written
        mock_atomic_write.assert_not_called()

        # State NOT saved
        mock_sync_state.save.assert_not_called()

        # No notifications
        mock_telegram.assert_not_called()


class TestSyncJiraError:
    """test_sync_jira_error: search raises JiraClientError."""

    @patch("app.jira_fetcher.fetcher.send_telegram")
    @patch("app.jira_fetcher.fetcher.sync_state")
    @patch("app.jira_fetcher.fetcher.search")
    def test_sync_jira_error(
        self,
        mock_search,
        mock_sync_state,
        mock_telegram,
        tmp_path,
        jira_env,
    ):
        mock_sync_state.load.return_value = _empty_state()
        mock_search.side_effect = JiraClientError("Connection refused")

        result = sync(str(tmp_path))

        assert result["status"] == "error"
        assert result["errors"] == 1
        assert "Connection refused" in result["message"]

        # State NOT saved on Jira error
        mock_sync_state.save.assert_not_called()

    @patch("app.jira_fetcher.fetcher.send_telegram")
    @patch("app.jira_fetcher.fetcher.sync_state")
    @patch("app.jira_fetcher.fetcher.search")
    def test_sync_jira_error_with_notify(
        self,
        mock_search,
        mock_sync_state,
        mock_telegram,
        tmp_path,
        jira_env,
    ):
        mock_sync_state.load.return_value = _empty_state()
        mock_search.side_effect = JiraClientError("Timeout")

        result = sync(str(tmp_path), notify=True)

        assert result["status"] == "error"

        # Notification sent on error when notify=True
        mock_telegram.assert_called_once()
        call_args = mock_telegram.call_args
        assert "Timeout" in call_args[0][0]
        assert call_args[1].get("parse_mode") is None


class TestSyncNotify:
    """test_sync_notify: notify=True sends Telegram summary."""

    @patch("app.jira_fetcher.fetcher.send_telegram")
    @patch("app.jira_fetcher.fetcher.append_domain_log")
    @patch("app.jira_fetcher.fetcher.update_domain_index")
    @patch("app.jira_fetcher.fetcher.atomic_write")
    @patch("app.jira_fetcher.fetcher.vault_paths")
    @patch("app.jira_fetcher.fetcher.sync_state")
    @patch("app.jira_fetcher.fetcher.search")
    def test_sync_notify(
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
        issue = _make_issue(key="GO-500")
        mock_search.return_value = [issue]
        mock_sync_state.load.return_value = _empty_state()
        mock_sync_state.diff.return_value = ([issue], [], [])

        raw_dir = tmp_path / "raw" / "inbound" / "tasks"
        raw_dir.mkdir(parents=True)
        mock_vault_paths.raw_tasks.return_value = raw_dir

        wiki_dir = tmp_path / "wiki" / "domains" / "general" / "tasks"
        wiki_dir.mkdir(parents=True)
        mock_vault_paths.wiki_domain_dir.return_value = wiki_dir

        result = sync(str(tmp_path), notify=True)

        assert result["status"] == "ok"

        # send_telegram called once with summary, parse_mode=None
        mock_telegram.assert_called_once()
        call_args = mock_telegram.call_args
        summary_text = call_args[0][0]
        assert "1 new" in summary_text
        assert call_args[1].get("parse_mode") is None


class TestSyncPartialFailure:
    """test_sync_partial_failure: one issue fails, others still processed."""

    @patch("app.jira_fetcher.fetcher.send_telegram")
    @patch("app.jira_fetcher.fetcher.append_domain_log")
    @patch("app.jira_fetcher.fetcher.update_domain_index")
    @patch("app.jira_fetcher.fetcher.atomic_write")
    @patch("app.jira_fetcher.fetcher.to_markdown")
    @patch("app.jira_fetcher.fetcher.vault_paths")
    @patch("app.jira_fetcher.fetcher.sync_state")
    @patch("app.jira_fetcher.fetcher.search")
    def test_sync_partial_failure(
        self,
        mock_search,
        mock_sync_state,
        mock_vault_paths,
        mock_to_markdown,
        mock_atomic_write,
        mock_update_index,
        mock_append_log,
        mock_telegram,
        tmp_path,
        jira_env,
    ):
        issue1 = _make_issue(key="GO-601", summary="Good task")
        issue2 = _make_issue(key="GO-602", summary="Bad task")

        mock_search.return_value = [issue1, issue2]
        mock_sync_state.load.return_value = _empty_state()
        mock_sync_state.diff.return_value = ([issue1, issue2], [], [])

        raw_dir = tmp_path / "raw" / "inbound" / "tasks"
        raw_dir.mkdir(parents=True)
        mock_vault_paths.raw_tasks.return_value = raw_dir

        wiki_dir = tmp_path / "wiki" / "domains" / "general" / "tasks"
        wiki_dir.mkdir(parents=True)
        mock_vault_paths.wiki_domain_dir.return_value = wiki_dir

        # to_markdown succeeds for first, raises for second
        call_count = {"n": 0}

        def to_markdown_side_effect(issue, jira_url):
            call_count["n"] += 1
            if issue["key"] == "GO-602":
                raise ValueError("Simulated mapper error")
            return f"---\nstatus: todo\n---\n# {issue['key']}\n"

        mock_to_markdown.side_effect = to_markdown_side_effect

        result = sync(str(tmp_path))

        assert result["status"] == "error"
        assert result["new"] == 2  # still counts all new from diff
        assert result["errors"] >= 1

        # First issue processed successfully (2 writes: raw + wiki)
        assert mock_atomic_write.call_count == 2

        # State should still be saved (partial success)
        mock_sync_state.save.assert_called_once()

        # Details contain both success and error entries
        assert any("GO-601" in d and "NEW" in d for d in result["details"])
        assert any("GO-602" in d and "ERROR" in d for d in result["details"])


class TestSyncMissingJiraUrl:
    """test_sync_missing_jira_url: JIRA_URL not set returns error."""

    @patch("app.jira_fetcher.fetcher.send_telegram")
    @patch("app.jira_fetcher.fetcher.sync_state")
    @patch("app.jira_fetcher.fetcher.search")
    def test_sync_missing_jira_url(
        self,
        mock_search,
        mock_sync_state,
        mock_telegram,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.delenv("JIRA_URL", raising=False)

        result = sync(str(tmp_path))

        assert result["status"] == "error"
        assert result["errors"] == 1
        assert "JIRA_URL" in result["message"]

        # search never called
        mock_search.assert_not_called()

        # State never loaded or saved
        mock_sync_state.load.assert_not_called()
        mock_sync_state.save.assert_not_called()

    @patch("app.jira_fetcher.fetcher.send_telegram")
    @patch("app.jira_fetcher.fetcher.sync_state")
    @patch("app.jira_fetcher.fetcher.search")
    def test_sync_missing_jira_url_with_notify(
        self,
        mock_search,
        mock_sync_state,
        mock_telegram,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.delenv("JIRA_URL", raising=False)

        result = sync(str(tmp_path), notify=True)

        assert result["status"] == "error"
        mock_telegram.assert_called_once()
        assert "JIRA_URL" in mock_telegram.call_args[0][0]


class TestSyncEmptyResults:
    """test_sync_empty_results: search returns empty list."""

    @patch("app.jira_fetcher.fetcher.send_telegram")
    @patch("app.jira_fetcher.fetcher.append_domain_log")
    @patch("app.jira_fetcher.fetcher.update_domain_index")
    @patch("app.jira_fetcher.fetcher.atomic_write")
    @patch("app.jira_fetcher.fetcher.vault_paths")
    @patch("app.jira_fetcher.fetcher.sync_state")
    @patch("app.jira_fetcher.fetcher.search")
    def test_sync_empty_results_no_state(
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
        """Empty search results with empty state: nothing to do."""
        mock_search.return_value = []
        mock_sync_state.load.return_value = _empty_state()
        mock_sync_state.diff.return_value = ([], [], [])

        result = sync(str(tmp_path))

        assert result["status"] == "ok"
        assert result["new"] == 0
        assert result["updated"] == 0
        assert result["closed"] == 0
        assert result["errors"] == 0

        # No files written
        mock_atomic_write.assert_not_called()

        # State still saved (to update last_sync)
        mock_sync_state.save.assert_called_once()

    @patch("app.jira_fetcher.fetcher.send_telegram")
    @patch("app.jira_fetcher.fetcher.append_domain_log")
    @patch("app.jira_fetcher.fetcher.update_domain_index")
    @patch("app.jira_fetcher.fetcher.atomic_write")
    @patch("app.jira_fetcher.fetcher.vault_paths")
    @patch("app.jira_fetcher.fetcher.sync_state")
    @patch("app.jira_fetcher.fetcher.search")
    def test_sync_empty_results_with_existing_state(
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
        """Empty search results with populated state: everything is closed."""
        mock_search.return_value = []

        state = _state_with_issues(
            ("GO-800", "todo", "2026-04-25T10:00:00", "general"),
        )
        mock_sync_state.load.return_value = state
        mock_sync_state.diff.return_value = ([], [], ["GO-800"])

        wiki_dir = tmp_path / "wiki" / "domains" / "general" / "tasks"
        wiki_dir.mkdir(parents=True)
        mock_vault_paths.wiki_domain_dir.return_value = wiki_dir

        # Create wiki file for the closing issue
        wiki_file = wiki_dir / "GO-800.md"
        wiki_file.write_text(
            "---\nstatus: todo\n---\n# GO-800\n", encoding="utf-8"
        )

        result = sync(str(tmp_path))

        assert result["status"] == "ok"
        assert result["closed"] == 1
        mock_sync_state.mark_closed.assert_called_once_with(state, "GO-800")


class TestSyncDomainIndexFailureNonfatal:
    """test_sync_domain_index_failure_nonfatal: index error doesn't break sync."""

    @patch("app.jira_fetcher.fetcher.send_telegram")
    @patch("app.jira_fetcher.fetcher.append_domain_log")
    @patch("app.jira_fetcher.fetcher.update_domain_index")
    @patch("app.jira_fetcher.fetcher.atomic_write")
    @patch("app.jira_fetcher.fetcher.vault_paths")
    @patch("app.jira_fetcher.fetcher.sync_state")
    @patch("app.jira_fetcher.fetcher.search")
    def test_sync_domain_index_failure_nonfatal(
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
        issue = _make_issue(key="GO-900")
        mock_search.return_value = [issue]
        mock_sync_state.load.return_value = _empty_state()
        mock_sync_state.diff.return_value = ([issue], [], [])

        raw_dir = tmp_path / "raw" / "inbound" / "tasks"
        raw_dir.mkdir(parents=True)
        mock_vault_paths.raw_tasks.return_value = raw_dir

        wiki_dir = tmp_path / "wiki" / "domains" / "general" / "tasks"
        wiki_dir.mkdir(parents=True)
        mock_vault_paths.wiki_domain_dir.return_value = wiki_dir

        # Make update_domain_index raise
        mock_update_index.side_effect = RuntimeError("Index rebuild failed")

        result = sync(str(tmp_path))

        # Sync still succeeds overall
        assert result["status"] == "ok"
        assert result["new"] == 1
        assert result["errors"] == 0

        # Files were written despite index failure
        assert mock_atomic_write.call_count == 2  # raw + wiki

        # State updated and saved
        mock_sync_state.update_entry.assert_called_once()
        mock_sync_state.save.assert_called_once()

        # The update_domain_index was called and raised
        mock_update_index.assert_called_once()


# ---------------------------------------------------------------------------
# Artifact type routing tests
# ---------------------------------------------------------------------------

class TestSyncArtifactTypeRouting:
    """Verify that sync routes wiki files to the correct artifact folder."""

    def _run_sync_with_issue_type(self, issue_type: str, expected_folder: str, tmp_path, monkeypatch):
        monkeypatch.setenv("JIRA_URL", "https://jira.example.com")
        monkeypatch.setenv("JIRA_TOKEN", "test-token")

        issue = _make_issue(key="GO-777", issue_type=issue_type)

        with (
            patch("app.jira_fetcher.fetcher.search") as mock_search,
            patch("app.jira_fetcher.fetcher.sync_state") as mock_sync_state,
            patch("app.jira_fetcher.fetcher.vault_paths") as mock_vault_paths,
            patch("app.jira_fetcher.fetcher.atomic_write"),
            patch("app.jira_fetcher.fetcher.update_domain_index"),
            patch("app.jira_fetcher.fetcher.append_domain_log"),
            patch("app.jira_fetcher.fetcher.send_telegram"),
        ):
            mock_search.return_value = [issue]
            mock_sync_state.load.return_value = _empty_state()
            mock_sync_state.diff.return_value = ([issue], [], [])

            raw_dir = tmp_path / "raw" / "inbound" / "tasks"
            raw_dir.mkdir(parents=True)
            mock_vault_paths.raw_tasks.return_value = raw_dir

            wiki_dir = tmp_path / "wiki" / "domains" / "general" / expected_folder
            wiki_dir.mkdir(parents=True)
            mock_vault_paths.wiki_domain_dir.return_value = wiki_dir

            result = sync(str(tmp_path))

        assert result["status"] == "ok"
        assert result["errors"] == 0
        mock_vault_paths.wiki_domain_dir.assert_called_with("general", expected_folder)

    def test_epic_routes_to_epics_folder(self, tmp_path, monkeypatch):
        self._run_sync_with_issue_type("Epic", "epics", tmp_path, monkeypatch)

    def test_bug_routes_to_bugs_folder(self, tmp_path, monkeypatch):
        self._run_sync_with_issue_type("Bug", "bugs", tmp_path, monkeypatch)

    def test_story_routes_to_userstories_folder(self, tmp_path, monkeypatch):
        self._run_sync_with_issue_type("Story", "userstories", tmp_path, monkeypatch)

    def test_task_routes_to_tasks_folder(self, tmp_path, monkeypatch):
        self._run_sync_with_issue_type("Task", "tasks", tmp_path, monkeypatch)


class TestSyncArtifactTypeStoredInState:
    """Verify artifact_type is stored in state for use by CLOSED section."""

    @patch("app.jira_fetcher.fetcher.send_telegram")
    @patch("app.jira_fetcher.fetcher.append_domain_log")
    @patch("app.jira_fetcher.fetcher.update_domain_index")
    @patch("app.jira_fetcher.fetcher.atomic_write")
    @patch("app.jira_fetcher.fetcher.vault_paths")
    @patch("app.jira_fetcher.fetcher.sync_state")
    @patch("app.jira_fetcher.fetcher.search")
    def test_artifact_type_stored_in_state_for_new_issue(
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
        issue = _make_issue(key="GO-888", issue_type="Epic")
        mock_search.return_value = [issue]

        state = _empty_state()
        mock_sync_state.load.return_value = state
        mock_sync_state.diff.return_value = ([issue], [], [])

        raw_dir = tmp_path / "raw" / "inbound" / "tasks"
        raw_dir.mkdir(parents=True)
        mock_vault_paths.raw_tasks.return_value = raw_dir

        wiki_dir = tmp_path / "wiki" / "domains" / "general" / "epics"
        wiki_dir.mkdir(parents=True)
        mock_vault_paths.wiki_domain_dir.return_value = wiki_dir

        sync(str(tmp_path))

        assert state["issues"]["GO-888"]["artifact_type"] == "epics"


class TestSyncClosedUsesArtifactTypeFromState:
    """Verify CLOSED section reads artifact_type from state (not hardcoded tasks)."""

    @patch("app.jira_fetcher.fetcher.send_telegram")
    @patch("app.jira_fetcher.fetcher.append_domain_log")
    @patch("app.jira_fetcher.fetcher.update_domain_index")
    @patch("app.jira_fetcher.fetcher.atomic_write")
    @patch("app.jira_fetcher.fetcher.vault_paths")
    @patch("app.jira_fetcher.fetcher.sync_state")
    @patch("app.jira_fetcher.fetcher.search")
    def test_closed_epic_uses_epics_folder(
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
        mock_search.return_value = []

        state = _empty_state()
        state["issues"]["GO-999"] = {
            "status": "in-progress",
            "updated": "2026-04-28T10:00:00",
            "domain": "general",
            "synced_at": "2026-04-30T10:00:00",
            "artifact_type": "epics",
        }
        mock_sync_state.load.return_value = state
        mock_sync_state.diff.return_value = ([], [], ["GO-999"])

        wiki_dir = tmp_path / "wiki" / "domains" / "general" / "epics"
        wiki_dir.mkdir(parents=True)
        mock_vault_paths.wiki_domain_dir.return_value = wiki_dir

        wiki_file = wiki_dir / "GO-999.md"
        wiki_file.write_text(
            "---\nstatus: in-progress\n---\n# GO-999: Some epic\n",
            encoding="utf-8",
        )

        result = sync(str(tmp_path))

        assert result["status"] == "ok"
        assert result["closed"] == 1
        # Loop checks all art types {art_type, "tasks", "epics"}, verify "epics" is among them
        mock_vault_paths.wiki_domain_dir.assert_any_call("general", "epics")

    @patch("app.jira_fetcher.fetcher.send_telegram")
    @patch("app.jira_fetcher.fetcher.append_domain_log")
    @patch("app.jira_fetcher.fetcher.update_domain_index")
    @patch("app.jira_fetcher.fetcher.atomic_write")
    @patch("app.jira_fetcher.fetcher.vault_paths")
    @patch("app.jira_fetcher.fetcher.sync_state")
    @patch("app.jira_fetcher.fetcher.search")
    def test_closed_old_entry_without_artifact_type_falls_back_to_tasks(
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
        mock_search.return_value = []

        state = _empty_state()
        state["issues"]["GO-998"] = {
            "status": "todo",
            "updated": "2026-04-28T10:00:00",
            "domain": "general",
            "synced_at": "2026-04-30T10:00:00",
        }
        mock_sync_state.load.return_value = state
        mock_sync_state.diff.return_value = ([], [], ["GO-998"])

        wiki_dir = tmp_path / "wiki" / "domains" / "general" / "tasks"
        wiki_dir.mkdir(parents=True)
        mock_vault_paths.wiki_domain_dir.return_value = wiki_dir

        result = sync(str(tmp_path))

        assert result["status"] == "ok"
        assert result["closed"] == 1
        # Loop checks all art types {art_type, "tasks", "epics"}, verify "tasks" is among them
        mock_vault_paths.wiki_domain_dir.assert_any_call("general", "tasks")


class TestImportSingleIssueRouting:
    """Verify import_single_issue routes to the correct artifact folder."""

    @patch("app.jira_fetcher.fetcher.send_telegram", create=True)
    @patch("app.jira_fetcher.fetcher.sync_state")
    @patch("app.jira_fetcher.fetcher.append_domain_log")
    @patch("app.jira_fetcher.fetcher.update_domain_index")
    @patch("app.jira_fetcher.fetcher.atomic_write")
    @patch("app.jira_fetcher.fetcher.vault_paths")
    @patch("app.jira_fetcher.fetcher.get_issue")
    def test_import_epic_routes_to_epics(
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
        issue = _make_issue(key="GO-EPC-1", issue_type="Epic")
        mock_get_issue.return_value = issue

        raw_dir = tmp_path / "raw" / "inbound" / "tasks"
        raw_dir.mkdir(parents=True)
        mock_vault_paths.raw_tasks.return_value = raw_dir

        wiki_dir = tmp_path / "wiki" / "domains" / "general" / "epics"
        wiki_dir.mkdir(parents=True)
        mock_vault_paths.wiki_domain_dir.return_value = wiki_dir

        st = _empty_state()
        mock_sync_state.load.return_value = st

        result = import_single_issue("GO-EPC-1", str(tmp_path))

        assert result["status"] == "ok"
        mock_vault_paths.wiki_domain_dir.assert_any_call("general", "epics")

    @patch("app.jira_fetcher.fetcher.send_telegram", create=True)
    @patch("app.jira_fetcher.fetcher.sync_state")
    @patch("app.jira_fetcher.fetcher.append_domain_log")
    @patch("app.jira_fetcher.fetcher.update_domain_index")
    @patch("app.jira_fetcher.fetcher.atomic_write")
    @patch("app.jira_fetcher.fetcher.vault_paths")
    @patch("app.jira_fetcher.fetcher.get_issue")
    def test_import_bug_routes_to_bugs(
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
        issue = _make_issue(key="GO-BUG-1", issue_type="Bug")
        mock_get_issue.return_value = issue

        raw_dir = tmp_path / "raw" / "inbound" / "tasks"
        raw_dir.mkdir(parents=True)
        mock_vault_paths.raw_tasks.return_value = raw_dir

        wiki_dir = tmp_path / "wiki" / "domains" / "general" / "bugs"
        wiki_dir.mkdir(parents=True)
        mock_vault_paths.wiki_domain_dir.return_value = wiki_dir

        st = _empty_state()
        mock_sync_state.load.return_value = st

        result = import_single_issue("GO-BUG-1", str(tmp_path))

        assert result["status"] == "ok"
        mock_vault_paths.wiki_domain_dir.assert_any_call("general", "bugs")

    @patch("app.jira_fetcher.fetcher.send_telegram", create=True)
    @patch("app.jira_fetcher.fetcher.sync_state")
    @patch("app.jira_fetcher.fetcher.append_domain_log")
    @patch("app.jira_fetcher.fetcher.update_domain_index")
    @patch("app.jira_fetcher.fetcher.atomic_write")
    @patch("app.jira_fetcher.fetcher.vault_paths")
    @patch("app.jira_fetcher.fetcher.get_issue")
    def test_import_story_routes_to_userstories(
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
        issue = _make_issue(key="GO-UST-1", issue_type="Story")
        mock_get_issue.return_value = issue

        raw_dir = tmp_path / "raw" / "inbound" / "tasks"
        raw_dir.mkdir(parents=True)
        mock_vault_paths.raw_tasks.return_value = raw_dir

        wiki_dir = tmp_path / "wiki" / "domains" / "general" / "userstories"
        wiki_dir.mkdir(parents=True)
        mock_vault_paths.wiki_domain_dir.return_value = wiki_dir

        st = _empty_state()
        mock_sync_state.load.return_value = st

        result = import_single_issue("GO-UST-1", str(tmp_path))

        assert result["status"] == "ok"
        mock_vault_paths.wiki_domain_dir.assert_any_call("general", "userstories")

    @patch("app.jira_fetcher.fetcher.send_telegram", create=True)
    @patch("app.jira_fetcher.fetcher.sync_state")
    @patch("app.jira_fetcher.fetcher.append_domain_log")
    @patch("app.jira_fetcher.fetcher.update_domain_index")
    @patch("app.jira_fetcher.fetcher.atomic_write")
    @patch("app.jira_fetcher.fetcher.vault_paths")
    @patch("app.jira_fetcher.fetcher.get_issue")
    def test_import_task_routes_to_tasks(
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
        issue = _make_issue(key="GO-TSK-1", issue_type="Task")
        mock_get_issue.return_value = issue

        raw_dir = tmp_path / "raw" / "inbound" / "tasks"
        raw_dir.mkdir(parents=True)
        mock_vault_paths.raw_tasks.return_value = raw_dir

        wiki_dir = tmp_path / "wiki" / "domains" / "general" / "tasks"
        wiki_dir.mkdir(parents=True)
        mock_vault_paths.wiki_domain_dir.return_value = wiki_dir

        st = _empty_state()
        mock_sync_state.load.return_value = st

        result = import_single_issue("GO-TSK-1", str(tmp_path))

        assert result["status"] == "ok"
        mock_vault_paths.wiki_domain_dir.assert_any_call("general", "tasks")
