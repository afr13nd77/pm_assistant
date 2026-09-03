"""Integration tests for settings and report regeneration endpoints.

Tests GET /api/v1/settings, POST /api/v1/settings, and POST /api/v1/report/regenerate.
Uses TestClient and a temporary vault directory.
"""

import os
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def vault_dir(tmp_path):
    """Create a temporary vault directory structure."""
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    meetings = tmp_path / "Meetings"
    meetings.mkdir()
    tasks_drafts = tmp_path / "Tasks" / "Drafts"
    tasks_drafts.mkdir(parents=True)
    epics = tmp_path / "Projects" / "Epics"
    epics.mkdir(parents=True)
    reports = tmp_path / "Reports"
    reports.mkdir()
    return tmp_path




# ---------------------------------------------------------------------------
# GET /api/v1/settings
# ---------------------------------------------------------------------------

class TestGetSettings:

    def test_returns_env_values(self, vault_dir):
        """Should return VAULT_PATH and TRANSCRIPTS_INBOX from environment."""
        with patch("app.vault_api.VAULT_PATH", vault_dir), \
             patch.dict(os.environ, {
                 "VAULT_PATH": "/my/vault",
                 "TRANSCRIPTS_INBOX": "/my/transcripts"
             }):
            from fastapi.testclient import TestClient

            from app.vault_api import app
            client = TestClient(app)

            resp = client.get("/api/v1/settings")
            assert resp.status_code == 200
            data = resp.json()
            assert data["vault_path"] == "/my/vault"
            assert data["transcripts_path"] == "/my/transcripts"

    @pytest.mark.xfail(reason="roadmap_*_label keys removed from settings")
    def test_returns_empty_roadmap_labels(self, vault_dir):
        """Should return empty roadmap labels by default."""
        with patch("app.vault_api.VAULT_PATH", vault_dir):
            from fastapi.testclient import TestClient

            from app.vault_api import app
            client = TestClient(app)

            resp = client.get("/api/v1/settings")
            assert resp.status_code == 200
            data = resp.json()
            assert data["roadmap_now_label"] == ""
            assert data["roadmap_next_label"] == ""
            assert data["roadmap_later_label"] == ""

    @pytest.mark.xfail(reason="roadmap_*_label keys removed from settings")
    def test_settings_structure(self, vault_dir):
        """Should return all expected keys in the response."""
        with patch("app.vault_api.VAULT_PATH", vault_dir):
            from fastapi.testclient import TestClient

            from app.vault_api import app
            client = TestClient(app)

            resp = client.get("/api/v1/settings")
            assert resp.status_code == 200
            data = resp.json()
            expected_keys = {
                "vault_path", "transcripts_path",
                "roadmap_now_label", "roadmap_next_label",
                "roadmap_later_label",
            }
            assert set(data.keys()) == expected_keys


# ---------------------------------------------------------------------------
# POST /api/v1/report/regenerate
# ---------------------------------------------------------------------------

class TestRegenerateReport:

    def test_regenerate_success(self, vault_dir):
        """Should call generate_weekly_report and write_report, return result."""
        mock_report_md = "# Weekly Report\n\nGenerated content."
        mock_filepath = MagicMock()
        mock_filepath.name = "2026-04-27-weekly.md"

        with patch("app.vault_api.VAULT_PATH", vault_dir), \
             patch("app.reporter.generate_weekly_report", return_value=mock_report_md), \
             patch("app.obsidian_writer.write_report", return_value=mock_filepath):
            from fastapi.testclient import TestClient

            from app.vault_api import app
            client = TestClient(app)

            resp = client.post("/api/v1/report/regenerate")

            assert resp.status_code == 200
            data = resp.json()
            assert data["filename"] == "2026-04-27-weekly.md"
            assert "Weekly Report" in data["content"]

    def test_regenerate_error(self, vault_dir):
        """Should return 500 when report generation fails."""
        with patch("app.vault_api.VAULT_PATH", vault_dir), \
             patch(
                 "app.reporter.generate_weekly_report",
                 side_effect=RuntimeError("Claude API unavailable"),
             ):
            from fastapi.testclient import TestClient

            from app.vault_api import app
            client = TestClient(app)

            resp = client.post("/api/v1/report/regenerate")

            assert resp.status_code == 500
            data = resp.json()
            assert "Claude API unavailable" in data["detail"]
