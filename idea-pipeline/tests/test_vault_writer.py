"""Unit tests for the updated domain-based vault_writer module."""

import json
import os
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest
import frontmatter

# Make the app/ directory importable as 'idea_pipeline'
_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "app" / ".."))

# We need to set VAULT_PATH before importing vault_paths so it picks up a
# temp directory instead of /vault.  The fixtures below handle this.


@pytest.fixture()
def vault_tmp(tmp_path):
    """Provide a temporary vault directory and patch vault_paths.VAULT_PATH."""
    with patch.dict(os.environ, {"VAULT_PATH": str(tmp_path)}):
        # Reimport vault_paths so VAULT_PATH is recalculated
        import idea_pipeline.vault_paths as vp
        vp.VAULT_PATH = tmp_path
        yield tmp_path


@pytest.fixture()
def _import_writer(vault_tmp):
    """Import vault_writer after vault_paths is patched."""
    import idea_pipeline.vault_writer as vw
    return vw


# ── get_pipeline_context ─────────────────────────────────────────────


def test_get_pipeline_context_creates_dirs(vault_tmp, _import_writer):
    vw = _import_writer
    ctx = vw.get_pipeline_context("my-idea", "travel")

    assert ctx["domain"] == "travel"
    assert ctx["slug"] == "my-idea"

    assert ctx["ideas_dir"].exists()
    assert ctx["prds_dir"].exists()
    assert ctx["epics_dir"].exists()
    assert ctx["tasks_dir"].exists()
    assert ctx["raw_dir"].exists()

    assert "wiki" in str(ctx["ideas_dir"])
    assert "domains" in str(ctx["ideas_dir"])
    assert "travel" in str(ctx["ideas_dir"])
    assert "ideas" in str(ctx["ideas_dir"])


# ── write_input ──────────────────────────────────────────────────────


def test_write_input_creates_file_in_raw(vault_tmp, _import_writer):
    vw = _import_writer
    today = date.today().isoformat()
    path = vw.write_input(
        text="Test idea text",
        pipeline_id="pid-001",
        input_type="text",
        slug="test-idea",
        domain="travel",
    )

    assert path.exists()
    assert path.name == f"{today}-test-idea-input.md"
    assert "raw" in str(path)
    assert "inbound" in str(path)
    assert "ideas" in str(path)

    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    assert post.metadata["pipeline_id"] == "pid-001"
    assert post.metadata["domain"] == "travel"
    assert post.metadata["input_type"] == "text"
    assert post.content == "Test idea text"


# ── write_analysis ───────────────────────────────────────────────────


def test_write_analysis_creates_file_in_domain(vault_tmp, _import_writer):
    vw = _import_writer
    today = date.today().isoformat()

    content = "---\ntitle: Analysis\n---\n# Analysis body"
    path = vw.write_analysis(
        content=content,
        pipeline_id="pid-001",
        model="claude-sonnet-4-20250514",
        slug="test-idea",
        domain="travel",
    )

    assert path.exists()
    assert path.name == f"{today}-test-idea-analysis.md"
    assert "wiki" in str(path) and "domains" in str(path) and "travel" in str(path)
    assert "ideas" in str(path)

    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    assert post.metadata["pipeline_id"] == "pid-001"
    assert post.metadata["model"] == "claude-sonnet-4-20250514"
    assert post.metadata["domain"] == "travel"


# ── write_prd ────────────────────────────────────────────────────────


def test_write_prd_creates_file_in_domain(vault_tmp, _import_writer):
    vw = _import_writer
    today = date.today().isoformat()

    content = "---\ntitle: PRD\n---\n# PRD body"
    path = vw.write_prd(
        content=content,
        pipeline_id="pid-001",
        model="claude-sonnet-4-20250514",
        slug="test-idea",
        domain="travel",
    )

    assert path.exists()
    assert path.name == f"{today}-test-idea-prd.md"
    assert "prds" in str(path)

    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    assert post.metadata["pipeline_id"] == "pid-001"
    assert post.metadata["domain"] == "travel"


