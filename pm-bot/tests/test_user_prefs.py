"""Unit and integration tests for user-prefs endpoints (GET/PUT /api/v1/user-prefs).

Tests theme field support alongside the existing refresh_mode field.
"""

import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch


@pytest.fixture
def vault_dir(tmp_path):
    """Create a temporary vault directory structure."""
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    return tmp_path


@pytest.fixture
def prefs_file(vault_dir):
    """Return the path where user prefs JSON will live."""
    return vault_dir / ".pm-user-prefs.json"


@pytest.fixture
def client(vault_dir):
    """Create a FastAPI test client with VAULT_PATH pointed at tmp dir."""
    with patch("app.vault_api.VAULT_PATH", vault_dir), \
         patch("shared.vault_paths.VAULT_PATH", vault_dir):
        from fastapi.testclient import TestClient
        from app.vault_api import app
        yield TestClient(app)


# ---------------------------------------------------------------------------
# Unit tests for constants and model
# ---------------------------------------------------------------------------

class TestUserPrefsModel:

    def test_valid_themes_contains_matrix_and_light(self):
        from app.vault_api import _VALID_THEMES
        assert "matrix" in _VALID_THEMES
        assert "light" in _VALID_THEMES
        assert len(_VALID_THEMES) == 2

    def test_default_user_prefs_includes_theme(self):
        from app.vault_api import _DEFAULT_USER_PREFS
        assert "theme" in _DEFAULT_USER_PREFS
        assert _DEFAULT_USER_PREFS["theme"] == "matrix"
        assert "refresh_mode" in _DEFAULT_USER_PREFS
        assert _DEFAULT_USER_PREFS["refresh_mode"] == "auto"

    def test_user_prefs_model_defaults(self):
        from app.vault_api import UserPrefs
        prefs = UserPrefs()
        assert prefs.refresh_mode == "auto"
        assert prefs.theme == "matrix"

    def test_user_prefs_model_custom_values(self):
        from app.vault_api import UserPrefs
        prefs = UserPrefs(refresh_mode="manual", theme="light")
        assert prefs.refresh_mode == "manual"
        assert prefs.theme == "light"


# ---------------------------------------------------------------------------
# GET /api/v1/user-prefs
# ---------------------------------------------------------------------------

class TestGetUserPrefs:

    def test_returns_defaults_when_no_file(self, client):
        """When no prefs file exists, should return defaults including theme=matrix."""
        resp = client.get("/api/v1/user-prefs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["refresh_mode"] == "auto"
        assert data["theme"] == "matrix"

    def test_returns_saved_prefs(self, client, prefs_file):
        """Should return saved prefs from file."""
        prefs_file.write_text(
            json.dumps({"refresh_mode": "manual", "theme": "light"}),
            encoding="utf-8",
        )
        resp = client.get("/api/v1/user-prefs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["refresh_mode"] == "manual"
        assert data["theme"] == "light"

    def test_normalizes_invalid_theme(self, client, prefs_file):
        """Should fall back to 'matrix' if saved theme is invalid."""
        prefs_file.write_text(
            json.dumps({"refresh_mode": "auto", "theme": "dark"}),
            encoding="utf-8",
        )
        resp = client.get("/api/v1/user-prefs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["theme"] == "matrix"

    def test_normalizes_missing_theme(self, client, prefs_file):
        """Should fall back to 'matrix' if theme key is missing from file."""
        prefs_file.write_text(
            json.dumps({"refresh_mode": "auto"}),
            encoding="utf-8",
        )
        resp = client.get("/api/v1/user-prefs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["theme"] == "matrix"

    def test_normalizes_invalid_refresh_mode_preserves_theme(self, client, prefs_file):
        """Should normalize refresh_mode but preserve valid theme."""
        prefs_file.write_text(
            json.dumps({"refresh_mode": "bogus", "theme": "light"}),
            encoding="utf-8",
        )
        resp = client.get("/api/v1/user-prefs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["refresh_mode"] == "auto"
        assert data["theme"] == "light"


# ---------------------------------------------------------------------------
# PUT /api/v1/user-prefs
# ---------------------------------------------------------------------------

class TestPutUserPrefs:

    def test_saves_valid_prefs_with_theme(self, client, prefs_file):
        """Should accept and persist valid refresh_mode + theme."""
        resp = client.put(
            "/api/v1/user-prefs",
            json={"refresh_mode": "manual", "theme": "light"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["refresh_mode"] == "manual"
        assert data["theme"] == "light"

        # Verify persistence
        saved = json.loads(prefs_file.read_text(encoding="utf-8"))
        assert saved["refresh_mode"] == "manual"
        assert saved["theme"] == "light"

    def test_saves_matrix_theme(self, client, prefs_file):
        """Should accept theme=matrix."""
        resp = client.put(
            "/api/v1/user-prefs",
            json={"refresh_mode": "auto", "theme": "matrix"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["theme"] == "matrix"

    def test_rejects_invalid_theme(self, client):
        """Should return 422 for an invalid theme value."""
        resp = client.put(
            "/api/v1/user-prefs",
            json={"refresh_mode": "auto", "theme": "dark"},
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "theme must be one of" in detail
        assert "light" in detail
        assert "matrix" in detail

    def test_rejects_invalid_refresh_mode(self, client):
        """Should still reject invalid refresh_mode (existing behavior preserved)."""
        resp = client.put(
            "/api/v1/user-prefs",
            json={"refresh_mode": "bogus", "theme": "matrix"},
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "refresh_mode must be one of" in detail

    def test_defaults_theme_to_matrix_when_omitted(self, client, prefs_file):
        """When theme is omitted from PUT body, should default to 'matrix'."""
        resp = client.put(
            "/api/v1/user-prefs",
            json={"refresh_mode": "auto"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["theme"] == "matrix"

    def test_roundtrip_get_after_put(self, client, prefs_file):
        """PUT then GET should return the same values."""
        client.put(
            "/api/v1/user-prefs",
            json={"refresh_mode": "manual", "theme": "light"},
        )
        resp = client.get("/api/v1/user-prefs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["refresh_mode"] == "manual"
        assert data["theme"] == "light"
