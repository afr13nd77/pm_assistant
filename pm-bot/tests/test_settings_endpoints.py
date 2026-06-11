"""Integration tests for settings and report regeneration endpoints.

Tests GET /api/v1/settings, POST /api/v1/settings, and POST /api/v1/report/regenerate.
Uses TestClient and a temporary vault directory, plus temporary prompts directory.
"""

import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


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


@pytest.fixture
def prompts_dir(tmp_path):
    """Create a temporary prompts directory with sample prompt files."""
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "idea.txt").write_text("You are a PM. Structure this idea.", encoding="utf-8")
    (prompts / "meeting.txt").write_text("Summarize this meeting transcript.", encoding="utf-8")
    (prompts / "jira_ticket.txt").write_text("Create a Jira ticket from this.", encoding="utf-8")
    (prompts / "weekly_report.txt").write_text("Generate a weekly report.", encoding="utf-8")
    return prompts


@pytest.fixture
def client(vault_dir, prompts_dir):
    """Create a FastAPI test client with VAULT and prompts dir patched."""
    with patch("app.vault_api.VAULT_PATH", vault_dir), \
         patch("app.vault_api.Path.__fspath__", return_value=str(prompts_dir)):
        from fastapi.testclient import TestClient
        from app.vault_api import app
        yield TestClient(app)


@pytest.fixture
def client_with_prompts(vault_dir, prompts_dir):
    """Create a test client where __file__ resolves to the temp prompts parent."""
    # We need to make Path(__file__).parent / "prompts" resolve to our temp prompts_dir.
    # The simplest approach: patch the prompts_dir used inside get_settings/save_settings.
    with patch("app.vault_api.VAULT_PATH", vault_dir):
        from fastapi.testclient import TestClient
        from app.vault_api import app
        # We'll patch Path(__file__).parent to return prompts_dir.parent
        # But it's cleaner to just use the real endpoints and patch at a lower level.
        yield TestClient(app), prompts_dir


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

    def test_returns_default_schedule(self, vault_dir):
        """Should return default report_time and report_day."""
        with patch("app.vault_api.VAULT_PATH", vault_dir):
            from fastapi.testclient import TestClient
            from app.vault_api import app
            client = TestClient(app)

            resp = client.get("/api/v1/settings")
            assert resp.status_code == 200
            data = resp.json()
            assert data["report_time"] == "09:00"
            assert data["report_day"] == "mon"

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

    def test_loads_prompt_files(self, vault_dir, prompts_dir):
        """Should load all .txt files from prompts directory."""
        with patch("app.vault_api.VAULT_PATH", vault_dir), \
             patch("app.vault_api.Path") as MockPath:
            # Instead of complex mocking, use the real endpoint and check
            # that prompts are returned. We need to ensure the prompts dir
            # resolves correctly.
            pass

        # Simpler approach: directly test with the real prompts dir
        import app.vault_api as vault_api_module
        original_file = vault_api_module.__file__
        with patch("app.vault_api.VAULT_PATH", vault_dir):
            from fastapi.testclient import TestClient
            from app.vault_api import app

            # Temporarily make the prompts dir accessible
            real_prompts = Path(vault_api_module.__file__).parent / "prompts"
            client = TestClient(app)

            resp = client.get("/api/v1/settings")
            assert resp.status_code == 200
            data = resp.json()
            # The actual prompts directory exists in the real codebase
            if real_prompts.exists():
                assert isinstance(data["prompts"], dict)
                assert len(data["prompts"]) > 0
            else:
                # If prompts dir doesn't exist (CI), prompts will be empty
                assert data["prompts"] == {}

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
                "vault_path", "transcripts_path", "report_time",
                "report_day", "roadmap_now_label", "roadmap_next_label",
                "roadmap_later_label", "prompts"
            }
            assert set(data.keys()) == expected_keys


# ---------------------------------------------------------------------------
# POST /api/v1/settings
# ---------------------------------------------------------------------------

