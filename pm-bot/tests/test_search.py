"""Unit and integration tests for vault search functionality:
_extract_search_keywords, _SearchIndex.query, and GET /api/v1/search endpoint.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# _extract_search_keywords
# ---------------------------------------------------------------------------

class TestExtractSearchKeywords:
    """Tests for _extract_search_keywords() — keyword extraction from title and body."""

    def test_title_words(self):
        """Should extract words from title that are longer than 2 chars."""
        from app.vault_api import _extract_search_keywords

        result = _extract_search_keywords("Hotel Content Checker", "")
        assert "hotel" in result
        assert "content" in result
        assert "checker" in result

    def test_heading_words(self):
        """Should extract words from ## headings that are longer than 2 chars."""
        from app.vault_api import _extract_search_keywords

        result = _extract_search_keywords("Test", "## Overview section\nSome body text")
        assert "overview" in result
        assert "section" in result

    def test_body_snippet(self):
        """Should extract words from body text that are longer than 3 chars."""
        from app.vault_api import _extract_search_keywords

        result = _extract_search_keywords(
            "Test", "This is a long description about hotels and rates"
        )
        assert "long" in result
        assert "description" in result
        assert "hotels" in result
        assert "rates" in result

    def test_short_words_excluded(self):
        """Should filter out short words: title > 2 chars, body > 3 chars."""
        from app.vault_api import _extract_search_keywords

        result = _extract_search_keywords("A B CD", "an it of")
        # "A", "B" have len <= 2 -> excluded from title
        # "CD" has len == 2 -> excluded from title (> 2 required)
        # "an", "it", "of" have len <= 3 -> excluded from body
        assert result == []


# ---------------------------------------------------------------------------
# _SearchIndex.query
# ---------------------------------------------------------------------------

def _make_index(entries_data):
    """Helper: create a _SearchIndex populated with _SearchEntry objects.

    entries_data is a list of dicts with keys matching _SearchEntry fields.
    """
    from app.vault_api import _SearchEntry, _SearchIndex

    idx = _SearchIndex()
    for data in entries_data:
        idx.entries.append(_SearchEntry(
            path=data.get("path", "test.md"),
            title=data.get("title", ""),
            tags=data.get("tags", []),
            keywords=data.get("keywords", []),
            artifact_id=data.get("artifact_id", ""),
            category=data.get("category", ""),
            domain=data.get("domain", ""),
            date=data.get("date", ""),
            url=data.get("url", ""),
        ))
    return idx


class TestSearchIndexQuery:
    """Tests for _SearchIndex.query() — scoring and result ordering."""

    def test_title_bonus(self):
        """Title substring match should give +3, ranking higher than keyword-only match."""
        idx = _make_index([
            {"title": "Hotel Booking", "keywords": []},
            {"title": "Some Document", "keywords": ["hotel"]},
        ])
        results = idx.query("hotel")
        assert len(results) == 2
        # First result should be "Hotel Booking" (title match = +3)
        assert results[0]["title"] == "Hotel Booking"
        assert results[0]["score"] > results[1]["score"]

    def test_tag_match(self):
        """Exact tag match (case-insensitive) should give +2."""
        idx = _make_index([
            {"title": "Document", "tags": ["hotel"]},
        ])
        results = idx.query("hotel")
        assert len(results) == 1
        assert results[0]["score"] == 2

    def test_keyword_match(self):
        """Keyword bidirectional substring match should give +1."""
        idx = _make_index([
            {"title": "Document", "keywords": ["hotel"]},
        ])
        results = idx.query("hotel")
        assert len(results) == 1
        assert results[0]["score"] == 1

    def test_case_insensitive(self):
        """Search should be case-insensitive for both Latin and Cyrillic."""
        idx = _make_index([
            {"title": "Oteli Bronirovanie", "tags": [], "keywords": []},
        ])

        results_upper = idx.query("OTELI")
        results_lower = idx.query("oteli")
        assert len(results_upper) == 1
        assert len(results_lower) == 1
        assert results_upper[0]["score"] == results_lower[0]["score"]

    def test_case_insensitive_cyrillic(self):
        """Cyrillic case-insensitive search should work."""
        idx = _make_index([
            {"title": "Отель Бронирование"},
        ])
        results_upper = idx.query("ОТЕЛЬ")
        results_lower = idx.query("отель")
        assert len(results_upper) >= 1
        assert len(results_lower) >= 1
        assert results_upper[0]["score"] == results_lower[0]["score"]

    def test_min_word_length(self):
        """Query words shorter than 2 chars should be ignored."""
        idx = _make_index([
            {"title": "A B", "tags": ["a"], "keywords": ["a"]},
        ])
        results = idx.query("a")
        assert results == []

    def test_empty_index(self):
        """Empty index should return empty results."""
        idx = _make_index([])
        results = idx.query("hotel")
        assert results == []

    def test_limit(self):
        """Limit parameter should restrict the number of returned results."""
        entries = [{"title": f"Hotel {i}"} for i in range(10)]
        idx = _make_index(entries)
        results = idx.query("hotel", limit=3)
        assert len(results) == 3

    def test_exact_artifact_id_match(self):
        """Exact artifact ID match should give +10, ranking first."""
        idx = _make_index([
            {"title": "Интеграция бота с Jira", "artifact_id": "IDEA-0023", "keywords": ["интеграция"]},
            {"title": "Another idea about Jira", "keywords": ["idea", "jira"]},
        ])
        results = idx.query("IDEA-0023")
        assert len(results) >= 1
        assert results[0]["artifact_id"] == "IDEA-0023"
        assert results[0]["score"] >= 10

    def test_artifact_id_case_insensitive(self):
        """Artifact ID match should be case-insensitive."""
        idx = _make_index([
            {"title": "Task", "artifact_id": "GO-156"},
        ])
        results = idx.query("go-156")
        assert len(results) == 1
        assert results[0]["score"] >= 10

    def test_artifact_id_no_false_positive(self):
        """Partial ID should NOT trigger exact ID match bonus."""
        idx = _make_index([
            {"title": "Task", "artifact_id": "IDEA-0023"},
        ])
        results = idx.query("IDEA-002")
        # Should NOT get +10 (not exact match), but may get keyword/title partial
        for r in results:
            assert r["score"] < 10


