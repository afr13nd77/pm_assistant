"""Unit tests for inline editing: _find_artifact_file, PATCH /artifact/{filename}/field, PATCH /artifact/{filename}/body."""

from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# _find_artifact_file
# ---------------------------------------------------------------------------

class TestFindArtifactFile:
    """Tests for _find_artifact_file() — searching artifacts across all domains."""

    def test_find_idea(self, tmp_path):
        """Should find an idea file in domains/*/ideas/."""
        from app.vault_scanner import _find_artifact_file

        # Create mock vault structure
        idea_dir = tmp_path / "wiki" / "domains" / "general" / "ideas"
        idea_dir.mkdir(parents=True)
        idea_file = idea_dir / "IDEA-001.md"
        idea_file.write_text("---\ntitle: test\n---\nbody", encoding="utf-8")

        with patch("app.vault_scanner.all_domains", return_value=["general"]), \
             patch("app.vault_scanner.wiki_domain_dir", side_effect=lambda d, t: tmp_path / "wiki" / "domains" / d / t), \
             patch("app.vault_scanner.VAULT_PATH", tmp_path):
            result = _find_artifact_file("IDEA-001.md")
            assert result is not None
            assert result.name == "IDEA-001.md"

    def test_find_task(self, tmp_path):
        """Should find a task file in domains/*/tasks/."""
        from app.vault_scanner import _find_artifact_file

        task_dir = tmp_path / "wiki" / "domains" / "static-metadata" / "tasks"
        task_dir.mkdir(parents=True)
        task_file = task_dir / "GO-156.md"
        task_file.write_text("---\ntitle: task\n---\nbody", encoding="utf-8")

        with patch("app.vault_scanner.all_domains", return_value=["static-metadata"]), \
             patch("app.vault_scanner.wiki_domain_dir", side_effect=lambda d, t: tmp_path / "wiki" / "domains" / d / t), \
             patch("app.vault_scanner.VAULT_PATH", tmp_path):
            result = _find_artifact_file("GO-156.md")
            assert result is not None
            assert result.name == "GO-156.md"

    def test_not_found(self, tmp_path):
        """Should return None when file doesn't exist."""
        from app.vault_scanner import _find_artifact_file

        # Create meetings dir so the fallback path exists but file is still absent
        (tmp_path / "wiki" / "meetings").mkdir(parents=True)

        with patch("app.vault_scanner.all_domains", return_value=["general"]), \
             patch("app.vault_scanner.wiki_domain_dir", side_effect=lambda d, t: tmp_path / "wiki" / "domains" / d / t), \
             patch("app.vault_scanner.VAULT_PATH", tmp_path):
            result = _find_artifact_file("nonexistent.md")
            assert result is None

    def test_find_in_meetings(self, tmp_path):
        """Should find a file in wiki/meetings/ if not in domain folders."""
        from app.vault_scanner import _find_artifact_file

        meetings_dir = tmp_path / "wiki" / "meetings"
        meetings_dir.mkdir(parents=True)
        meeting_file = meetings_dir / "2026-01-01-standup.md"
        meeting_file.write_text("---\ntitle: standup\n---\nnotes", encoding="utf-8")

        with patch("app.vault_scanner.all_domains", return_value=[]), \
             patch("app.vault_scanner.VAULT_PATH", tmp_path):
            result = _find_artifact_file("2026-01-01-standup.md")
            assert result is not None
            assert result.name == "2026-01-01-standup.md"


# ---------------------------------------------------------------------------
# PATCH /api/v1/artifact/{filename}/field
# ---------------------------------------------------------------------------

