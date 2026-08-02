"""Tests for signal_moderator module (T-10).

AC-01: score_signal returns relevance 0-10
AC-02: reason is 1 sentence
AC-03: matched_entities is a list
AC-04: _write_skipped_md writes skipped to wiki/signals/
AC-05: analyze_signal determines reaction (idea/report)
AC-06: idea_draft contains title, problem, solution, domain
AC-07: report_brief contains topic, questions, scope
AC-08: dispatch_idea creates idea in vault
AC-10: idea contains source=signal, signal_date, signal_source
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
    ScoringResult,
    _build_analysis_prompt,
    _build_scoring_prompt,
    _load_prompt,
    _parse_json_response,
    _write_processed_md,
    _write_skipped_md,
    analyze_signal,
    dispatch_idea,
    dispatch_report,
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
