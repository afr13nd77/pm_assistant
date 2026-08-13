"""Tests for research reports API helpers (T-06, BL-198; T-01, BL-199).

Covers additive changes from T-05:
  - _build_reports_list() — scans wiki/reports/ for research-report frontmatter,
    now also surfaces outcome / outcome_details / ideas_count.
  - _match_report() — matches a research task's slug to a report file using the
    new `*-{slug}*.md` naming pattern, and now returns outcome fields too.

BL-199 additions (T-01):
  - _parse_idea_body() — parses markdown body of an idea by ## headings.
  - _build_extracted_ideas() — collects idea files referenced by research reports.
  - _build_reports_list() — now includes ideas_refs field.
"""

from __future__ import annotations

import pathlib
import textwrap

import pytest

from app.api import (
    _build_extracted_ideas,
    _build_reports_list,
    _match_report,
    _parse_idea_body,
)


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
        reports_dir = vault / "wiki" / "reports" / "signals"
        _write_report(
            reports_dir,
            "2026-08-03-test.md",
            """
            type: signal-report
            title: "Test"
            signal_date: "2026-08-03"
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
        reports_dir = vault / "wiki" / "reports" / "signals"
        _write_report(
            reports_dir,
            "2026-08-03-idea-report.md",
            """
            type: signal-report
            title: "Idea Report"
            signal_date: "2026-08-03"
            outcome: idea
            ideas_count: 2
            """,
        )

        result = _build_reports_list(str(vault))

        assert len(result) == 1
        assert result[0]["outcome"] == "idea"
        assert result[0]["ideas_count"] == 2

    def test_build_reports_list_old_report_no_outcome(self, vault):
        reports_dir = vault / "wiki" / "reports" / "signals"
        _write_report(
            reports_dir,
            "2026-06-01-old-report.md",
            """
            type: signal-report
            title: "Old Report"
            signal_date: "2026-06-01"
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


# ---------------------------------------------------------------------------
# _parse_idea_body (BL-199)
# ---------------------------------------------------------------------------


class TestParseIdeaBody:
    def test_parses_all_sections(self):
        body = textwrap.dedent("""\
            ## Проблема
            Нет автоматической отмены бронирований.

            ## Решение
            Добавить cron-задачу.

            ## Анализ
            Снизит нагрузку на поддержку.
        """)
        result = _parse_idea_body(body)

        assert result["problem"] == "Нет автоматической отмены бронирований."
        assert result["solution"] == "Добавить cron-задачу."
        assert result["rationale"] == "Снизит нагрузку на поддержку."

    def test_missing_sections_return_empty(self):
        body = "## Проблема\nТекст проблемы."
        result = _parse_idea_body(body)

        assert result["problem"] == "Текст проблемы."
        assert result["solution"] == ""
        assert result["rationale"] == ""

    def test_empty_body(self):
        result = _parse_idea_body("")

        assert result == {"problem": "", "solution": "", "rationale": ""}

    def test_unknown_headings_ignored(self):
        body = textwrap.dedent("""\
            ## Описание
            Это не парсится.
            ## Проблема
            Парсится.
        """)
        result = _parse_idea_body(body)

        assert result["problem"] == "Парсится."
        assert result["solution"] == ""

    def test_multiline_section(self):
        body = textwrap.dedent("""\
            ## Решение
            Строка 1.
            Строка 2.

            Строка 3.
        """)
        result = _parse_idea_body(body)

        assert "Строка 1." in result["solution"]
        assert "Строка 2." in result["solution"]
        assert "Строка 3." in result["solution"]


# ---------------------------------------------------------------------------
# _build_reports_list ideas_refs field (BL-199)
# ---------------------------------------------------------------------------


class TestBuildReportsListIdeasRefs:
    def test_ideas_refs_included_when_ideas_count_positive(self, vault):
        reports_dir = vault / "wiki" / "reports" / "signals"
        _write_report(
            reports_dir,
            "2026-08-03-ref-report.md",
            """
            type: signal-report
            title: "Ref Report"
            signal_date: "2026-08-03"
            outcome: idea
            ideas_count: 2
            ideas_refs:
              - idea-auto-cancel.md
              - idea-pricing-model.md
            """,
        )

        result = _build_reports_list(str(vault))

        assert len(result) == 1
        assert result[0]["ideas_refs"] == ["idea-auto-cancel.md", "idea-pricing-model.md"]

    def test_ideas_refs_empty_when_no_ideas(self, vault):
        reports_dir = vault / "wiki" / "reports" / "signals"
        _write_report(
            reports_dir,
            "2026-08-03-no-ideas.md",
            """
            type: signal-report
            title: "No Ideas"
            signal_date: "2026-08-03"
            outcome: monitor
            ideas_count: 0
            """,
        )

        result = _build_reports_list(str(vault))

        assert len(result) == 1
        assert result[0]["ideas_refs"] == []


# ---------------------------------------------------------------------------
# _build_extracted_ideas (BL-199)
# ---------------------------------------------------------------------------


def _write_idea(ideas_dir: pathlib.Path, filename: str, frontmatter: str, body: str = "") -> pathlib.Path:
    ideas_dir.mkdir(parents=True, exist_ok=True)
    content = f"---\n{textwrap.dedent(frontmatter).strip()}\n---\n\n{body}"
    path = ideas_dir / filename
    path.write_text(content, encoding="utf-8")
    return path


class TestBuildExtractedIdeas:
    def test_collects_ideas_from_reports(self, vault):
        # Create idea file
        ideas_dir = vault / "raw" / "inbound" / "ideas"
        _write_idea(
            ideas_dir,
            "idea-auto-cancel.md",
            """
            title: "Auto Cancel"
            domain: booking
            status: new
            created: "2026-08-01"
            signal_date: "2026-07-30"
            priority_hint: high
            """,
            body=textwrap.dedent("""\
                ## Проблема
                Бронирования не отменяются вовремя.

                ## Решение
                Cron-задача.
            """),
        )

        reports_list = [
            {
                "filename": "2026-08-03-report.md",
                "ideas_refs": ["idea-auto-cancel.md"],
                "ideas_count": 1,
            },
        ]

        result = _build_extracted_ideas(reports_list, str(vault))

        assert len(result) == 1
        idea = result[0]
        assert idea["filename"] == "idea-auto-cancel.md"
        assert idea["title"] == "Auto Cancel"
        assert idea["domain"] == "booking"
        assert idea["problem"] == "Бронирования не отменяются вовремя."
        assert idea["solution"] == "Cron-задача."
        assert idea["rationale"] == ""
        assert idea["report_ref"] == "2026-08-03-report.md"
        assert idea["priority_hint"] == "high"

    def test_returns_empty_when_no_refs(self, vault):
        reports_list = [
            {"filename": "report.md", "ideas_refs": []},
        ]

        result = _build_extracted_ideas(reports_list, str(vault))

        assert result == []

    def test_skips_missing_idea_files(self, vault):
        # No ideas directory at all
        reports_list = [
            {"filename": "report.md", "ideas_refs": ["nonexistent.md"]},
        ]

        result = _build_extracted_ideas(reports_list, str(vault))

        assert result == []

    def test_deduplicates_across_reports(self, vault):
        ideas_dir = vault / "raw" / "inbound" / "ideas"
        _write_idea(
            ideas_dir,
            "shared-idea.md",
            """
            title: "Shared Idea"
            domain: tech
            status: new
            created: "2026-08-01"
            """,
        )

        reports_list = [
            {"filename": "report-1.md", "ideas_refs": ["shared-idea.md"]},
            {"filename": "report-2.md", "ideas_refs": ["shared-idea.md"]},
        ]

        result = _build_extracted_ideas(reports_list, str(vault))

        # Should appear only once
        assert len(result) == 1

    def test_sorted_by_created_desc(self, vault):
        ideas_dir = vault / "raw" / "inbound" / "ideas"
        _write_idea(ideas_dir, "old-idea.md", """
            title: "Old"
            created: "2026-07-01"
        """)
        _write_idea(ideas_dir, "new-idea.md", """
            title: "New"
            created: "2026-08-01"
        """)

        reports_list = [
            {"filename": "report.md", "ideas_refs": ["old-idea.md", "new-idea.md"]},
        ]

        result = _build_extracted_ideas(reports_list, str(vault))

        assert len(result) == 2
        assert result[0]["title"] == "New"
        assert result[1]["title"] == "Old"
