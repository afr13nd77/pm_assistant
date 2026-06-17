"""Unit tests for OpenRouter API endpoints in vault_api.py.

Covers:
  GET  /api/v1/openrouter-key-status
  GET  /api/v1/openrouter-models
  POST /api/v1/test-openrouter
  GET  /api/v1/user-prefs      — transcription_provider / openrouter_model defaults
  PUT  /api/v1/user-prefs      — transcription_provider / openrouter_model round-trip
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path):
    """FastAPI test client with VAULT_PATH isolated to a temp directory."""
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    # Import first so the module exists, then patch VAULT_PATH on it
    from app.vault_api import app
    import app.vault_api as vault_api_module
    import shared.vault_paths as vault_paths_module
    with patch.object(vault_api_module, "VAULT_PATH", tmp_path), \
         patch.object(vault_paths_module, "VAULT_PATH", tmp_path):
        yield TestClient(app)


@pytest.fixture
def prefs_file(tmp_path):
    """Path where user prefs JSON will live (matches vault_api._read_user_prefs)."""
    return tmp_path / ".pm-user-prefs.json"


# ---------------------------------------------------------------------------
# GET /api/v1/openrouter-key-status
# ---------------------------------------------------------------------------

class TestOpenRouterKeyStatus:

    def test_has_key_returns_true(self, client):
        """When OPENROUTER_API_KEY is set, has_key should be True."""
        with patch("app.vault_api.os.getenv", return_value="sk-test-key"):
            resp = client.get("/api/v1/openrouter-key-status")
        assert resp.status_code == 200
        assert resp.json() == {"has_key": True}

    def test_no_key_returns_false(self, client):
        """When OPENROUTER_API_KEY is absent, has_key should be False."""
        with patch("app.vault_api.os.getenv", return_value=None):
            resp = client.get("/api/v1/openrouter-key-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_key"] is False

    def test_empty_string_key_returns_false(self, client):
        """Empty string env var should be treated as no key (bool('') == False)."""
        with patch("app.vault_api.os.getenv", return_value=""):
            resp = client.get("/api/v1/openrouter-key-status")
        assert resp.status_code == 200
        assert resp.json()["has_key"] is False


# ---------------------------------------------------------------------------
# GET /api/v1/openrouter-models
# ---------------------------------------------------------------------------

class TestOpenRouterModels:

    def test_returns_models_list(self, client):
        """Should return 200 with a 'models' list of 6 entries."""
        resp = client.get("/api/v1/openrouter-models")
        assert resp.status_code == 200
        data = resp.json()
        assert "models" in data
        assert len(data["models"]) == 6

    def test_first_model_is_qwen3_32b(self, client):
        """First model should be qwen/qwen3-32b (the default)."""
        resp = client.get("/api/v1/openrouter-models")
        assert resp.status_code == 200
        first = resp.json()["models"][0]
        assert first["id"] == "qwen/qwen3-32b"

    def test_each_model_has_id_and_name(self, client):
        """Every model entry must have both 'id' and 'name' keys."""
        resp = client.get("/api/v1/openrouter-models")
        assert resp.status_code == 200
        for model in resp.json()["models"]:
            assert "id" in model
            assert "name" in model


# ---------------------------------------------------------------------------
# POST /api/v1/test-openrouter
# ---------------------------------------------------------------------------

class TestTestOpenRouter:

    def test_success(self, client):
        """When key is present and test_connection succeeds, return status=ok."""
        mock_result = {
            "status": "ok",
            "model": "qwen/qwen3-32b",
            "model_name": "Qwen3 32B",
        }
        with patch("app.vault_api.os.getenv", return_value="sk-test-key"), \
             patch("shared.openrouter_client.test_connection", return_value=mock_result):
            resp = client.post(
                "/api/v1/test-openrouter",
                json={"model": "qwen/qwen3-32b"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["model"] == "qwen/qwen3-32b"

    def test_no_key_returns_error(self, client):
        """When OPENROUTER_API_KEY is absent, should return status=error without calling API."""
        with patch("app.vault_api.os.getenv", return_value=None):
            resp = client.post(
                "/api/v1/test-openrouter",
                json={"model": "qwen/qwen3-32b"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "not set" in data["detail"]

    def test_connection_exception_returns_error(self, client):
        """When test_connection raises an exception, endpoint returns status=error."""
        with patch("app.vault_api.os.getenv", return_value="sk-test-key"), \
             patch("shared.openrouter_client.test_connection",
                   side_effect=RuntimeError("network failure")):
            resp = client.post(
                "/api/v1/test-openrouter",
                json={"model": "qwen/qwen3-32b"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "network failure" in data["detail"]

    def test_custom_model_is_forwarded(self, client):
        """The model from the request body must be passed to test_connection."""
        mock_result = {
            "status": "ok",
            "model": "google/gemini-2.5-flash",
            "model_name": "Gemini 2.5 Flash",
        }
        with patch("app.vault_api.os.getenv", return_value="sk-test-key"), \
             patch("shared.openrouter_client.test_connection",
                   return_value=mock_result) as mock_conn:
            resp = client.post(
                "/api/v1/test-openrouter",
                json={"model": "google/gemini-2.5-flash"},
            )
        assert resp.status_code == 200
        # Verify the endpoint forwarded the correct model to test_connection
        call_args = mock_conn.call_args
        assert "google/gemini-2.5-flash" in call_args[0] or \
               call_args[1].get("model") == "google/gemini-2.5-flash"

    def test_missing_model_uses_default(self, client):
        """POST body without 'model' field should use default qwen/qwen3-32b."""
        mock_result = {"status": "ok", "model": "qwen/qwen3-32b", "model_name": "Qwen3 32B"}
        with patch("app.vault_api.os.getenv", return_value="sk-test-key"), \
             patch("shared.openrouter_client.test_connection",
                   return_value=mock_result) as mock_conn:
            resp = client.post("/api/v1/test-openrouter", json={})
        assert resp.status_code == 200
        call_args = mock_conn.call_args
        assert "qwen/qwen3-32b" in call_args[0] or \
               call_args[1].get("model") == "qwen/qwen3-32b"


# ---------------------------------------------------------------------------
# GET /api/v1/user-prefs — transcription fields
# ---------------------------------------------------------------------------

class TestUserPrefsTranscription:

    def test_get_defaults_include_transcription_provider(self, client):
        """GET user-prefs returns transcription_provider='default' when no file exists."""
        resp = client.get("/api/v1/user-prefs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["transcription_provider"] == "default"

    def test_get_defaults_include_openrouter_model(self, client):
        """GET user-prefs returns openrouter_model='qwen/qwen3-32b' when no file exists."""
        resp = client.get("/api/v1/user-prefs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["openrouter_model"] == "qwen/qwen3-32b"

    def test_get_saved_transcription_provider(self, client, prefs_file):
        """GET user-prefs returns saved transcription_provider from disk."""
        prefs_file.write_text(
            json.dumps({
                "refresh_mode": "auto",
                "theme": "matrix",
                "llm_provider": "claude",
                "ollama_url": "",
                "ollama_model": "qwen3.5:latest",
                "jira_sync_notify": True,
                "transcription_provider": "openrouter",
                "openrouter_model": "qwen/qwen3-32b",
            }),
            encoding="utf-8",
        )
        resp = client.get("/api/v1/user-prefs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["transcription_provider"] == "openrouter"
        assert data["openrouter_model"] == "qwen/qwen3-32b"

    def test_get_missing_transcription_provider_falls_back_to_default(self, client, prefs_file):
        """If transcription_provider is absent from saved prefs, falls back to 'default'."""
        prefs_file.write_text(
            json.dumps({"refresh_mode": "auto", "theme": "matrix", "llm_provider": "claude"}),
            encoding="utf-8",
        )
        resp = client.get("/api/v1/user-prefs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["transcription_provider"] == "default"


# ---------------------------------------------------------------------------
# PUT /api/v1/user-prefs — transcription fields
# ---------------------------------------------------------------------------

class TestPutUserPrefsTranscription:

    def _full_body(self, **overrides) -> dict:
        """Build a complete valid PUT body, with optional overrides."""
        base = {
            "refresh_mode": "auto",
            "theme": "matrix",
            "llm_provider": "claude",
            "ollama_url": "",
            "ollama_model": "qwen3.5:latest",
            "jira_sync_notify": True,
            "transcription_provider": "default",
            "openrouter_model": "qwen/qwen3-32b",
        }
        base.update(overrides)
        return base

    def test_put_transcription_provider_openrouter(self, client, prefs_file):
        """PUT accepts transcription_provider='openrouter' and persists it."""
        resp = client.put(
            "/api/v1/user-prefs",
            json=self._full_body(transcription_provider="openrouter"),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["transcription_provider"] == "openrouter"
        # Verify persistence
        saved = json.loads(prefs_file.read_text(encoding="utf-8"))
        assert saved["transcription_provider"] == "openrouter"

    def test_put_transcription_provider_default(self, client, prefs_file):
        """PUT accepts transcription_provider='default'."""
        resp = client.put(
            "/api/v1/user-prefs",
            json=self._full_body(transcription_provider="default"),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["transcription_provider"] == "default"

    def test_put_openrouter_model_is_saved(self, client, prefs_file):
        """PUT persists openrouter_model to disk."""
        resp = client.put(
            "/api/v1/user-prefs",
            json=self._full_body(
                transcription_provider="openrouter",
                openrouter_model="google/gemini-2.5-flash",
            ),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["openrouter_model"] == "google/gemini-2.5-flash"
        saved = json.loads(prefs_file.read_text(encoding="utf-8"))
        assert saved["openrouter_model"] == "google/gemini-2.5-flash"

    def test_put_invalid_transcription_provider_returns_422(self, client):
        """PUT rejects an unknown transcription_provider with 422."""
        resp = client.put(
            "/api/v1/user-prefs",
            json=self._full_body(transcription_provider="invalid_provider"),
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "transcription_provider" in detail

    def test_roundtrip_transcription_get_after_put(self, client, prefs_file):
        """PUT then GET should return the same transcription fields."""
        client.put(
            "/api/v1/user-prefs",
            json=self._full_body(
                transcription_provider="openrouter",
                openrouter_model="qwen/qwen3-32b",
            ),
        )
        resp = client.get("/api/v1/user-prefs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["transcription_provider"] == "openrouter"
        assert data["openrouter_model"] == "qwen/qwen3-32b"
