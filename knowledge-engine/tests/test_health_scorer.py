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
        from shared import vault_paths
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


# ---------------------------------------------------------------------------
# Helpers for ingest backlog tests
# ---------------------------------------------------------------------------

def _write_raw(tmp_path: Path, art_type: str, filename: str, frontmatter_fields: dict | None = None) -> Path:
    """Write a raw inbound .md file with optional frontmatter."""
    lines = []
    if frontmatter_fields:
        lines.append("---")
        for k, v in frontmatter_fields.items():
            lines.append(f"{k}: {v}")
        lines.append("---")
    lines.append("")
    lines.append("Body content.")
    content = "\n".join(lines)
    path = tmp_path / "raw" / "inbound" / art_type / filename
    return _write_md(path, content)


def _write_wiki_idea(tmp_path: Path, domain: str, filename: str,
                     idea_id: str | None = None) -> Path:
    """Write a wiki idea .md file with optional id in frontmatter."""
    fm = {"type": "idea", "status": "draft", "title": "test"}
    if idea_id is not None:
        fm["id"] = idea_id
    lines = ["---"]
    for k, v in fm.items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append("")
    lines.append("Wiki body.")
    content = "\n".join(lines)
    path = tmp_path / "wiki" / "domains" / domain / "ideas" / filename
    return _write_md(path, content)


def _write_wiki_task(tmp_path: Path, domain: str, filename: str) -> Path:
    """Write a wiki task .md file."""
    content = "---\nstatus: draft\ntitle: test\n---\n\nTask body."
    path = tmp_path / "wiki" / "domains" / domain / "tasks" / filename
    return _write_md(path, content)


# ---------------------------------------------------------------------------
# Tests: _check_ingest_backlog
# ---------------------------------------------------------------------------

