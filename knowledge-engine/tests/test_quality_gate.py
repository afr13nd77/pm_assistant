"""Tests for quality_gate module: QualityGate class with 5 public checks."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.quality_gate import (
    DOMAIN_KEYWORDS,
    DedupResult,
    QualityGate,
    QualityResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeConfig:
    """Minimal config object mimicking ModeratorConfig."""

    quality_threshold: int = 6
    dedup_similarity_threshold: int = 8
    dedup_related_threshold: int = 6
    completeness_threshold: int = 6
    domain_auto_correct: bool = False


def _gate(tmp_path: Path, config: _FakeConfig | None = None) -> QualityGate:
    return QualityGate(
        vault_path=str(tmp_path),
        config=config or _FakeConfig(),
    )


def _make_llm_response(data: dict) -> tuple[str, dict]:
    """Simulate call_detailed return value."""
    return json.dumps(data), {"used": "claude", "errors": []}


# ---------------------------------------------------------------------------
# Dataclass basics
# ---------------------------------------------------------------------------


class TestDataclasses:
    def test_quality_result_defaults(self):
        qr = QualityResult(passed=True, score=8)
        assert qr.passed is True
        assert qr.score == 8
        assert qr.issues == []
        assert qr.improvements == {}

    def test_quality_result_with_issues(self):
        qr = QualityResult(passed=False, score=3, issues=["too vague", "no domain"])
        assert len(qr.issues) == 2
        assert qr.passed is False

    def test_dedup_result_defaults(self):
        dr = DedupResult(is_duplicate=False)
        assert dr.similar_to is None
        assert dr.similarity == 0
        assert dr.reason == ""

    def test_dedup_result_duplicate(self):
        dr = DedupResult(
            is_duplicate=True, similar_to="IDEA-0042", similarity=9, reason="same"
        )
        assert dr.is_duplicate is True
        assert dr.similar_to == "IDEA-0042"


# ---------------------------------------------------------------------------
# DOMAIN_KEYWORDS
# ---------------------------------------------------------------------------


class TestDomainKeywords:
    def test_has_expected_domains(self):
        assert "static-metadata" in DOMAIN_KEYWORDS
        assert "suggester" in DOMAIN_KEYWORDS
        assert "search-engine" in DOMAIN_KEYWORDS
        assert "partner-search-engine" in DOMAIN_KEYWORDS
        assert "general" in DOMAIN_KEYWORDS

    def test_general_is_empty(self):
        assert DOMAIN_KEYWORDS["general"] == []

    def test_each_domain_has_keywords(self):
        for domain, keywords in DOMAIN_KEYWORDS.items():
            if domain != "general":
                assert len(keywords) > 0, f"{domain} should have keywords"


# ---------------------------------------------------------------------------
# check_analysis_quality
# ---------------------------------------------------------------------------


class TestCheckAnalysisQuality:
    @patch("app.quality_gate.call_detailed")
    @patch("app.quality_gate.QualityGate._load_prompt")
    def test_idea_draft_passes(self, mock_prompt, mock_llm, tmp_path):
        """AC-17: check_analysis_quality returns QualityResult on success."""
        mock_prompt.return_value = "template {title} {problem} {solution} {domain}"
        mock_llm.return_value = _make_llm_response({
            "quality_score": 8,
            "issues": [],
            "improved_title": "",
            "improved_solution": "",
            "pass": True,
        })

        gate = _gate(tmp_path)
        result = gate.check_analysis_quality({
            "idea_draft": {
                "title": "Add caching",
                "problem": "Slow search",
                "solution": "Redis cache",
                "domain": "search-engine",
            }
        })

        assert isinstance(result, QualityResult)
        assert result.passed is True
        assert result.score == 8

    @patch("app.quality_gate.call_detailed")
    @patch("app.quality_gate.QualityGate._load_prompt")
    def test_report_brief_shape(self, mock_prompt, mock_llm, tmp_path):
        """AC-17: report_brief analysis is supported."""
        mock_prompt.return_value = "template {title} {problem} {solution} {domain}"
        mock_llm.return_value = _make_llm_response({
            "quality_score": 7,
            "issues": [],
            "improved_title": "",
            "improved_solution": "",
            "pass": True,
        })

        gate = _gate(tmp_path)
        result = gate.check_analysis_quality({
            "report_brief": {
                "topic": "Market trends",
                "questions": ["Q1?", "Q2?"],
            }
        })

        assert result.passed is True
        assert result.score == 7

    @patch("app.quality_gate.call_detailed")
    @patch("app.quality_gate.QualityGate._load_prompt")
    def test_fails_below_threshold(self, mock_prompt, mock_llm, tmp_path):
        """AC-17: quality_score below threshold -> passed=False."""
        mock_prompt.return_value = "template {title} {problem} {solution} {domain}"
        mock_llm.return_value = _make_llm_response({
            "quality_score": 4,
            "issues": ["too vague", "no product binding"],
            "improved_title": "Better title",
            "improved_solution": "Better solution",
            "pass": False,
        })

        gate = _gate(tmp_path)
        result = gate.check_analysis_quality({
            "idea_draft": {
                "title": "Improve",
                "problem": "Bad",
                "solution": "Fix",
                "domain": "general",
            }
        })

        assert result.passed is False
        assert result.score == 4
        assert len(result.issues) == 2
        assert result.improvements.get("improved_title") == "Better title"

    @patch("app.quality_gate.call_detailed", side_effect=RuntimeError("API down"))
    @patch("app.quality_gate.QualityGate._load_prompt")
    def test_llm_error_returns_safe_default(self, mock_prompt, mock_llm, tmp_path):
        """AC-17: LLM error -> QualityResult(passed=True, score=5)."""
        mock_prompt.return_value = "template {title} {problem} {solution} {domain}"

        gate = _gate(tmp_path)
        result = gate.check_analysis_quality({
            "idea_draft": {
                "title": "X",
                "problem": "Y",
                "solution": "Z",
                "domain": "general",
            }
        })

        assert result.passed is True
        assert result.score == 5
        assert any("LLM check failed" in i for i in result.issues)


# ---------------------------------------------------------------------------
# check_idea_quality
# ---------------------------------------------------------------------------


class TestCheckIdeaQuality:
    @patch("app.quality_gate.call_detailed")
    @patch("app.quality_gate.QualityGate._load_prompt")
    def test_high_quality_idea(self, mock_prompt, mock_llm, tmp_path):
        """AC-21: High-quality idea passes."""
        mock_prompt.return_value = "template {title} {problem} {solution} {domain}"
        mock_llm.return_value = _make_llm_response({
            "quality_score": 9,
            "criterion_scores": {
                "конкретность": 2, "привязка": 2, "обоснование": 2,
                "реализуемость": 1, "ценность": 2,
            },
            "issues": [],
            "improved_title": "",
            "improved_solution": "",
            "pass": True,
        })

        gate = _gate(tmp_path)
        result = gate.check_idea_quality({
            "title": "Add Redis cache to search API",
            "problem": "Search response time > 2s",
            "solution": "Implement Redis cache layer for search results",
            "domain": "search-engine",
        })

        assert result.passed is True
        assert result.score == 9

    @patch("app.quality_gate.call_detailed")
    @patch("app.quality_gate.QualityGate._load_prompt")
    def test_low_quality_idea_with_improvements(self, mock_prompt, mock_llm, tmp_path):
        """AC-21: Low-quality idea returns improvements."""
        mock_prompt.return_value = "template {title} {problem} {solution} {domain}"
        mock_llm.return_value = _make_llm_response({
            "quality_score": 3,
            "issues": ["слишком абстрактно", "нет привязки к компоненту"],
            "improved_title": "Concrete title",
            "improved_solution": "Concrete solution",
            "pass": False,
        })

        gate = _gate(tmp_path)
        result = gate.check_idea_quality({
            "title": "Improve stuff",
            "problem": "Bad",
            "solution": "Make better",
            "domain": "general",
        })

        assert result.passed is False
        assert result.score == 3
        assert result.improvements.get("improved_title") == "Concrete title"
        assert result.improvements.get("improved_solution") == "Concrete solution"


# ---------------------------------------------------------------------------
# check_dedup
# ---------------------------------------------------------------------------


class TestCheckDedup:
    @patch("app.quality_gate.QualityGate._load_existing_ideas")
    def test_no_existing_ideas_returns_unique(self, mock_load, tmp_path):
        """AC-20: No existing ideas -> unique."""
        mock_load.return_value = []

        gate = _gate(tmp_path)
        result = gate.check_dedup({"title": "New idea", "problem": "Problem"})

        assert isinstance(result, DedupResult)
        assert result.is_duplicate is False

    @patch("app.quality_gate.call_detailed")
    @patch("app.quality_gate.QualityGate._load_prompt")
    @patch("app.quality_gate.QualityGate._load_existing_ideas")
    def test_duplicate_detected(self, mock_load, mock_prompt, mock_llm, tmp_path):
        """AC-20: Duplicate with similarity >= 8."""
        mock_load.return_value = [
            {"id": "IDEA-0001", "title": "Add Redis cache", "domain": "search-engine",
             "problem": "Slow search response"},
        ]
        mock_prompt.return_value = (
            "candidates: {candidates_list}\n"
            "title: {title}\nproblem: {problem}\nsolution: {solution}"
        )
        mock_llm.return_value = _make_llm_response({
            "is_duplicate": True,
            "similar_to": "IDEA-0001",
            "similarity": 9,
            "reason": "Same problem and solution",
        })

        gate = _gate(tmp_path)
        result = gate.check_dedup({
            "title": "Implement Redis caching",
            "problem": "Search is slow",
            "solution": "Add Redis",
        })

        assert result.is_duplicate is True
        assert result.similar_to == "IDEA-0001"
        assert result.similarity == 9

    @patch("app.quality_gate.call_detailed")
    @patch("app.quality_gate.QualityGate._load_prompt")
    @patch("app.quality_gate.QualityGate._load_existing_ideas")
    def test_related_but_not_duplicate(self, mock_load, mock_prompt, mock_llm, tmp_path):
        """AC-20: Related idea (similarity 6-7) is not marked as duplicate."""
        mock_load.return_value = [
            {"id": "IDEA-0002", "title": "Optimize search ranking",
             "domain": "search-engine", "problem": "Bad relevance"},
        ]
        mock_prompt.return_value = (
            "candidates: {candidates_list}\n"
            "title: {title}\nproblem: {problem}\nsolution: {solution}"
        )
        mock_llm.return_value = _make_llm_response({
            "is_duplicate": False,
            "similar_to": "IDEA-0002",
            "similarity": 6,
            "reason": "Same domain but different approach",
        })

        gate = _gate(tmp_path)
        result = gate.check_dedup({
            "title": "Improve search filters",
            "problem": "Users can't find what they need",
            "solution": "Add faceted search",
        })

        assert result.is_duplicate is False
        assert result.similarity == 6

    @patch("app.quality_gate.call_detailed", side_effect=RuntimeError("timeout"))
    @patch("app.quality_gate.QualityGate._load_prompt")
    @patch("app.quality_gate.QualityGate._load_existing_ideas")
    def test_llm_error_returns_not_duplicate(
        self, mock_load, mock_prompt, mock_llm, tmp_path
    ):
        """AC-20: LLM error -> treat as not duplicate."""
        mock_load.return_value = [
            {"id": "IDEA-0003", "title": "Some idea", "domain": "general",
             "problem": "Some problem"},
        ]
        mock_prompt.return_value = "template {candidates_list} {title} {problem} {solution}"

        gate = _gate(tmp_path)
        result = gate.check_dedup({
            "title": "Some idea variation",
            "problem": "Some problem variation",
        })

        assert result.is_duplicate is False
        assert "LLM check failed" in result.reason


# ---------------------------------------------------------------------------
# check_report_completeness
# ---------------------------------------------------------------------------


class TestCheckReportCompleteness:
    @patch("app.quality_gate.call_detailed")
    @patch("app.quality_gate.QualityGate._load_prompt")
    def test_complete_report(self, mock_prompt, mock_llm, tmp_path):
        """AC-22: Complete report passes."""
        report = tmp_path / "report.md"
        report.write_text("# Report\nDetailed analysis...", encoding="utf-8")

        mock_prompt.return_value = (
            "questions: {original_questions}\n"
            "report: {report_content_first_3000_tokens}"
        )
        mock_llm.return_value = _make_llm_response({
            "completeness": 8,
            "answered_questions": [1, 2, 3],
            "unanswered_questions": [],
            "unsourced_claims_count": 0,
            "has_enough_for_ideas": True,
            "pass": True,
        })

        gate = _gate(tmp_path)
        result = gate.check_report_completeness(
            report, ["Question 1?", "Question 2?", "Question 3?"]
        )

        assert result.passed is True
        assert result.score == 8
        assert result.improvements["has_enough_for_ideas"] is True

    @patch("app.quality_gate.call_detailed")
    @patch("app.quality_gate.QualityGate._load_prompt")
    def test_incomplete_report_fails(self, mock_prompt, mock_llm, tmp_path):
        """AC-22: completeness < 4 -> not passed."""
        report = tmp_path / "report.md"
        report.write_text("# Report\nShort.", encoding="utf-8")

        mock_prompt.return_value = (
            "questions: {original_questions}\n"
            "report: {report_content_first_3000_tokens}"
        )
        mock_llm.return_value = _make_llm_response({
            "completeness": 3,
            "answered_questions": [1],
            "unanswered_questions": [2, 3],
            "unsourced_claims_count": 2,
            "has_enough_for_ideas": False,
            "pass": False,
        })

        gate = _gate(tmp_path)
        result = gate.check_report_completeness(
            report, ["Q1?", "Q2?", "Q3?"]
        )

        assert result.passed is False
        assert result.score == 3
        assert any("Unanswered" in i for i in result.issues)

    @patch("app.quality_gate.call_detailed")
    @patch("app.quality_gate.QualityGate._load_prompt")
    def test_marginal_report_passes_with_warning(self, mock_prompt, mock_llm, tmp_path):
        """AC-22: completeness 4-5 -> passed but with _quality_warning."""
        report = tmp_path / "report.md"
        report.write_text("# Report\nSome content.", encoding="utf-8")

        mock_prompt.return_value = (
            "questions: {original_questions}\n"
            "report: {report_content_first_3000_tokens}"
        )
        mock_llm.return_value = _make_llm_response({
            "completeness": 5,
            "answered_questions": [1, 2],
            "unanswered_questions": [3],
            "unsourced_claims_count": 1,
            "has_enough_for_ideas": True,
            "pass": True,
        })

        gate = _gate(tmp_path)
        result = gate.check_report_completeness(report, ["Q1?", "Q2?", "Q3?"])

        assert result.passed is True
        assert result.score == 5
        assert result.improvements.get("_quality_warning") is True

    def test_empty_report_fails(self, tmp_path):
        """AC-22: Empty report file -> not passed."""
        report = tmp_path / "empty.md"
        report.write_text("", encoding="utf-8")

        gate = _gate(tmp_path)
        result = gate.check_report_completeness(report, ["Q1?"])

        assert result.passed is False
        assert result.score == 1

    def test_missing_report_fails(self, tmp_path):
        """AC-22: Missing report file -> not passed."""
        report = tmp_path / "missing.md"

        gate = _gate(tmp_path)
        result = gate.check_report_completeness(report, ["Q1?"])

        assert result.passed is False
        assert result.score == 1


# ---------------------------------------------------------------------------
# check_domain
# ---------------------------------------------------------------------------


class TestCheckDomain:
    def test_correct_domain_detected(self, tmp_path):
        """AC-23: Keyword match confirms domain."""
        gate = _gate(tmp_path)
        is_correct, suggestion = gate.check_domain({
            "title": "Improve search ranking",
            "problem": "Bad relevance in search results",
            "solution": "Tune ranking algorithm",
            "domain": "search-engine",
        })

        assert is_correct is True
        assert suggestion is None

    def test_no_keyword_match_trusts_llm(self, tmp_path):
        """AC-23: No keywords matched -> trust LLM domain."""
        gate = _gate(tmp_path)
        is_correct, suggestion = gate.check_domain({
            "title": "Add dark mode",
            "problem": "Users want dark theme",
            "solution": "Implement CSS dark mode",
            "domain": "frontend",
        })

        assert is_correct is True
        assert suggestion is None

    def test_domain_mismatch_without_auto_correct(self, tmp_path):
        """AC-23: Mismatch detected, but auto_correct=False -> trust LLM."""
        config = _FakeConfig()
        config.domain_auto_correct = False

        gate = _gate(tmp_path, config)
        is_correct, suggestion = gate.check_domain({
            "title": "Add typeahead suggestions",
            "problem": "Users type slowly",
            "solution": "Add autocomplete with suggestions",
            "domain": "search-engine",  # should be suggester
        })

        assert is_correct is True
        assert suggestion is None

    def test_domain_mismatch_with_auto_correct(self, tmp_path):
        """AC-24: Mismatch + auto_correct=True -> return (False, best_domain)."""
        config = _FakeConfig()
        config.domain_auto_correct = True

        gate = _gate(tmp_path, config)
        is_correct, suggestion = gate.check_domain({
            "title": "Add typeahead autocomplete suggestions",
            "problem": "Users need better autocomplete",
            "solution": "Implement typeahead suggester with prefix matching",
            "domain": "search-engine",  # keywords match "suggester" more
        })

        assert is_correct is False
        assert suggestion == "suggester"

    def test_partner_search_domain(self, tmp_path):
        """AC-23: Partner-search-engine keywords detected correctly."""
        gate = _gate(tmp_path)
        is_correct, suggestion = gate.check_domain({
            "title": "Supplier onboarding",
            "problem": "Partner integration is manual",
            "solution": "Automated supplier registration",
            "domain": "partner-search-engine",
        })

        assert is_correct is True
        assert suggestion is None


# ---------------------------------------------------------------------------
# _keyword_overlap
# ---------------------------------------------------------------------------


class TestKeywordOverlap:
    def test_basic_overlap(self, tmp_path):
        gate = _gate(tmp_path)
        existing = [
            {"id": "A", "title": "Redis cache for search", "problem": "Slow search"},
            {"id": "B", "title": "Dark mode UI", "problem": "Bright screen"},
            {"id": "C", "title": "Search ranking tuning", "problem": "Bad search results"},
        ]

        candidates = gate._keyword_overlap(
            {"title": "Search optimization", "problem": "Slow search response"},
            existing,
            top_n=2,
        )

        assert len(candidates) <= 2
        # "A" and "C" should rank higher (both share "search" words)
        candidate_ids = [c["id"] for c in candidates]
        assert "B" not in candidate_ids or len(candidates) < 2

    def test_no_overlap(self, tmp_path):
        gate = _gate(tmp_path)
        existing = [
            {"id": "X", "title": "ABC DEF", "problem": "GHI JKL"},
        ]

        candidates = gate._keyword_overlap(
            {"title": "Unrelated topic here", "problem": "Completely different"},
            existing,
            top_n=5,
        )

        # Words need to be >= 3 chars. Check if there's genuine no overlap
        # between the two sets of words.
        assert isinstance(candidates, list)

    def test_empty_existing(self, tmp_path):
        gate = _gate(tmp_path)
        candidates = gate._keyword_overlap(
            {"title": "Something", "problem": "Problem"},
            [],
            top_n=5,
        )
        assert candidates == []


# ---------------------------------------------------------------------------
# _load_existing_ideas (with vault fixture)
# ---------------------------------------------------------------------------


class TestLoadExistingIdeas:
    @patch("app.quality_gate.vault_paths")
    def test_caching(self, mock_vp, tmp_path):
        """Ideas are loaded once and cached."""
        mock_vp.all_domains.return_value = []

        gate = _gate(tmp_path)
        # First call loads
        ideas1 = gate._load_existing_ideas()
        # Second call uses cache
        ideas2 = gate._load_existing_ideas()

        assert ideas1 is ideas2
        mock_vp.all_domains.assert_called_once()

    @patch("app.quality_gate.read_frontmatter")
    @patch("app.quality_gate.vault_paths")
    def test_loads_from_vault(self, mock_vp, mock_fm, tmp_path):
        """Ideas are loaded from wiki/domains/*/ideas/*.md."""
        domain_ideas = tmp_path / "ideas"
        domain_ideas.mkdir()
        idea_file = domain_ideas / "IDEA-0001.md"
        idea_file.write_text("# Test idea\nBody", encoding="utf-8")

        mock_vp.all_domains.return_value = ["search-engine"]
        mock_vp.wiki_domain_dir.return_value = domain_ideas
        mock_fm.return_value = (
            {"id": "IDEA-0001", "status": "inbox", "title": "Test idea"},
            "# Test idea\nBody",
        )

        gate = _gate(tmp_path)
        ideas = gate._load_existing_ideas()

        assert len(ideas) == 1
        assert ideas[0]["id"] == "IDEA-0001"
        assert ideas[0]["domain"] == "search-engine"

    @patch("app.quality_gate.vault_paths")
    def test_skips_service_files(self, mock_vp, tmp_path):
        """index.md and log.md are skipped."""
        domain_ideas = tmp_path / "ideas"
        domain_ideas.mkdir()
        (domain_ideas / "index.md").write_text("---\ntype: index\n---\n", encoding="utf-8")
        (domain_ideas / "log.md").write_text("---\ntype: log\n---\n", encoding="utf-8")

        mock_vp.all_domains.return_value = ["general"]
        mock_vp.wiki_domain_dir.return_value = domain_ideas

        gate = _gate(tmp_path)
        ideas = gate._load_existing_ideas()

        assert len(ideas) == 0


# ---------------------------------------------------------------------------
# _parse_json_response
# ---------------------------------------------------------------------------


class TestParseJsonResponse:
    def test_raw_json(self, tmp_path):
        gate = _gate(tmp_path)
        data = {"quality_score": 7, "pass": True}
        result = gate._parse_json_response(json.dumps(data))
        assert result == data

    def test_markdown_code_block(self, tmp_path):
        gate = _gate(tmp_path)
        text = 'Some text\n```json\n{"quality_score": 8}\n```\nMore text'
        result = gate._parse_json_response(text)
        assert result is not None
        assert result["quality_score"] == 8

    def test_embedded_json(self, tmp_path):
        gate = _gate(tmp_path)
        text = 'Here is my analysis: {"score": 5, "pass": false} end.'
        result = gate._parse_json_response(text)
        assert result is not None
        assert result["score"] == 5

    def test_unparseable_returns_none(self, tmp_path):
        gate = _gate(tmp_path)
        result = gate._parse_json_response("no json here at all")
        assert result is None

    def test_markdown_block_without_json_label(self, tmp_path):
        gate = _gate(tmp_path)
        text = '```\n{"key": "value"}\n```'
        result = gate._parse_json_response(text)
        assert result is not None
        assert result["key"] == "value"


# ---------------------------------------------------------------------------
# _load_prompt
# ---------------------------------------------------------------------------


class TestLoadPrompt:
    def test_loads_existing_prompt(self, tmp_path):
        gate = _gate(tmp_path)
        # Use the actual quality_check.txt prompt
        content = gate._load_prompt("quality_check")
        assert len(content) > 0
        assert "{title}" in content

    def test_missing_prompt_returns_empty(self, tmp_path):
        gate = _gate(tmp_path)
        content = gate._load_prompt("nonexistent_prompt_xyz")
        assert content == ""


# ---------------------------------------------------------------------------
# Integration: QualityGate with AgentLoop
# ---------------------------------------------------------------------------


class TestQualityGateAgentLoopIntegration:
    @patch("app.quality_gate.call_detailed")
    @patch("app.quality_gate.QualityGate._load_prompt")
    def test_quality_result_compatible_with_agent_loop(
        self, mock_prompt, mock_llm, tmp_path
    ):
        """QualityResult has .passed, .score, .issues needed by AgentLoop."""
        mock_prompt.return_value = "template {title} {problem} {solution} {domain}"
        mock_llm.return_value = _make_llm_response({
            "quality_score": 4,
            "issues": ["too vague"],
            "improved_title": "",
            "improved_solution": "",
            "pass": False,
        })

        gate = _gate(tmp_path)
        qr = gate.check_analysis_quality({
            "idea_draft": {
                "title": "X",
                "problem": "Y",
                "solution": "Z",
                "domain": "general",
            }
        })

        # AgentLoop accesses these attributes
        assert hasattr(qr, "passed")
        assert hasattr(qr, "score")
        assert hasattr(qr, "issues")
        assert hasattr(qr, "improvements")
        assert isinstance(qr.passed, bool)
        assert isinstance(qr.score, int)
        assert isinstance(qr.issues, list)


# ---------------------------------------------------------------------------
# BUG-026: _extract_fields with None branches
# ---------------------------------------------------------------------------


class TestExtractFieldsBug026:
    """BUG-026: _extract_fields must use truthiness, not key-existence checks.

    When AnalysisResult.__dict__ always contains both 'idea_draft' and
    'report_brief' keys (dataclass fields default to None), the old code
    crashed with 'NoneType' object has no attribute 'get' because
    ``"idea_draft" in analysis`` was always True even when the value was None.
    """

    def test_report_brief_when_idea_draft_is_none(self, tmp_path):
        """reaction=report: idea_draft=None, report_brief has data -> use report_brief."""
        gate = _gate(tmp_path)
        analysis = {
            "idea_draft": None,
            "report_brief": {
                "topic": "Market trends in OTA",
                "questions": ["What drives growth?", "Who are competitors?"],
                "scope": "OTA market 2026",
            },
        }

        title, problem, solution, domain = gate._extract_fields(analysis)

        assert title == "Market trends in OTA"
        assert problem == "Нужен глубокий анализ"
        assert "What drives growth?" in solution
        assert "Who are competitors?" in solution
        assert domain == "general"

    def test_idea_draft_when_report_brief_is_none(self, tmp_path):
        """reaction=idea: idea_draft has data, report_brief=None -> use idea_draft."""
        gate = _gate(tmp_path)
        analysis = {
            "idea_draft": {
                "title": "Add Redis caching",
                "problem": "Search is slow",
                "solution": "Implement Redis cache layer",
                "domain": "search-engine",
            },
            "report_brief": None,
        }

        title, problem, solution, domain = gate._extract_fields(analysis)

        assert title == "Add Redis caching"
        assert problem == "Search is slow"
        assert solution == "Implement Redis cache layer"
        assert domain == "search-engine"

    def test_both_none_uses_flat_fallback(self, tmp_path):
        """Both idea_draft and report_brief are None -> flat dict fallback."""
        gate = _gate(tmp_path)
        analysis = {
            "idea_draft": None,
            "report_brief": None,
            "title": "Fallback title",
            "problem": "Fallback problem",
            "solution": "Fallback solution",
            "domain": "general",
        }

        title, problem, solution, domain = gate._extract_fields(analysis)

        assert title == "Fallback title"
        assert problem == "Fallback problem"
        assert solution == "Fallback solution"
        assert domain == "general"

    def test_both_none_no_flat_keys_returns_empty(self, tmp_path):
        """Both None and no flat keys -> empty strings with 'general' domain."""
        gate = _gate(tmp_path)
        analysis = {
            "idea_draft": None,
            "report_brief": None,
        }

        title, problem, solution, domain = gate._extract_fields(analysis)

        assert title == ""
        assert problem == ""
        assert solution == ""
        assert domain == "general"
