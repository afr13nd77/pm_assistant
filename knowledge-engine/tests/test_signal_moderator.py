"""Tests for signal_moderator module (T-10, T-20).

AC-01: score_signal returns relevance 0-10
AC-02: reason is 1 sentence / SignalData has 13 fields (BL-203)
AC-03: matched_entities is a list
AC-04: _write_skipped_md writes skipped to wiki/signals/
AC-05: analyze_signal determines reaction (idea/report)
AC-06: idea_draft contains title, problem, solution, domain
AC-07: report_brief contains topic, questions, scope
AC-08: dispatch_idea creates idea in vault
AC-10: idea contains source=signal, signal_date, signal_source
AC-15: dispatch_signal creates raw JSON + wiki MD (BL-203)
AC-16: dispatch_signal dry_run creates no files (BL-203)
AC-30: dispatch_idea sends Telegram notification
AC-31: dispatch_report sends Telegram notification
AC-43: Input format news_item: title + summary + source
AC-45: _write_processed_md writes results
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.signal_moderator import (
    AnalysisResult,
    ReportResult,
    ScoringResult,
    SignalData,
    _build_analysis_prompt,
    _build_scoring_prompt,
    _load_prompt,
    _parse_json_response,
    _write_processed_md,
    _write_skipped_md,
    analyze_signal,
    dispatch_idea,
    dispatch_report,
    dispatch_signal,
    extract_signals,
    generate_analysis_report,
    score_signal,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SCORE_PROMPT_TEMPLATE = """\
