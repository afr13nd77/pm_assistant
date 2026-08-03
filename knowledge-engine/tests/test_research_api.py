"""Tests for research reports API helpers (T-06, BL-198).

Covers additive changes from T-05:
  - _build_reports_list() — scans wiki/reports/ for research-report frontmatter,
    now also surfaces outcome / outcome_details / ideas_count.
  - _match_report() — matches a research task's slug to a report file using the
    new `*-{slug}*.md` naming pattern, and now returns outcome fields too.
"""

from __future__ import annotations

import pathlib
import textwrap

import pytest

from app.api import _build_reports_list, _match_report


@pytest.fixture
def vault(tmp_path, monkeypatch):
    """Point shared.vault_paths.VAULT_PATH at a temp dir and return it."""
    from shared import vault_paths as _vp

    monkeypatch.setattr(_vp, "VAULT_PATH", pathlib.Path(tmp_path))
    return tmp_path


def _write_report(reports_dir: pathlib.Path, filename: str, frontmatter: str, body: str = "# Report\n") -> pathlib.Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    content = f"---\n{textwrap.dedent(frontmatter).strip()}\n---\n\n{body}"
    path = reports_dir / filename
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# _build_reports_list
# ---------------------------------------------------------------------------


class TestBuildReportsList:
    def test_build_reports_list_filters_by_type(self, vault):
        reports_dir = vault / "wiki" / "reports"
        _write_report(
            reports_dir,
            "2026-08-03-test.md",
            """
            type: research-report
            topic: "Test"
            date: "2026-08-03"
            """,
        )
        _write_report(
            reports_dir,
            "2026-07-24-week-30.md",
            """
            type: weekly-report
            """,
        )
        reports_dir.mkdir(parents=True, exist_ok=True)
        (reports_dir / "README.md").write_text("Just a readme, no frontmatter.\n", encoding="utf-8")

        result = _build_reports_list(str(vault))

        assert len(result) == 1
        assert result[0]["filename"] == "2026-08-03-test.md"
        assert result[0]["topic"] == "Test"
        assert result[0]["date"] == "2026-08-03"

    def test_build_reports_list_reads_outcome(self, vault):
        reports_dir = vault / "wiki" / "reports"
        _write_report(
            reports_dir,
            "2026-08-03-idea-report.md",
            """
            type: research-report
            topic: "Idea Report"
            date: "2026-08-03"
            outcome: idea
            ideas_count: 2
            """,
        )

        result = _build_reports_list(str(vault))

        assert len(result) == 1
        assert result[0]["outcome"] == "idea"
        assert result[0]["ideas_count"] == 2

    def test_build_reports_list_old_report_no_outcome(self, vault):
        reports_dir = vault / "wiki" / "reports"
        _write_report(
            reports_dir,
            "2026-06-01-old-report.md",
            """
            type: research-report
            topic: "Old Report"
            date: "2026-06-01"
            """,
        )

        result = _build_reports_list(str(vault))

        assert len(result) == 1
        assert result[0]["outcome"] is None


# ---------------------------------------------------------------------------
# _match_report
# ---------------------------------------------------------------------------


class TestMatchReport:
    def test_match_report_new_naming(self, vault):
        reports_dir = vault / "wiki" / "reports"
        _write_report(
            reports_dir,
            "2026-08-03-test-topic.md",
            """
            type: research-report
            topic: "Test Topic"
            completeness: 7
            """,
        )

        result = _match_report("test-topic", str(vault))

        assert result is not None
        assert result["report_path"] == "wiki/reports/2026-08-03-test-topic.md" or (
            "test-topic" in result["report_path"]
        )
        assert result["completeness"] == 7

    def test_match_report_reads_outcome_fields(self, vault):
        reports_dir = vault / "wiki" / "reports"
        _write_report(
            reports_dir,
            "2026-08-03-outcome-topic.md",
            """
            type: research-report
            topic: "Outcome Topic"
            completeness: 8
            outcome: idea
            outcome_details: "some details"
            ideas_count: 3
            """,
        )

        result = _match_report("outcome-topic", str(vault))

        assert result is not None
        assert result["outcome"] == "idea"
        assert result["outcome_details"] == "some details"
        assert result["ideas_count"] == 3

    def test_match_report_no_match_returns_none(self, vault):
        # reports dir exists but nothing matches the slug
        (vault / "wiki" / "reports").mkdir(parents=True, exist_ok=True)

        result = _match_report("missing-topic", str(vault))

        assert result is None