# ── write_epic ───────────────────────────────────────────────────────


def test_write_epic_creates_file_in_domain(vault_tmp, _import_writer):
    vw = _import_writer
    today = date.today().isoformat()

    epic_data = {
        "title": "Epic Title",
        "goal": "Epic goal",
        "success_metrics": ["Metric 1", "Metric 2"],
        "body_markdown": "Some extra body.",
        "_tasks_ref": [
            {"story_points": 3},
            {"story_points": 5},
        ],
    }
    path = vw.write_epic(
        epic_data=epic_data,
        pipeline_id="pid-001",
        model="claude-sonnet-4-20250514",
        slug="test-idea",
        domain="travel",
    )

    assert path.exists()
    assert path.name == f"{today}-test-idea-epic.md"
    assert "epics" in str(path)

    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    assert post.metadata["pipeline_id"] == "pid-001"
    assert post.metadata["domain"] == "travel"
    assert post.metadata["total_tasks"] == 2
    assert post.metadata["total_story_points"] == 8
    assert "Epic Title" in post.content


# ── write_tasks ──────────────────────────────────────────────────────


def test_write_tasks_creates_files_in_domain(vault_tmp, _import_writer):
    vw = _import_writer
    today = date.today().isoformat()

    tasks_data = [
        {
            "id": "TASK-01",
            "title": "Task One",
            "type": "backend",
            "story_points": 3,
            "priority": "high",
            "depends_on": [],
            "description_markdown": "Do something.",
        },
        {
            "id": "TASK-02",
            "title": "Task Two",
            "type": "frontend",
            "story_points": 2,
            "priority": "medium",
            "depends_on": ["TASK-01"],
            "description_markdown": "Do another thing.",
        },
    ]
    paths = vw.write_tasks(
        tasks_data=tasks_data,
        pipeline_id="pid-001",
        model="claude-sonnet-4-20250514",
        slug="test-idea",
        domain="travel",
    )

    assert len(paths) == 2
    assert paths[0].name == f"{today}-test-idea-task-01.md"
    assert paths[1].name == f"{today}-test-idea-task-02.md"
    assert all("tasks" in str(p) for p in paths)
    assert all(p.exists() for p in paths)

    post = frontmatter.loads(paths[0].read_text(encoding="utf-8"))
    assert post.metadata["pipeline_id"] == "pid-001"
    assert post.metadata["domain"] == "travel"
    assert post.metadata["task_id"] == "TASK-01"


# ── save_state / load_state ─────────────────────────────────────────


def test_save_and_load_state(vault_tmp, _import_writer):
    vw = _import_writer

    state = {"pipeline_id": "pid-001", "stage": "completed", "artifacts": []}
    path = vw.save_state(state, slug="test-idea", domain="travel")

    assert path.exists()
    assert path.name == "test-idea_state.json"
    assert "ideas" in str(path)

    loaded = vw.load_state(slug="test-idea", domain="travel")
    assert loaded is not None
    assert loaded["pipeline_id"] == "pid-001"
    assert loaded["stage"] == "completed"


def test_load_state_returns_none_when_missing(vault_tmp, _import_writer):
    vw = _import_writer
    result = vw.load_state(slug="nonexistent", domain="travel")
    assert result is None


# ── _inject_frontmatter ──────────────────────────────────────────────


def test_inject_frontmatter_adds_domain(vault_tmp, _import_writer):
    vw = _import_writer

    content = "---\ntitle: Test\n---\n# Hello"
    result = vw._inject_frontmatter(content, "pid-001", "model-x", "travel")

    post = frontmatter.loads(result)
    assert post.metadata["pipeline_id"] == "pid-001"
    assert post.metadata["model"] == "model-x"
    assert post.metadata["domain"] == "travel"
    assert post.metadata["title"] == "Test"


# ── slug sanitization ───────────────────────────────────────────────


def test_slug_is_sanitized(vault_tmp, _import_writer):
    vw = _import_writer
    ctx = vw.get_pipeline_context("My Crazy Idea!!!", "travel")
    assert ctx["slug"] == "my-crazy-idea"
