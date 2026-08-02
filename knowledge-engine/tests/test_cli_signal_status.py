"""Tests for CLI signal-status subcommand (T-05, BL-190)."""

import importlib
import io
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_RUN = {
    "run_id": "2026-08-03-0800",
    "digest_path": "/vault/raw/inbound/news/digest.json",
    "started_at": "2026-08-03T08:00:00",
    "status": "completed",
    "completed_at": "2026-08-03T08:00:45",
    "items": {
        "abc123": {
            "title": "Test news title here",
            "status": "completed",
            "started_at": "2026-08-03T08:00:01",
            "completed_at": "2026-08-03T08:00:10",
            "current_step": "done",
            "result_ref": "ideas/test.md",
            "iterations": 2,
            "errors": [],
            "quality_warnings": [],
            "iterations_history": [
                {"attempt": 1, "quality_score": 5, "critique": "Weak analysis", "escalated": False, "operation": "signal_analyze"},
                {"attempt": 2, "quality_score": 7, "critique": None, "escalated": True, "operation": "signal_analyze_escalation"},
            ],
            "gate_results": [
                {"gate": "quality", "passed": True, "score": 7, "failed_criteria": []},
                {"gate": "dedup", "passed": True, "similarity": 2, "compared_with": None},
            ],
            "reaction": "idea",
        }
    },
    "summary": {"total": 1, "relevant": 1, "ideas": 1, "reports": 0, "retries": 1, "errors": 0, "quality_warnings": 0},
}

_SAMPLE_RUN_2 = {
    "run_id": "2026-08-02-0800",
    "digest_path": "/vault/raw/inbound/news/digest2.json",
    "started_at": "2026-08-02T08:00:00",
    "status": "completed",
    "completed_at": "2026-08-02T08:02:05",
    "items": {},
    "summary": {"total": 3, "relevant": 2, "ideas": 0, "reports": 1, "retries": 0, "errors": 1, "quality_warnings": 0},
}

_SAMPLE_RUN_3 = {
    "run_id": "2026-08-01-0800",
    "digest_path": "/vault/raw/inbound/news/digest3.json",
    "started_at": "2026-08-01T08:00:00",
    "status": "failed",
    "completed_at": "2026-08-01T08:01:30",
    "items": {},
    "summary": {"total": 5, "relevant": 3, "ideas": 2, "reports": 0, "retries": 0, "errors": 2, "quality_warnings": 1},
}


