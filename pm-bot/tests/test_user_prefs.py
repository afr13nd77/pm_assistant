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


# ---------------------------------------------------------------------------
# PUT /api/v1/user-prefs -- fallback-chain object steps (T-07, BL-155)
# ---------------------------------------------------------------------------

class TestPutUserPrefsFallbackChainSteps:
    """Covers design.md §3.3/§3.4 -- multi-model OpenRouter fallback chains."""

    def test_multiple_openrouter_steps_with_different_models_accepted(self, client, prefs_file):
        """AC-03/AC-04: two+ openrouter steps with different models in one
        chain must be accepted (this is the direct point of BL-155 -- the
        old duplicate-provider check used to reject this)."""
        chain = [
            {"provider": "openrouter", "model": "qwen/qwen3-next-80b-a3b-instruct:free"},
            {"provider": "openrouter", "model": "openai/gpt-oss-120b:free"},
            {"provider": "claude"},
        ]
        resp = client.put(
            "/api/v1/user-prefs",
            json={"capture_fallback": chain},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["capture_fallback"] == chain

        saved = json.loads(prefs_file.read_text(encoding="utf-8"))
        assert saved["capture_fallback"] == chain

    def test_openrouter_step_without_model_rejected_422(self, client):
        """AC-06 defense-in-depth: an openrouter step object without a
        non-empty model must be rejected with a clear message."""
        chain = [
            {"provider": "openrouter"},
            {"provider": "claude"},
        ]
        resp = client.put(
            "/api/v1/user-prefs",
            json={"capture_fallback": chain},
        )
        assert resp.status_code == 422
        assert "OpenRouter step requires a non-empty model" in resp.json()["detail"]

    def test_openrouter_step_with_empty_string_model_rejected_422(self, client):
        """Empty-string model must be treated the same as a missing model."""
        chain = [{"provider": "openrouter", "model": "   "}]
        resp = client.put(
            "/api/v1/user-prefs",
            json={"transcription_fallback": chain},
        )
        assert resp.status_code == 422
        assert "OpenRouter step requires a non-empty model" in resp.json()["detail"]

    def test_adjacent_identical_openrouter_steps_collapsed(self, client, prefs_file):
        """design.md §3.4: two adjacent identical (provider, model) steps are
        collapsed into one before saving."""
        chain = [
            {"provider": "openrouter", "model": "qwen/qwen3-next-80b-a3b-instruct:free"},
            {"provider": "openrouter", "model": "qwen/qwen3-next-80b-a3b-instruct:free"},
            {"provider": "claude"},
        ]
        resp = client.put(
            "/api/v1/user-prefs",
            json={"analysis_fallback": chain},
        )
        assert resp.status_code == 200
        expected = [
            {"provider": "openrouter", "model": "qwen/qwen3-next-80b-a3b-instruct:free"},
            {"provider": "claude"},
        ]
        assert resp.json()["analysis_fallback"] == expected

        saved = json.loads(prefs_file.read_text(encoding="utf-8"))
        assert saved["analysis_fallback"] == expected

    def test_adjacent_identical_legacy_string_steps_collapsed(self, client, prefs_file):
        """Two adjacent legacy "openrouter" strings resolve to the same
        default model and must also be collapsed."""
        resp = client.put(
            "/api/v1/user-prefs",
            json={
                "openrouter_model": "qwen/qwen3-32b",
                "capture_fallback": ["openrouter", "openrouter", "claude"],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["capture_fallback"] == ["openrouter", "claude"]

    def test_non_adjacent_identical_steps_not_collapsed(self, client):
        """Identical steps separated by another step are left untouched."""
        chain = [
            {"provider": "openrouter", "model": "model-A"},
            {"provider": "claude"},
            {"provider": "openrouter", "model": "model-A"},
        ]
        resp = client.put(
            "/api/v1/user-prefs",
            json={"capture_fallback": chain},
        )
        assert resp.status_code == 200
        assert resp.json()["capture_fallback"] == chain

    def test_legacy_string_chain_still_accepted(self, client, prefs_file):
        """FLOW-04: legacy string-only chains remain valid (no rejection,
        no forced conversion to the object format)."""
        chain = ["openrouter", "ollama", "claude"]
        resp = client.put(
            "/api/v1/user-prefs",
            json={"transcription_fallback": chain},
        )
        assert resp.status_code == 200
        assert resp.json()["transcription_fallback"] == chain

        saved = json.loads(prefs_file.read_text(encoding="utf-8"))
        assert saved["transcription_fallback"] == chain

    def test_mixed_legacy_and_object_steps_accepted(self, client):
        """A chain may mix legacy strings and new-format objects."""
        chain = [
            "openrouter",
            {"provider": "openrouter", "model": "openai/gpt-oss-120b:free"},
            {"provider": "claude"},
        ]
        resp = client.put(
            "/api/v1/user-prefs",
            json={"analysis_fallback": chain},
        )
        assert resp.status_code == 200
        assert resp.json()["analysis_fallback"] == chain

    def test_invalid_provider_still_rejected(self, client):
        """Existing validation (provider must be claude/ollama/openrouter)
        must keep working for both string and object step formats."""
        resp = client.put(
            "/api/v1/user-prefs",
            json={"capture_fallback": ["claude", "gemini"]},
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "contains invalid providers" in detail
        assert "gemini" in detail

    def test_invalid_provider_in_object_step_still_rejected(self, client):
        """Same check must apply when the invalid provider is inside an
        object-format step."""
        resp = client.put(
            "/api/v1/user-prefs",
            json={"capture_fallback": [{"provider": "gemini", "model": "x"}]},
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "contains invalid providers" in detail
        assert "gemini" in detail

    def test_empty_chain_still_rejected(self, client):
        """Existing empty-list guard must keep working."""
        resp = client.put(
            "/api/v1/user-prefs",
            json={"capture_fallback": []},
        )
        assert resp.status_code == 422
        assert "non-empty list" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /api/v1/user-prefs -- fallback chain normalization (T-08)
# ---------------------------------------------------------------------------

class TestGetUserPrefsFallbackChainNormalization:
    """T-08: GET must always return fallback chains in the canonical object
    format {provider, model}, regardless of how they are actually stored on
    disk (legacy strings, new-format objects, or a mix -- design.md §2.1/§3.2).

    This also covers the T-07 bug (see tasks.md T-07 note / T-08 task): the
    old filter `p in _VALID_FALLBACK_PROVIDERS` compared a dict against a
    frozenset of strings and silently dropped every object-format step.
    """

    def test_legacy_string_chain_normalized_to_objects(self, client, prefs_file):
        """FLOW-04: a legacy string-only chain must come back as objects,
        with the default model filled in for openrouter steps."""
        prefs_file.write_text(
            json.dumps({
                "openrouter_model": "qwen/qwen3-32b",
                "transcription_fallback": ["openrouter", "claude"],
            }),
            encoding="utf-8",
        )
        resp = client.get("/api/v1/user-prefs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["transcription_fallback"] == [
            {"provider": "openrouter", "model": "qwen/qwen3-32b"},
            {"provider": "claude", "model": None},
        ]

    def test_object_format_steps_are_preserved_not_dropped(self, client, prefs_file):
        """Regression test for the T-07 bug: object-format steps (as saved by
        PUT after T-07) must NOT be silently filtered out by GET."""
        chain = [
            {"provider": "openrouter", "model": "qwen/qwen3-next-80b-a3b-instruct:free"},
            {"provider": "openrouter", "model": "openai/gpt-oss-120b:free"},
            {"provider": "claude"},
        ]
        prefs_file.write_text(
            json.dumps({"capture_fallback": chain}),
            encoding="utf-8",
        )
        resp = client.get("/api/v1/user-prefs")
        assert resp.status_code == 200
        data = resp.json()
        # Before the T-08 fix, this would have been reset to the ["claude"]
        # default (all dict elements silently filtered out as "invalid").
        assert data["capture_fallback"] == [
            {"provider": "openrouter", "model": "qwen/qwen3-next-80b-a3b-instruct:free"},
            {"provider": "openrouter", "model": "openai/gpt-oss-120b:free"},
            {"provider": "claude", "model": None},
        ]

    def test_mixed_string_and_object_steps_normalized(self, client, prefs_file):
        """A chain mixing legacy strings and new-format objects must have
        every element normalized to the same canonical shape."""
        prefs_file.write_text(
            json.dumps({
                "openrouter_model": "qwen/qwen3-32b",
                "analysis_fallback": [
                    "openrouter",
                    {"provider": "openrouter", "model": "openai/gpt-oss-120b:free"},
                    "ollama",
                    {"provider": "claude"},
                ],
            }),
            encoding="utf-8",
        )
        resp = client.get("/api/v1/user-prefs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["analysis_fallback"] == [
            {"provider": "openrouter", "model": "qwen/qwen3-32b"},
            {"provider": "openrouter", "model": "openai/gpt-oss-120b:free"},
            {"provider": "ollama", "model": None},
            {"provider": "claude", "model": None},
        ]

    def test_invalid_provider_element_still_filtered_out(self, client, prefs_file):
        """Elements with an unknown provider (string or object form) must
        still be dropped, exactly like before T-08."""
        prefs_file.write_text(
            json.dumps({
                "capture_fallback": [
                    "gemini",
                    {"provider": "gemini", "model": "x"},
                    {"provider": "claude"},
                ],
            }),
            encoding="utf-8",
        )
        resp = client.get("/api/v1/user-prefs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["capture_fallback"] == [{"provider": "claude", "model": None}]

    def test_all_invalid_resets_to_default_object(self, client, prefs_file):
        """If every element is invalid, fall back to the default chain, now
        expressed in the canonical object format."""
        prefs_file.write_text(
            json.dumps({"capture_fallback": ["gemini", {"provider": "unknown"}]}),
            encoding="utf-8",
        )
        resp = client.get("/api/v1/user-prefs")
        assert resp.status_code == 200
        assert resp.json()["capture_fallback"] == [{"provider": "claude", "model": None}]

    def test_put_then_get_roundtrip_preserves_multiple_openrouter_steps(self, client, prefs_file):
        """Direct regression test for the T-07 note: save two openrouter
        steps with different models via PUT, then GET must return both,
        unchanged -- nothing lost."""
        chain = [
            {"provider": "openrouter", "model": "qwen/qwen3-next-80b-a3b-instruct:free"},
            {"provider": "openrouter", "model": "openai/gpt-oss-120b:free"},
            {"provider": "claude"},
        ]
        put_resp = client.put("/api/v1/user-prefs", json={"capture_fallback": chain})
        assert put_resp.status_code == 200

        get_resp = client.get("/api/v1/user-prefs")
        assert get_resp.status_code == 200
        assert get_resp.json()["capture_fallback"] == [
            {"provider": "openrouter", "model": "qwen/qwen3-next-80b-a3b-instruct:free"},
            {"provider": "openrouter", "model": "openai/gpt-oss-120b:free"},
            {"provider": "claude", "model": None},
        ]
