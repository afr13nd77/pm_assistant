"""Tests for _calculate_pipeline_metrics in health_scorer module."""
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


def _write_md(path: Path, frontmatter: dict = None, body: str = "") -> Path:
    """Write a .md file with optional YAML frontmatter."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["---"]
    for k, v in (frontmatter or {}).items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append(body)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _set_mtime(path: Path, mtime: float) -> None:
    """Set modification time of a file."""
    os.utime(str(path), (mtime, mtime))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCalculatePipelineMetrics:

    def test_empty_raw(self, tmp_path):
        """raw/inbound does not exist -> ratio=100.0, lag=None, raw_total=0."""
        scorer = _import_health_scorer(tmp_path)

        result = scorer._calculate_pipeline_metrics(str(tmp_path), [])

        assert result["raw_total"] == 0
        assert result["processed_count"] == 0
        assert result["backlog_count"] == 0
        assert result["ingest_ratio"] == 100.0
        assert result["avg_lag_hours"] is None
        assert result["matched_pairs"] == 0
        assert result["raw_counts"] == {"ideas": 0, "tasks": 0}

    def test_empty_raw_dirs_exist(self, tmp_path):
        """raw/inbound/ideas/ and raw/inbound/tasks/ exist but are empty -> ratio=100.0, raw_total=0."""
        scorer = _import_health_scorer(tmp_path)
        (tmp_path / "raw" / "inbound" / "ideas").mkdir(parents=True)
        (tmp_path / "raw" / "inbound" / "tasks").mkdir(parents=True)

        result = scorer._calculate_pipeline_metrics(str(tmp_path), [])

        assert result["raw_total"] == 0
        assert result["ingest_ratio"] == 100.0
        assert result["raw_counts"] == {"ideas": 0, "tasks": 0}

    def test_all_processed(self, tmp_path):
        """3 raw idea files, all have wiki copies, backlog=[] -> ratio=100.0, processed=3."""
        scorer = _import_health_scorer(tmp_path)

        for i in range(1, 4):
            _write_md(tmp_path / "raw" / "inbound" / "ideas" / f"IDEA-000{i}-desc.md")
            _write_md(
                tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / f"IDEA-000{i}-desc.md",
                frontmatter={"id": f"idea-000{i}"},
            )

        result = scorer._calculate_pipeline_metrics(str(tmp_path), [])

        assert result["raw_total"] == 3
        assert result["processed_count"] == 3
        assert result["backlog_count"] == 0
        assert result["ingest_ratio"] == 100.0

    def test_partial_backlog(self, tmp_path):
        """5 raw idea files, 2 in backlog -> ratio=60.0, processed=3, backlog=2."""
        scorer = _import_health_scorer(tmp_path)

        for i in range(1, 6):
            _write_md(tmp_path / "raw" / "inbound" / "ideas" / f"IDEA-000{i}-desc.md")

        # 2 files are in the backlog (not yet processed)
        backlog = [
            {"file": "raw/inbound/ideas/IDEA-0004-desc.md", "type": "ideas"},
            {"file": "raw/inbound/ideas/IDEA-0005-desc.md", "type": "ideas"},
        ]

        result = scorer._calculate_pipeline_metrics(str(tmp_path), backlog)

        assert result["raw_total"] == 5
        assert result["backlog_count"] == 2
        assert result["processed_count"] == 3
        assert result["ingest_ratio"] == 60.0

    def test_ingest_ratio_calculation(self, tmp_path):
        """10 raw (7 ideas + 3 tasks), 3 in backlog -> ratio=70.0."""
        scorer = _import_health_scorer(tmp_path)

        for i in range(1, 8):
            _write_md(tmp_path / "raw" / "inbound" / "ideas" / f"IDEA-{i:04d}-desc.md")
        for i in range(1, 4):
            _write_md(tmp_path / "raw" / "inbound" / "tasks" / f"task-{i:03d}.md")

        backlog = [
            {"file": "raw/inbound/ideas/IDEA-0005-desc.md", "type": "ideas"},
            {"file": "raw/inbound/ideas/IDEA-0006-desc.md", "type": "ideas"},
            {"file": "raw/inbound/ideas/IDEA-0007-desc.md", "type": "ideas"},
        ]

        result = scorer._calculate_pipeline_metrics(str(tmp_path), backlog)

        assert result["raw_total"] == 10
        assert result["backlog_count"] == 3
        assert result["processed_count"] == 7
        assert result["ingest_ratio"] == 70.0

    def test_avg_lag_positive(self, tmp_path):
        """2 matched pairs with known mtime -> avg_lag_hours=1.0."""
        scorer = _import_health_scorer(tmp_path)

        raw_mtime = 1000.0   # arbitrary epoch timestamp
        wiki_mtime = 4600.0  # raw_mtime + 3600s = +1.0h

        for i in range(1, 3):
            raw_file = _write_md(
                tmp_path / "raw" / "inbound" / "ideas" / f"IDEA-{i:04d}-desc.md",
                frontmatter={"id": f"idea-{i:04d}"},
            )
            _set_mtime(raw_file, raw_mtime)

            wiki_file = _write_md(
                tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / f"IDEA-{i:04d}-desc.md",
                frontmatter={"id": f"idea-{i:04d}"},
            )
            _set_mtime(wiki_file, wiki_mtime)

        result = scorer._calculate_pipeline_metrics(str(tmp_path), [])

        assert result["matched_pairs"] == 2
        assert result["avg_lag_hours"] == 1.0

    def test_avg_lag_null_no_matches(self, tmp_path):
        """Raw files exist, backlog=[], but no wiki pairs found -> avg_lag_hours=None."""
        scorer = _import_health_scorer(tmp_path)

        # Raw files with IDEA-ID pattern
        for i in range(1, 3):
            _write_md(
                tmp_path / "raw" / "inbound" / "ideas" / f"IDEA-{i:04d}-desc.md",
                frontmatter={"id": f"idea-{i:04d}"},
            )

        # Wiki files exist but with completely different names and ids
        for i in range(10, 12):
            _write_md(
                tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / f"IDEA-{i:04d}-other.md",
                frontmatter={"id": f"idea-{i:04d}"},
            )

        result = scorer._calculate_pipeline_metrics(str(tmp_path), [])

        assert result["avg_lag_hours"] is None
        assert result["matched_pairs"] == 0

    def test_negative_lag_clamped(self, tmp_path):
        """wiki_mtime < raw_mtime -> lag clamped to 0.0."""
        scorer = _import_health_scorer(tmp_path)

        raw_mtime = 5000.0
        wiki_mtime = 1000.0  # wiki is older than raw

        raw_file = _write_md(
            tmp_path / "raw" / "inbound" / "ideas" / "IDEA-0001-desc.md",
            frontmatter={"id": "idea-0001"},
        )
        _set_mtime(raw_file, raw_mtime)

        wiki_file = _write_md(
            tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "IDEA-0001-desc.md",
            frontmatter={"id": "idea-0001"},
        )
        _set_mtime(wiki_file, wiki_mtime)

        result = scorer._calculate_pipeline_metrics(str(tmp_path), [])

        assert result["matched_pairs"] == 1
        assert result["avg_lag_hours"] == 0.0

    def test_raw_counts_by_type(self, tmp_path):
        """4 ideas + 2 tasks -> raw_counts={"ideas": 4, "tasks": 2}."""
        scorer = _import_health_scorer(tmp_path)

        for i in range(1, 5):
            _write_md(tmp_path / "raw" / "inbound" / "ideas" / f"IDEA-{i:04d}-desc.md")
        for i in range(1, 3):
            _write_md(tmp_path / "raw" / "inbound" / "tasks" / f"task-{i:03d}.md")

        result = scorer._calculate_pipeline_metrics(str(tmp_path), [])

        assert result["raw_counts"] == {"ideas": 4, "tasks": 2}
        assert result["raw_total"] == 6

    def test_raw_dir_missing(self, tmp_path):
        """raw/inbound does not exist at all -> ratio=100.0, raw_total=0."""
        scorer = _import_health_scorer(tmp_path)

        result = scorer._calculate_pipeline_metrics(str(tmp_path), [])

        assert result["raw_total"] == 0
        assert result["ingest_ratio"] == 100.0
        assert result["raw_counts"] == {"ideas": 0, "tasks": 0}

    def test_idea_matching_by_frontmatter_id(self, tmp_path):
        """Raw idea with frontmatter id='IDEA-0001', wiki idea with same id -> matched_pairs=1."""
        scorer = _import_health_scorer(tmp_path)

        raw_mtime = 1000.0
        wiki_mtime = 4600.0

        raw_file = _write_md(
            tmp_path / "raw" / "inbound" / "ideas" / "raw-idea-unrelated-name.md",
            frontmatter={"id": "IDEA-0001"},
        )
        _set_mtime(raw_file, raw_mtime)

        wiki_file = _write_md(
            tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "wiki-idea-different-name.md",
            frontmatter={"id": "IDEA-0001"},
        )
        _set_mtime(wiki_file, wiki_mtime)

        result = scorer._calculate_pipeline_metrics(str(tmp_path), [])

        assert result["matched_pairs"] == 1

    def test_idea_matching_by_filename_pattern(self, tmp_path):
        """Raw 'IDEA-0002-description.md', wiki 'IDEA-0002-another.md' with id='idea-0002' -> matched_pairs=1."""
        scorer = _import_health_scorer(tmp_path)

        raw_mtime = 1000.0
        wiki_mtime = 4600.0

        raw_file = _write_md(
            tmp_path / "raw" / "inbound" / "ideas" / "IDEA-0002-description.md",
        )
        _set_mtime(raw_file, raw_mtime)

        wiki_file = _write_md(
            tmp_path / "wiki" / "domains" / "test-domain" / "ideas" / "IDEA-0002-another.md",
            frontmatter={"id": "idea-0002"},
        )
        _set_mtime(wiki_file, wiki_mtime)

        result = scorer._calculate_pipeline_metrics(str(tmp_path), [])

        assert result["matched_pairs"] == 1

    def test_task_matching_by_stem(self, tmp_path):
        """Raw task 'my-task.md', wiki task 'my-task.md' -> matched_pairs=1."""
        scorer = _import_health_scorer(tmp_path)

        raw_mtime = 1000.0
        wiki_mtime = 4600.0

        raw_file = _write_md(
            tmp_path / "raw" / "inbound" / "tasks" / "my-task.md",
        )
        _set_mtime(raw_file, raw_mtime)

        wiki_file = _write_md(
            tmp_path / "wiki" / "domains" / "test-domain" / "tasks" / "my-task.md",
        )
        _set_mtime(wiki_file, wiki_mtime)

        result = scorer._calculate_pipeline_metrics(str(tmp_path), [])

        assert result["matched_pairs"] == 1
        assert result["avg_lag_hours"] == 1.0
