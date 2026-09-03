"""Unit tests for prompt management endpoints (BL-197, T-19)."""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# conftest.py handles idea_pipeline aliasing; ensure it ran.
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def prompts_dir(tmp_path: Path):
    """Create a temporary prompts directory with 3 prompt files and defaults."""
    d = tmp_path / "prompts"
    d.mkdir()

    contents = {
        "analyst": "You are an analyst.\nLine 2.",
        "pm": "You are a PM agent.\nLine 2.\nLine 3.",
        "decomposer": "You are a decomposer.",
    }
    for name, text in contents.items():
        (d / f"{name}.txt").write_text(text, encoding="utf-8")
        (d / f"{name}.txt.default").write_text(text, encoding="utf-8")

    return d


@pytest.fixture()
def mock_orchestrator():
    """Return a MagicMock that mimics PipelineOrchestrator.reload_agents."""
    orch = MagicMock()
    orch.reload_agents.return_value = ["analyst", "pm", "decomposer"]
    return orch


@pytest.fixture()
def client(prompts_dir: Path, mock_orchestrator: MagicMock):
    """Create a TestClient with patched prompts dir, orchestrator, and no API key."""
    import idea_pipeline.api as api_module

    original_dir = api_module._pipeline_prompts_dir
    original_orch = api_module._orchestrator

    api_module._pipeline_prompts_dir = prompts_dir
    api_module._orchestrator = mock_orchestrator

    with patch.dict(os.environ, {"PIPELINE_API_KEY": ""}, clear=False):
        # Recreate the middleware so it picks up the empty key (dev mode)
        tc = TestClient(api_module.app, raise_server_exceptions=False)
        yield tc

    # Restore originals
    api_module._pipeline_prompts_dir = original_dir
    api_module._orchestrator = original_orch


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGetPrompts:
    """GET /api/v1/prompts"""

    def test_get_prompts(self, client: TestClient):
        """Returns 3 prompts with all required fields."""
        resp = client.get("/api/v1/prompts")
        assert resp.status_code == 200

        data = resp.json()
        assert "prompts" in data
        prompts = data["prompts"]
        assert len(prompts) == 3

        names = {p["name"] for p in prompts}
        assert names == {"analyst", "pm", "decomposer"}

        required_fields = {"name", "description", "content", "lines", "variables", "is_modified"}
        for p in prompts:
            assert required_fields.issubset(p.keys()), f"Missing fields in prompt {p.get('name')}"

    def test_get_prompts_is_modified_false_when_unmodified(self, client: TestClient):
        """All prompts start unmodified (content == default)."""
        resp = client.get("/api/v1/prompts")
        for p in resp.json()["prompts"]:
            assert p["is_modified"] is False, f"{p['name']} should not be modified"

    def test_get_prompts_line_count(self, client: TestClient):
        """Line count matches actual content lines."""
        resp = client.get("/api/v1/prompts")
        for p in resp.json()["prompts"]:
            expected_lines = p["content"].count("\n") + 1
            assert p["lines"] == expected_lines, (
                f"{p['name']}: expected {expected_lines} lines, got {p['lines']}"
            )


class TestSavePrompt:
    """POST /api/v1/prompts/{name}"""

    def test_save_prompt(self, client: TestClient, mock_orchestrator: MagicMock):
        """Saving a prompt returns 200 with agents_reloaded=true."""
        resp = client.post(
            "/api/v1/prompts/analyst",
            json={"content": "Updated analyst prompt."},
        )
        assert resp.status_code == 200

        body = resp.json()
        assert body["status"] == "ok"
        assert body["name"] == "analyst"
        assert body["agents_reloaded"] is True
        mock_orchestrator.reload_agents.assert_called()

    def test_save_prompt_content_persists(self, client: TestClient):
        """After save, GET returns the updated content."""
        new_content = "Brand new analyst content.\nSecond line."
        client.post("/api/v1/prompts/analyst", json={"content": new_content})

        resp = client.get("/api/v1/prompts")
        analyst = next(p for p in resp.json()["prompts"] if p["name"] == "analyst")
        assert analyst["content"] == new_content
        assert analyst["is_modified"] is True

    def test_save_prompt_updates_is_modified(self, client: TestClient):
        """Saving different content marks prompt as modified."""
        resp = client.post(
            "/api/v1/prompts/pm",
            json={"content": "Completely different content."},
        )
        assert resp.status_code == 200
        assert resp.json()["is_modified"] is True

    def test_save_prompt_same_content_not_modified(self, client: TestClient):
        """Saving original content keeps is_modified=false."""
        # Read original content
        get_resp = client.get("/api/v1/prompts")
        pm_prompt = next(p for p in get_resp.json()["prompts"] if p["name"] == "pm")
        original_content = pm_prompt["content"]

        resp = client.post(
            "/api/v1/prompts/pm",
            json={"content": original_content},
        )
        assert resp.status_code == 200
        assert resp.json()["is_modified"] is False


