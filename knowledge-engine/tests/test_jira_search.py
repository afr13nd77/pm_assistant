"""Unit tests for GET /api/v1/jira-search endpoint and _map_jira_issue helper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    from app.api import app
    return TestClient(app)


def _make_raw_issue(
    key: str = "SUP-1",
    summary: str = "Test summary",
    issue_type: str = "Task",
    status: str = "Open",
    assignee_name: str = "John Doe",
    labels: list | None = None,
    priority: str = "Medium",
) -> dict:
    """Build a raw Jira issue dict as returned by client.search."""
    return {
        "key": key,
        "fields": {
            "summary": summary,
            "issuetype": {"name": issue_type},
            "status": {"name": status},
            "assignee": {"displayName": assignee_name},
            "labels": labels if labels is not None else ["label-a", "label-b"],
            "priority": {"name": priority},
        },
    }


# ---------------------------------------------------------------------------
# test_jira_search_valid_project
# ---------------------------------------------------------------------------

class TestJiraSearchValidProject:
    def test_jira_search_valid_project(self, client):
        """GET /api/v1/jira-search with project=SUP returns 200 and correctly mapped fields."""
        raw_issues = [
            _make_raw_issue(key="SUP-1", summary="Fix login", issue_type="Bug",
                            status="In Progress", assignee_name="Alice", labels=["auth"], priority="High"),
        ]

        with patch("app.jira_fetcher.client.search", return_value=raw_issues) as mock_search:
            resp = client.get("/api/v1/jira-search", params={"project": "SUP"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["total"] == 1

        issue = data["issues"][0]
        assert issue["key"] == "SUP-1"
        assert issue["summary"] == "Fix login"
        assert issue["type"] == "Bug"
        assert issue["status"] == "In Progress"
        assert issue["assignee"] == "Alice"
        assert issue["labels"] == ["auth"]
        assert issue["priority"] == "High"

        mock_search.assert_called_once()
        call_jql = mock_search.call_args[0][0]
        assert "project = SUP" in call_jql
        assert "ORDER BY updated DESC" in call_jql


# ---------------------------------------------------------------------------
# test_jira_search_with_type_filter
# ---------------------------------------------------------------------------

class TestJiraSearchWithTypeFilter:
    def test_jira_search_with_type_filter(self, client):
        """GET /api/v1/jira-search with type=Bug results in JQL containing issuetype = \"Bug\"."""
        raw_issues = [_make_raw_issue(issue_type="Bug")]

        with patch("app.jira_fetcher.client.search", return_value=raw_issues) as mock_search:
            resp = client.get("/api/v1/jira-search", params={"project": "SUP", "type": "Bug"})

        assert resp.status_code == 200
        call_jql = mock_search.call_args[0][0]
        assert 'issuetype = "Bug"' in call_jql
        assert "project = SUP" in call_jql


# ---------------------------------------------------------------------------
# test_jira_search_with_status_filter
# ---------------------------------------------------------------------------

class TestJiraSearchWithStatusFilter:
    def test_jira_search_with_status_filter(self, client):
        """GET /api/v1/jira-search with status=Done results in JQL containing status = \"Done\"."""
        raw_issues = [_make_raw_issue(status="Done")]

        with patch("app.jira_fetcher.client.search", return_value=raw_issues) as mock_search:
            resp = client.get("/api/v1/jira-search", params={"project": "SUP", "status": "Done"})

        assert resp.status_code == 200
        call_jql = mock_search.call_args[0][0]
        assert 'status = "Done"' in call_jql
        assert "project = SUP" in call_jql


# ---------------------------------------------------------------------------
# test_jira_search_invalid_project
# ---------------------------------------------------------------------------

class TestJiraSearchInvalidProject:
    def test_jira_search_invalid_project_lowercase(self, client):
        """GET /api/v1/jira-search with lowercase project key returns 400."""
        resp = client.get("/api/v1/jira-search", params={"project": "sup"})
        assert resp.status_code == 400
        assert "Invalid project key" in resp.json()["detail"]

    def test_jira_search_invalid_project_with_spaces(self, client):
        """GET /api/v1/jira-search with spaces in project key returns 400."""
        resp = client.get("/api/v1/jira-search", params={"project": "SU P"})
        assert resp.status_code == 400

    def test_jira_search_invalid_project_single_char(self, client):
        """GET /api/v1/jira-search with single-char project key (e.g. 'S') returns 400."""
        resp = client.get("/api/v1/jira-search", params={"project": "S"})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# test_jira_search_max_results_boundary
# ---------------------------------------------------------------------------

