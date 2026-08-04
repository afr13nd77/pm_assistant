"""Tests for idea_extractor module (T-11, T-22).

AC-38: extract_ideas принимает report_path и возвращает list[dict] с идеями
AC-39: Каждая идея содержит source='report' и report_ref=report_path.name
AC-40: Если LLM не нашёл actionable идей -- возвращает пустой список
AC-46: Функция поддерживает вызов через AgentLoop (dict-совместимый формат)
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.idea_extractor import (
    _build_extraction_prompt,
    _load_report,
    _parse_json_response,
    extract_ideas,
    extract_ideas_full,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_REPORT = """\
---
title: Test Report
date: 2026-08-01
---

# Market Analysis

Booking.com launched a new loyalty program targeting short-term rentals.
This could impact our competitive position in the OTA market.

## Key Findings

1. 15% increase in repeat bookings for competitors with loyalty programs
2. Average discount of 10% drives 25% higher conversion
"""

SAMPLE_LLM_RESPONSE = json.dumps({
    "ideas": [
        {
            "title": "Loyalty program for Sutochno.ru",
            "problem": "Competitors gaining repeat bookings through loyalty programs",
            "solution": "Implement tiered loyalty program with cashback",
            "domain": "product",
            "priority_hint": "high",
            "rationale": "15% lift in repeat bookings reported by competitors",
        },
        {
            "title": "Conversion optimization via targeted discounts",
            "problem": "Lower conversion compared to competitors offering discounts",
            "solution": "A/B test 10% discount for first-time bookers",
            "domain": "growth",
            "priority_hint": "medium",
            "rationale": "25% higher conversion with 10% discount per market data",
        },
    ]
})

SAMPLE_LLM_NO_IDEAS = json.dumps({
    "ideas": [],
    "no_ideas_reason": "Report contains only internal metrics, no actionable opportunities",
})

SAMPLE_LLM_NO_IDEAS_RU = json.dumps({
    "ideas": [],
    "no_ideas_reason": "не наш профиль, другая отрасль",
})

PROMPT_TEMPLATE = """\
Business context:
{business_context}

Report:
{report_content}

