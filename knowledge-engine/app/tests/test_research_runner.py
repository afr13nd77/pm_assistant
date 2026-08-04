"""Tests for research_runner — existing report outcome recovery (BL-200 / BUG-030)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.research_runner import ResearchResult, ResearchTask, process_task


def _make_task(**overrides) -> ResearchTask:
    defaults = dict(
        topic="Test Topic",
        questions=["Q1?", "Q2?"],
        scope="test scope",
        signal_source="test",
        signal_date="2026-08-04",
        competitor="",
        source_path=Path("/fake/queue/task.json"),
    )
    defaults.update(overrides)
    return ResearchTask(**defaults)


def _make_config() -> MagicMock:
    cfg = MagicMock()
    cfg.report_method = "internal"
    cfg.completeness_threshold = 6
    return cfg


_MODULE = "app.research_runner"


class TestExistingReportOutcomeRecovery:
    """When an existing report is found, outcome=None must trigger _extract_and_classify."""

    @patch(f"{_MODULE}._move_task_file")
    @patch(f"{_MODULE}._extract_and_classify")
    @patch(f"{_MODULE}.read_frontmatter")
    @patch(f"{_MODULE}._check_existing_report")
    def test_outcome_none_triggers_extract_and_classify(
        self,
        mock_check_existing: MagicMock,
        mock_read_fm: MagicMock,
        mock_extract: MagicMock,
        mock_move: MagicMock,
    ):
        """When existing report has outcome=None, _extract_and_classify MUST be called."""
        existing_path = Path("/vault/wiki/reports/2026-08-04-test-topic.md")
        mock_check_existing.return_value = existing_path

        # Frontmatter without outcome (simulates crash before step 8a)
        mock_read_fm.return_value = ({"completeness": 7}, "body text")

        mock_extract.return_value = ("idea", "found ideas", 3, ["ref1", "ref2", "ref3"])

        task = _make_task()
        config = _make_config()

        result = process_task(task, "/vault", config, method="internal")

        # _extract_and_classify MUST have been called
        mock_extract.assert_called_once_with(
            report_path=existing_path,
            task=task,
            vault_path="/vault",
            config=config,
        )

        assert isinstance(result, ResearchResult)
        assert result.outcome == "idea"
        assert result.outcome_details == "found ideas"
        assert result.ideas_count == 3
        assert result.completeness == 7
        assert result.report_path == str(existing_path)
        assert result.error is None

    @patch(f"{_MODULE}._move_task_file")
    @patch(f"{_MODULE}._extract_and_classify")
    @patch(f"{_MODULE}.read_frontmatter")
    @patch(f"{_MODULE}._check_existing_report")
    def test_outcome_set_skips_extract_and_classify(
        self,
        mock_check_existing: MagicMock,
        mock_read_fm: MagicMock,
        mock_extract: MagicMock,
        mock_move: MagicMock,
    ):
        """When existing report already has outcome, _extract_and_classify must NOT be called."""
        existing_path = Path("/vault/wiki/reports/2026-08-04-test-topic.md")
        mock_check_existing.return_value = existing_path

        # Frontmatter WITH outcome already set
        mock_read_fm.return_value = (
            {
                "completeness": 8,
                "outcome": "idea",
                "outcome_details": "found 2 ideas",
                "ideas_count": 2,
            },
            "body text",
        )

        task = _make_task()
        config = _make_config()

        result = process_task(task, "/vault", config, method="internal")

        # _extract_and_classify must NOT have been called
        mock_extract.assert_not_called()

        assert isinstance(result, ResearchResult)
        assert result.outcome == "idea"
        assert result.outcome_details == "found 2 ideas"
        assert result.ideas_count == 2
        assert result.completeness == 8
        assert result.report_path == str(existing_path)
        assert result.error is None

    @patch(f"{_MODULE}._move_task_file")
    @patch(f"{_MODULE}._extract_and_classify")
    @patch(f"{_MODULE}.read_frontmatter")
    @patch(f"{_MODULE}._check_existing_report")
    def test_result_fields_correct_with_existing_outcome(
        self,
        mock_check_existing: MagicMock,
        mock_read_fm: MagicMock,
        mock_extract: MagicMock,
        mock_move: MagicMock,
    ):
        """Returned ResearchResult must have correct field values from frontmatter."""
        existing_path = Path("/vault/wiki/reports/2026-08-04-test-topic.md")
        mock_check_existing.return_value = existing_path
        mock_read_fm.return_value = (
            {
                "completeness": 9,
                "outcome": "not_relevant",
                "outcome_details": "Не наш профиль",
                "ideas_count": 0,
            },
            "body",
        )

        task = _make_task()
        config = _make_config()

        result = process_task(task, "/vault", config, method="internal")

        assert result.topic == "Test Topic"
        assert result.method == "internal"
        assert result.tokens_in == 0
        assert result.tokens_out == 0
        assert result.quality_warning is False
        assert result.outcome == "not_relevant"
        assert result.outcome_details == "Не наш профиль"
        assert result.ideas_count == 0
        assert result.completeness == 9

    @patch(f"{_MODULE}._move_task_file")
    @patch(f"{_MODULE}._extract_and_classify")
    @patch(f"{_MODULE}.read_frontmatter")
    @patch(f"{_MODULE}._check_existing_report")
    def test_move_task_file_called_before_outcome_check(
        self,
        mock_check_existing: MagicMock,
        mock_read_fm: MagicMock,
        mock_extract: MagicMock,
        mock_move: MagicMock,
    ):
        """Task file must be moved to processed/ regardless of outcome status."""
        existing_path = Path("/vault/wiki/reports/2026-08-04-test-topic.md")
        mock_check_existing.return_value = existing_path
        mock_read_fm.return_value = ({"completeness": 5}, "body")
        mock_extract.return_value = ("insight", "info only", 0, [])

        task = _make_task()
        config = _make_config()

        process_task(task, "/vault", config, method="internal", dry_run=False)

        mock_move.assert_called_once_with(task.source_path, "processed", "/vault")

    @patch(f"{_MODULE}._move_task_file")
    @patch(f"{_MODULE}._extract_and_classify")
    @patch(f"{_MODULE}.read_frontmatter")
    @patch(f"{_MODULE}._check_existing_report")
    def test_dry_run_skips_move(
        self,
        mock_check_existing: MagicMock,
        mock_read_fm: MagicMock,
        mock_extract: MagicMock,
        mock_move: MagicMock,
    ):
        """In dry_run mode, task file must NOT be moved."""
        existing_path = Path("/vault/wiki/reports/2026-08-04-test-topic.md")
        mock_check_existing.return_value = existing_path
        mock_read_fm.return_value = ({"outcome": "idea", "ideas_count": 1}, "body")

        task = _make_task()
        config = _make_config()

        process_task(task, "/vault", config, method="internal", dry_run=True)

        mock_move.assert_not_called()

    @patch(f"{_MODULE}._move_task_file")
    @patch(f"{_MODULE}._extract_and_classify")
    @patch(f"{_MODULE}.read_frontmatter")
    @patch(f"{_MODULE}._check_existing_report")
    def test_frontmatter_read_failure_falls_back_to_extract(
        self,
        mock_check_existing: MagicMock,
        mock_read_fm: MagicMock,
        mock_extract: MagicMock,
        mock_move: MagicMock,
    ):
        """If read_frontmatter raises, treat as outcome=None and call _extract_and_classify."""
        existing_path = Path("/vault/wiki/reports/2026-08-04-test-topic.md")
        mock_check_existing.return_value = existing_path
        mock_read_fm.side_effect = Exception("YAML parse error")
        mock_extract.return_value = ("error", "YAML parse error", 0, [])

        task = _make_task()
        config = _make_config()

        result = process_task(task, "/vault", config, method="internal")

        # Should fall back to _extract_and_classify since meta is empty
        mock_extract.assert_called_once()
        assert result.outcome == "error"
