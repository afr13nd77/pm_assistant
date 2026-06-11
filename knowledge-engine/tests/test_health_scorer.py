"""Tests for health_scorer._check_description_coverage."""
import importlib
import os
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_vault(tmp_path: Path):
    """Reload vault_paths so VAULT_PATH points to tmp_path."""
    with patch.dict(os.environ, {"VAULT_PATH": str(tmp_path)}):
        from app import vault_paths
        importlib.reload(vault_paths)
    return tmp_path


def _import_health_scorer(tmp_path: Path):
    """Set up vault and return a freshly-reloaded health_scorer module."""
    _setup_vault(tmp_path)
    from app import health_scorer
    importlib.reload(health_scorer)
    return health_scorer


def _write_md(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_artifact(tmp_path: Path, domain: str, artifact_type: str,
                    filename: str, body: str, status: str = "draft") -> Path:
    """Write an artifact .md file with frontmatter and body."""
    content = f"---\nstatus: {status}\ntitle: test\n---\n\n{body}"
    path = tmp_path / "wiki" / "domains" / domain / artifact_type / filename
    return _write_md(path, content)


# ---------------------------------------------------------------------------
# Tests: _check_description_coverage
# ---------------------------------------------------------------------------

class TestCheckDescriptionCoverage:

    def test_empty_vault_returns_defaults(self, tmp_path):
        """No domains at all -> total_pages=0, pct=100."""
        scorer = _import_health_scorer(tmp_path)
        result = scorer._check_description_coverage(str(tmp_path))

        assert result["total_pages"] == 0
        assert result["pages_with_description"] == 0
        assert result["pct"] == 100

    def test_empty_domain_no_artifacts(self, tmp_path):
        """Domain dir exists but has no artifact subdirs -> total_pages=0."""
        scorer = _import_health_scorer(tmp_path)
        (tmp_path / "wiki" / "domains" / "search").mkdir(parents=True)

        result = scorer._check_description_coverage(str(tmp_path))

        assert result["total_pages"] == 0
        assert result["pct"] == 100

    def test_all_files_have_descriptions(self, tmp_path):
        """All artifact files have >= 2 sentences -> pct=100."""
        scorer = _import_health_scorer(tmp_path)
        body = "This is sentence one. This is sentence two."
        _write_artifact(tmp_path, "search", "ideas", "idea-01.md", body)
        _write_artifact(tmp_path, "search", "prds", "prd-01.md", body)

        result = scorer._check_description_coverage(str(tmp_path))

        assert result["total_pages"] == 2
        assert result["pages_with_description"] == 2
        assert result["pct"] == 100

    def test_no_files_have_descriptions(self, tmp_path):
        """All artifact files have < 2 sentences -> pct=0."""
        scorer = _import_health_scorer(tmp_path)
        # Single word body -- only 1 sentence
        _write_artifact(tmp_path, "search", "ideas", "idea-01.md", "Short")
        _write_artifact(tmp_path, "search", "epics", "epic-01.md", "Minimal")

        result = scorer._check_description_coverage(str(tmp_path))

        assert result["total_pages"] == 2
        assert result["pages_with_description"] == 0
        assert result["pct"] == 0

    def test_mixed_coverage(self, tmp_path):
        """Some files have descriptions, some don't -> correct percentage."""
        scorer = _import_health_scorer(tmp_path)
        good_body = "First sentence here. Second sentence here."
        bad_body = "Only one"

        _write_artifact(tmp_path, "search", "ideas", "idea-01.md", good_body)
        _write_artifact(tmp_path, "search", "ideas", "idea-02.md", bad_body)
        _write_artifact(tmp_path, "search", "prds", "prd-01.md", good_body)
        _write_artifact(tmp_path, "search", "prds", "prd-02.md", bad_body)

        result = scorer._check_description_coverage(str(tmp_path))

        assert result["total_pages"] == 4
        assert result["pages_with_description"] == 2
        assert result["pct"] == 50

    def test_service_files_excluded(self, tmp_path):
        """Service files (index.md, log.md, etc.) are not counted."""
        scorer = _import_health_scorer(tmp_path)
        good_body = "First sentence. Second sentence."

        _write_artifact(tmp_path, "search", "ideas", "idea-01.md", good_body)
        # Service files -- should be excluded from counting
        _write_artifact(tmp_path, "search", "ideas", "index.md", "Short")
        _write_artifact(tmp_path, "search", "ideas", "log.md", "Short")
        _write_artifact(tmp_path, "search", "ideas", "decisions.md", "Short")
        _write_artifact(tmp_path, "search", "ideas", "glossary.md", "Short")

        result = scorer._check_description_coverage(str(tmp_path))

        assert result["total_pages"] == 1
        assert result["pages_with_description"] == 1
        assert result["pct"] == 100

    def test_all_six_artifact_types_scanned(self, tmp_path):
        """Files in all 6 artifact types are scanned."""
        scorer = _import_health_scorer(tmp_path)
        body = "Sentence one. Sentence two."

        for art_type in ("ideas", "prds", "epics", "userstories", "tasks", "bugs"):
            _write_artifact(tmp_path, "search", art_type, f"{art_type}-01.md", body)

        result = scorer._check_description_coverage(str(tmp_path))

        assert result["total_pages"] == 6
        assert result["pages_with_description"] == 6
        assert result["pct"] == 100

    def test_multiple_domains(self, tmp_path):
        """Files from multiple domains are all counted."""
        scorer = _import_health_scorer(tmp_path)
        good = "First sentence. Second sentence."
        bad = "Stub"

        _write_artifact(tmp_path, "search", "ideas", "idea-01.md", good)
        _write_artifact(tmp_path, "booking", "prds", "prd-01.md", bad)
        _write_artifact(tmp_path, "payments", "tasks", "task-01.md", good)

        result = scorer._check_description_coverage(str(tmp_path))

        assert result["total_pages"] == 3
        assert result["pages_with_description"] == 2
        assert result["pct"] == 67  # round(2/3*100) = 67

    def test_sentence_splitting_exclamation(self, tmp_path):
        """Exclamation marks count as sentence endings."""
        scorer = _import_health_scorer(tmp_path)
        body = "This is important! And this is the second part."
        _write_artifact(tmp_path, "search", "ideas", "idea-01.md", body)

        result = scorer._check_description_coverage(str(tmp_path))

        assert result["pages_with_description"] == 1

    def test_sentence_splitting_question(self, tmp_path):
        """Question marks count as sentence endings."""
        scorer = _import_health_scorer(tmp_path)
        body = "What is this? This is the answer."
        _write_artifact(tmp_path, "search", "ideas", "idea-01.md", body)

        result = scorer._check_description_coverage(str(tmp_path))

        assert result["pages_with_description"] == 1

    def test_sentence_splitting_double_newline(self, tmp_path):
        """Double newlines count as sentence separators."""
        scorer = _import_health_scorer(tmp_path)
        body = "First paragraph\n\nSecond paragraph"
        _write_artifact(tmp_path, "search", "ideas", "idea-01.md", body)

        result = scorer._check_description_coverage(str(tmp_path))

        assert result["pages_with_description"] == 1

    def test_empty_body_not_counted(self, tmp_path):
        """File with empty body (frontmatter only) -> not counted as having description."""
        scorer = _import_health_scorer(tmp_path)
        _write_artifact(tmp_path, "search", "ideas", "idea-01.md", "")

        result = scorer._check_description_coverage(str(tmp_path))

        assert result["total_pages"] == 1
        assert result["pages_with_description"] == 0

    def test_non_md_files_ignored(self, tmp_path):
        """Non-.md files in artifact dirs are not counted."""
        scorer = _import_health_scorer(tmp_path)
        # Create a .txt file in the artifact dir
        txt_path = tmp_path / "wiki" / "domains" / "search" / "ideas" / "notes.txt"
        txt_path.parent.mkdir(parents=True, exist_ok=True)
        txt_path.write_text("Some content. More content.", encoding="utf-8")

        result = scorer._check_description_coverage(str(tmp_path))

        assert result["total_pages"] == 0

    def test_unreadable_file_skipped(self, tmp_path):
        """Unreadable files are skipped, not crashing the function."""
        scorer = _import_health_scorer(tmp_path)
        good_body = "First sentence. Second sentence."
        _write_artifact(tmp_path, "search", "ideas", "idea-01.md", good_body)

        # Write a file with invalid frontmatter that will cause read_frontmatter to raise
        bad_path = tmp_path / "wiki" / "domains" / "search" / "ideas" / "idea-02.md"
        bad_path.write_text("---\ninvalid: [unclosed\n---\n\nBody text. More text.", encoding="utf-8")

        # Should not raise; the bad file is either skipped or parsed anyway
        result = scorer._check_description_coverage(str(tmp_path))

        assert result["total_pages"] >= 1  # at least the good file is counted
