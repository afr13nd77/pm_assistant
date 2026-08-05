"""Tests for research_runner module (T-04).

Covers: ResearchTask dataclass, _parse_task, _scan_queue,
_resolve_method, _check_existing_report, _collect_context,
_format_report, _generate_internal_report, _run_completeness_check,
_move_task_file, process_task, run_all.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.research_runner import (
    ResearchError,
    ResearchResult,
    ResearchTask,
    _check_existing_report,
    _classify_by_reason,
    _collect_context,
    _extract_and_classify,
    _format_report,
    _generate_internal_report,
    _move_task_file,
    _parse_task,
    _resolve_method,
    _run_completeness_check,
    _scan_queue,
    _update_processed_json,
    process_task,
    run_all,
)
from app.signal_orchestrator import ModeratorConfig

# ---------------------------------------------------------------------------
# ResearchTask dataclass
# ---------------------------------------------------------------------------


class TestResearchTask:
    def test_slug_simple(self):
        t = ResearchTask(topic="Test Topic", questions=["q1"], scope="s")
        assert t.slug == "test-topic"

    def test_slug_cyrillic(self):
        t = ResearchTask(topic="Тестовая тема", questions=["q1"], scope="s")
        assert "тестовая" in t.slug
        assert "тема" in t.slug

    def test_slug_special_chars(self):
        t = ResearchTask(topic="Test!@#$%Topic", questions=["q1"], scope="s")
        assert "--" not in t.slug
        assert t.slug == "test-topic"

    def test_slug_truncation(self):
        t = ResearchTask(topic="A" * 100, questions=["q1"], scope="s")
        assert len(t.slug) <= 50

    def test_report_filename(self):
        t = ResearchTask(topic="Test Topic", questions=["q1"], scope="s")
        today = date.today().isoformat()
        assert t.report_filename == f"{today}-test-topic.md"

    def test_defaults(self):
        t = ResearchTask(topic="t", questions=["q"], scope="s")
        assert t.signal_source == ""
        assert t.signal_date == ""
        assert t.competitor == ""
        assert t.source_path == Path(".")


# ---------------------------------------------------------------------------
# _parse_task
# ---------------------------------------------------------------------------


class TestParseTask:
    def test_valid_task(self, tmp_path):
        task_file = tmp_path / "task.json"
        task_file.write_text(json.dumps({
            "topic": "My Topic",
            "questions": ["Q1", "Q2"],
            "scope": "analysis",
            "signal_source": "news",
            "competitor": "Booking",
        }), encoding="utf-8")

        task = _parse_task(task_file)
        assert task.topic == "My Topic"
        assert task.questions == ["Q1", "Q2"]
        assert task.scope == "analysis"
        assert task.signal_source == "news"
        assert task.competitor == "Booking"
        assert task.source_path == task_file

    def test_missing_topic(self, tmp_path):
        task_file = tmp_path / "task.json"
        task_file.write_text(json.dumps({
            "questions": ["Q1"],
            "scope": "s",
        }), encoding="utf-8")
        with pytest.raises(ValueError, match="topic"):
            _parse_task(task_file)

    def test_missing_questions(self, tmp_path):
        task_file = tmp_path / "task.json"
        task_file.write_text(json.dumps({
            "topic": "T",
            "scope": "s",
        }), encoding="utf-8")
        with pytest.raises(ValueError, match="questions"):
            _parse_task(task_file)

    def test_empty_questions(self, tmp_path):
        task_file = tmp_path / "task.json"
        task_file.write_text(json.dumps({
            "topic": "T",
            "questions": [],
            "scope": "s",
        }), encoding="utf-8")
        with pytest.raises(ValueError, match="questions"):
            _parse_task(task_file)

    def test_missing_scope(self, tmp_path):
        task_file = tmp_path / "task.json"
        task_file.write_text(json.dumps({
            "topic": "T",
            "questions": ["Q1"],
        }), encoding="utf-8")
        with pytest.raises(ValueError, match="scope"):
            _parse_task(task_file)

    def test_invalid_json(self, tmp_path):
        task_file = tmp_path / "task.json"
        task_file.write_text("not json", encoding="utf-8")
        with pytest.raises(ValueError, match="Cannot parse"):
            _parse_task(task_file)


# ---------------------------------------------------------------------------
# _scan_queue
# ---------------------------------------------------------------------------


class TestScanQueue:
    @patch("app.research_runner.raw_research_queue")
    def test_empty_queue(self, mock_queue, tmp_path):
        queue_dir = tmp_path / "queue"
        queue_dir.mkdir()
        mock_queue.return_value = queue_dir
        result = _scan_queue("/vault")
        assert result == []

    @patch("app.research_runner.raw_research_queue")
    def test_finds_json_files(self, mock_queue, tmp_path):
        queue_dir = tmp_path / "queue"
        queue_dir.mkdir()
        (queue_dir / "2026-01-01-task.json").write_text("{}", encoding="utf-8")
        (queue_dir / "2026-01-02-task.json").write_text("{}", encoding="utf-8")
        (queue_dir / "readme.txt").write_text("ignore", encoding="utf-8")
        mock_queue.return_value = queue_dir
        result = _scan_queue("/vault")
        assert len(result) == 2
        assert all(p.suffix == ".json" for p in result)

    @patch("app.research_runner.raw_research_queue")
    def test_sorted_by_name(self, mock_queue, tmp_path):
        queue_dir = tmp_path / "queue"
        queue_dir.mkdir()
        (queue_dir / "b.json").write_text("{}", encoding="utf-8")
        (queue_dir / "a.json").write_text("{}", encoding="utf-8")
        mock_queue.return_value = queue_dir
        result = _scan_queue("/vault")
        assert result[0].name == "a.json"
        assert result[1].name == "b.json"

    @patch("app.research_runner.raw_research_queue")
    def test_target_file(self, mock_queue, tmp_path):
        queue_dir = tmp_path / "queue"
        queue_dir.mkdir()
        target = queue_dir / "specific.json"
        target.write_text("{}", encoding="utf-8")
        (queue_dir / "other.json").write_text("{}", encoding="utf-8")
        mock_queue.return_value = queue_dir
        result = _scan_queue("/vault", target_file="specific.json")
        assert len(result) == 1
        assert result[0].name == "specific.json"

    @patch("app.research_runner.raw_research_queue")
    def test_target_file_not_found(self, mock_queue, tmp_path):
        queue_dir = tmp_path / "queue"
        queue_dir.mkdir()
        mock_queue.return_value = queue_dir
        result = _scan_queue("/vault", target_file="missing.json")
        assert result == []

    @patch("app.research_runner.raw_research_queue")
    def test_nonexistent_queue_dir(self, mock_queue, tmp_path):
        mock_queue.return_value = tmp_path / "nonexistent"
        result = _scan_queue("/vault")
        assert result == []


# ---------------------------------------------------------------------------
# _resolve_method
# ---------------------------------------------------------------------------


class TestResolveMethod:
    def test_override(self):
        config = ModeratorConfig()
        assert _resolve_method(config, "external") == "external"

    def test_cowork_fallback(self):
        config = ModeratorConfig(report_method="cowork")
        assert _resolve_method(config, None) == "internal"

    def test_internal_from_config(self):
        config = ModeratorConfig(report_method="internal")
        assert _resolve_method(config, None) == "internal"


# ---------------------------------------------------------------------------
# _check_existing_report
# ---------------------------------------------------------------------------


class TestCheckExistingReport:
    @patch("app.research_runner.wiki_reports")
    def test_no_existing(self, mock_reports, tmp_path):
        mock_reports.return_value = tmp_path
        task = ResearchTask(topic="New Topic", questions=["q"], scope="s")
        assert _check_existing_report("/vault", task) is None

    @patch("app.research_runner.wiki_reports")
    def test_existing_found(self, mock_reports, tmp_path):
        mock_reports.return_value = tmp_path
        task = ResearchTask(topic="New Topic", questions=["q"], scope="s")
        report = tmp_path / f"2026-01-01-{task.slug}.md"
        report.write_text("content", encoding="utf-8")
        result = _check_existing_report("/vault", task)
        assert result is not None
        assert result.name == report.name


# ---------------------------------------------------------------------------
# _collect_context
# ---------------------------------------------------------------------------


class TestCollectContext:
    def test_both_contexts(self, tmp_path):
        concepts_dir = tmp_path / "wiki" / "concepts"
        concepts_dir.mkdir(parents=True)
        (concepts_dir / "business-context-brief.md").write_text(
            "Business context", encoding="utf-8"
        )

        reports_dir = tmp_path / "wiki" / "reports"
        reports_dir.mkdir(parents=True)
        (reports_dir / "Competitor-Info-Booking.md").write_text(
            "Booking info", encoding="utf-8"
        )

        task = ResearchTask(
            topic="t", questions=["q"], scope="s", competitor="Booking",
        )
        ctx = _collect_context(str(tmp_path), task)
        assert ctx["business_context"] == "Business context"
        assert ctx["competitor_context"] == "Booking info"

    def test_no_files(self, tmp_path):
        task = ResearchTask(topic="t", questions=["q"], scope="s")
        ctx = _collect_context(str(tmp_path), task)
        assert ctx["business_context"] == ""
        assert ctx["competitor_context"] == ""

    def test_no_competitor(self, tmp_path):
        concepts_dir = tmp_path / "wiki" / "concepts"
        concepts_dir.mkdir(parents=True)
        (concepts_dir / "business-context-brief.md").write_text("BC", encoding="utf-8")

        task = ResearchTask(topic="t", questions=["q"], scope="s")
        ctx = _collect_context(str(tmp_path), task)
        assert ctx["business_context"] == "BC"
        assert ctx["competitor_context"] == ""


# ---------------------------------------------------------------------------
# _format_report
# ---------------------------------------------------------------------------


class TestFormatReport:
    def test_contains_frontmatter(self):
        task = ResearchTask(
            topic="Test", questions=["Q1", "Q2"], scope="s",
            signal_source="news",
        )
        result = _format_report("Report body", task, 8)
        assert "---" in result
        assert "type: research-report" in result
        assert 'topic: "Test"' in result
        assert "completeness: 8" in result
        assert "decay_rate: 0.03" in result

    def test_contains_questions(self):
        task = ResearchTask(topic="T", questions=["Q1", "Q2"], scope="s")
        result = _format_report("Body", task, 5)
        assert '"Q1"' in result
        assert '"Q2"' in result

    def test_contains_heading(self):
        task = ResearchTask(topic="My Topic", questions=["q"], scope="s")
        result = _format_report("Content", task, 7)
        assert "# Исследование: My Topic" in result

    def test_contains_body(self):
        task = ResearchTask(topic="T", questions=["q"], scope="s")
        result = _format_report("Actual content here", task, 6)
        assert "Actual content here" in result


# ---------------------------------------------------------------------------
# _generate_internal_report
# ---------------------------------------------------------------------------


class TestGenerateInternalReport:
    @patch("app.research_runner.call_detailed")
    def test_success(self, mock_call):
        mock_call.return_value = ("A" * 300, {"input_tokens": 100, "output_tokens": 200, "used": "claude"})
        task = ResearchTask(topic="T", questions=["Q1"], scope="s")
        context = {"business_context": "bc", "competitor_context": "cc"}
        config = ModeratorConfig()

        content, t_in, t_out = _generate_internal_report(task, context, config)
        assert len(content) == 300
        assert t_in == 100
        assert t_out == 200
        mock_call.assert_called_once()

    @patch("app.research_runner.call_detailed")
    def test_retry_on_short_response(self, mock_call):
        mock_call.side_effect = [
            ("short", {"input_tokens": 10, "output_tokens": 5, "used": "claude"}),
            ("A" * 300, {"input_tokens": 100, "output_tokens": 200, "used": "claude"}),
        ]
        task = ResearchTask(topic="T", questions=["Q1"], scope="s")
        context = {"business_context": "", "competitor_context": ""}
        config = ModeratorConfig()

        content, t_in, t_out = _generate_internal_report(task, context, config)
        assert len(content) == 300
        assert mock_call.call_count == 2

    @patch("app.research_runner.call_detailed")
    def test_error_after_retries(self, mock_call):
        mock_call.side_effect = RuntimeError("LLM failed")
        task = ResearchTask(topic="T", questions=["Q1"], scope="s")
        context = {"business_context": "", "competitor_context": ""}
        config = ModeratorConfig()

        with pytest.raises(ResearchError, match="LLM call failed"):
            _generate_internal_report(task, context, config)

    @patch("app.research_runner.call_detailed")
    def test_short_response_after_all_retries(self, mock_call):
        mock_call.return_value = ("x", {"input_tokens": 1, "output_tokens": 1, "used": "claude"})
        task = ResearchTask(topic="T", questions=["Q1"], scope="s")
        context = {"business_context": "", "competitor_context": ""}
        config = ModeratorConfig()

        with pytest.raises(ResearchError, match="too short"):
            _generate_internal_report(task, context, config)

    @patch("app.research_runner.call_detailed")
    def test_null_tokens_default_to_zero(self, mock_call):
        mock_call.return_value = ("A" * 300, {"input_tokens": None, "output_tokens": None, "used": "claude"})
        task = ResearchTask(topic="T", questions=["Q1"], scope="s")
        context = {"business_context": "", "competitor_context": ""}
        config = ModeratorConfig()

        _, t_in, t_out = _generate_internal_report(task, context, config)
        assert t_in == 0
        assert t_out == 0


# ---------------------------------------------------------------------------
# _run_completeness_check
# ---------------------------------------------------------------------------


class TestRunCompletenessCheck:
    @patch("app.research_runner.QualityGate")
    def test_success(self, MockGate):
        mock_result = MagicMock()
        mock_result.score = 8
        mock_result.improvements = {
            "_quality_warning": False,
            "unanswered_questions": [],
        }
        MockGate.return_value.check_report_completeness.return_value = mock_result

        score, warning, unanswered = _run_completeness_check(
            "Report content", ["Q1"], "/vault", ModeratorConfig(),
        )
        assert score == 8
        assert warning is False
        assert unanswered == []

    @patch("app.research_runner.QualityGate")
    def test_quality_warning(self, MockGate):
        mock_result = MagicMock()
        mock_result.score = 5
        mock_result.improvements = {
            "_quality_warning": True,
            "unanswered_questions": [1, 3],
        }
        MockGate.return_value.check_report_completeness.return_value = mock_result

        score, warning, unanswered = _run_completeness_check(
            "Content", ["Q1", "Q2", "Q3"], "/vault", ModeratorConfig(),
        )
        assert score == 5
        assert warning is True
        assert unanswered == [1, 3]

    @patch("app.research_runner.QualityGate")
    def test_exception_returns_defaults(self, MockGate):
        MockGate.return_value.check_report_completeness.side_effect = RuntimeError("fail")

        score, warning, unanswered = _run_completeness_check(
            "Content", ["Q1"], "/vault", ModeratorConfig(),
        )
        assert score == 5
        assert warning is False
        assert unanswered == []


# ---------------------------------------------------------------------------
# _move_task_file
# ---------------------------------------------------------------------------


class TestMoveTaskFile:
    @patch("app.research_runner.raw_research_queue_processed")
    def test_move_to_processed(self, mock_processed, tmp_path):
        src = tmp_path / "task.json"
        src.write_text("{}", encoding="utf-8")
        dest_dir = tmp_path / "processed"
        dest_dir.mkdir()
        mock_processed.return_value = dest_dir

        _move_task_file(src, "processed", "/vault")
        assert not src.exists()
        assert (dest_dir / "task.json").exists()

    @patch("app.research_runner.raw_research_queue_failed")
    def test_move_to_failed(self, mock_failed, tmp_path):
        src = tmp_path / "task.json"
        src.write_text("{}", encoding="utf-8")
        dest_dir = tmp_path / "failed"
        dest_dir.mkdir()
        mock_failed.return_value = dest_dir

        _move_task_file(src, "failed", "/vault")
        assert not src.exists()
        assert (dest_dir / "task.json").exists()

    def test_nonexistent_source(self, tmp_path):
        src = tmp_path / "nonexistent.json"
        _move_task_file(src, "processed", "/vault")  # should not raise


# ---------------------------------------------------------------------------
# process_task
# ---------------------------------------------------------------------------


class TestProcessTask:
    @patch("app.research_runner._move_task_file")
    @patch("app.research_runner._check_existing_report")
    def test_existing_report_skips(self, mock_check, mock_move, tmp_path):
        existing = tmp_path / "report-existing.md"
        existing.write_text("old", encoding="utf-8")
        mock_check.return_value = existing

        task = ResearchTask(
            topic="T", questions=["q"], scope="s",
            source_path=tmp_path / "task.json",
        )
        result = process_task(task, "/vault", ModeratorConfig())
        assert result.report_path == str(existing)
        assert result.error is None
        mock_move.assert_called_once()

    @patch("app.research_runner._move_task_file")
    @patch("app.research_runner._write_report")
    @patch("app.research_runner._run_completeness_check")
    @patch("app.research_runner._generate_internal_report")
    @patch("app.research_runner._collect_context")
    @patch("app.research_runner._check_existing_report")
    def test_full_pipeline(
        self, mock_check, mock_ctx, mock_gen, mock_comp, mock_write, mock_move,
    ):
        mock_check.return_value = None
        mock_ctx.return_value = {"business_context": "", "competitor_context": ""}
        mock_gen.return_value = ("Report content " * 20, 100, 200)
        mock_comp.return_value = (8, False, [])
        mock_write.return_value = Path("/vault/wiki/reports/report-t.md")

        task = ResearchTask(
            topic="T", questions=["Q1"], scope="s",
            source_path=Path("/tmp/task.json"),
        )
        result = process_task(task, "/vault", ModeratorConfig())
        assert result.completeness == 8
        assert result.quality_warning is False
        assert result.tokens_in == 100
        assert result.tokens_out == 200
        assert result.error is None
        mock_write.assert_called_once()
        mock_move.assert_called_once()

    @patch("app.research_runner._move_task_file")
    @patch("app.research_runner._write_report")
    @patch("app.research_runner._run_completeness_check")
    @patch("app.research_runner._generate_internal_report")
    @patch("app.research_runner._collect_context")
    @patch("app.research_runner._check_existing_report")
    def test_retry_on_low_completeness(
        self, mock_check, mock_ctx, mock_gen, mock_comp, mock_write, mock_move,
    ):
        mock_check.return_value = None
        mock_ctx.return_value = {"business_context": "", "competitor_context": ""}
        mock_gen.side_effect = [
            ("Initial content " * 20, 50, 100),
            ("Retry content " * 20, 30, 60),
        ]
        mock_comp.side_effect = [
            (3, False, [1]),   # first check: score < 4, triggers retry
            (7, False, []),    # after retry: score OK
        ]
        mock_write.return_value = Path("/vault/wiki/reports/report-t.md")

        task = ResearchTask(
            topic="T", questions=["Q1"], scope="s",
            source_path=Path("/tmp/task.json"),
        )
        result = process_task(task, "/vault", ModeratorConfig())
        assert result.completeness == 7
        assert result.tokens_in == 80  # 50 + 30
        assert result.tokens_out == 160  # 100 + 60
        assert mock_gen.call_count == 2

    @patch("app.research_runner._move_task_file")
    @patch("app.research_runner._write_report")
    @patch("app.research_runner._run_completeness_check")
    @patch("app.research_runner._generate_internal_report")
    @patch("app.research_runner._collect_context")
    @patch("app.research_runner._check_existing_report")
    def test_catastrophic_quality_full_regeneration(
        self, mock_check, mock_ctx, mock_gen, mock_comp, mock_write, mock_move,
    ):
        """BUG-028: score < 2 triggers full regeneration, not supplement."""
        mock_check.return_value = None
        mock_ctx.return_value = {"business_context": "", "competitor_context": ""}
        mock_gen.side_effect = [
            ("Garbage " * 50, 100, 200),      # first: garbage
            ("Good content " * 50, 100, 200),  # regeneration: good
        ]
        mock_comp.side_effect = [
            (0, True, []),   # first check: catastrophic
            (8, False, []),  # after regeneration: good
        ]
        mock_write.return_value = Path("/vault/wiki/reports/report-t.md")

        task = ResearchTask(
            topic="T", questions=["Q1"], scope="s",
            source_path=Path("/tmp/task.json"),
        )
        result = process_task(task, "/vault", ModeratorConfig())
        assert result.completeness == 8
        assert result.error is None
        assert mock_gen.call_count == 2
        mock_move.assert_called_once_with(Path("/tmp/task.json"), "processed", "/vault")

    @patch("app.research_runner._move_task_file")
    @patch("app.research_runner._write_report")
    @patch("app.research_runner._run_completeness_check")
    @patch("app.research_runner._generate_internal_report")
    @patch("app.research_runner._collect_context")
    @patch("app.research_runner._check_existing_report")
    def test_rejected_report_goes_to_failed(
        self, mock_check, mock_ctx, mock_gen, mock_comp, mock_write, mock_move,
    ):
        """BUG-028: if score stays below threshold after retry, move to failed."""
        mock_check.return_value = None
        mock_ctx.return_value = {"business_context": "", "competitor_context": ""}
        mock_gen.side_effect = [
            ("Bad content " * 20, 50, 100),   # first attempt
            ("Still bad " * 20, 50, 100),     # regeneration attempt
        ]
        mock_comp.side_effect = [
            (1, True, []),   # first check: catastrophic
            (2, True, []),   # after regeneration: still bad
        ]

        task = ResearchTask(
            topic="T", questions=["Q1"], scope="s",
            source_path=Path("/tmp/task.json"),
        )
        result = process_task(task, "/vault", ModeratorConfig())
        assert result.completeness == 2
        assert result.error is not None
        assert "Rejected" in result.error
        assert result.report_path is None
        mock_write.assert_not_called()
        mock_move.assert_called_once_with(Path("/tmp/task.json"), "failed", "/vault")

    @patch("app.research_runner._move_task_file")
    @patch("app.research_runner._write_report")
    @patch("app.research_runner._run_completeness_check")
    @patch("app.research_runner._generate_internal_report")
    @patch("app.research_runner._collect_context")
    @patch("app.research_runner._check_existing_report")
    def test_partial_quality_supplement_then_accept(
        self, mock_check, mock_ctx, mock_gen, mock_comp, mock_write, mock_move,
    ):
        """BUG-028: score 2-3 with unanswered triggers supplement, not regeneration."""
        mock_check.return_value = None
        mock_ctx.return_value = {"business_context": "", "competitor_context": ""}
        mock_gen.side_effect = [
            ("Partial content " * 20, 50, 100),
            ("Supplement " * 20, 30, 60),
        ]
        mock_comp.side_effect = [
            (3, False, [1]),   # partial quality with unanswered
            (7, False, []),    # after supplement: good
        ]
        mock_write.return_value = Path("/vault/wiki/reports/report-t.md")

        task = ResearchTask(
            topic="T", questions=["Q1"], scope="s",
            source_path=Path("/tmp/task.json"),
        )
        result = process_task(task, "/vault", ModeratorConfig())
        assert result.completeness == 7
        assert result.error is None
        mock_move.assert_called_once_with(Path("/tmp/task.json"), "processed", "/vault")

    @patch("app.research_runner._move_task_file")
    @patch("app.research_runner._write_report")
    @patch("app.research_runner._run_completeness_check")
    @patch("app.research_runner._generate_internal_report")
    @patch("app.research_runner._collect_context")
    @patch("app.research_runner._check_existing_report")
    def test_score_at_threshold_passes(
        self, mock_check, mock_ctx, mock_gen, mock_comp, mock_write, mock_move,
    ):
        """BUG-028: score == completeness_threshold should pass."""
        mock_check.return_value = None
        mock_ctx.return_value = {"business_context": "", "competitor_context": ""}
        mock_gen.return_value = ("OK content " * 30, 100, 200)
        mock_comp.return_value = (6, False, [])
        mock_write.return_value = Path("/vault/wiki/reports/report-t.md")

        task = ResearchTask(
            topic="T", questions=["Q1"], scope="s",
            source_path=Path("/tmp/task.json"),
        )
        result = process_task(task, "/vault", ModeratorConfig())
        assert result.completeness == 6
        assert result.error is None
        assert result.report_path is not None
        mock_move.assert_called_once_with(Path("/tmp/task.json"), "processed", "/vault")

    @patch("app.research_runner._check_existing_report")
    @patch("app.research_runner._collect_context")
    @patch("app.research_runner._generate_internal_report")
    @patch("app.research_runner._run_completeness_check")
    def test_dry_run_no_write(self, mock_comp, mock_gen, mock_ctx, mock_check):
        mock_check.return_value = None
        mock_ctx.return_value = {"business_context": "", "competitor_context": ""}
        mock_gen.return_value = ("Content " * 30, 100, 200)
        mock_comp.return_value = (8, False, [])

        task = ResearchTask(
            topic="T", questions=["Q1"], scope="s",
            source_path=Path("/tmp/task.json"),
        )
        result = process_task(task, "/vault", ModeratorConfig(), dry_run=True)
        assert result.report_path is None
        assert result.error is None


# ---------------------------------------------------------------------------
# run_all
# ---------------------------------------------------------------------------


class TestRunAll:
    @patch("app.research_runner._scan_queue")
    @patch("app.research_runner.load_config_from_settings")
    def test_empty_queue(self, mock_config, mock_scan):
        mock_config.return_value = ModeratorConfig()
        mock_scan.return_value = []
        results = run_all("/vault")
        assert results == []

    @patch("app.research_runner.process_task")
    @patch("app.research_runner._parse_task")
    @patch("app.research_runner._scan_queue")
    @patch("app.research_runner.load_config_from_settings")
    def test_processes_tasks(self, mock_config, mock_scan, mock_parse, mock_process, tmp_path):
        mock_config.return_value = ModeratorConfig()
        task_file = tmp_path / "task.json"
        task_file.write_text(json.dumps({
            "topic": "T", "questions": ["Q"], "scope": "s",
        }), encoding="utf-8")
        mock_scan.return_value = [task_file]
        mock_parse.return_value = ResearchTask(
            topic="T", questions=["Q"], scope="s", source_path=task_file,
        )
        mock_process.return_value = ResearchResult(
            topic="T", report_path="/vault/report.md", completeness=8,
            quality_warning=False, ideas_count=0, tokens_in=100,
            tokens_out=200, method="internal", error=None,
        )

        results = run_all("/vault")
        assert len(results) == 1
        assert results[0].completeness == 8
        assert results[0].error is None

    @patch("app.research_runner._parse_task")
    @patch("app.research_runner._scan_queue")
    @patch("app.research_runner.load_config_from_settings")
    def test_error_per_task_no_abort(self, mock_config, mock_scan, mock_parse, tmp_path):
        mock_config.return_value = ModeratorConfig()
        f1 = tmp_path / "task1.json"
        f1.write_text("{}", encoding="utf-8")
        f2 = tmp_path / "task2.json"
        f2.write_text("{}", encoding="utf-8")
        mock_scan.return_value = [f1, f2]
        mock_parse.side_effect = ValueError("bad task")

        results = run_all("/vault")
        assert len(results) == 2
        assert all(r.error is not None for r in results)


# ---------------------------------------------------------------------------
# Outcome classification (BL-198): _classify_by_reason, _extract_and_classify,
# _update_processed_json, and the outcome fields on process_task's result.
# ---------------------------------------------------------------------------


class TestOutcome:
    @patch("app.research_runner._update_processed_json")
    @patch("app.research_runner.update_frontmatter")
    @patch("app.research_runner.dispatch_signal")
    @patch("app.research_runner.extract_signals")
    def test_outcome_signal_dispatches_signals(
        self, mock_extract, mock_dispatch, mock_fm, mock_proc, tmp_path,
    ):
        from app.signal_moderator import SignalData

        mock_extract.return_value = [
            SignalData(title="Signal 1", analysis="a1"),
            SignalData(title="Signal 2", analysis="a2"),
        ]
        mock_dispatch.side_effect = ["ref1", "ref2"]

        report_path = tmp_path / "report.md"
        report_path.write_text("content", encoding="utf-8")
        task = ResearchTask(
            topic="T", questions=["Q1"], scope="s",
            source_path=tmp_path / "task.json",
        )

        # Create business context file expected by _extract_and_classify
        bc_dir = tmp_path / "wiki" / "concepts"
        bc_dir.mkdir(parents=True, exist_ok=True)
        (bc_dir / "business-context-brief.md").write_text("bc", encoding="utf-8")

        outcome, details, count, refs = _extract_and_classify(
            report_path=report_path,
            task=task,
            vault_path=str(tmp_path),
            config=ModeratorConfig(),
        )

        assert outcome == "signal"
        assert count == 2
        assert refs == ["ref1", "ref2"]
        assert mock_dispatch.call_count == 2

        # Verify dispatch_signal called with source="research-report"
        for call_args in mock_dispatch.call_args_list:
            assert call_args[1]["item"]["source"] == "research-report"

        mock_fm.assert_called_once()
        fm_path, fm_data = mock_fm.call_args[0]
        assert fm_path == report_path
        assert fm_data["outcome"] == "signal"
        assert fm_data["signals_count"] == 2

    @patch("app.research_runner._update_processed_json")
    @patch("app.research_runner.update_frontmatter")
    @patch("app.research_runner.dispatch_signal")
    @patch("app.research_runner.extract_signals")
    def test_outcome_no_signals_insight(
        self, mock_extract, mock_dispatch, mock_fm, mock_proc, tmp_path,
    ):
        mock_extract.return_value = []

        report_path = tmp_path / "report.md"
        report_path.write_text("content", encoding="utf-8")
        task = ResearchTask(
            topic="T", questions=["Q1"], scope="s",
            source_path=tmp_path / "task.json",
        )

        outcome, details, count, refs = _extract_and_classify(
            report_path=report_path,
            task=task,
            vault_path=str(tmp_path),
            config=ModeratorConfig(),
        )

        assert outcome == "insight"
        assert "No actionable signals" in details
        assert count == 0
        mock_dispatch.assert_not_called()

    @patch("app.research_runner._update_processed_json")
    @patch("app.research_runner.update_frontmatter")
    @patch("app.research_runner.dispatch_signal")
    @patch("app.research_runner.extract_signals")
    def test_outcome_empty_signals_list(
        self, mock_extract, mock_dispatch, mock_fm, mock_proc, tmp_path,
    ):
        """When extract_signals() returns [], outcome should be 'insight'."""
        mock_extract.return_value = []

        report_path = tmp_path / "report.md"
        report_path.write_text("content", encoding="utf-8")
        task = ResearchTask(
            topic="T", questions=["Q1"], scope="s",
            source_path=tmp_path / "task.json",
        )

        outcome, details, count, refs = _extract_and_classify(
            report_path=report_path,
            task=task,
            vault_path=str(tmp_path),
            config=ModeratorConfig(),
        )

        assert outcome == "insight"
        assert count == 0
        assert refs == []
        mock_dispatch.assert_not_called()

        mock_fm.assert_called_once()
        fm_path, fm_data = mock_fm.call_args[0]
        assert fm_data["signals_count"] == 0
        assert fm_data["signal_refs"] == []

    @patch("app.research_runner.update_frontmatter")
    @patch("app.research_runner.extract_signals")
    @patch("app.research_runner._move_task_file")
    @patch("app.research_runner._write_report")
    @patch("app.research_runner._run_completeness_check")
    @patch("app.research_runner._generate_internal_report")
    @patch("app.research_runner._collect_context")
    @patch("app.research_runner._check_existing_report")
    def test_outcome_error_does_not_block_report(
        self, mock_check, mock_ctx, mock_gen, mock_comp, mock_write, mock_move,
        mock_extract, mock_fm,
    ):
        """A crash inside signal extraction/classification must never poison the
        already-written report or the overall ResearchResult.error field."""
        mock_check.return_value = None
        mock_ctx.return_value = {"business_context": "", "competitor_context": ""}
        mock_gen.return_value = ("Report content " * 20, 100, 200)
        mock_comp.return_value = (8, False, [])
        mock_write.return_value = Path("/vault/wiki/reports/report-t.md")
        mock_extract.side_effect = Exception("LLM timeout")

        task = ResearchTask(
            topic="T", questions=["Q1"], scope="s",
            source_path=Path("/tmp/task.json"),
        )
        result = process_task(task, "/vault", ModeratorConfig())

        assert result.report_path is not None
        assert result.error is None
        assert result.outcome == "error"
        assert "LLM timeout" in result.outcome_details

    @patch("app.research_runner._extract_and_classify")
    @patch("app.research_runner._move_task_file")
    @patch("app.research_runner._write_report")
    @patch("app.research_runner._run_completeness_check")
    @patch("app.research_runner._generate_internal_report")
    @patch("app.research_runner._collect_context")
    @patch("app.research_runner._check_existing_report")
    def test_outcome_skipped_on_dry_run(
        self, mock_check, mock_ctx, mock_gen, mock_comp, mock_write, mock_move,
        mock_extract,
    ):
        mock_check.return_value = None
        mock_ctx.return_value = {"business_context": "", "competitor_context": ""}
        mock_gen.return_value = ("Content " * 30, 100, 200)
        mock_comp.return_value = (8, False, [])

        task = ResearchTask(
            topic="T", questions=["Q1"], scope="s",
            source_path=Path("/tmp/task.json"),
        )
        result = process_task(task, "/vault", ModeratorConfig(), dry_run=True)

        mock_extract.assert_not_called()
        assert result.outcome is None

    def test_classify_by_reason_markers(self):
        assert _classify_by_reason("") == "insight"
        assert _classify_by_reason("Не наш профиль, другая отрасль") == "not_relevant"
        assert _classify_by_reason("Нет пересечений с продуктом") == "not_relevant"
        assert _classify_by_reason("Тема полезная, но конкретных идей нет") == "insight"
        assert _classify_by_reason("Вне сферы деятельности компании") == "not_relevant"

    @patch("app.research_runner.raw_research_queue_processed")
    def test_update_processed_json(self, mock_processed, tmp_path):
        proc_dir = tmp_path / "processed"
        proc_dir.mkdir()
        proc_file = proc_dir / "task.json"
        proc_file.write_text(
            json.dumps({"topic": "T", "questions": ["Q"], "scope": "s"}),
            encoding="utf-8",
        )
        mock_processed.return_value = proc_dir

        _update_processed_json(Path("/tmp/task.json"), {
            "outcome": "signal",
            "outcome_details": "",
            "signals_count": 2,
            "signal_refs": ["ref1", "ref2"],
        })

        data = json.loads(proc_file.read_text(encoding="utf-8"))
        assert data["outcome"] == "signal"
        assert data["signals_count"] == 2
        assert data["signal_refs"] == ["ref1", "ref2"]
        # original fields preserved
        assert data["topic"] == "T"