def _create_run_file(runs_dir: Path, run_data: dict) -> Path:
    """Write a run JSON file into runs_dir."""
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / f"{run_data['run_id']}.json"
    path.write_text(json.dumps(run_data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _run_main(argv: list[str], tmp_path: Path):
    """Invoke cli.main() with argv, capturing stdout and stderr.
    Returns (exit_code, stdout_text, stderr_text).
    """
    captured_out = io.StringIO()
    captured_err = io.StringIO()
    with patch.dict(os.environ, {"VAULT_PATH": str(tmp_path)}):
        with patch.object(sys, "argv", ["knowledge_engine"] + argv):
            from app import cli
            importlib.reload(cli)
            with patch("sys.stdout", captured_out), patch("sys.stderr", captured_err):
                try:
                    cli.main()
                    exit_code = 0
                except SystemExit as e:
                    exit_code = e.code if isinstance(e.code, int) else 0
    return exit_code, captured_out.getvalue(), captured_err.getvalue()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSignalStatusNoRuns:
    def test_signal_status_no_runs_prints_message(self, tmp_path):
        """No runs_dir at all -> prints 'No runs found' and exits 0."""
        exit_code, stdout, _stderr = _run_main(
            ["signal-status", "--vault", str(tmp_path)], tmp_path
        )
        assert exit_code == 0
        assert "No runs found" in stdout


class TestSignalStatusListView:
    def test_signal_status_last_n_shows_table(self, tmp_path):
        """3 run files, --last 2 -> only 2 data rows in output."""
        runs_dir = tmp_path / "wiki" / "signals" / "runs"
        _create_run_file(runs_dir, _SAMPLE_RUN)
        _create_run_file(runs_dir, _SAMPLE_RUN_2)
        _create_run_file(runs_dir, _SAMPLE_RUN_3)

        exit_code, stdout, _stderr = _run_main(
            ["signal-status", "--vault", str(tmp_path), "--last", "2"], tmp_path
        )
        assert exit_code == 0
        lines = [l for l in stdout.strip().split("\n") if l.strip()]
        # header + separator + 2 data rows = 4 lines
        data_lines = [l for l in lines if l.startswith("2026-")]
        assert len(data_lines) == 2

    def test_signal_status_table_format_headers(self, tmp_path):
        """Default table format includes expected column headers."""
        runs_dir = tmp_path / "wiki" / "signals" / "runs"
        _create_run_file(runs_dir, _SAMPLE_RUN)

        exit_code, stdout, _stderr = _run_main(
            ["signal-status", "--vault", str(tmp_path)], tmp_path
        )
        assert exit_code == 0
        assert "RUN" in stdout
        assert "STATUS" in stdout
        assert "TOTAL" in stdout

    def test_signal_status_skips_corrupted_files(self, tmp_path):
        """Corrupted JSON file is skipped, remaining runs are shown."""
        runs_dir = tmp_path / "wiki" / "signals" / "runs"
        _create_run_file(runs_dir, _SAMPLE_RUN)
        # Create corrupted file
        corrupted = runs_dir / "2026-08-04-0800.json"
        corrupted.write_text("{invalid json!!!", encoding="utf-8")

        exit_code, stdout, _stderr = _run_main(
            ["signal-status", "--vault", str(tmp_path)], tmp_path
        )
        assert exit_code == 0
        # The valid run should still appear
        assert "2026-08-03-0800" in stdout


class TestSignalStatusDetailView:
    def test_signal_status_run_detail_found(self, tmp_path):
        """--run with valid id shows detail view."""
        runs_dir = tmp_path / "wiki" / "signals" / "runs"
        _create_run_file(runs_dir, _SAMPLE_RUN)

        exit_code, stdout, _stderr = _run_main(
            ["signal-status", "--vault", str(tmp_path), "--run", "2026-08-03-0800"], tmp_path
        )
        assert exit_code == 0
        assert "Run: 2026-08-03-0800" in stdout
        assert "Status: completed" in stdout
        assert "Duration: 45s" in stdout
        assert "abc123" in stdout
        assert "Test news title here" in stdout

    def test_signal_status_run_not_found_exits_1(self, tmp_path):
        """--run with invalid id -> stderr message, exit 1."""
        runs_dir = tmp_path / "wiki" / "signals" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)

        exit_code, _stdout, stderr = _run_main(
            ["signal-status", "--vault", str(tmp_path), "--run", "nonexistent"], tmp_path
        )
        assert exit_code == 1
        assert "Run not found: nonexistent" in stderr


class TestSignalStatusJsonFormat:
    def test_signal_status_json_format(self, tmp_path):
        """--format json outputs valid JSON."""
        runs_dir = tmp_path / "wiki" / "signals" / "runs"
        _create_run_file(runs_dir, _SAMPLE_RUN)

        exit_code, stdout, _stderr = _run_main(
            ["signal-status", "--vault", str(tmp_path), "--format", "json"], tmp_path
        )
        assert exit_code == 0
        # Parse JSON from the last non-empty line (skip log lines)
        json_line = [l for l in stdout.strip().split("\n") if l.strip()][-1]
        data = json.loads(json_line)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["run_id"] == "2026-08-03-0800"
        assert data[0]["summary"]["total"] == 1


class TestFormatDuration:
    def test_print_runs_table_formats_duration(self):
        """_format_duration: 45s -> '45s', 125s -> '2m 5s'."""
        from app.cli import _format_duration

        assert _format_duration("2026-08-03T08:00:00", "2026-08-03T08:00:45") == "45s"
        assert _format_duration("2026-08-03T08:00:00", "2026-08-03T08:02:05") == "2m 5s"
        assert _format_duration(None, "2026-08-03T08:00:45") == "-"
        assert _format_duration("2026-08-03T08:00:00", None) == "-"
        assert _format_duration(None, None) == "-"