class TestJiraSearchMaxResultsBoundary:
    def test_max_results_zero_returns_422(self, client):
        """GET /api/v1/jira-search with max_results=0 returns 422 (below ge=1)."""
        resp = client.get("/api/v1/jira-search", params={"project": "SUP", "max_results": 0})
        assert resp.status_code == 422

    def test_max_results_101_returns_422(self, client):
        """GET /api/v1/jira-search with max_results=101 returns 422 (above le=100)."""
        resp = client.get("/api/v1/jira-search", params={"project": "SUP", "max_results": 101})
        assert resp.status_code == 422

    def test_max_results_1_is_valid(self, client):
        """GET /api/v1/jira-search with max_results=1 returns 200."""
        with patch("app.jira_fetcher.client.search", return_value=[]):
            resp = client.get("/api/v1/jira-search", params={"project": "SUP", "max_results": 1})
        assert resp.status_code == 200

    def test_max_results_100_is_valid(self, client):
        """GET /api/v1/jira-search with max_results=100 returns 200."""
        with patch("app.jira_fetcher.client.search", return_value=[]):
            resp = client.get("/api/v1/jira-search", params={"project": "SUP", "max_results": 100})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# test_jira_search_client_error
# ---------------------------------------------------------------------------

class TestJiraSearchClientError:
    def test_jira_search_client_error_returns_502(self, client):
        """GET /api/v1/jira-search when client.search raises JiraClientError returns 502."""
        from app.jira_fetcher.client import JiraClientError

        with patch(
            "app.jira_fetcher.client.search",
            side_effect=JiraClientError("Jira API unavailable"),
        ):
            resp = client.get("/api/v1/jira-search", params={"project": "SUP"})

        assert resp.status_code == 502
        assert "Jira API unavailable" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# test_map_issue_missing_fields
# ---------------------------------------------------------------------------

class TestMapIssueMissingFields:
    def test_null_assignee(self):
        """_map_jira_issue with null assignee field returns empty string for assignee."""
        from app.api import _map_jira_issue

        raw = {
            "key": "SUP-5",
            "fields": {
                "summary": "No assignee issue",
                "issuetype": {"name": "Task"},
                "status": {"name": "Open"},
                "assignee": None,
                "labels": [],
                "priority": {"name": "Low"},
            },
        }
        result = _map_jira_issue(raw)
        assert result["assignee"] == ""

    def test_empty_labels(self):
        """_map_jira_issue with empty labels list returns empty list."""
        from app.api import _map_jira_issue

        raw = {
            "key": "SUP-6",
            "fields": {
                "summary": "No labels",
                "issuetype": {"name": "Story"},
                "status": {"name": "Done"},
                "assignee": {"displayName": "Bob"},
                "labels": [],
                "priority": {"name": "Medium"},
            },
        }
        result = _map_jira_issue(raw)
        assert result["labels"] == []

    def test_missing_fields_key(self):
        """_map_jira_issue with missing 'fields' key returns empty strings for all fields."""
        from app.api import _map_jira_issue

        raw = {"key": "SUP-7"}
        result = _map_jira_issue(raw)
        assert result["key"] == "SUP-7"
        assert result["summary"] == ""
        assert result["type"] == ""
        assert result["status"] == ""
        assert result["assignee"] == ""
        assert result["labels"] == []
        assert result["priority"] == ""

    def test_null_issuetype(self):
        """_map_jira_issue with null issuetype returns empty string for type."""
        from app.api import _map_jira_issue

        raw = {
            "key": "SUP-8",
            "fields": {
                "summary": "Null type",
                "issuetype": None,
                "status": {"name": "Open"},
                "assignee": None,
                "labels": [],
                "priority": None,
            },
        }
        result = _map_jira_issue(raw)
        assert result["type"] == ""
        assert result["priority"] == ""

    def test_null_status(self):
        """_map_jira_issue with null status returns empty string for status."""
        from app.api import _map_jira_issue

        raw = {
            "key": "SUP-9",
            "fields": {
                "summary": "Null status",
                "issuetype": {"name": "Task"},
                "status": None,
                "assignee": None,
                "labels": [],
                "priority": {"name": "Low"},
            },
        }
        result = _map_jira_issue(raw)
        assert result["status"] == ""

    def test_url_uses_key(self):
        """_map_jira_issue url field contains the issue key."""
        from app.api import _map_jira_issue

        raw = {
            "key": "SUP-42",
            "fields": {
                "summary": "URL test",
                "issuetype": {"name": "Task"},
                "status": {"name": "Open"},
                "assignee": None,
                "labels": [],
                "priority": {"name": "Medium"},
            },
        }
        result = _map_jira_issue(raw)
        assert "SUP-42" in result["url"]