Extract actionable ideas as JSON.
"""


@pytest.fixture
def report_file(tmp_path: Path) -> Path:
    """Create a temporary report file."""
    p = tmp_path / "test-report.md"
    p.write_text(SAMPLE_REPORT, encoding="utf-8")
    return p


@pytest.fixture
def empty_report_file(tmp_path: Path) -> Path:
    """Create an empty report file."""
    p = tmp_path / "empty-report.md"
    p.write_text("", encoding="utf-8")
    return p


@pytest.fixture
def frontmatter_only_file(tmp_path: Path) -> Path:
    """Create a report with only frontmatter (no content after it)."""
    p = tmp_path / "frontmatter-only.md"
    p.write_text("---\ntitle: Empty\n---\n", encoding="utf-8")
    return p


@pytest.fixture
def mock_config() -> MagicMock:
    """Fake ModeratorConfig."""
    config = MagicMock()
    config.relevance_threshold = 6
    config.max_items_per_run = 20
    return config


# ---------------------------------------------------------------------------
# _load_report tests
# ---------------------------------------------------------------------------

class TestLoadReport:
    def test_strips_frontmatter(self, report_file: Path):
        """Frontmatter (--- ... ---) should be removed."""
        content = _load_report(report_file)
        assert "---" not in content
        assert "title: Test Report" not in content
        assert "# Market Analysis" in content

    def test_preserves_body(self, report_file: Path):
        content = _load_report(report_file)
        assert "Booking.com" in content
        assert "Key Findings" in content

    def test_empty_file_returns_empty(self, empty_report_file: Path):
        content = _load_report(empty_report_file)
        assert content == ""

    def test_frontmatter_only_returns_empty(self, frontmatter_only_file: Path):
        content = _load_report(frontmatter_only_file)
        assert content == ""

    def test_truncates_long_content(self, tmp_path: Path):
        """Reports longer than 12000 chars should be truncated."""
        long_content = "A" * 15000
        p = tmp_path / "long-report.md"
        p.write_text(long_content, encoding="utf-8")

        content = _load_report(p)
        assert len(content) <= 12000 + 50  # Allow for truncation message
        assert "[...report truncated...]" in content

    def test_missing_file_returns_empty(self, tmp_path: Path):
        content = _load_report(tmp_path / "nonexistent.md")
        assert content == ""


# ---------------------------------------------------------------------------
# _parse_json_response tests
# ---------------------------------------------------------------------------

class TestParseJsonResponse:
    def test_direct_json(self):
        data = {"ideas": [{"title": "test"}]}
        result = _parse_json_response(json.dumps(data))
        assert result == data

    def test_markdown_code_block(self):
        text = 'Some preamble\n```json\n{"ideas": [{"title": "test"}]}\n```\nSome epilogue'
        result = _parse_json_response(text)
        assert result is not None
        assert result["ideas"][0]["title"] == "test"

    def test_markdown_code_block_no_lang(self):
        text = 'Preamble\n```\n{"ideas": []}\n```'
        result = _parse_json_response(text)
        assert result is not None
        assert result["ideas"] == []

    def test_embedded_json_object(self):
        text = 'Here is the result: {"ideas": [{"title": "found"}]} end.'
        result = _parse_json_response(text)
        assert result is not None
        assert result["ideas"][0]["title"] == "found"

    def test_invalid_json_returns_none(self):
        result = _parse_json_response("This is not JSON at all")
        assert result is None

    def test_empty_string_returns_none(self):
        result = _parse_json_response("")
        assert result is None

    def test_truncated_json_missing_closing_brackets(self):
        """Truncated JSON with missing ]} at the end should parse and return partial ideas."""
        full = {
            "ideas": [
                {"title": "Idea 1", "problem": "P1", "solution": "S1",
                 "domain": "product", "priority_hint": "high", "rationale": "R1"},
                {"title": "Idea 2", "problem": "P2", "solution": "S2",
                 "domain": "growth", "priority_hint": "medium", "rationale": "R2"},
            ],
            "no_ideas_reason": "",
        }
        full_json = json.dumps(full)
        # Simulate max_tokens cutoff: remove the closing ]}
        truncated = full_json.rstrip("}")  # removes outer }
        truncated = truncated.rstrip()
        # Remove trailing ] too to simulate real truncation
        truncated = truncated.rstrip("]").rstrip().rstrip(",")
        # Now the JSON is missing the closing of the array and outer object
        # But both idea objects are complete

        result = _parse_json_response(truncated)
        assert result is not None
        assert "ideas" in result
        assert len(result["ideas"]) >= 1

    def test_truncated_json_mid_object(self):
        """Truncated JSON mid-object should return ideas up to last complete object."""
        idea1 = {"title": "Complete Idea", "problem": "P1", "solution": "S1",
                 "domain": "product", "priority_hint": "high", "rationale": "R1"}
        # Build JSON that is cut off mid-second-object
        text = '{"ideas": [' + json.dumps(idea1) + ', {"title": "Partial Idea", "prob'

        result = _parse_json_response(text)
        assert result is not None
        assert "ideas" in result
        assert len(result["ideas"]) == 1
        assert result["ideas"][0]["title"] == "Complete Idea"

    def test_truncated_json_in_markdown_block(self):
        """Truncated JSON inside markdown code fence should still be repaired."""
        idea1 = {"title": "First", "problem": "P", "solution": "S",
                 "domain": "d", "priority_hint": "h", "rationale": "R"}
        # Simulate markdown-wrapped truncated response
        text = '```json\n{"ideas": [' + json.dumps(idea1) + ', {"title": "Sec'

        result = _parse_json_response(text)
        assert result is not None
        assert len(result["ideas"]) == 1
        assert result["ideas"][0]["title"] == "First"

    def test_truncated_json_no_ideas_key_returns_none(self):
        """Truncated JSON without 'ideas' key should not be repaired."""
        text = '{"data": [{"title": "X"'
        result = _parse_json_response(text)
        assert result is None


# ---------------------------------------------------------------------------
# _build_extraction_prompt tests
# ---------------------------------------------------------------------------

class TestBuildExtractionPrompt:
    @patch("app.idea_extractor._load_prompt", return_value=PROMPT_TEMPLATE)
    def test_substitutes_placeholders(self, mock_load: MagicMock):
        result = _build_extraction_prompt("report text here", "business context here")
        assert "business context here" in result
        assert "report text here" in result
        assert "{business_context}" not in result
        assert "{report_content}" not in result

    @patch("app.idea_extractor._load_prompt", return_value="")
    def test_empty_template_returns_empty(self, mock_load: MagicMock):
        result = _build_extraction_prompt("report", "context")
        assert result == ""


# ---------------------------------------------------------------------------
# extract_ideas tests
# ---------------------------------------------------------------------------

class TestExtractIdeas:
    @patch("app.idea_extractor._load_prompt", return_value=PROMPT_TEMPLATE)
    @patch("app.idea_extractor.call_detailed")
    def test_extracts_ideas_from_report(
        self, mock_call: MagicMock, mock_prompt: MagicMock,
        report_file: Path, mock_config: MagicMock,
    ):
        """AC-38: extract_ideas returns list[dict] with ideas."""
        mock_call.return_value = (SAMPLE_LLM_RESPONSE, {"used": "claude"})

        ideas = extract_ideas(
            report_path=report_file,
            vault_path=str(report_file.parent),
            business_context="OTA company context",
            config=mock_config,
        )

        assert len(ideas) == 2
        assert ideas[0]["title"] == "Loyalty program for Sutochno.ru"
        assert ideas[1]["domain"] == "growth"

    @patch("app.idea_extractor._load_prompt", return_value=PROMPT_TEMPLATE)
    @patch("app.idea_extractor.call_detailed")
    def test_ideas_have_source_metadata(
        self, mock_call: MagicMock, mock_prompt: MagicMock,
        report_file: Path, mock_config: MagicMock,
    ):
        """AC-39: Each idea contains source='report' and report_ref."""
        mock_call.return_value = (SAMPLE_LLM_RESPONSE, {"used": "claude"})

        ideas = extract_ideas(
            report_path=report_file,
            vault_path=str(report_file.parent),
            business_context="context",
            config=mock_config,
        )

        for idea in ideas:
            assert idea["source"] == "report"
            assert idea["report_ref"] == report_file.name

    @patch("app.idea_extractor._load_prompt", return_value=PROMPT_TEMPLATE)
    @patch("app.idea_extractor.call_detailed")
    def test_no_ideas_returns_empty_list(
        self, mock_call: MagicMock, mock_prompt: MagicMock,
        report_file: Path, mock_config: MagicMock,
    ):
        """AC-40: If LLM finds no actionable ideas, return empty list."""
        mock_call.return_value = (SAMPLE_LLM_NO_IDEAS, {"used": "claude"})

        ideas = extract_ideas(
            report_path=report_file,
            vault_path=str(report_file.parent),
            business_context="context",
            config=mock_config,
        )

        assert ideas == []

    @patch("app.idea_extractor._load_prompt", return_value=PROMPT_TEMPLATE)
    @patch("app.idea_extractor.call_detailed")
    def test_llm_error_returns_empty_list(
        self, mock_call: MagicMock, mock_prompt: MagicMock,
        report_file: Path, mock_config: MagicMock,
    ):
        """LLM failure should not crash, return empty list."""
        mock_call.side_effect = RuntimeError("All providers failed")

        ideas = extract_ideas(
            report_path=report_file,
            vault_path=str(report_file.parent),
            business_context="context",
            config=mock_config,
        )

        assert ideas == []

    def test_empty_report_returns_empty_list(
        self, empty_report_file: Path, mock_config: MagicMock,
    ):
        """Empty report should not call LLM."""
        ideas = extract_ideas(
            report_path=empty_report_file,
            vault_path=str(empty_report_file.parent),
            business_context="context",
            config=mock_config,
        )

        assert ideas == []

    @patch("app.idea_extractor._load_prompt", return_value=PROMPT_TEMPLATE)
    @patch("app.idea_extractor.call_detailed")
    def test_unparseable_response_returns_empty(
        self, mock_call: MagicMock, mock_prompt: MagicMock,
        report_file: Path, mock_config: MagicMock,
    ):
        """Invalid JSON from LLM should return empty list."""
        mock_call.return_value = ("This is not JSON", {"used": "claude"})

        ideas = extract_ideas(
            report_path=report_file,
            vault_path=str(report_file.parent),
            business_context="context",
            config=mock_config,
        )

        assert ideas == []

    @patch("app.idea_extractor._load_prompt", return_value=PROMPT_TEMPLATE)
    @patch("app.idea_extractor.call_detailed")
    def test_dict_compatible_format_for_agent_loop(
        self, mock_call: MagicMock, mock_prompt: MagicMock,
        report_file: Path, mock_config: MagicMock,
    ):
        """AC-46: Return format is dict-compatible (list of dicts)."""
        mock_call.return_value = (SAMPLE_LLM_RESPONSE, {"used": "claude"})

        ideas = extract_ideas(
            report_path=report_file,
            vault_path=str(report_file.parent),
            business_context="context",
            config=mock_config,
        )

        assert isinstance(ideas, list)
        for idea in ideas:
            assert isinstance(idea, dict)
            # Check expected keys from LLM response
            assert "title" in idea
            assert "problem" in idea
            assert "solution" in idea
            # Check enrichment keys (AC-39)
            assert "source" in idea
            assert "report_ref" in idea

    @patch("app.idea_extractor._load_prompt", return_value=PROMPT_TEMPLATE)
    @patch("app.idea_extractor.call_detailed")
    def test_markdown_wrapped_response(
        self, mock_call: MagicMock, mock_prompt: MagicMock,
        report_file: Path, mock_config: MagicMock,
    ):
        """LLM response wrapped in markdown code block should be parsed."""
        wrapped = f"Here are the ideas:\n```json\n{SAMPLE_LLM_RESPONSE}\n```"
        mock_call.return_value = (wrapped, {"used": "claude"})

        ideas = extract_ideas(
            report_path=report_file,
            vault_path=str(report_file.parent),
            business_context="context",
            config=mock_config,
        )

        assert len(ideas) == 2
        assert ideas[0]["source"] == "report"


# ---------------------------------------------------------------------------
# extract_ideas_full tests (T-02, BL-198)
# ---------------------------------------------------------------------------

class TestExtractIdeasFull:
    @patch("app.idea_extractor._load_prompt", return_value=PROMPT_TEMPLATE)
    @patch("app.idea_extractor.call_detailed")
    def test_full_returns_ideas_and_empty_reason(
        self, mock_call: MagicMock, mock_prompt: MagicMock,
        report_file: Path, mock_config: MagicMock,
    ):
        """LLM returns 2 ideas with no_ideas_reason="" -> (ideas, "")."""
        mock_call.return_value = (SAMPLE_LLM_RESPONSE, {"used": "claude"})

        ideas, reason = extract_ideas_full(
            report_path=report_file,
            vault_path=str(report_file.parent),
            business_context="OTA company context",
            config=mock_config,
        )

        assert len(ideas) == 2
        assert reason == ""
        for idea in ideas:
            assert idea["source"] == "report"
            assert idea["report_ref"] == report_file.name

    @patch("app.idea_extractor._load_prompt", return_value=PROMPT_TEMPLATE)
    @patch("app.idea_extractor.call_detailed")
    def test_full_returns_empty_ideas_with_reason(
        self, mock_call: MagicMock, mock_prompt: MagicMock,
        report_file: Path, mock_config: MagicMock,
    ):
        """LLM returns ideas=[] with a no_ideas_reason -> ([], reason)."""
        mock_call.return_value = (SAMPLE_LLM_NO_IDEAS_RU, {"used": "claude"})

        ideas, reason = extract_ideas_full(
            report_path=report_file,
            vault_path=str(report_file.parent),
            business_context="context",
            config=mock_config,
        )

        assert ideas == []
        assert reason == "не наш профиль, другая отрасль"

    @patch("app.idea_extractor._load_prompt", return_value=PROMPT_TEMPLATE)
    @patch("app.idea_extractor.call_detailed")
    def test_full_empty_report_returns_reason(
        self, mock_call: MagicMock, mock_prompt: MagicMock,
        empty_report_file: Path, mock_config: MagicMock,
    ):
        """Empty report -> ([], "empty report"), LLM is not called."""
        ideas, reason = extract_ideas_full(
            report_path=empty_report_file,
            vault_path=str(empty_report_file.parent),
            business_context="context",
            config=mock_config,
        )

        assert ideas == []
        assert reason == "empty report"
        mock_call.assert_not_called()

    @patch("app.idea_extractor._load_prompt", return_value=PROMPT_TEMPLATE)
    @patch("app.idea_extractor.call_detailed")
    def test_full_llm_error_raises(
        self, mock_call: MagicMock, mock_prompt: MagicMock,
        report_file: Path, mock_config: MagicMock,
    ):
        """LLM call failure must propagate, not be swallowed."""
        mock_call.side_effect = Exception("API timeout")

        with pytest.raises(Exception, match="API timeout"):
            extract_ideas_full(
                report_path=report_file,
                vault_path=str(report_file.parent),
                business_context="context",
                config=mock_config,
            )

    @patch("app.idea_extractor._load_prompt", return_value=PROMPT_TEMPLATE)
    @patch("app.idea_extractor.call_detailed")
    def test_full_json_parse_error_raises(
        self, mock_call: MagicMock, mock_prompt: MagicMock,
        report_file: Path, mock_config: MagicMock,
    ):
        """Unparseable LLM response must raise ValueError."""
        mock_call.return_value = ("not a json", {"used": "claude"})

        with pytest.raises(ValueError):
            extract_ideas_full(
                report_path=report_file,
                vault_path=str(report_file.parent),
                business_context="context",
                config=mock_config,
            )

    @patch("app.idea_extractor._load_prompt", return_value=PROMPT_TEMPLATE)
    @patch("app.idea_extractor.call_detailed")
    def test_original_extract_ideas_unchanged(
        self, mock_call: MagicMock, mock_prompt: MagicMock,
        report_file: Path, mock_config: MagicMock,
    ):
        """extract_ideas() keeps returning list[dict] (not a tuple) -- backward compat."""
        mock_call.return_value = (SAMPLE_LLM_RESPONSE, {"used": "claude"})

        result = extract_ideas(
            report_path=report_file,
            vault_path=str(report_file.parent),
            business_context="context",
            config=mock_config,
        )

        assert isinstance(result, list)
        assert not isinstance(result, tuple)
        assert len(result) == 2
        for idea in result:
            assert isinstance(idea, dict)
