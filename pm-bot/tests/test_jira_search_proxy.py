"""Unit tests for GET /api/v1/jira/search proxy endpoint in vault_api."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests
from starlette.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    from app.vault_api import app
    return TestClient(app)


# ---------------------------------------------------------------------------
# test_jira_search_proxy_success
# ---------------------------------------------------------------------------

class TestJiraSearchProxySuccess:
    def test_jira_search_proxy_success(self, client):
        """GET /api/v1/jira/search proxies to ke_client and returns 200 with result."""
        ke_response = {
            "status": "ok",
            "total": 2,
            "issues": [
                {
                    "key": "SUP-1",
                    "summary": "First issue",
                    "type": "Task",
                    "status": "Open",
                    "assignee": "Alice",
                    "labels": [],
                    "priority": "High",
                    "url": "https://jira.example.com/browse/SUP-1",
                },
                {
                    "key": "SUP-2",
                    "summary": "Second issue",
                    "type": "Bug",
                    "status": "In Progress",
                    "assignee": "Bob",
                    "labels": ["backend"],
                    "priority": "Medium",
                    "url": "https://jira.example.com/browse/SUP-2",
                },
            ],
        }

        with patch("app.ke_client.jira_search", return_value=ke_response) as mock_search:
            resp = client.get("/api/v1/jira/search", params={"project": "SUP"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["total"] == 2
        assert len(data["issues"]) == 2
        mock_search.assert_called_once()


# ---------------------------------------------------------------------------
# test_jira_search_proxy_invalid_key
# ---------------------------------------------------------------------------

class TestJiraSearchProxyInvalidKey:
    def test_jira_search_proxy_lowercase_project_returns_400(self, client):
        """GET /api/v1/jira/search with lowercase project key returns 400 before calling ke_client."""
        with patch("app.ke_client.jira_search") as mock_search:
            resp = client.get("/api/v1/jira/search", params={"project": "abc"})

        assert resp.status_code == 400
        assert "Invalid project key" in resp.json()["detail"]
        mock_search.assert_not_called()

    def test_jira_search_proxy_single_char_returns_400(self, client):
        """GET /api/v1/jira/search with single-char project key returns 400."""
        with patch("app.ke_client.jira_search") as mock_search:
            resp = client.get("/api/v1/jira/search", params={"project": "S"})

        assert resp.status_code == 400
        mock_search.assert_not_called()

    def test_jira_search_proxy_mixed_case_returns_400(self, client):
        """GET /api/v1/jira/search with mixed-case project key returns 400."""
        with patch("app.ke_client.jira_search") as mock_search:
            resp = client.get("/api/v1/jira/search", params={"project": "Sup"})

        assert resp.status_code == 400
        mock_search.assert_not_called()


# ---------------------------------------------------------------------------
# test_jira_search_proxy_ke_unavailable
# ---------------------------------------------------------------------------

class TestJiraSearchProxyKEUnavailable:
    def test_jira_search_proxy_connection_error_returns_502(self, client):
        """GET /api/v1/jira/search when ke_client raises requests.RequestException returns 502."""
        with patch(
            "app.ke_client.jira_search",
            side_effect=requests.RequestException("Connection refused"),
        ):
            resp = client.get("/api/v1/jira/search", params={"project": "SUP"})

        assert resp.status_code == 502
        assert "KE API error" in resp.json()["detail"]

    def test_jira_search_proxy_timeout_returns_502(self, client):
        """GET /api/v1/jira/search when ke_client raises requests.Timeout returns 502."""
        with patch(
            "app.ke_client.jira_search",
            side_effect=requests.Timeout("Read timed out"),
        ):
            resp = client.get("/api/v1/jira/search", params={"project": "SUP"})

        assert resp.status_code == 502


# ---------------------------------------------------------------------------
# test_jira_search_proxy_passes_filters
# ---------------------------------------------------------------------------

class TestJiraSearchProxyPassesFilters:
    def test_proxy_passes_type_filter(self, client):
        """GET /api/v1/jira/search passes type parameter to ke_client.jira_search."""
        ke_response = {"status": "ok", "total": 0, "issues": []}

        with patch("app.ke_client.jira_search", return_value=ke_response) as mock_search:
            resp = client.get(
                "/api/v1/jira/search",
                params={"project": "SUP", "type": "Bug"},
            )

        assert resp.status_code == 200
        mock_search.assert_called_once()
        call_args = mock_search.call_args
        # type filter must be forwarded — check positional or keyword args
        assert "Bug" in call_args[0] or call_args[1].get("type") == "Bug" or call_args[0][1] == "Bug"

    def test_proxy_passes_status_filter(self, client):
        """GET /api/v1/jira/search passes status parameter to ke_client.jira_search."""
        ke_response = {"status": "ok", "total": 0, "issues": []}

        with patch("app.ke_client.jira_search", return_value=ke_response) as mock_search:
            resp = client.get(
                "/api/v1/jira/search",
                params={"project": "SUP", "status": "Done"},
            )

        assert resp.status_code == 200
        mock_search.assert_called_once()
        call_args = mock_search.call_args
        assert "Done" in call_args[0] or call_args[1].get("status") == "Done" or call_args[0][2] == "Done"

    def test_proxy_passes_max_results(self, client):
        """GET /api/v1/jira/search passes max_results to ke_client.jira_search."""
        ke_response = {"status": "ok", "total": 0, "issues": []}

        with patch("app.ke_client.jira_search", return_value=ke_response) as mock_search:
            resp = client.get(
                "/api/v1/jira/search",
                params={"project": "SUP", "max_results": 25},
            )

        assert resp.status_code == 200
        mock_search.assert_called_once()
        call_args = mock_search.call_args
        assert 25 in call_args[0] or call_args[1].get("max_results") == 25 or call_args[0][3] == 25

    def test_proxy_passes_all_filters(self, client):
        """GET /api/v1/jira/search passes project, type, status, and max_results together."""
        ke_response = {"status": "ok", "total": 0, "issues": []}

        with patch("app.ke_client.jira_search", return_value=ke_response) as mock_search:
            resp = client.get(
                "/api/v1/jira/search",
                params={"project": "GO", "type": "Story", "status": "In Progress", "max_results": 10},
            )

        assert resp.status_code == 200
        mock_search.assert_called_once_with("GO", "Story", "In Progress", 10)