Context: {business_context}
{memory_context}
News: {news_item}
Return JSON.
"""

ANALYZE_PROMPT_TEMPLATE = """\
Context: {business_context}
Competitor: {competitor_profile}
{memory_history}
News: {news_item}
Return JSON.
"""

SAMPLE_SCORE_RESPONSE = json.dumps({
    "relevance": 8,
    "reason": "Directly related to OTA competitors",
    "matched_entities": ["Booking.com", "search-engine"],
})

SAMPLE_ANALYZE_IDEA_RESPONSE = json.dumps({
    "reaction": "idea",
    "analysis": "Booking.com launched a new feature that directly impacts our search ranking. "
                "This creates both a threat and an opportunity for Sutochno.ru.",
    "threat_level": "medium",
    "idea_draft": {
        "title": "Improve search ranking algorithm",
        "problem": "Competitors gaining advantage through better ranking",
        "solution": "Implement ML-based ranking model",
        "domain": "search-engine",
    },
    "report_brief": None,
})

SAMPLE_ANALYZE_REPORT_RESPONSE = json.dumps({
    "reaction": "report",
    "analysis": "New market entrant requires strategic analysis of their technology stack.",
    "threat_level": "high",
    "idea_draft": None,
    "report_brief": {
        "topic": "Analysis of new market entrant",
        "questions": ["What technology stack do they use?", "What is their pricing strategy?"],
        "scope": "Russian OTA market competitive landscape",
    },
})

SAMPLE_ITEM = {
    "title": "Booking.com launches AI-powered search",
    "summary": "New ML algorithm improves search relevance by 30%",
    "source": "TechCrunch",
    "source_url": "https://example.com/article",
    "date": "2026-08-01",
}


@pytest.fixture
def mock_config() -> MagicMock:
    config = MagicMock()
    config.relevance_threshold = 7
    config.quality_threshold = 6
    config.dedup_related_threshold = 6
    return config


@pytest.fixture(autouse=True)
def _clear_prompt_cache():
    """Clear module-level prompt cache before each test."""
    from app.signal_moderator import _prompt_cache
    _prompt_cache.clear()
    yield
    _prompt_cache.clear()


# ---------------------------------------------------------------------------
# _load_prompt tests
# ---------------------------------------------------------------------------


class TestLoadPrompt:
    def test_loads_existing_prompt(self):
        """signal_score.txt should exist and be loadable."""
        content = _load_prompt("signal_score")
        assert len(content) > 0
        assert "{business_context}" in content

    def test_caches_on_second_call(self):
        """Second call should return cached version."""
        content1 = _load_prompt("signal_score")
        content2 = _load_prompt("signal_score")
        assert content1 == content2

    def test_missing_prompt_returns_empty(self):
        content = _load_prompt("nonexistent_prompt")
        assert content == ""


# ---------------------------------------------------------------------------
# _parse_json_response tests
# ---------------------------------------------------------------------------


class TestParseJsonResponse:
    def test_direct_json(self):
        data = {"relevance": 7, "reason": "test"}
        result = _parse_json_response(json.dumps(data))
        assert result == data

    def test_markdown_code_block(self):
        text = 'Preamble\n```json\n{"relevance": 5}\n```\nEpilogue'
        result = _parse_json_response(text)
        assert result is not None
        assert result["relevance"] == 5

    def test_embedded_json(self):
        text = 'Here is the result: {"relevance": 9, "reason": "test"} done.'
        result = _parse_json_response(text)
        assert result is not None
        assert result["relevance"] == 9

    def test_invalid_returns_none(self):
        result = _parse_json_response("Not JSON at all")
        assert result is None

    def test_empty_returns_none(self):
        result = _parse_json_response("")
        assert result is None


# ---------------------------------------------------------------------------
# _build_scoring_prompt tests
# ---------------------------------------------------------------------------


class TestBuildScoringPrompt:
    @patch("app.signal_moderator._load_prompt", return_value=SCORE_PROMPT_TEMPLATE)
    def test_substitutes_placeholders(self, mock_load: MagicMock):
        result = _build_scoring_prompt(
            SAMPLE_ITEM, "business context here", "memory context here"
        )
        assert "business context here" in result
        assert "memory context here" in result
        assert "Booking.com launches AI-powered search" in result
        assert "{business_context}" not in result
        assert "{news_item}" not in result

    @patch("app.signal_moderator._load_prompt", return_value=SCORE_PROMPT_TEMPLATE)
    def test_news_item_format(self, mock_load: MagicMock):
        """AC-43: news_item contains title + summary + source."""
        result = _build_scoring_prompt(SAMPLE_ITEM, "ctx", "mem")
        assert "Заголовок: Booking.com launches AI-powered search" in result
        assert "Суть: New ML algorithm" in result
        assert "Источник: TechCrunch" in result

    @patch("app.signal_moderator._load_prompt", return_value="")
    def test_empty_template_returns_empty(self, mock_load: MagicMock):
        result = _build_scoring_prompt(SAMPLE_ITEM, "ctx", "mem")
        assert result == ""


# ---------------------------------------------------------------------------
# _build_analysis_prompt tests
# ---------------------------------------------------------------------------


class TestBuildAnalysisPrompt:
    @patch("app.signal_moderator._load_prompt", return_value=ANALYZE_PROMPT_TEMPLATE)
    def test_substitutes_all_placeholders(self, mock_load: MagicMock):
        scoring = ScoringResult(relevance=8, reason="relevant", matched_entities=["Booking.com"])
        result = _build_analysis_prompt(
            SAMPLE_ITEM, scoring, "biz ctx", "competitor info", "history"
        )
        assert "biz ctx" in result
        assert "competitor info" in result
        assert "history" in result
        assert "Booking.com launches" in result

    @patch("app.signal_moderator._load_prompt", return_value=ANALYZE_PROMPT_TEMPLATE)
    def test_none_competitor_replaced_with_default(self, mock_load: MagicMock):
        scoring = ScoringResult()
        result = _build_analysis_prompt(SAMPLE_ITEM, scoring, "ctx", None, "")
        assert "Нет данных" in result

    @patch("app.signal_moderator._load_prompt", return_value=ANALYZE_PROMPT_TEMPLATE)
    def test_critique_appended(self, mock_load: MagicMock):
        scoring = ScoringResult()
        result = _build_analysis_prompt(
            SAMPLE_ITEM, scoring, "ctx", None, "", critique="Fix the analysis"
        )
        assert "Предыдущая попытка не прошла проверку" in result
        assert "Fix the analysis" in result


# ---------------------------------------------------------------------------
# score_signal tests
# ---------------------------------------------------------------------------


class TestScoreSignal:
    @patch("app.signal_moderator._load_prompt", return_value=SCORE_PROMPT_TEMPLATE)
    @patch("app.signal_moderator.call_detailed")
    def test_returns_valid_scoring_result(
        self, mock_call: MagicMock, mock_prompt: MagicMock, mock_config: MagicMock
    ):
        """AC-01: relevance is 0-10."""
        mock_call.return_value = (SAMPLE_SCORE_RESPONSE, {"used": "claude"})

        result = score_signal(SAMPLE_ITEM, "context", "memory", mock_config)

        assert isinstance(result, ScoringResult)
        assert 0 <= result.relevance <= 10
        assert result.relevance == 8

    @patch("app.signal_moderator._load_prompt", return_value=SCORE_PROMPT_TEMPLATE)
    @patch("app.signal_moderator.call_detailed")
    def test_reason_is_string(
        self, mock_call: MagicMock, mock_prompt: MagicMock, mock_config: MagicMock
    ):
        """AC-02: reason is a string."""
        mock_call.return_value = (SAMPLE_SCORE_RESPONSE, {"used": "claude"})

        result = score_signal(SAMPLE_ITEM, "context", "memory", mock_config)

        assert isinstance(result.reason, str)
        assert len(result.reason) > 0

    @patch("app.signal_moderator._load_prompt", return_value=SCORE_PROMPT_TEMPLATE)
    @patch("app.signal_moderator.call_detailed")
    def test_matched_entities_is_list(
        self, mock_call: MagicMock, mock_prompt: MagicMock, mock_config: MagicMock
    ):
        """AC-03: matched_entities is a list."""
        mock_call.return_value = (SAMPLE_SCORE_RESPONSE, {"used": "claude"})

        result = score_signal(SAMPLE_ITEM, "context", "memory", mock_config)

        assert isinstance(result.matched_entities, list)
        assert "Booking.com" in result.matched_entities

    @patch("app.signal_moderator._load_prompt", return_value=SCORE_PROMPT_TEMPLATE)
    @patch("app.signal_moderator.call_detailed")
    def test_clamps_relevance_to_range(
        self, mock_call: MagicMock, mock_prompt: MagicMock, mock_config: MagicMock
    ):
        """Relevance outside 0-10 should be clamped."""
        bad_response = json.dumps({"relevance": 15, "reason": "too high", "matched_entities": []})
        mock_call.return_value = (bad_response, {"used": "claude"})

        result = score_signal(SAMPLE_ITEM, "context", "memory", mock_config)
        assert result.relevance == 10

    @patch("app.signal_moderator._load_prompt", return_value=SCORE_PROMPT_TEMPLATE)
    @patch("app.signal_moderator.call_detailed")
    def test_json_parse_error_retries(
        self, mock_call: MagicMock, mock_prompt: MagicMock, mock_config: MagicMock
    ):
        """On JSONDecodeError, should retry once then return default."""
        mock_call.return_value = ("Not valid JSON", {"used": "claude"})

        result = score_signal(SAMPLE_ITEM, "context", "memory", mock_config)

        assert result.relevance == 0
        assert "JSON parse error" in result.reason
        assert mock_call.call_count == 2  # original + 1 retry

    @patch("app.signal_moderator._load_prompt", return_value=SCORE_PROMPT_TEMPLATE)
    @patch("app.signal_moderator.call_detailed")
    def test_llm_error_returns_default(
        self, mock_call: MagicMock, mock_prompt: MagicMock, mock_config: MagicMock
    ):
        """LLM failure should not raise, returns default ScoringResult."""
        mock_call.side_effect = RuntimeError("All providers failed")

        result = score_signal(SAMPLE_ITEM, "context", "memory", mock_config)

        assert isinstance(result, ScoringResult)
        assert result.relevance == 0
        assert "LLM call error" in result.reason

    @patch("app.signal_moderator._load_prompt", return_value=SCORE_PROMPT_TEMPLATE)
    @patch("app.signal_moderator.call_detailed")
    def test_retry_succeeds_on_second_attempt(
        self, mock_call: MagicMock, mock_prompt: MagicMock, mock_config: MagicMock
    ):
        """If first attempt fails JSON parse but second succeeds, return valid result."""
        mock_call.side_effect = [
            ("Invalid JSON", {"used": "claude"}),
            (SAMPLE_SCORE_RESPONSE, {"used": "claude"}),
        ]

        result = score_signal(SAMPLE_ITEM, "context", "memory", mock_config)

        assert result.relevance == 8
        assert mock_call.call_count == 2

    @patch("app.signal_moderator._load_prompt", return_value=SCORE_PROMPT_TEMPLATE)
    @patch("app.signal_moderator.call_detailed")
    def test_non_list_entities_becomes_empty(
        self, mock_call: MagicMock, mock_prompt: MagicMock, mock_config: MagicMock
    ):
        """If matched_entities is not a list, default to empty list."""
        response = json.dumps({
            "relevance": 5, "reason": "test", "matched_entities": "not a list"
        })
        mock_call.return_value = (response, {"used": "claude"})

        result = score_signal(SAMPLE_ITEM, "context", "memory", mock_config)
        assert result.matched_entities == []


# ---------------------------------------------------------------------------
# analyze_signal tests
# ---------------------------------------------------------------------------


class TestAnalyzeSignal:
    @patch("app.signal_moderator._load_prompt", return_value=ANALYZE_PROMPT_TEMPLATE)
    @patch("app.signal_moderator.call_detailed")
    def test_returns_idea_reaction(
        self, mock_call: MagicMock, mock_prompt: MagicMock, mock_config: MagicMock
    ):
        """AC-05: analyze_signal determines reaction='idea'."""
        mock_call.return_value = (SAMPLE_ANALYZE_IDEA_RESPONSE, {"used": "claude"})
        scoring = ScoringResult(relevance=8, reason="relevant", matched_entities=["Booking.com"])

        result = analyze_signal(
            SAMPLE_ITEM, scoring, "ctx", None, "", mock_config
        )

        assert isinstance(result, AnalysisResult)
        assert result.reaction == "idea"

    @patch("app.signal_moderator._load_prompt", return_value=ANALYZE_PROMPT_TEMPLATE)
    @patch("app.signal_moderator.call_detailed")
    def test_idea_draft_has_required_fields(
        self, mock_call: MagicMock, mock_prompt: MagicMock, mock_config: MagicMock
    ):
        """AC-06: idea_draft contains title, problem, solution, domain."""
        mock_call.return_value = (SAMPLE_ANALYZE_IDEA_RESPONSE, {"used": "claude"})
        scoring = ScoringResult()

        result = analyze_signal(SAMPLE_ITEM, scoring, "ctx", None, "", mock_config)

        assert result.idea_draft is not None
        assert "title" in result.idea_draft
        assert "problem" in result.idea_draft
        assert "solution" in result.idea_draft
        assert "domain" in result.idea_draft

    @patch("app.signal_moderator._load_prompt", return_value=ANALYZE_PROMPT_TEMPLATE)
    @patch("app.signal_moderator.call_detailed")
    def test_returns_report_reaction(
        self, mock_call: MagicMock, mock_prompt: MagicMock, mock_config: MagicMock
    ):
        """AC-05: analyze_signal determines reaction='report'."""
        mock_call.return_value = (SAMPLE_ANALYZE_REPORT_RESPONSE, {"used": "claude"})
        scoring = ScoringResult()

        result = analyze_signal(SAMPLE_ITEM, scoring, "ctx", None, "", mock_config)

        assert result.reaction == "report"
        assert result.report_brief is not None

    @patch("app.signal_moderator._load_prompt", return_value=ANALYZE_PROMPT_TEMPLATE)
    @patch("app.signal_moderator.call_detailed")
    def test_report_brief_has_required_fields(
        self, mock_call: MagicMock, mock_prompt: MagicMock, mock_config: MagicMock
    ):
        """AC-07: report_brief contains topic, questions, scope."""
        mock_call.return_value = (SAMPLE_ANALYZE_REPORT_RESPONSE, {"used": "claude"})
        scoring = ScoringResult()

        result = analyze_signal(SAMPLE_ITEM, scoring, "ctx", None, "", mock_config)

        assert result.report_brief is not None
        assert "topic" in result.report_brief
        assert "questions" in result.report_brief
        assert "scope" in result.report_brief

    @patch("app.signal_moderator._load_prompt", return_value=ANALYZE_PROMPT_TEMPLATE)
    @patch("app.signal_moderator.call_detailed")
    def test_escalation_uses_correct_operation(
        self, mock_call: MagicMock, mock_prompt: MagicMock, mock_config: MagicMock
    ):
        """When operation_group=signal_escalation, use signal_analyze_escalation operation."""
        mock_call.return_value = (SAMPLE_ANALYZE_IDEA_RESPONSE, {"used": "claude"})
        scoring = ScoringResult()

        analyze_signal(
            SAMPLE_ITEM, scoring, "ctx", None, "", mock_config,
            operation_group="signal_escalation",
        )

        call_args = mock_call.call_args
        assert call_args.kwargs.get("operation") == "signal_analyze_escalation" or \
               call_args[1].get("operation") == "signal_analyze_escalation" or \
               (len(call_args[0]) > 0 and call_args[0][0] == "signal_analyze_escalation")

    @patch("app.signal_moderator._load_prompt", return_value=ANALYZE_PROMPT_TEMPLATE)
    @patch("app.signal_moderator.call_detailed")
    def test_normal_uses_signal_analyze_operation(
        self, mock_call: MagicMock, mock_prompt: MagicMock, mock_config: MagicMock
    ):
        """Without escalation, use signal_analyze operation."""
        mock_call.return_value = (SAMPLE_ANALYZE_IDEA_RESPONSE, {"used": "claude"})
        scoring = ScoringResult()

        analyze_signal(SAMPLE_ITEM, scoring, "ctx", None, "", mock_config)

        call_args = mock_call.call_args
        assert call_args.kwargs.get("operation") == "signal_analyze" or \
               call_args[1].get("operation") == "signal_analyze" or \
               (len(call_args[0]) > 0 and call_args[0][0] == "signal_analyze")

    @patch("app.signal_moderator._load_prompt", return_value=ANALYZE_PROMPT_TEMPLATE)
    @patch("app.signal_moderator.call_detailed")
    def test_llm_error_returns_default(
        self, mock_call: MagicMock, mock_prompt: MagicMock, mock_config: MagicMock
    ):
        """LLM failure should not raise, returns default AnalysisResult."""
        mock_call.side_effect = RuntimeError("Provider error")
        scoring = ScoringResult()

        result = analyze_signal(SAMPLE_ITEM, scoring, "ctx", None, "", mock_config)

        assert isinstance(result, AnalysisResult)
        assert "LLM call error" in result.analysis

    @patch("app.signal_moderator._load_prompt", return_value=ANALYZE_PROMPT_TEMPLATE)
    @patch("app.signal_moderator.call_detailed")
    def test_invalid_reaction_defaults_to_idea(
        self, mock_call: MagicMock, mock_prompt: MagicMock, mock_config: MagicMock
    ):
        """Invalid reaction value should default to 'idea'."""
        response = json.dumps({
            "reaction": "invalid_value",
            "analysis": "test",
            "threat_level": "low",
        })
        mock_call.return_value = (response, {"used": "claude"})
        scoring = ScoringResult()

        result = analyze_signal(SAMPLE_ITEM, scoring, "ctx", None, "", mock_config)
        assert result.reaction == "idea"

    @patch("app.signal_moderator._load_prompt", return_value=ANALYZE_PROMPT_TEMPLATE)
    @patch("app.signal_moderator.call_detailed")
    def test_critique_passed_to_prompt(
        self, mock_call: MagicMock, mock_prompt: MagicMock, mock_config: MagicMock
    ):
        """Critique from AgentLoop should be included in prompt."""
        mock_call.return_value = (SAMPLE_ANALYZE_IDEA_RESPONSE, {"used": "claude"})
        scoring = ScoringResult()

        analyze_signal(
            SAMPLE_ITEM, scoring, "ctx", None, "", mock_config,
            critique="Previous attempt was too vague",
        )

        call_args = mock_call.call_args
        messages = call_args.kwargs.get("messages") or call_args[1].get("messages")
        prompt_text = messages[0]["content"]
        assert "Предыдущая попытка не прошла проверку" in prompt_text
        assert "Previous attempt was too vague" in prompt_text


# ---------------------------------------------------------------------------
# dispatch_idea tests
# ---------------------------------------------------------------------------


class TestDispatchIdea:
    def _make_analysis(self) -> AnalysisResult:
        return AnalysisResult(
            reaction="idea",
            analysis="Test analysis with details about the opportunity.",
            threat_level="medium",
            idea_draft={
                "title": "Improve search ranking",
                "problem": "Competitors ahead in ranking",
                "solution": "Implement ML model",
                "domain": "search-engine",
            },
        )

    def test_creates_idea_file(self, tmp_path: Path):
        """AC-08: dispatch_idea creates idea in vault."""
        analysis = self._make_analysis()
        result = dispatch_idea(
            SAMPLE_ITEM, analysis, str(tmp_path), notify=False, dry_run=False
        )

        assert result is not None
        # Check file was created
        ideas_dir = tmp_path / "raw" / "inbound" / "ideas"
        files = list(ideas_dir.glob("*.md"))
        assert len(files) == 1

    def test_idea_has_signal_metadata(self, tmp_path: Path):
        """AC-10: idea contains source=signal, signal_date, signal_source."""
        analysis = self._make_analysis()
        dispatch_idea(SAMPLE_ITEM, analysis, str(tmp_path), notify=False, dry_run=False)

        ideas_dir = tmp_path / "raw" / "inbound" / "ideas"
        files = list(ideas_dir.glob("*.md"))
        content = files[0].read_text(encoding="utf-8")

        assert "source: signal" in content
        assert "signal_date:" in content
        assert "signal_source:" in content

    def test_dry_run_returns_none(self, tmp_path: Path):
        """Dry run should not write files."""
        analysis = self._make_analysis()
        result = dispatch_idea(
            SAMPLE_ITEM, analysis, str(tmp_path), notify=False, dry_run=True
        )

        assert result is None
        ideas_dir = tmp_path / "raw" / "inbound" / "ideas"
        if ideas_dir.exists():
            assert len(list(ideas_dir.glob("*.md"))) == 0

    def test_no_idea_draft_returns_none(self, tmp_path: Path):
        """No idea_draft should return None without writing."""
        analysis = AnalysisResult(reaction="idea", analysis="test")
        result = dispatch_idea(
            SAMPLE_ITEM, analysis, str(tmp_path), notify=False, dry_run=False
        )
        assert result is None

    def test_telegram_notification_sent(self, tmp_path: Path):
        """AC-30: dispatch_idea sends Telegram notification when notify=True."""
        analysis = self._make_analysis()
        mock_tg = MagicMock(return_value=True)

        # send_telegram is imported inside the function via 'from app.notifier import send_telegram'
        # We patch the notifier module so the dynamic import picks up the mock
        notifier_mock = MagicMock(send_telegram=mock_tg)
        with patch.dict("sys.modules", {"app.notifier": notifier_mock}):
            dispatch_idea(
                SAMPLE_ITEM, analysis, str(tmp_path), notify=True, dry_run=False
            )

        mock_tg.assert_called_once()
        call_args = mock_tg.call_args
        msg = call_args[0][0] if call_args[0] else call_args[1].get("message", "")
        assert "Improve search ranking" in msg

    def test_related_idea_marked_in_frontmatter(self, tmp_path: Path):
        """When dedup_result has similarity >= 6, related should be in frontmatter."""
        analysis = self._make_analysis()
        dedup = MagicMock()
        dedup.similarity = 7
        dedup.similar_to = "IDEA-0042"

        dispatch_idea(
            SAMPLE_ITEM, analysis, str(tmp_path),
            notify=False, dry_run=False, dedup_result=dedup,
        )

        ideas_dir = tmp_path / "raw" / "inbound" / "ideas"
        files = list(ideas_dir.glob("*.md"))
        content = files[0].read_text(encoding="utf-8")
        assert "IDEA-0042" in content

    def test_writes_processed_md(self, tmp_path: Path):
        """AC-45: dispatch_idea writes to processed.md."""
        analysis = self._make_analysis()
        dispatch_idea(
            SAMPLE_ITEM, analysis, str(tmp_path), notify=False, dry_run=False
        )

        signals_dir = tmp_path / "wiki" / "signals"
        processed_files = list(signals_dir.glob("*-processed.md"))
        assert len(processed_files) == 1
        content = processed_files[0].read_text(encoding="utf-8")
        assert "idea" in content

    def test_idea_file_has_frontmatter_and_content(self, tmp_path: Path):
        """Idea file should have proper markdown structure."""
        analysis = self._make_analysis()
        dispatch_idea(
            SAMPLE_ITEM, analysis, str(tmp_path), notify=False, dry_run=False
        )

        ideas_dir = tmp_path / "raw" / "inbound" / "ideas"
        files = list(ideas_dir.glob("*.md"))
        content = files[0].read_text(encoding="utf-8")

        assert content.startswith("---")
        assert "# Improve search ranking" in content
        assert "## Проблема" in content
        assert "## Решение" in content
        assert "## Анализ" in content


# ---------------------------------------------------------------------------
# dispatch_report tests
# ---------------------------------------------------------------------------


class TestDispatchReport:
    def _make_analysis(self) -> AnalysisResult:
        return AnalysisResult(
            reaction="report",
            analysis="Deep analysis needed for competitive strategy.",
            threat_level="high",
            report_brief={
                "topic": "Competitive analysis of new entrant",
                "questions": ["What is their tech stack?", "Pricing model?"],
                "scope": "Russian OTA market",
            },
        )

    def test_creates_research_queue_json(self, tmp_path: Path):
        """AC-07: dispatch_report creates JSON in research-queue."""
        analysis = self._make_analysis()
        result = dispatch_report(
            SAMPLE_ITEM, analysis, str(tmp_path), notify=False, dry_run=False
        )

        assert result is not None
        queue_dir = tmp_path / "raw" / "inbound" / "research-queue"
        files = list(queue_dir.glob("*.json"))
        assert len(files) == 1

        data = json.loads(files[0].read_text(encoding="utf-8"))
        assert data["topic"] == "Competitive analysis of new entrant"
        assert len(data["questions"]) == 2

    def test_dry_run_returns_none(self, tmp_path: Path):
        """Dry run should not write files."""
        analysis = self._make_analysis()
        result = dispatch_report(
            SAMPLE_ITEM, analysis, str(tmp_path), notify=False, dry_run=True
        )
        assert result is None

    def test_no_report_brief_returns_none(self, tmp_path: Path):
        analysis = AnalysisResult(reaction="report", analysis="test")
        result = dispatch_report(
            SAMPLE_ITEM, analysis, str(tmp_path), notify=False, dry_run=False
        )
        assert result is None

    def test_research_json_has_signal_metadata(self, tmp_path: Path):
        """Research queue JSON should contain signal source info."""
        analysis = self._make_analysis()
        dispatch_report(
            SAMPLE_ITEM, analysis, str(tmp_path), notify=False, dry_run=False
        )

        queue_dir = tmp_path / "raw" / "inbound" / "research-queue"
        files = list(queue_dir.glob("*.json"))
        data = json.loads(files[0].read_text(encoding="utf-8"))

        assert "signal_source" in data
        assert "signal_date" in data
        assert data["competitor"] != SAMPLE_ITEM["source"]

    def test_competitor_from_parameter(self, tmp_path: Path):
        """BUG-027: competitor should come from scoring, not item source."""
        analysis = self._make_analysis()
        dispatch_report(
            SAMPLE_ITEM, analysis, str(tmp_path), notify=False, dry_run=False,
            competitor="Booking.com",
        )

        queue_dir = tmp_path / "raw" / "inbound" / "research-queue"
        files = list(queue_dir.glob("*.json"))
        data = json.loads(files[0].read_text(encoding="utf-8"))

        assert data["competitor"] == "Booking.com"

    def test_competitor_from_report_brief_takes_priority(self, tmp_path: Path):
        """BUG-027: LLM competitor in report_brief overrides scoring competitor."""
        analysis = self._make_analysis()
        analysis.report_brief["competitor"] = "Kayak"
        dispatch_report(
            SAMPLE_ITEM, analysis, str(tmp_path), notify=False, dry_run=False,
            competitor="Booking.com",
        )

        queue_dir = tmp_path / "raw" / "inbound" / "research-queue"
        files = list(queue_dir.glob("*.json"))
        data = json.loads(files[0].read_text(encoding="utf-8"))

        assert data["competitor"] == "Kayak"

    def test_competitor_empty_when_none_identified(self, tmp_path: Path):
        """BUG-027: competitor should be empty when no competitor identified."""
        analysis = self._make_analysis()
        dispatch_report(
            SAMPLE_ITEM, analysis, str(tmp_path), notify=False, dry_run=False,
        )

        queue_dir = tmp_path / "raw" / "inbound" / "research-queue"
        files = list(queue_dir.glob("*.json"))
        data = json.loads(files[0].read_text(encoding="utf-8"))

        assert data["competitor"] == ""


# ---------------------------------------------------------------------------
# _write_skipped_md tests
# ---------------------------------------------------------------------------


class TestWriteSkippedMd:
    def test_creates_file_with_header(self, tmp_path: Path):
        """AC-04: _write_skipped_md creates markdown file with table header."""
        items = [
            {"title": "Irrelevant news", "relevance": 2, "reason": "Not OTA related"},
        ]
        _write_skipped_md(str(tmp_path), "2026-08-01", items)

        filepath = tmp_path / "wiki" / "signals" / "2026-08-01-skipped.md"
        assert filepath.exists()
        content = filepath.read_text(encoding="utf-8")
        assert "# Skipped Signals" in content
        assert "| Irrelevant news | 2 | Not OTA related |" in content

    def test_appends_to_existing_file(self, tmp_path: Path):
        """Subsequent calls should append, not overwrite."""
        items1 = [{"title": "News 1", "relevance": 1, "reason": "r1"}]
        items2 = [{"title": "News 2", "relevance": 3, "reason": "r2"}]

        _write_skipped_md(str(tmp_path), "2026-08-01", items1)
        _write_skipped_md(str(tmp_path), "2026-08-01", items2)

        filepath = tmp_path / "wiki" / "signals" / "2026-08-01-skipped.md"
        content = filepath.read_text(encoding="utf-8")
        assert "News 1" in content
        assert "News 2" in content

    def test_escapes_pipe_in_title(self, tmp_path: Path):
        """Pipe characters in title should be escaped for markdown table."""
        items = [{"title": "News | with pipe", "relevance": 5, "reason": "test"}]
        _write_skipped_md(str(tmp_path), "2026-08-01", items)

        filepath = tmp_path / "wiki" / "signals" / "2026-08-01-skipped.md"
        content = filepath.read_text(encoding="utf-8")
        assert "\\|" in content


# ---------------------------------------------------------------------------
# _write_processed_md tests
# ---------------------------------------------------------------------------


class TestWriteProcessedMd:
    def test_creates_file_with_header(self, tmp_path: Path):
        """AC-45: _write_processed_md creates markdown file."""
        items = [
            {
                "title": "Processed signal",
                "reaction": "idea",
                "result_ref": "2026-08-01-signal-test.md",
                "quality_score": 8,
            },
        ]
        _write_processed_md(str(tmp_path), "2026-08-01", items)

        filepath = tmp_path / "wiki" / "signals" / "2026-08-01-processed.md"
        assert filepath.exists()
        content = filepath.read_text(encoding="utf-8")
        assert "# Processed Signals" in content
        assert "| Processed signal | idea | 2026-08-01-signal-test.md | 8 |" in content

    def test_appends_to_existing_file(self, tmp_path: Path):
        items1 = [{"title": "S1", "reaction": "idea", "result_ref": "r1", "quality_score": 7}]
        items2 = [{"title": "S2", "reaction": "report", "result_ref": "r2", "quality_score": 6}]

        _write_processed_md(str(tmp_path), "2026-08-01", items1)
        _write_processed_md(str(tmp_path), "2026-08-01", items2)

        filepath = tmp_path / "wiki" / "signals" / "2026-08-01-processed.md"
        content = filepath.read_text(encoding="utf-8")
        assert "S1" in content
        assert "S2" in content


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


class TestDataclasses:
    def test_scoring_result_defaults(self):
        r = ScoringResult()
        assert r.relevance == 0
        assert r.reason == ""
        assert r.matched_entities == []

    def test_analysis_result_defaults(self):
        r = AnalysisResult()
        assert r.reaction == ""
        assert r.analysis == ""
        assert r.threat_level == "low"
        assert r.idea_draft is None
        assert r.report_brief is None
        assert r._quality_warning is False
        assert r._attempts == 1

    def test_scoring_result_with_values(self):
        r = ScoringResult(relevance=7, reason="test", matched_entities=["A", "B"])
        assert r.relevance == 7
        assert r.matched_entities == ["A", "B"]

    def test_analysis_result_with_idea(self):
        r = AnalysisResult(
            reaction="idea",
            analysis="test analysis",
            idea_draft={"title": "test"},
        )
        assert r.reaction == "idea"
        assert r.idea_draft["title"] == "test"

    def test_report_result_defaults(self):
        r = ReportResult()
        assert r.content == ""
        assert r.threat_level == "medium"
        assert r._quality_warning is False
        assert r._attempts == 1

    def test_report_result_with_values(self):
        r = ReportResult(content="# Report", threat_level="high")
        assert r.content == "# Report"
        assert r.threat_level == "high"

    def test_signal_data_defaults(self):
        s = SignalData()
        assert s.title == ""
        assert s.analysis == ""
        assert s.threat_level == "low"
        assert s.recommended_action == ""
        assert s.draft_idea is None
        assert s.domain == "general"
        assert s.priority_hint == "medium"
        assert s.rationale == ""

    def test_signal_data_with_values(self):
        s = SignalData(
            title="Test Signal",
            analysis="Analysis text",
            threat_level="high",
            recommended_action="Act immediately",
            draft_idea={"title": "Idea", "problem": "P", "solution": "S", "domain": "search-engine"},
            domain="search-engine",
            priority_hint="high",
            rationale="Critical competitor move",
        )
        assert s.title == "Test Signal"
        assert s.threat_level == "high"
        assert s.draft_idea["domain"] == "search-engine"
        assert s.priority_hint == "high"


# ---------------------------------------------------------------------------
# generate_analysis_report tests (BL-203)
# ---------------------------------------------------------------------------


class TestGenerateAnalysisReport:
    def test_success(self, monkeypatch, mock_config):
        """generate_analysis_report returns ReportResult with content and threat_level."""
        md_content = '# Report\nSome analysis.\n<report_meta>{"threat_level": "high"}</report_meta>'
        monkeypatch.setattr(
            "app.signal_moderator.call_detailed",
            lambda **kw: (md_content, {"used": "claude"}),
        )
        monkeypatch.setattr(
            "app.signal_moderator._load_prompt",
            lambda name: "prompt {business_context} {competitor_profile} {memory_history} {news_item}",
        )

        result = generate_analysis_report(
            item={"title": "Test", "summary": "Test summary", "source": "TestSource"},
            scoring=ScoringResult(relevance=8, reason="test", matched_entities=[]),
            business_context="test context",
            competitor_profile="competitor info",
            memory_history="memory",
            config=mock_config,
        )
        assert isinstance(result, ReportResult)
        assert "Report" in result.content
        assert result.threat_level == "high"

    def test_no_meta_tag_fallback(self, monkeypatch, mock_config):
        """When <report_meta> tag is missing, threat_level defaults to 'medium'."""
        monkeypatch.setattr(
            "app.signal_moderator.call_detailed",
            lambda **kw: ("Just a report without meta", {"used": "claude"}),
        )
        monkeypatch.setattr(
            "app.signal_moderator._load_prompt",
            lambda name: "prompt {business_context} {competitor_profile} {memory_history} {news_item}",
        )

        result = generate_analysis_report(
            item={"title": "Test", "summary": "s", "source": "src"},
            scoring=ScoringResult(relevance=5, reason="r", matched_entities=[]),
            business_context="ctx",
            competitor_profile=None,
            memory_history="",
            config=mock_config,
        )
        assert result.threat_level == "medium"

    def test_llm_error_returns_error_result(self, monkeypatch, mock_config):
        """LLM error returns ReportResult with error message (not raised)."""
        def raise_err(**kw):
            raise RuntimeError("LLM unavailable")

        monkeypatch.setattr("app.signal_moderator.call_detailed", raise_err)
        monkeypatch.setattr(
            "app.signal_moderator._load_prompt",
            lambda name: "prompt {business_context} {competitor_profile} {memory_history} {news_item}",
        )

        result = generate_analysis_report(
            item={"title": "t", "summary": "s", "source": "src"},
            scoring=ScoringResult(relevance=5, reason="r", matched_entities=[]),
            business_context="ctx",
            competitor_profile=None,
            memory_history="",
            config=mock_config,
        )
        assert isinstance(result, ReportResult)
        assert "LLM call error" in result.content
        assert result.threat_level == "medium"

    def test_empty_prompt_returns_default(self, monkeypatch, mock_config):
        """When prompt template is empty/missing, return default ReportResult."""
        monkeypatch.setattr("app.signal_moderator._load_prompt", lambda name: "")

        result = generate_analysis_report(
            item={"title": "t", "summary": "s", "source": "src"},
            scoring=ScoringResult(),
            business_context="ctx",
            competitor_profile=None,
            memory_history="",
            config=mock_config,
        )
        assert "Empty prompt template" in result.content

    def test_escalation_operation(self, monkeypatch, mock_config):
        """With operation_group='signal_escalation', use escalation operation."""
        captured = {}

        def mock_call(**kw):
            captured.update(kw)
            return ("Report content", {"used": "claude"})

        monkeypatch.setattr("app.signal_moderator.call_detailed", mock_call)
        monkeypatch.setattr(
            "app.signal_moderator._load_prompt",
            lambda name: "prompt {business_context} {competitor_profile} {memory_history} {news_item}",
        )

        generate_analysis_report(
            item={"title": "t", "summary": "s", "source": "src"},
            scoring=ScoringResult(),
            business_context="ctx",
            competitor_profile=None,
            memory_history="",
            config=mock_config,
            operation_group="signal_escalation",
        )
        assert captured["operation"] == "signal_analyze_escalation"

    def test_content_stripped_from_meta(self, monkeypatch, mock_config):
        """Content before <report_meta> tag is returned, meta tag itself is stripped."""
        resp = '# Title\n\nBody content.\n<report_meta>{"threat_level": "low"}</report_meta>'
        monkeypatch.setattr(
            "app.signal_moderator.call_detailed",
            lambda **kw: (resp, {"used": "claude"}),
        )
        monkeypatch.setattr(
            "app.signal_moderator._load_prompt",
            lambda name: "prompt {business_context} {competitor_profile} {memory_history} {news_item}",
        )

        result = generate_analysis_report(
            item={"title": "t", "summary": "s", "source": "src"},
            scoring=ScoringResult(),
            business_context="ctx",
            competitor_profile=None,
            memory_history="",
            config=mock_config,
        )
        assert "<report_meta>" not in result.content
        assert "Body content" in result.content
        assert result.threat_level == "low"


# ---------------------------------------------------------------------------
# extract_signals tests (BL-203)
# ---------------------------------------------------------------------------


class TestExtractSignals:
    def test_success(self, tmp_path, monkeypatch, mock_config):
        """extract_signals returns list of SignalData from LLM JSON response."""
        report_path = tmp_path / "report.md"
        report_path.write_text("# Report\nContent here", encoding="utf-8")

        json_resp = json.dumps({"signals": [
            {"title": "Signal 1", "analysis": "A1", "threat_level": "high",
             "recommended_action": "Act", "draft_idea": {"title": "I1", "problem": "P", "solution": "S", "domain": "general"},
             "domain": "general", "priority_hint": "high", "rationale": "R1"},
            {"title": "Signal 2", "analysis": "A2", "threat_level": "low",
             "recommended_action": "Monitor", "draft_idea": None,
             "domain": "search-engine", "priority_hint": "low", "rationale": "R2"},
        ]})
        monkeypatch.setattr(
            "app.signal_moderator.call_detailed",
            lambda **kw: (json_resp, {"used": "claude"}),
        )
        monkeypatch.setattr(
            "app.signal_moderator._load_prompt",
            lambda name: "prompt {business_context} {report_content}",
        )

        result = extract_signals(report_path, str(tmp_path), "ctx", mock_config)
        assert len(result) == 2
        assert isinstance(result[0], SignalData)
        assert result[0].title == "Signal 1"
        assert result[0].threat_level == "high"
        assert result[1].draft_idea is None

    def test_empty_signals(self, tmp_path, monkeypatch, mock_config):
        """When LLM returns empty signals list, return empty list."""
        report_path = tmp_path / "report.md"
        report_path.write_text("# Report\nContent", encoding="utf-8")

        json_resp = json.dumps({"signals": [], "no_signals_reason": "Nothing actionable"})
        monkeypatch.setattr(
            "app.signal_moderator.call_detailed",
            lambda **kw: (json_resp, {"used": "claude"}),
        )
        monkeypatch.setattr(
            "app.signal_moderator._load_prompt",
            lambda name: "prompt {business_context} {report_content}",
        )

        result = extract_signals(report_path, str(tmp_path), "ctx", mock_config)
        assert result == []

    def test_invalid_json(self, tmp_path, monkeypatch, mock_config):
        """When LLM returns invalid JSON, return empty list."""
        report_path = tmp_path / "report.md"
        report_path.write_text("# Report\nContent", encoding="utf-8")

        monkeypatch.setattr(
            "app.signal_moderator.call_detailed",
            lambda **kw: ("not json at all {broken", {"used": "claude"}),
        )
        monkeypatch.setattr(
            "app.signal_moderator._load_prompt",
            lambda name: "prompt {business_context} {report_content}",
        )

        result = extract_signals(report_path, str(tmp_path), "ctx", mock_config)
        assert result == []

    def test_missing_report_file(self, tmp_path, monkeypatch, mock_config):
        """When report file doesn't exist, return empty list."""
        report_path = tmp_path / "nonexistent.md"

        result = extract_signals(report_path, str(tmp_path), "ctx", mock_config)
        assert result == []

    def test_llm_error(self, tmp_path, monkeypatch, mock_config):
        """LLM error returns empty list."""
        report_path = tmp_path / "report.md"
        report_path.write_text("# Report\nContent", encoding="utf-8")

        def raise_err(**kw):
            raise RuntimeError("LLM down")

        monkeypatch.setattr("app.signal_moderator.call_detailed", raise_err)
        monkeypatch.setattr(
            "app.signal_moderator._load_prompt",
            lambda name: "prompt {business_context} {report_content}",
        )

        result = extract_signals(report_path, str(tmp_path), "ctx", mock_config)
        assert result == []

    def test_skips_invalid_entries(self, tmp_path, monkeypatch, mock_config):
        """Signals without required title/analysis are skipped."""
        report_path = tmp_path / "report.md"
        report_path.write_text("# Report", encoding="utf-8")

        json_resp = json.dumps({"signals": [
            {"title": "", "analysis": "A1", "threat_level": "low"},
            {"title": "Valid", "analysis": "A2"},
            "not_a_dict",
        ]})
        monkeypatch.setattr(
            "app.signal_moderator.call_detailed",
            lambda **kw: (json_resp, {"used": "claude"}),
        )
        monkeypatch.setattr(
            "app.signal_moderator._load_prompt",
            lambda name: "prompt {business_context} {report_content}",
        )

        result = extract_signals(report_path, str(tmp_path), "ctx", mock_config)
        assert len(result) == 1
        assert result[0].title == "Valid"

    def test_invalid_threat_level_defaults_to_low(self, tmp_path, monkeypatch, mock_config):
        """Invalid threat_level values default to 'low'."""
        report_path = tmp_path / "report.md"
        report_path.write_text("# Report", encoding="utf-8")

        json_resp = json.dumps({"signals": [
            {"title": "S1", "analysis": "A1", "threat_level": "critical"},
        ]})
        monkeypatch.setattr(
            "app.signal_moderator.call_detailed",
            lambda **kw: (json_resp, {"used": "claude"}),
        )
        monkeypatch.setattr(
            "app.signal_moderator._load_prompt",
            lambda name: "prompt {business_context} {report_content}",
        )

        result = extract_signals(report_path, str(tmp_path), "ctx", mock_config)
        assert result[0].threat_level == "low"