class TestSaveSettings:

    def test_save_existing_prompt(self, vault_dir):
        """Should save content to an existing prompt file."""
        import app.vault_api as vault_api_module
        prompts_dir = Path(vault_api_module.__file__).parent / "prompts"

        if not prompts_dir.exists():
            pytest.skip("Prompts directory not available")

        # Read original content to restore later
        idea_prompt = prompts_dir / "idea.txt"
        if not idea_prompt.exists():
            pytest.skip("idea.txt prompt not available")

        original_content = idea_prompt.read_text(encoding="utf-8")

        with patch("app.vault_api.VAULT_PATH", vault_dir):
            from fastapi.testclient import TestClient
            from app.vault_api import app
            client = TestClient(app)

            resp = client.post(
                "/api/v1/settings",
                json={
                    "vault_path": "/vault",
                    "transcripts_path": "/transcripts",
                    "report_time": "09:00",
                    "report_day": "mon",
                    "roadmap_now_label": "",
                    "roadmap_next_label": "",
                    "roadmap_later_label": "",
                    "prompts": {"idea": "Updated idea prompt content"},
                },
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["saved_prompts"] == 1

            # Verify file was actually written
            updated = idea_prompt.read_text(encoding="utf-8")
            assert updated == "Updated idea prompt content"

            # Restore original content
            idea_prompt.write_text(original_content, encoding="utf-8")

    def test_reject_unknown_prompt(self, vault_dir):
        """Should skip prompt files that don't exist."""
        with patch("app.vault_api.VAULT_PATH", vault_dir):
            from fastapi.testclient import TestClient
            from app.vault_api import app
            client = TestClient(app)

            resp = client.post(
                "/api/v1/settings",
                json={
                    "prompts": {"nonexistent_prompt": "Should not be saved"},
                },
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["saved_prompts"] == 0

    def test_reject_path_traversal_dotdot(self, vault_dir):
        """Should reject prompt names containing '..'."""
        with patch("app.vault_api.VAULT_PATH", vault_dir):
            from fastapi.testclient import TestClient
            from app.vault_api import app
            client = TestClient(app)

            resp = client.post(
                "/api/v1/settings",
                json={
                    "prompts": {"../../../etc/passwd": "malicious"},
                },
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data["saved_prompts"] == 0

    def test_reject_path_traversal_slash(self, vault_dir):
        """Should reject prompt names containing forward slashes."""
        with patch("app.vault_api.VAULT_PATH", vault_dir):
            from fastapi.testclient import TestClient
            from app.vault_api import app
            client = TestClient(app)

            resp = client.post(
                "/api/v1/settings",
                json={
                    "prompts": {"foo/bar": "malicious"},
                },
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data["saved_prompts"] == 0

    def test_reject_path_traversal_backslash(self, vault_dir):
        """Should reject prompt names containing backslashes."""
        with patch("app.vault_api.VAULT_PATH", vault_dir):
            from fastapi.testclient import TestClient
            from app.vault_api import app
            client = TestClient(app)

            resp = client.post(
                "/api/v1/settings",
                json={
                    "prompts": {"foo\\bar": "malicious"},
                },
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data["saved_prompts"] == 0

    def test_empty_prompts_saves_nothing(self, vault_dir):
        """Should return 0 saved when prompts dict is empty."""
        with patch("app.vault_api.VAULT_PATH", vault_dir):
            from fastapi.testclient import TestClient
            from app.vault_api import app
            client = TestClient(app)

            resp = client.post(
                "/api/v1/settings",
                json={"prompts": {}},
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["saved_prompts"] == 0

    def test_response_format(self, vault_dir):
        """Should return correct response format with status and saved_prompts."""
        with patch("app.vault_api.VAULT_PATH", vault_dir):
            from fastapi.testclient import TestClient
            from app.vault_api import app
            client = TestClient(app)

            resp = client.post(
                "/api/v1/settings",
                json={
                    "vault_path": "/vault",
                    "transcripts_path": "/transcripts",
                    "report_time": "10:00",
                    "report_day": "fri",
                    "roadmap_now_label": "Sprint 42",
                    "roadmap_next_label": "Sprint 43",
                    "roadmap_later_label": "Backlog",
                    "prompts": {},
                },
            )

            assert resp.status_code == 200
            data = resp.json()
            assert "status" in data
            assert "saved_prompts" in data
            assert data["status"] == "ok"


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