class TestUpdateField:
    """Tests for PATCH /api/v1/artifact/{filename}/field endpoint."""

    @pytest.fixture
    def field_client(self, tmp_path):
        """TestClient with a mock artifact file."""
        from app.vault_api import app
        from app.vault_cache import _cache

        idea_dir = tmp_path / "wiki" / "domains" / "general" / "ideas"
        idea_dir.mkdir(parents=True)
        idea_file = idea_dir / "IDEA-001.md"
        idea_file.write_text("---\ntitle: Test Idea\nstatus: Новая\ndomain: general\ntags: [pricing]\n---\n# Overview\nSome body", encoding="utf-8")

        def mock_find(filename):
            candidate = idea_dir / filename
            return candidate if candidate.exists() else None

        with patch("app.routers.artifacts._find_artifact_file", side_effect=mock_find):
            from fastapi.testclient import TestClient
            _cache.invalidate()
            yield TestClient(app)

    def test_update_status(self, field_client):
        """PATCH field with key=status should return 200 and update field."""
        resp = field_client.patch(
            "/api/v1/artifact/IDEA-001.md/field",
            json={"key": "status", "value": "done"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["key"] == "status"
        assert data["value"] == "done"
        assert "readiness" in data
        assert "updated" in data

    def test_invalid_key(self, field_client):
        """PATCH field with non-whitelisted key should return 400."""
        resp = field_client.patch(
            "/api/v1/artifact/IDEA-001.md/field",
            json={"key": "title", "value": "hacked"}
        )
        assert resp.status_code == 400
        assert "Invalid key" in resp.json()["detail"]

    def test_file_not_found(self, field_client):
        """PATCH field for nonexistent file should return 404."""
        resp = field_client.patch(
            "/api/v1/artifact/nonexistent.md/field",
            json={"key": "status", "value": "done"}
        )
        assert resp.status_code == 404

    def test_invalid_filename_traversal(self, field_client):
        """PATCH field with path traversal in filename should return 400."""
        # Use '..' in filename without slashes — slashes would break URL routing
        resp = field_client.patch(
            "/api/v1/artifact/..secret.md/field",
            json={"key": "status", "value": "done"}
        )
        assert resp.status_code == 400

    def test_invalid_filename_no_md(self, field_client):
        """PATCH field for non-.md filename should return 400."""
        resp = field_client.patch(
            "/api/v1/artifact/IDEA-001.txt/field",
            json={"key": "status", "value": "done"}
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# PATCH /api/v1/artifact/{filename}/body
# ---------------------------------------------------------------------------

class TestUpdateBody:
    """Tests for PATCH /api/v1/artifact/{filename}/body endpoint."""

    @pytest.fixture
    def body_client(self, tmp_path):
        """TestClient with a mock artifact file."""
        from app.vault_api import app
        from app.vault_cache import _cache

        idea_dir = tmp_path / "wiki" / "domains" / "general" / "ideas"
        idea_dir.mkdir(parents=True)
        idea_file = idea_dir / "IDEA-002.md"
        idea_file.write_text("---\ntitle: Body Test\nstatus: Новая\n---\n# Original body\nContent here", encoding="utf-8")

        def mock_find(filename):
            candidate = idea_dir / filename
            return candidate if candidate.exists() else None

        with patch("app.routers.artifacts._find_artifact_file", side_effect=mock_find):
            from fastapi.testclient import TestClient
            _cache.invalidate()
            yield TestClient(app)

    def test_update_body_success(self, body_client):
        """PATCH body should return 200 and update body."""
        resp = body_client.patch(
            "/api/v1/artifact/IDEA-002.md/body",
            json={"body": "# New body\nUpdated content"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["filename"] == "IDEA-002.md"
        assert "readiness" in data

    def test_body_preserves_frontmatter(self, body_client, tmp_path):
        """PATCH body should preserve frontmatter while replacing body."""
        body_client.patch(
            "/api/v1/artifact/IDEA-002.md/body",
            json={"body": "# New body\nReplaced"}
        )
        # Read file and check frontmatter is preserved
        idea_file = tmp_path / "wiki" / "domains" / "general" / "ideas" / "IDEA-002.md"
        text = idea_file.read_text(encoding="utf-8")
        assert "title: Body Test" in text
        assert "# New body" in text
        assert "Replaced" in text
        assert "# Original body" not in text

    def test_body_too_long(self, body_client):
        """PATCH body with >50000 chars should return 422."""
        resp = body_client.patch(
            "/api/v1/artifact/IDEA-002.md/body",
            json={"body": "x" * 50001}
        )
        assert resp.status_code == 422

    def test_body_file_not_found(self, body_client):
        """PATCH body for nonexistent file should return 404."""
        resp = body_client.patch(
            "/api/v1/artifact/nonexistent.md/body",
            json={"body": "test"}
        )
        assert resp.status_code == 404
