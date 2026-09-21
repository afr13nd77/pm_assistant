"""Unit tests for _extract_report_type function."""

import pytest

from app.routers.reports import _extract_report_type


def test_extract_report_type_valid():
    text = "---\ntype: daily\n---\n"
    assert _extract_report_type(text) == "daily"


def test_extract_report_type_no_frontmatter():
    text = "Just some plain text without any frontmatter markers."
    assert _extract_report_type(text) == "other"


def test_extract_report_type_no_type_field():
    text = "---\ntitle: My Report\ndate: 2026-07-13\n---\nBody here."
    assert _extract_report_type(text) == "other"


def test_extract_report_type_empty_value():
    text = "---\ntype:\n---\n"
    assert _extract_report_type(text) == "other"


def test_extract_report_type_single_quotes():
    text = "---\ntype: 'synthesis'\n---\n"
    assert _extract_report_type(text) == "synthesis"


def test_extract_report_type_double_quotes():
    text = '---\ntype: "weekly-status-report"\n---\n'
    assert _extract_report_type(text) == "weekly-status-report"


def test_extract_report_type_with_body():
    text = (
        "---\n"
        "title: Sprint Review\n"
        "type: planning\n"
        "date: 2026-07-13\n"
        "---\n"
        "# Sprint Review\n\n"
        "## Summary\n\n"
        "This week we completed 5 tasks.\n"
    )
    assert _extract_report_type(text) == "planning"


def test_extract_report_type_leading_whitespace():
    text = "  \n\n  ---\ntype: daily\n---\n"
    assert _extract_report_type(text) == "daily"


@pytest.mark.parametrize(
    "report_type",
    [
        "daily",
        "daily-status-report",
        "sync",
        "planning",
        "weekly-status-report",
        "synthesis",
        "supplier-profile",
        "competitor-info",
        "feature-analysis-report",
        "pm_assistant-audit",
        "analysis",
        "plan-next-week",
    ],
)
def test_extract_report_type_all_known_types(report_type):
    text = f"---\ntype: {report_type}\n---\n"
    assert _extract_report_type(text) == report_type