class TestCheckIngestBacklog:

    def test_empty_vault_returns_empty(self, tmp_path):
        """No raw or wiki dirs -> empty backlog."""
        scorer = _import_health_scorer(tmp_path)
        result = scorer._check_ingest_backlog(str(tmp_path))
        assert result == []

    def test_idea_matched_by_id_different_stem(self, tmp_path):
        """Raw idea with id matching wiki idea (different stem) -> not backlog."""
        scorer = _import_health_scorer(tmp_path)
        _write_raw(tmp_path, "ideas", "IDEA-0032-rest-method.md", {"id": "IDEA-0032", "type": "idea"})
        _write_wiki_idea(tmp_path, "search-engine", "IDEA-0032-cashback.md", idea_id="IDEA-0032")

        result = scorer._check_ingest_backlog(str(tmp_path))
        assert result == []

    def test_idea_not_matched_by_id(self, tmp_path):
        """Raw idea with id NOT in wiki -> backlog."""
        scorer = _import_health_scorer(tmp_path)
        _write_raw(tmp_path, "ideas", "IDEA-0099-new-feature.md", {"id": "IDEA-0099", "type": "idea"})
        _write_wiki_idea(tmp_path, "search-engine", "IDEA-0032-cashback.md", idea_id="IDEA-0032")

        result = scorer._check_ingest_backlog(str(tmp_path))
        assert len(result) == 1
        assert result[0]["type"] == "ideas"
        assert "IDEA-0099" in result[0]["file"]

    def test_idea_id_case_insensitive(self, tmp_path):
        """Id comparison is case-insensitive."""
        scorer = _import_health_scorer(tmp_path)
        _write_raw(tmp_path, "ideas", "idea-005.md", {"id": "idea-005", "type": "idea"})
        _write_wiki_idea(tmp_path, "general", "IDEA-005-title.md", idea_id="IDEA-005")

        result = scorer._check_ingest_backlog(str(tmp_path))
        assert result == []

    def test_idea_id_with_whitespace_stripped(self, tmp_path):
        """Id values are stripped before comparison."""
        scorer = _import_health_scorer(tmp_path)
        _write_raw(tmp_path, "ideas", "idea-010.md", {"id": "  IDEA-010  ", "type": "idea"})
        _write_wiki_idea(tmp_path, "general", "IDEA-010-whatever.md", idea_id="IDEA-010")

        result = scorer._check_ingest_backlog(str(tmp_path))
        assert result == []

    def test_idea_no_id_falls_back_to_stem(self, tmp_path):
        """Raw idea without id field -> stem matching (same stem = not backlog)."""
        scorer = _import_health_scorer(tmp_path)
        _write_raw(tmp_path, "ideas", "my-idea.md", {"type": "idea"})  # no id
        _write_wiki_idea(tmp_path, "general", "my-idea.md", idea_id=None)

        result = scorer._check_ingest_backlog(str(tmp_path))
        assert result == []

    def test_idea_no_id_stem_not_found(self, tmp_path):
        """Raw idea without id, stem not in wiki -> backlog."""
        scorer = _import_health_scorer(tmp_path)
        _write_raw(tmp_path, "ideas", "unique-idea.md", {"type": "idea"})  # no id
        _write_wiki_idea(tmp_path, "general", "other-idea.md", idea_id=None)

        result = scorer._check_ingest_backlog(str(tmp_path))
        assert len(result) == 1
        assert result[0]["type"] == "ideas"

    def test_task_still_uses_stem_matching(self, tmp_path):
        """Tasks use stem matching, not id-based."""
        scorer = _import_health_scorer(tmp_path)
        _write_raw(tmp_path, "tasks", "JIRA-123-do-thing.md", {"id": "JIRA-123", "type": "task"})
        _write_wiki_task(tmp_path, "general", "JIRA-123-do-thing.md")

        result = scorer._check_ingest_backlog(str(tmp_path))
        assert result == []

    def test_task_different_stem_is_backlog(self, tmp_path):
        """Task with different stem is backlog (even if hypothetical id matches)."""
        scorer = _import_health_scorer(tmp_path)
        _write_raw(tmp_path, "tasks", "JIRA-456-new-name.md", {"id": "JIRA-456", "type": "task"})
        _write_wiki_task(tmp_path, "general", "JIRA-456-old-name.md")

        result = scorer._check_ingest_backlog(str(tmp_path))
        assert len(result) == 1
        assert result[0]["type"] == "tasks"

    def test_mixed_ideas_and_tasks(self, tmp_path):
        """Mixed scenario with ideas (id-based) and tasks (stem-based)."""
        scorer = _import_health_scorer(tmp_path)
        # Idea matched by id (different stem) -> not backlog
        _write_raw(tmp_path, "ideas", "IDEA-001-v1.md", {"id": "IDEA-001", "type": "idea"})
        _write_wiki_idea(tmp_path, "search", "IDEA-001-v2.md", idea_id="IDEA-001")
        # Idea not matched -> backlog
        _write_raw(tmp_path, "ideas", "IDEA-002-new.md", {"id": "IDEA-002", "type": "idea"})
        # Task matched by stem -> not backlog
        _write_raw(tmp_path, "tasks", "TASK-100.md", {"type": "task"})
        _write_wiki_task(tmp_path, "search", "TASK-100.md")
        # Task not matched -> backlog
        _write_raw(tmp_path, "tasks", "TASK-200.md", {"type": "task"})

        result = scorer._check_ingest_backlog(str(tmp_path))
        assert len(result) == 2
        types = {r["type"] for r in result}
        assert types == {"ideas", "tasks"}

    def test_raw_idea_bad_frontmatter_falls_back(self, tmp_path):
        """Raw idea with unreadable frontmatter falls back to filename/stem matching."""
        scorer = _import_health_scorer(tmp_path)
        # Write a valid raw idea -> backlog (no wiki match)
        _write_raw(tmp_path, "ideas", "IDEA-010-good.md", {"id": "IDEA-010", "type": "idea"})
        # Write a raw idea with broken frontmatter; IDEA-011 is 3 digits -> no filename match -> stem fallback -> backlog
        bad_path = tmp_path / "raw" / "inbound" / "ideas" / "IDEA-011-bad.md"
        bad_path.parent.mkdir(parents=True, exist_ok=True)
        bad_path.write_text("---\ninvalid: [unclosed\n---\nBody.", encoding="utf-8")

        result = scorer._check_ingest_backlog(str(tmp_path))
        # Both are in backlog: IDEA-010 (id not in wiki), IDEA-011-bad (stem not in wiki)
        assert len(result) == 2
        files = {r["file"] for r in result}
        assert any("IDEA-010" in f for f in files)
        assert any("IDEA-011" in f for f in files)

    def test_wiki_idea_bad_frontmatter_uses_stem(self, tmp_path):
        """Wiki idea with unreadable frontmatter still contributes its stem."""
        scorer = _import_health_scorer(tmp_path)
        # Wiki idea with broken frontmatter — stem still collected
        bad_wiki = tmp_path / "wiki" / "domains" / "general" / "ideas" / "my-idea.md"
        bad_wiki.parent.mkdir(parents=True, exist_ok=True)
        bad_wiki.write_text("---\ninvalid: [unclosed\n---\nBody.", encoding="utf-8")
        # Raw idea with no id, same stem -> not backlog (stem fallback)
        _write_raw(tmp_path, "ideas", "my-idea.md", {"type": "idea"})

        result = scorer._check_ingest_backlog(str(tmp_path))
        assert result == []

    def test_multiple_domains_idea_ids_merged(self, tmp_path):
        """Ids from wiki ideas across multiple domains are all considered."""
        scorer = _import_health_scorer(tmp_path)
        _write_wiki_idea(tmp_path, "search", "IDEA-001-search.md", idea_id="IDEA-001")
        _write_wiki_idea(tmp_path, "booking", "IDEA-002-booking.md", idea_id="IDEA-002")
        # Raw ideas match ids from different domains
        _write_raw(tmp_path, "ideas", "IDEA-001-raw.md", {"id": "IDEA-001", "type": "idea"})
        _write_raw(tmp_path, "ideas", "IDEA-002-raw.md", {"id": "IDEA-002", "type": "idea"})

        result = scorer._check_ingest_backlog(str(tmp_path))
        assert result == []

    def test_no_raw_dirs_returns_empty(self, tmp_path):
        """Wiki exists but no raw dirs -> empty backlog."""
        scorer = _import_health_scorer(tmp_path)
        _write_wiki_idea(tmp_path, "general", "IDEA-001.md", idea_id="IDEA-001")

        result = scorer._check_ingest_backlog(str(tmp_path))
        assert result == []

    def test_return_format_file_uses_forward_slashes(self, tmp_path):
        """Returned file paths use forward slashes."""
        scorer = _import_health_scorer(tmp_path)
        _write_raw(tmp_path, "ideas", "IDEA-099-test.md", {"id": "IDEA-099", "type": "idea"})

        result = scorer._check_ingest_backlog(str(tmp_path))
        assert len(result) == 1
        assert "\\" not in result[0]["file"]
        assert result[0]["file"] == "raw/inbound/ideas/IDEA-099-test.md"

    def test_idea_id_from_filename(self, tmp_path):
        """Raw idea without id in frontmatter matched by filename IDEA-NNNN pattern."""
        scorer = _import_health_scorer(tmp_path)
        # Raw idea has no 'id' in frontmatter, but filename contains IDEA-0032
        _write_raw(tmp_path, "ideas", "IDEA-0032-2026-04-25_getresults.md", {"type": "idea"})
        # Wiki idea has id in frontmatter
        _write_wiki_idea(tmp_path, "search-engine", "IDEA-0032-cashback.md", idea_id="IDEA-0032")

        result = scorer._check_ingest_backlog(str(tmp_path))
        assert result == []

    def test_idea_id_from_filename_both_sides(self, tmp_path):
        """Both raw and wiki idea lack frontmatter id but match via filename IDEA-NNNN."""
        scorer = _import_health_scorer(tmp_path)
        # Raw idea: no frontmatter id, filename IDEA-0032
        _write_raw(tmp_path, "ideas", "IDEA-0032-2026-04-25_getresults.md", {"type": "idea"})
        # Wiki idea: no frontmatter id, filename IDEA-0032
        _write_wiki_idea(tmp_path, "search-engine", "IDEA-0032-rest-method.md", idea_id=None)

        result = scorer._check_ingest_backlog(str(tmp_path))
        assert result == []

    def test_idea_id_frontmatter_overrides_filename(self, tmp_path):
        """Frontmatter id takes priority over filename id."""
        scorer = _import_health_scorer(tmp_path)
        # Raw idea: filename says IDEA-0099, but frontmatter says IDEA-0032
        _write_raw(tmp_path, "ideas", "IDEA-0099-wrong-name.md", {"id": "IDEA-0032", "type": "idea"})
        # Wiki idea has id IDEA-0032 in frontmatter
        _write_wiki_idea(tmp_path, "general", "IDEA-0032-correct.md", idea_id="IDEA-0032")

        result = scorer._check_ingest_backlog(str(tmp_path))
        # Should match by frontmatter id (IDEA-0032), not filename (IDEA-0099)
        assert result == []
