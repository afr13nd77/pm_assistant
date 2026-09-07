"""Integration tests for Prompts API endpoints (BL-197, T-04).

Covers:
  - GET  /api/v1/prompts           (list all prompts)
  - POST /api/v1/prompts/{name}    (save prompt)
  - POST /api/v1/prompts/{name}/reset (reset prompt to default)

No LLM calls: tests use tmp-files and monkeypatched paths.
"""

from __future__ import annotations

import pathlib

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def prompts_dir(tmp_path):
    """Create a temporary prompts directory with sample prompt files."""
    prompts = tmp_path / "prompts"
    prompts.mkdir()

    # Create sample prompt files
    (prompts / "enrich.txt").write_text("Enrich prompt content", encoding="utf-8")
    (prompts / "enrich.txt.default").write_text("Enrich prompt content", encoding="utf-8")

    (prompts / "signal_score.txt").write_text("Signal score content", encoding="utf-8")
    (prompts / "signal_score.txt.default").write_text("Signal score content", encoding="utf-8")

    return prompts


@pytest.fixture
def client(tmp_path, prompts_dir, monkeypatch):
    """TestClient with monkeypatched prompts dir and vault path."""
    from app import api
    from shared import vault_paths as _vp

    monkeypatch.setattr(_vp, "VAULT_PATH", pathlib.Path(tmp_path))
    monkeypatch.setattr(api, "_ke_prompts_dir", prompts_dir)

    # Provide a minimal PROMPT_REGISTRY matching our test files
    test_registry = {
        "enrich": {"description": "Enrichment prompt", "variables": []},
        "signal_score": {
            "description": "Signal scoring",
            "variables": ["business_context", "memory_context", "news_item"],
        },
        "missing_file": {"description": "No file exists", "variables": []},
    }
    monkeypatch.setattr(api, "PROMPT_REGISTRY", test_registry)

    return TestClient(api.app)


# ---------------------------------------------------------------------------
# GET /api/v1/prompts
# ---------------------------------------------------------------------------


class TestGetPrompts:
    def test_returns_all_existing_prompts(self, client):
        resp = client.get("/api/v1/prompts")
        assert resp.status_code == 200
        data = resp.json()
        assert "prompts" in data
        # Only 2 prompts have files, "missing_file" should be skipped
        assert len(data["prompts"]) == 2

    def test_prompt_fields(self, client):
        resp = client.get("/api/v1/prompts")
        prompts = resp.json()["prompts"]
        enrich = next(p for p in prompts if p["name"] == "enrich")
        assert enrich["description"] == "Enrichment prompt"
        assert enrich["content"] == "Enrich prompt content"
        assert enrich["lines"] == 1
        assert enrich["variables"] == []
        assert enrich["is_modified"] is False

    def test_is_modified_true_when_changed(self, client, prompts_dir):
        # Modify the prompt file so it differs from default
        (prompts_dir / "enrich.txt").write_text("Modified content", encoding="utf-8")
        resp = client.get("/api/v1/prompts")
        prompts = resp.json()["prompts"]
        enrich = next(p for p in prompts if p["name"] == "enrich")
        assert enrich["is_modified"] is True

    def test_skips_missing_files(self, client):
        resp = client.get("/api/v1/prompts")
        names = [p["name"] for p in resp.json()["prompts"]]
        assert "missing_file" not in names


# ---------------------------------------------------------------------------
# POST /api/v1/prompts/{name}
# ---------------------------------------------------------------------------