# ---------------------------------------------------------------------------
# dispatch_signal tests (BL-203)
# ---------------------------------------------------------------------------


class TestDispatchSignal:
    def _make_signal(self, **overrides) -> SignalData:
        defaults = dict(
            title="Test Signal",
            analysis="Analysis text",
            threat_level="medium",
            recommended_action="Monitor",
            draft_idea={"title": "Idea", "problem": "P", "solution": "S", "domain": "general"},
            domain="general",
            priority_hint="medium",
            rationale="R",
        )
        defaults.update(overrides)
        return SignalData(**defaults)

    def _make_scoring(self) -> ScoringResult:
        return ScoringResult(relevance=7, reason="Relevant", matched_entities=["ota"])

    def _setup_vault_paths(self, monkeypatch, tmp_path):
        """Monkeypatch vault_paths to use tmp_path directories."""
        raw_dir = tmp_path / "raw" / "inbound" / "signals"
        raw_dir.mkdir(parents=True, exist_ok=True)
        wiki_dir = tmp_path / "wiki" / "reports" / "signals"
        wiki_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr("shared.vault_paths.raw_signals", lambda: raw_dir)
        monkeypatch.setattr("shared.vault_paths.wiki_signals", lambda: wiki_dir)
        return raw_dir, wiki_dir

    def test_creates_raw_and_wiki(self, tmp_path, monkeypatch):
        """AC-15: dispatch_signal creates both raw JSON and wiki MD files."""
        raw_dir, wiki_dir = self._setup_vault_paths(monkeypatch, tmp_path)

        signal = self._make_signal()
        scoring = self._make_scoring()
        item = {"title": "News", "date": "2026-08-01", "source": "TestSrc", "source_url": "https://example.com"}

        result = dispatch_signal(signal, "report.md", item, scoring, str(tmp_path), "run-001")

        assert result is not None
        raw_files = list(raw_dir.glob("*.json"))
        wiki_files = list(wiki_dir.glob("*.md"))
        assert len(raw_files) == 1
        assert len(wiki_files) == 1

    def test_raw_json_schema(self, tmp_path, monkeypatch):
        """Raw JSON contains all required fields (AC-02)."""
        raw_dir, wiki_dir = self._setup_vault_paths(monkeypatch, tmp_path)

        signal = self._make_signal(title="Schema Test", threat_level="high")
        scoring = ScoringResult(relevance=9, reason="Critical", matched_entities=["booking"])
        item = {"title": "News", "date": "2026-08-01", "source": "Src", "source_url": "https://x.com"}

        dispatch_signal(signal, "report.md", item, scoring, str(tmp_path), "run-002")

        raw_files = list(raw_dir.glob("*.json"))
        assert len(raw_files) == 1
        data = json.loads(raw_files[0].read_text(encoding="utf-8"))

        # Check all fields from dispatch_signal raw_data dict
        required = [
            "title", "source_url", "source", "relevance_score",
            "analysis", "threat_level", "recommended_action", "draft_idea",
            "signal_date", "run_id", "status", "report_ref", "created_at",
        ]
        for fld in required:
            assert fld in data, f"Missing field: {fld}"

        assert data["title"] == "Schema Test"
        assert data["relevance_score"] == 9
        assert data["report_ref"] == "report.md"
        assert data["run_id"] == "run-002"
        assert data["status"] == "pending"

    def test_wiki_md_has_frontmatter(self, tmp_path, monkeypatch):
        """Wiki MD file contains YAML frontmatter with signal metadata."""
        raw_dir, wiki_dir = self._setup_vault_paths(monkeypatch, tmp_path)

        signal = self._make_signal(title="Wiki Test")
        scoring = self._make_scoring()
        item = {"title": "News", "date": "2026-08-01", "source": "Src", "source_url": "https://x.com"}

        dispatch_signal(signal, "report.md", item, scoring, str(tmp_path), "run-004")

        wiki_files = list(wiki_dir.glob("*.md"))
        assert len(wiki_files) == 1
        content = wiki_files[0].read_text(encoding="utf-8")

        assert content.startswith("---\n")
        assert "type: signal" in content
        assert "status: pending" in content
        assert "# Wiki Test" in content

    def test_dry_run(self, tmp_path, monkeypatch):
        """AC-16: In dry_run mode, no files are created but signal_id is returned."""
        raw_dir, wiki_dir = self._setup_vault_paths(monkeypatch, tmp_path)

        signal = self._make_signal(title="Dry Run")
        scoring = ScoringResult(relevance=3, reason="Low", matched_entities=[])
        item = {"title": "News", "date": "2026-08-01", "source": "Src"}

        result = dispatch_signal(signal, "r.md", item, scoring, str(tmp_path), "run-003", dry_run=True)

        # Returns signal_id even in dry_run
        assert result is not None
        assert "dry-run" in result.lower() or isinstance(result, str)

        raw_files = list(raw_dir.glob("*.json"))
        wiki_files = list(wiki_dir.glob("*.md"))
        assert len(raw_files) == 0
        assert len(wiki_files) == 0

    def test_returns_signal_id_string(self, tmp_path, monkeypatch):
        """dispatch_signal returns signal_id (str) on success."""
        self._setup_vault_paths(monkeypatch, tmp_path)

        signal = self._make_signal(title="ID Test")
        scoring = self._make_scoring()
        item = {"title": "News", "date": "2026-08-01", "source": "Src"}

        result = dispatch_signal(signal, "ref.md", item, scoring, str(tmp_path), "run-005")

        assert isinstance(result, str)
        assert "id-test" in result

    def test_draft_idea_section_in_wiki(self, tmp_path, monkeypatch):
        """Wiki MD contains draft idea section when draft_idea is present."""
        raw_dir, wiki_dir = self._setup_vault_paths(monkeypatch, tmp_path)

        signal = self._make_signal(
            title="With Idea",
            draft_idea={"title": "Great Idea", "problem": "The Problem", "solution": "The Solution", "domain": "pricing"},
        )
        scoring = self._make_scoring()
        item = {"title": "News", "date": "2026-08-01", "source": "Src"}

        dispatch_signal(signal, "ref.md", item, scoring, str(tmp_path), "run-006")

        wiki_files = list(wiki_dir.glob("*.md"))
        content = wiki_files[0].read_text(encoding="utf-8")
        assert "Great Idea" in content
        assert "The Problem" in content
        assert "The Solution" in content

    def test_no_draft_idea_section_when_none(self, tmp_path, monkeypatch):
        """Wiki MD omits draft idea section when draft_idea is None."""
        raw_dir, wiki_dir = self._setup_vault_paths(monkeypatch, tmp_path)

        signal = self._make_signal(title="No Idea", draft_idea=None)
        scoring = self._make_scoring()
        item = {"title": "News", "date": "2026-08-01", "source": "Src"}

        dispatch_signal(signal, "ref.md", item, scoring, str(tmp_path), "run-007")

        wiki_files = list(wiki_dir.glob("*.md"))
        content = wiki_files[0].read_text(encoding="utf-8")
        assert "Черновик идеи" not in content
