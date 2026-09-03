"""Integration tests for Prompts API endpoints (BL-197, T-14).

Tests:
  GET  /api/v1/prompts/all
  POST /api/v1/prompts/{component}/{name}
  POST /api/v1/prompts/{component}/{name}/reset
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def prompts_dir(tmp_path):
    """Create temp prompts dir with sample prompt files and defaults."""
    d = tmp_path / "prompts"
    d.mkdir()
    (d / "idea.txt").write_text("idea prompt content", encoding="utf-8")
    (d / "idea.txt.default").write_text("idea prompt content", encoding="utf-8")
    (d / "meeting.txt").write_text("meeting prompt content", encoding="utf-8")
    (d / "meeting.txt.default").write_text("meeting prompt content", encoding="utf-8")
    (d / "daily.txt").write_text("daily prompt content", encoding="utf-8")
    (d / "daily.txt.default").write_text("daily prompt content", encoding="utf-8")
    (d / "jira_ticket.txt").write_text("jira prompt content", encoding="utf-8")
    (d / "jira_ticket.txt.default").write_text("jira prompt content", encoding="utf-8")
    (d / "weekly_report.txt").write_text("weekly prompt content", encoding="utf-8")
    (d / "weekly_report.txt.default").write_text("weekly prompt content", encoding="utf-8")
    return d


@pytest.fixture()
def client(prompts_dir):
    """TestClient with patched prompts dir and mocked external clients."""
    with patch("app.vault_api._pmbot_prompts_dir", prompts_dir):
        from app.vault_api import app
        yield TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/v1/prompts/all
# ---------------------------------------------------------------------------

class TestGetAllPrompts:

    def test_returns_all_components(self, client, prompts_dir):
        """Should return prompts for all three components."""
        with patch("app.vault_api.ke_client") as mock_ke, \
             patch("app.vault_api.pipeline_client") as mock_pl:
            mock_ke.get_prompts.return_value = {
                "prompts": [{"name": "ke_prompt", "content": "ke content"}],
            }
            mock_pl.get_prompts.return_value = {
                "prompts": [{"name": "pl_prompt", "content": "pl content"}],
            }

            resp = client.get("/api/v1/prompts/all")
            assert resp.status_code == 200
            data = resp.json()

            assert "pm-bot" in data
            assert "knowledge-engine" in data
            assert "idea-pipeline" in data

            assert data["pm-bot"]["status"] == "ok"
            assert len(data["pm-bot"]["prompts"]) == 5

            assert data["knowledge-engine"]["status"] == "ok"
            assert len(data["knowledge-engine"]["prompts"]) == 1

            assert data["idea-pipeline"]["status"] == "ok"
            assert len(data["idea-pipeline"]["prompts"]) == 1

    def test_pmbot_prompt_structure(self, client, prompts_dir):
        """pm-bot prompts should have correct fields."""
        with patch("app.vault_api.ke_client") as mock_ke, \
             patch("app.vault_api.pipeline_client") as mock_pl:
            mock_ke.get_prompts.return_value = {"prompts": []}
            mock_pl.get_prompts.return_value = {"prompts": []}

            resp = client.get("/api/v1/prompts/all")
            data = resp.json()
            prompts = data["pm-bot"]["prompts"]

            idea_prompt = next(p for p in prompts if p["name"] == "idea")
            assert idea_prompt["content"] == "idea prompt content"
            assert idea_prompt["lines"] == 1
            assert idea_prompt["is_modified"] is False
            assert "description" in idea_prompt
            assert "variables" in idea_prompt

    def test_modified_prompt_detected(self, client, prompts_dir):
        """Modified prompts should have is_modified=True."""
        # Modify one prompt
        (prompts_dir / "idea.txt").write_text("MODIFIED content", encoding="utf-8")

        with patch("app.vault_api.ke_client") as mock_ke, \
             patch("app.vault_api.pipeline_client") as mock_pl:
            mock_ke.get_prompts.return_value = {"prompts": []}
            mock_pl.get_prompts.return_value = {"prompts": []}

            resp = client.get("/api/v1/prompts/all")
            data = resp.json()
            prompts = data["pm-bot"]["prompts"]

            idea_prompt = next(p for p in prompts if p["name"] == "idea")
            assert idea_prompt["is_modified"] is True

    def test_ke_error_graceful(self, client, prompts_dir):
        """KE failure should return error status, not crash."""
        with patch("app.vault_api.ke_client") as mock_ke, \
             patch("app.vault_api.pipeline_client") as mock_pl:
            mock_ke.get_prompts.side_effect = ConnectionError("KE down")
            mock_pl.get_prompts.return_value = {"prompts": []}

            resp = client.get("/api/v1/prompts/all")
            assert resp.status_code == 200
            data = resp.json()
            assert data["knowledge-engine"]["status"] == "error"
            assert "KE down" in data["knowledge-engine"]["error"]
            assert data["knowledge-engine"]["prompts"] == []

    def test_pipeline_error_graceful(self, client, prompts_dir):
        """Pipeline failure should return error status, not crash."""
        with patch("app.vault_api.ke_client") as mock_ke, \
             patch("app.vault_api.pipeline_client") as mock_pl:
            mock_ke.get_prompts.return_value = {"prompts": []}
            mock_pl.get_prompts.side_effect = ConnectionError("Pipeline down")

            resp = client.get("/api/v1/prompts/all")
            assert resp.status_code == 200
            data = resp.json()
            assert data["idea-pipeline"]["status"] == "error"
            assert "Pipeline down" in data["idea-pipeline"]["error"]


# ---------------------------------------------------------------------------
# POST /api/v1/prompts/{component}/{name}
# ---------------------------------------------------------------------------

class TestSaveComponentPrompt:

    def test_save_pmbot_prompt(self, client, prompts_dir):
        """Should save pm-bot prompt to disk."""
        resp = client.post(
            "/api/v1/prompts/pm-bot/idea",
            json={"content": "new idea prompt"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["name"] == "idea"
        assert data["is_modified"] is True
        assert data["lines"] == 1

        # Verify file on disk
        saved = (prompts_dir / "idea.txt").read_text(encoding="utf-8")
        assert saved == "new idea prompt"

    def test_save_ke_prompt(self, client):
        """Should proxy save to ke_client."""
        with patch("app.vault_api.ke_client") as mock_ke:
            mock_ke.save_prompt.return_value = {"status": "ok", "name": "ke_test"}

            resp = client.post(
                "/api/v1/prompts/knowledge-engine/ke_test",
                json={"content": "ke content"},
            )
            assert resp.status_code == 200
            mock_ke.save_prompt.assert_called_once_with("ke_test", "ke content")

    def test_save_pipeline_prompt(self, client):
        """Should proxy save to pipeline_client."""
        with patch("app.vault_api.pipeline_client") as mock_pl:
            mock_pl.save_prompt.return_value = {"status": "ok", "name": "pl_test"}

            resp = client.post(
                "/api/v1/prompts/idea-pipeline/pl_test",
                json={"content": "pl content"},
            )
            assert resp.status_code == 200
            mock_pl.save_prompt.assert_called_once_with("pl_test", "pl content")

    def test_invalid_component(self, client):
        """Should reject unknown component."""
        resp = client.post(
            "/api/v1/prompts/invalid-comp/test",
            json={"content": "x"},
        )
        assert resp.status_code == 400
        assert "Invalid component" in resp.json()["detail"]

    def test_invalid_prompt_name(self, client):
        """Should reject invalid prompt names."""
        resp = client.post(
            "/api/v1/prompts/pm-bot/INVALID-NAME",
            json={"content": "x"},
        )
        assert resp.status_code == 400
        assert "Invalid prompt name" in resp.json()["detail"]

    def test_nonexistent_pmbot_prompt(self, client, prompts_dir):
        """Should return 404 for non-existent pm-bot prompt."""
        resp = client.post(
            "/api/v1/prompts/pm-bot/nonexistent",
            json={"content": "x"},
        )
        assert resp.status_code == 404

    def test_ke_unavailable(self, client):
        """Should return 502 when KE is unavailable."""
        with patch("app.vault_api.ke_client") as mock_ke:
            mock_ke.save_prompt.side_effect = ConnectionError("KE down")

            resp = client.post(
                "/api/v1/prompts/knowledge-engine/test_prompt",
                json={"content": "x"},
            )
            assert resp.status_code == 502

    def test_pipeline_unavailable(self, client):
        """Should return 502 when pipeline is unavailable."""
        with patch("app.vault_api.pipeline_client") as mock_pl:
            mock_pl.save_prompt.side_effect = ConnectionError("Pipeline down")

            resp = client.post(
                "/api/v1/prompts/idea-pipeline/test_prompt",
                json={"content": "x"},
            )
            assert resp.status_code == 502


# ---------------------------------------------------------------------------
# POST /api/v1/prompts/{component}/{name}/reset
# ---------------------------------------------------------------------------

class TestResetComponentPrompt:

    def test_reset_pmbot_prompt(self, client, prompts_dir):
        """Should reset pm-bot prompt to default."""
        # First modify the prompt
        (prompts_dir / "idea.txt").write_text("MODIFIED", encoding="utf-8")

        resp = client.post("/api/v1/prompts/pm-bot/idea/reset")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["name"] == "idea"
        assert data["is_modified"] is False
        assert data["content"] == "idea prompt content"

        # Verify file on disk
        saved = (prompts_dir / "idea.txt").read_text(encoding="utf-8")
        assert saved == "idea prompt content"

    def test_reset_ke_prompt(self, client):
        """Should proxy reset to ke_client."""
        with patch("app.vault_api.ke_client") as mock_ke:
            mock_ke.reset_prompt.return_value = {"status": "ok", "name": "ke_test"}

            resp = client.post("/api/v1/prompts/knowledge-engine/ke_test/reset")
            assert resp.status_code == 200
            mock_ke.reset_prompt.assert_called_once_with("ke_test")

    def test_reset_pipeline_prompt(self, client):
        """Should proxy reset to pipeline_client."""
        with patch("app.vault_api.pipeline_client") as mock_pl:
            mock_pl.reset_prompt.return_value = {"status": "ok", "name": "pl_test"}

            resp = client.post("/api/v1/prompts/idea-pipeline/pl_test/reset")
            assert resp.status_code == 200
            mock_pl.reset_prompt.assert_called_once_with("pl_test")

    def test_reset_invalid_component(self, client):
        """Should reject unknown component."""
        resp = client.post("/api/v1/prompts/invalid/test/reset")
        assert resp.status_code == 400

    def test_reset_invalid_name(self, client):
        """Should reject invalid prompt name."""
        resp = client.post("/api/v1/prompts/pm-bot/BAD-NAME/reset")
        assert resp.status_code == 400

    def test_reset_no_default(self, client, prompts_dir):
        """Should return 404 if no default exists."""
        # Create prompt without default
        (prompts_dir / "orphan.txt").write_text("orphan", encoding="utf-8")

        resp = client.post("/api/v1/prompts/pm-bot/orphan/reset")
        assert resp.status_code == 404
        assert "Default not found" in resp.json()["detail"]

    def test_reset_ke_unavailable(self, client):
        """Should return 502 when KE is unavailable."""
        with patch("app.vault_api.ke_client") as mock_ke:
            mock_ke.reset_prompt.side_effect = ConnectionError("KE down")

            resp = client.post("/api/v1/prompts/knowledge-engine/test_prompt/reset")
            assert resp.status_code == 502

    def test_reset_pipeline_unavailable(self, client):
        """Should return 502 when pipeline is unavailable."""
        with patch("app.vault_api.pipeline_client") as mock_pl:
            mock_pl.reset_prompt.side_effect = ConnectionError("Pipeline down")

            resp = client.post("/api/v1/prompts/idea-pipeline/test_prompt/reset")
            assert resp.status_code == 502


# ---------------------------------------------------------------------------
# Validation helpers (unit tests)
# ---------------------------------------------------------------------------

class TestValidationHelpers:

    def test_valid_prompt_names(self):
        """Should accept valid prompt names."""
        from app.vault_api import _validate_prompt_name
        # Should not raise
        _validate_prompt_name("idea")
        _validate_prompt_name("weekly_report")
        _validate_prompt_name("a")
        _validate_prompt_name("test123")

    def test_invalid_prompt_names(self):
        """Should reject invalid prompt names."""
        from app.vault_api import _validate_prompt_name
        from fastapi import HTTPException
        for bad in ["", "UPPER", "has-dash", "123start", "../escape", "a" * 65]:
            with pytest.raises(HTTPException) as exc_info:
                _validate_prompt_name(bad)
            assert exc_info.value.status_code == 400

    def test_valid_components(self):
        """Should accept valid component names."""
        from app.vault_api import _validate_component
        _validate_component("pm-bot")
        _validate_component("knowledge-engine")
        _validate_component("idea-pipeline")

    def test_invalid_components(self):
        """Should reject invalid component names."""
        from app.vault_api import _validate_component
        from fastapi import HTTPException
        for bad in ["", "unknown", "PM-BOT", "frontend"]:
            with pytest.raises(HTTPException) as exc_info:
                _validate_component(bad)
            assert exc_info.value.status_code == 400

    def test_is_modified_true(self, tmp_path):
        """Should detect modified prompt."""
        from app.vault_api import _is_modified
        p = tmp_path / "test.txt"
        d = tmp_path / "test.txt.default"
        p.write_text("modified", encoding="utf-8")
        d.write_text("original", encoding="utf-8")
        assert _is_modified(p) is True

    def test_is_modified_false(self, tmp_path):
        """Should detect unmodified prompt."""
        from app.vault_api import _is_modified
        p = tmp_path / "test.txt"
        d = tmp_path / "test.txt.default"
        p.write_text("same", encoding="utf-8")
        d.write_text("same", encoding="utf-8")
        assert _is_modified(p) is False

    def test_is_modified_no_default(self, tmp_path):
        """Should return False if no default exists."""
        from app.vault_api import _is_modified
        p = tmp_path / "test.txt"
        p.write_text("content", encoding="utf-8")
        assert _is_modified(p) is False