class TestSavePrompt:
    def test_save_valid_prompt(self, client, prompts_dir):
        new_content = "Updated signal score prompt"
        resp = client.post(
            "/api/v1/prompts/signal_score",
            json={"content": new_content},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["name"] == "signal_score"
        assert data["lines"] == 1
        assert data["is_modified"] is True
        assert data["cache_invalidated"] is True

        # Verify file was actually written
        saved = (prompts_dir / "signal_score.txt").read_text(encoding="utf-8")
        assert saved == new_content

    def test_save_invalid_name_returns_400(self, client):
        resp = client.post(
            "/api/v1/prompts/INVALID-NAME",
            json={"content": "test"},
        )
        assert resp.status_code == 400
        assert "Invalid prompt name" in resp.json()["detail"]

    def test_save_path_traversal_returns_400(self, client):
        resp = client.post(
            "/api/v1/prompts/../../etc",
            json={"content": "test"},
        )
        # FastAPI will treat this as a different path, but our regex blocks it
        assert resp.status_code in (400, 404, 422)

    def test_save_nonexistent_prompt_returns_404(self, client):
        resp = client.post(
            "/api/v1/prompts/nonexistent",
            json={"content": "test"},
        )
        assert resp.status_code == 404

    def test_save_empty_content(self, client, prompts_dir):
        resp = client.post(
            "/api/v1/prompts/enrich",
            json={"content": ""},
        )
        assert resp.status_code == 200
        saved = (prompts_dir / "enrich.txt").read_text(encoding="utf-8")
        assert saved == ""

    def test_save_multiline_content(self, client, prompts_dir):
        content = "Line 1\nLine 2\nLine 3"
        resp = client.post(
            "/api/v1/prompts/enrich",
            json={"content": content},
        )
        assert resp.status_code == 200
        assert resp.json()["lines"] == 3


# ---------------------------------------------------------------------------
# POST /api/v1/prompts/{name}/reset
# ---------------------------------------------------------------------------


class TestResetPrompt:
    def test_reset_modified_prompt(self, client, prompts_dir):
        # First modify the prompt
        (prompts_dir / "enrich.txt").write_text("Modified", encoding="utf-8")

        # Then reset
        resp = client.post("/api/v1/prompts/enrich/reset")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["name"] == "enrich"
        assert data["content"] == "Enrich prompt content"
        assert data["is_modified"] is False
        assert data["cache_invalidated"] is True

        # Verify file was restored
        restored = (prompts_dir / "enrich.txt").read_text(encoding="utf-8")
        assert restored == "Enrich prompt content"

    def test_reset_invalid_name_returns_400(self, client):
        resp = client.post("/api/v1/prompts/BAD_NAME/reset")
        assert resp.status_code == 400

    def test_reset_nonexistent_prompt_returns_404(self, client):
        resp = client.post("/api/v1/prompts/nonexistent/reset")
        assert resp.status_code == 404

    def test_reset_without_default_file_returns_404(self, client, prompts_dir):
        # Create a prompt file without a .default counterpart
        (prompts_dir / "orphan.txt").write_text("orphan", encoding="utf-8")
        resp = client.post("/api/v1/prompts/orphan/reset")
        assert resp.status_code == 404
        assert "Default not found" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Helper function unit tests
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_validate_prompt_name_valid(self):
        from app.api import _validate_prompt_name

        # Should not raise
        _validate_prompt_name("enrich")
        _validate_prompt_name("signal_score")
        _validate_prompt_name("a1b2c3")

    def test_validate_prompt_name_invalid(self):
        from app.api import _validate_prompt_name

        with pytest.raises(Exception):
            _validate_prompt_name("UPPERCASE")
        with pytest.raises(Exception):
            _validate_prompt_name("has-dash")
        with pytest.raises(Exception):
            _validate_prompt_name("1starts_with_digit")
        with pytest.raises(Exception):
            _validate_prompt_name("")
        with pytest.raises(Exception):
            _validate_prompt_name("a" * 65)

    def test_is_modified_false_when_same(self, tmp_path):
        from app.api import _is_modified

        p = tmp_path / "test.txt"
        d = tmp_path / "test.txt.default"
        p.write_text("same content", encoding="utf-8")
        d.write_text("same content", encoding="utf-8")
        assert _is_modified(p) is False

    def test_is_modified_true_when_different(self, tmp_path):
        from app.api import _is_modified

        p = tmp_path / "test.txt"
        d = tmp_path / "test.txt.default"
        p.write_text("modified", encoding="utf-8")
        d.write_text("original", encoding="utf-8")
        assert _is_modified(p) is True

    def test_is_modified_false_when_no_default(self, tmp_path):
        from app.api import _is_modified

        p = tmp_path / "test.txt"
        p.write_text("content", encoding="utf-8")
        assert _is_modified(p) is False