# ---------------------------------------------------------------------------
# _extract_artifact_id
# ---------------------------------------------------------------------------

class TestExtractArtifactId:
    """Tests for _extract_artifact_id() — ID extraction from frontmatter/filename."""

    def test_from_frontmatter_id(self):
        """Should extract id from frontmatter 'id' field."""
        from app.vault_api import _extract_artifact_id
        note = {"id": "IDEA-0023"}
        result = _extract_artifact_id(note, Path("some-file.md"))
        assert result == "IDEA-0023"

    def test_from_frontmatter_jira_key(self):
        """Should extract jira_key when id is absent."""
        from app.vault_api import _extract_artifact_id
        note = {"jira_key": "GO-156"}
        result = _extract_artifact_id(note, Path("some-file.md"))
        assert result == "GO-156"

    def test_from_filename(self):
        """Should extract ID from filename pattern PREFIX-NUMBER."""
        from app.vault_api import _extract_artifact_id
        note = {}
        result = _extract_artifact_id(note, Path("PLATFORM-10272-some-task.md"))
        assert result == "PLATFORM-10272"

    def test_id_priority_over_jira_key(self):
        """Frontmatter 'id' takes priority over 'jira_key'."""
        from app.vault_api import _extract_artifact_id
        note = {"id": "IDEA-0023", "jira_key": "GO-156"}
        result = _extract_artifact_id(note, Path("test.md"))
        assert result == "IDEA-0023"

    def test_no_id(self):
        """Should return empty string when no ID found."""
        from app.vault_api import _extract_artifact_id
        note = {}
        result = _extract_artifact_id(note, Path("some-random-file.md"))
        assert result == ""


# ---------------------------------------------------------------------------
# GET /api/v1/search endpoint
# ---------------------------------------------------------------------------

class TestSearchEndpoint:
    """Integration tests for the GET /api/v1/search endpoint."""

    @pytest.fixture
    def search_client(self):
        """TestClient with a pre-built search index."""
        from app.vault_api import _cache, _SearchEntry, _SearchIndex, app

        idx = _SearchIndex()
        idx.entries.append(_SearchEntry(
            path="test.md",
            title="Test Document",
            tags=["test"],
            keywords=["document"],
            category="idea",
            domain="d1",
            date="2026-01-01",
            url="ideas.html",
        ))

        with patch("app.vault_api._get_search_index", return_value=idx):
            from fastapi.testclient import TestClient
            _cache.invalidate()
            yield TestClient(app)

    def test_valid_query(self, search_client):
        """Valid search query should return 200 with query, total, results."""
        resp = search_client.get("/api/v1/search", params={"q": "test"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "test"
        assert "total" in data
        assert "results" in data
        assert data["total"] >= 1

    def test_short_query(self, search_client):
        """Query shorter than 2 chars should return 422 validation error."""
        resp = search_client.get("/api/v1/search", params={"q": "a"})
        assert resp.status_code == 422

    def test_no_query(self, search_client):
        """Missing query parameter should return 422 validation error."""
        resp = search_client.get("/api/v1/search")
        assert resp.status_code == 422