class TestResetPrompt:
    """POST /api/v1/prompts/{name}/reset"""

    def test_reset_prompt(self, client: TestClient, mock_orchestrator: MagicMock):
        """Resetting a prompt restores default content and returns is_modified=false."""
        # First modify the prompt
        client.post(
            "/api/v1/prompts/analyst",
            json={"content": "Modified content."},
        )

        # Then reset it
        resp = client.post("/api/v1/prompts/analyst/reset")
        assert resp.status_code == 200

        body = resp.json()
        assert body["status"] == "ok"
        assert body["name"] == "analyst"
        assert body["is_modified"] is False
        assert body["agents_reloaded"] is True
        mock_orchestrator.reload_agents.assert_called()

    def test_reset_prompt_content_matches_default(
        self, client: TestClient, prompts_dir: Path
    ):
        """After reset, content matches the .default file."""
        # Modify
        client.post(
            "/api/v1/prompts/decomposer",
            json={"content": "Changed decomposer."},
        )

        # Reset
        resp = client.post("/api/v1/prompts/decomposer/reset")
        body = resp.json()

        default_content = (prompts_dir / "decomposer.txt.default").read_text(
            encoding="utf-8"
        )
        assert body["content"] == default_content


class TestReloadAgents:
    """POST /api/v1/reload-agents"""

    def test_reload_agents(self, client: TestClient, mock_orchestrator: MagicMock):
        """Reloading agents returns the list of reloaded agent names."""
        resp = client.post("/api/v1/reload-agents")
        assert resp.status_code == 200

        body = resp.json()
        assert body["status"] == "ok"
        assert body["agents_reloaded"] == ["analyst", "pm", "decomposer"]
        mock_orchestrator.reload_agents.assert_called_once()

    def test_reload_agents_no_orchestrator(self, client: TestClient):
        """Returns 503 when orchestrator is not initialized."""
        import idea_pipeline.api as api_module

        saved = api_module._orchestrator
        api_module._orchestrator = None
        try:
            resp = client.post("/api/v1/reload-agents")
            assert resp.status_code == 503
        finally:
            api_module._orchestrator = saved


class TestValidation:
    """Edge cases and error handling."""

    def test_invalid_name_rejected(self, client: TestClient):
        """Path-traversal-like and invalid names are rejected.

        Note: FastAPI normalises URLs containing '..' so /api/v1/prompts/../etc
        becomes /api/v1/etc (404 from router, never reaches handler).
        Names that *do* reach the handler are validated by the regex.
        """
        # Name with dots reaches handler but fails regex -> 400
        resp = client.post(
            "/api/v1/prompts/..etc",
            json={"content": "Malicious content."},
        )
        assert resp.status_code == 400

    def test_invalid_name_special_chars(self, client: TestClient):
        """Names with special characters are rejected."""
        for bad_name in ["UPPER", "with-dash", "with.dot", "123starts"]:
            resp = client.post(
                f"/api/v1/prompts/{bad_name}",
                json={"content": "test"},
            )
            assert resp.status_code == 400, f"Expected 400 for name '{bad_name}'"

    def test_unknown_prompt_404(self, client: TestClient):
        """Saving to a non-existent prompt returns 404."""
        resp = client.post(
            "/api/v1/prompts/nonexistent",
            json={"content": "Does not exist."},
        )
        assert resp.status_code == 404

    def test_unknown_prompt_reset_404(self, client: TestClient):
        """Resetting a non-existent prompt returns 404."""
        resp = client.post("/api/v1/prompts/nonexistent/reset")
        assert resp.status_code == 404
