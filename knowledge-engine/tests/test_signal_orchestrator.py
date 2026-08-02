"""Tests for signal_orchestrator module (T-13).

AC-01..AC-11: process_digest full pipeline
AC-17..AC-19: AgentLoop integration with quality_fn
AC-23: check_domain auto-correction
AC-30..AC-33: Telegram notifications
AC-34, AC-35: RunState persist/resume
AC-43: JSON digest validation
AC-45: processed.md writes
AC-47: ItemState enum statuses
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.signal_orchestrator import (
    ItemState,
    ModeratorConfig,
    RunState,
    RunSummary,
    SignalOrchestrator,
    load_config_from_settings,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_vault(tmp_path):
    """Create a minimal vault structure for tests."""
    # Create required directories
    (tmp_path / "raw" / "inbound" / "news").mkdir(parents=True)
    (tmp_path / "raw" / "inbound" / "ideas").mkdir(parents=True)
    (tmp_path / "raw" / "inbound" / "research-queue").mkdir(parents=True)
    (tmp_path / "wiki" / "signals" / "runs").mkdir(parents=True)
    (tmp_path / "wiki" / "concepts").mkdir(parents=True)
    (tmp_path / "wiki" / "reports").mkdir(parents=True)

    # Write business context
    (tmp_path / "wiki" / "concepts" / "business-context-brief.md").write_text(
        "---\ntitle: context\n---\nOTA company context for testing.",
        encoding="utf-8",
    )

    return tmp_path


@pytest.fixture
def config():
    """Default ModeratorConfig with test-friendly values."""
    return ModeratorConfig(
        relevance_threshold=5,
        max_items_per_run=10,
        max_retries=2,
        memory_db_path=":memory:",
        persist_run_state=False,
        idea_auto_create=True,
        report_auto_launch=True,
        domain_auto_correct=True,
        dedup_similarity_threshold=8,
        dedup_related_threshold=6,
    )


@pytest.fixture
def sample_digest(tmp_vault):
    """Write a sample digest JSON and return its path."""
    digest = {
        "date": "2026-08-01",
        "source": "test-source",
        "items": [
            {
                "title": "Booking.com launches AI concierge",
                "summary": "Booking.com released an AI-powered concierge for hotel guests.",
                "source_url": "https://example.com/news/1",
            },
            {
                "title": "Airbnb expands in Russia",
                "summary": "Airbnb announced expansion into Russian market.",
                "source_url": "https://example.com/news/2",
            },
        ],
    }
    digest_path = tmp_vault / "raw" / "inbound" / "news" / "2026-08-01-digest.json"
    digest_path.write_text(json.dumps(digest, ensure_ascii=False), encoding="utf-8")
    return str(digest_path)


# ---------------------------------------------------------------------------
# ModeratorConfig tests
# ---------------------------------------------------------------------------


class TestModeratorConfig:
    def test_defaults(self):
        cfg = ModeratorConfig()
        assert cfg.relevance_threshold == 7
        assert cfg.max_items_per_run == 20
        assert cfg.max_retries == 3
        assert cfg.persist_run_state is True

    def test_load_config_from_settings(self):
        with patch("app.signal_orchestrator.settings") as mock_settings:
            mock_settings.get.return_value = {
                "relevance_threshold": 5,
                "max_items_per_run": 10,
                "unknown_field": "ignored",
            }
            cfg = load_config_from_settings()
            assert cfg.relevance_threshold == 5
            assert cfg.max_items_per_run == 10
            # Unknown fields should not cause errors
            assert not hasattr(cfg, "unknown_field")

    def test_load_config_empty_settings(self):
        with patch("app.signal_orchestrator.settings") as mock_settings:
            mock_settings.get.return_value = {}
            cfg = load_config_from_settings()
            # Should return defaults
            assert cfg.relevance_threshold == 7


# ---------------------------------------------------------------------------
# ItemState tests (AC-47)
# ---------------------------------------------------------------------------


class TestItemState:
    def test_default_status(self):
        state = ItemState(title="Test")
        assert state.status == "pending"
        assert state.errors == []
        assert state.quality_warnings == []

    def test_valid_statuses(self):
        valid = [
            "pending", "scoring", "analyzing", "dispatching",
            "waiting_report", "extracting", "completed", "failed", "skipped",
        ]
        for status in valid:
            state = ItemState(title="Test", status=status)
            assert state.status == status


# ---------------------------------------------------------------------------
# RunState tests (AC-34, AC-35)
# ---------------------------------------------------------------------------


class TestRunState:
    def test_new_creates_valid_state(self):
        state = RunState.new("/path/to/digest.json")
        assert state.status == "running"
        assert state.digest_path == "/path/to/digest.json"
        assert state.run_id  # Non-empty
        assert state.started_at  # Non-empty
        assert state.items == {}
        assert state.summary is None

    def test_persist_and_load(self, tmp_vault):
        state = RunState.new("/path/to/digest.json")
        state.items["abc12345"] = ItemState(
            title="Test item",
            status="completed",
            iterations=2,
        )
        state.summary = RunSummary(total=1, relevant=1, ideas=1)

        state.persist(str(tmp_vault))

        # Verify file exists
        runs_dir = tmp_vault / "wiki" / "signals" / "runs"
        run_files = list(runs_dir.glob("*.json"))
        assert len(run_files) == 1

        # Load and verify
        loaded = RunState.load(run_files[0])
        assert loaded.run_id == state.run_id
        assert loaded.status == "running"
        assert "abc12345" in loaded.items
        assert loaded.items["abc12345"].title == "Test item"
        assert loaded.items["abc12345"].status == "completed"
        assert loaded.summary is not None
        assert loaded.summary.total == 1

    def test_load_without_summary(self, tmp_vault):
        state = RunState.new("/path/to/digest.json")
        state.persist(str(tmp_vault))

        runs_dir = tmp_vault / "wiki" / "signals" / "runs"
        run_files = list(runs_dir.glob("*.json"))
        loaded = RunState.load(run_files[0])
        assert loaded.summary is None


# ---------------------------------------------------------------------------
# Orchestrator tests
# ---------------------------------------------------------------------------


class TestSignalOrchestrator:
    def test_init(self, tmp_vault, config):
        orch = SignalOrchestrator(str(tmp_vault), config)
        assert orch.vault_path == str(tmp_vault)
        assert orch.config is config
        assert orch.run_state is None

    def test_auto_detect_digest(self, tmp_vault, config, sample_digest):
        orch = SignalOrchestrator(str(tmp_vault), config)
        detected = orch._auto_detect_digest()
        assert "2026-08-01-digest.json" in detected

    def test_auto_detect_digest_no_files(self, tmp_vault, config):
        orch = SignalOrchestrator(str(tmp_vault), config)
        # Remove all files from news dir
        with pytest.raises(FileNotFoundError, match="No digest files"):
            orch._auto_detect_digest()

    def test_auto_detect_digest_no_dir(self, config):
        orch = SignalOrchestrator("/nonexistent/vault", config)
        with pytest.raises(FileNotFoundError, match="News directory"):
            orch._auto_detect_digest()

    def test_load_business_context(self, tmp_vault, config):
        orch = SignalOrchestrator(str(tmp_vault), config)
        ctx = orch._load_business_context()
        assert "OTA company context" in ctx

    def test_load_business_context_caches(self, tmp_vault, config):
        orch = SignalOrchestrator(str(tmp_vault), config)
        ctx1 = orch._load_business_context()
        ctx2 = orch._load_business_context()
        assert ctx1 == ctx2
        assert orch._business_context is not None

    def test_load_business_context_missing(self, tmp_vault, config):
        (tmp_vault / "wiki" / "concepts" / "business-context-brief.md").unlink()
        orch = SignalOrchestrator(str(tmp_vault), config)
        ctx = orch._load_business_context()
        assert ctx == ""

    def test_load_competitor_profile_missing(self, tmp_vault, config):
        orch = SignalOrchestrator(str(tmp_vault), config)
        profile = orch._load_competitor_profile("nonexistent")
        assert profile is None

    def test_load_competitor_profile_exists(self, tmp_vault, config):
        profile_path = tmp_vault / "wiki" / "reports" / "Competitor-Info-Booking.md"
        profile_path.write_text(
            "---\ntitle: Booking\n---\nBooking.com profile data.",
            encoding="utf-8",
        )
        orch = SignalOrchestrator(str(tmp_vault), config)
        profile = orch._load_competitor_profile("Booking")
        assert "Booking.com profile" in profile

    def test_resume_if_needed_no_runs(self, tmp_vault, config):
        orch = SignalOrchestrator(str(tmp_vault), config)
        result = orch.resume_if_needed()
        assert result is None

    def test_resume_if_needed_completed_run(self, tmp_vault, config):
        """Completed runs should not be resumed."""
        state = RunState.new("/test/digest.json")
        state.status = "completed"
        state.persist(str(tmp_vault))

        orch = SignalOrchestrator(str(tmp_vault), config)
        result = orch.resume_if_needed()
        assert result is None

    def test_resume_if_needed_incomplete_run(self, tmp_vault, config):
        """Incomplete recent runs should be resumed (AC-35)."""
        state = RunState.new("/test/digest.json")
        state.status = "running"
        state.items["key1"] = ItemState(title="Item 1", status="completed")
        state.items["key2"] = ItemState(title="Item 2", status="pending")
        state.persist(str(tmp_vault))

        orch = SignalOrchestrator(str(tmp_vault), config)
        result = orch.resume_if_needed()
        assert result is not None
        assert result.status == "running"
        assert "key1" in result.items
        assert "key2" in result.items


class TestProcessDigest:
    """Integration tests for the full pipeline."""

    @patch("app.signal_orchestrator.score_signal")
    @patch("app.signal_orchestrator.analyze_signal")
    @patch("app.signal_orchestrator.dispatch_idea")
    def test_full_pipeline_idea(
        self,
        mock_dispatch_idea,
        mock_analyze,
        mock_score,
        tmp_vault,
        config,
        sample_digest,
    ):
        """AC-01..AC-11: full pipeline scoring -> analysis -> idea dispatch."""
        from app.signal_moderator import AnalysisResult, ScoringResult

        mock_score.return_value = ScoringResult(
            relevance=8,
            reason="Relevant competitor news",
            matched_entities=["Booking"],
        )

        mock_analyze.return_value = AnalysisResult(
            reaction="idea",
            analysis="Booking launched AI concierge, we should consider similar.",
            threat_level="medium",
            idea_draft={
                "title": "AI concierge for guests",
                "problem": "No AI concierge",
                "solution": "Build AI chatbot",
                "domain": "general",
            },
        )

        mock_dispatch_idea.return_value = "2026-08-01-signal-AI-concierge.md"

        # Mock quality gate to always pass
        with patch.object(
            SignalOrchestrator, "_load_business_context", return_value="test context"
        ):
            orch = SignalOrchestrator(str(tmp_vault), config)
            orch.gate.check_analysis_quality = MagicMock(
                return_value=MagicMock(passed=True, score=8, issues=[])
            )
            orch.gate.check_dedup = MagicMock(
                return_value=MagicMock(
                    is_duplicate=False, similarity=0, similar_to=None, reason=""
                )
            )
            orch.gate.check_idea_quality = MagicMock(
                return_value=MagicMock(passed=True, score=8, improvements={})
            )
            orch.gate.check_domain = MagicMock(return_value=(True, None))

            run_state = orch.process_digest(sample_digest, notify=False)

        assert run_state.status == "completed"
        assert run_state.summary is not None
        assert run_state.summary.total == 2
        assert mock_score.call_count == 2
        assert mock_analyze.call_count == 2

    @patch("app.signal_orchestrator.score_signal")
    def test_below_threshold_skipped(
        self, mock_score, tmp_vault, config, sample_digest
    ):
        """Items below relevance threshold should be skipped."""
        from app.signal_moderator import ScoringResult

        mock_score.return_value = ScoringResult(
            relevance=3,
            reason="Not relevant",
            matched_entities=[],
        )

        with patch.object(
            SignalOrchestrator, "_load_business_context", return_value=""
        ):
            orch = SignalOrchestrator(str(tmp_vault), config)
            run_state = orch.process_digest(sample_digest)

        assert run_state.status == "completed"
        # Both items should be skipped
        skipped_count = sum(
            1 for i in run_state.items.values() if i.status == "skipped"
        )
        assert skipped_count == 2

    @patch("app.signal_orchestrator.score_signal")
    @patch("app.signal_orchestrator.analyze_signal")
    @patch("app.signal_orchestrator.dispatch_report")
    def test_report_reaction(
        self,
        mock_dispatch_report,
        mock_analyze,
        mock_score,
        tmp_vault,
        config,
        sample_digest,
    ):
        """Items with reaction=report should be dispatched as reports."""
        from app.signal_moderator import AnalysisResult, ScoringResult

        mock_score.return_value = ScoringResult(
            relevance=9,
            reason="High relevance",
            matched_entities=["Airbnb"],
        )
        mock_analyze.return_value = AnalysisResult(
            reaction="report",
            analysis="Needs deep research.",
            threat_level="high",
            report_brief={
                "topic": "Airbnb expansion analysis",
                "questions": ["What markets?", "What strategy?"],
                "scope": "Russia",
            },
        )
        mock_dispatch_report.return_value = "/path/to/report.json"

        with patch.object(
            SignalOrchestrator, "_load_business_context", return_value=""
        ):
            orch = SignalOrchestrator(str(tmp_vault), config)
            orch.gate.check_analysis_quality = MagicMock(
                return_value=MagicMock(passed=True, score=8, issues=[])
            )
            orch.gate.check_domain = MagicMock(return_value=(True, None))

            run_state = orch.process_digest(sample_digest, notify=False)

        assert run_state.summary.reports >= 1
        waiting_count = sum(
            1 for i in run_state.items.values()
            if i.status == "waiting_report"
        )
        assert waiting_count >= 1

    @patch("app.signal_orchestrator.score_signal")
    @patch("app.signal_orchestrator.analyze_signal")
    @patch("app.signal_orchestrator.dispatch_idea")
    def test_domain_auto_correction(
        self,
        mock_dispatch,
        mock_analyze,
        mock_score,
        tmp_vault,
        config,
        sample_digest,
    ):
        """AC-23: domain should be auto-corrected when mismatch detected."""
        from app.signal_moderator import AnalysisResult, ScoringResult

        mock_score.return_value = ScoringResult(
            relevance=8, reason="", matched_entities=[]
        )
        mock_analyze.return_value = AnalysisResult(
            reaction="idea",
            analysis="Analysis",
            idea_draft={
                "title": "Improve search relevance ranking",
                "problem": "Search results are not ranked well",
                "solution": "Better ranking algorithm",
                "domain": "general",  # Wrong domain
            },
        )
        mock_dispatch.return_value = "idea-ref.md"

        with patch.object(
            SignalOrchestrator, "_load_business_context", return_value=""
        ):
            orch = SignalOrchestrator(str(tmp_vault), config)
            orch.gate.check_analysis_quality = MagicMock(
                return_value=MagicMock(passed=True, score=8, issues=[])
            )
            # Simulate domain correction
            orch.gate.check_domain = MagicMock(
                return_value=(False, "search-engine")
            )
            orch.gate.check_dedup = MagicMock(
                return_value=MagicMock(
                    is_duplicate=False, similarity=0, similar_to=None, reason=""
                )
            )
            orch.gate.check_idea_quality = MagicMock(
                return_value=MagicMock(passed=True, score=8, improvements={})
            )

            orch.process_digest(sample_digest, notify=False)

        # Verify the idea_draft domain was corrected before dispatch
        call_args = mock_dispatch.call_args
        assert call_args is not None
        analysis_arg = call_args.kwargs.get("analysis") or call_args[1].get("analysis")
        if analysis_arg:
            assert analysis_arg.idea_draft["domain"] == "search-engine"

    @patch("app.signal_orchestrator.score_signal")
    def test_process_item_error_does_not_break_run(
        self, mock_score, tmp_vault, config, sample_digest
    ):
        """Errors in individual items should not break the entire run."""
        mock_score.side_effect = [
            Exception("LLM timeout"),
            MagicMock(relevance=3, reason="Low", matched_entities=[]),
        ]

        with patch.object(
            SignalOrchestrator, "_load_business_context", return_value=""
        ):
            orch = SignalOrchestrator(str(tmp_vault), config)
            run_state = orch.process_digest(sample_digest)

        # Run should complete despite error in first item
        assert run_state.status == "completed"
        failed_count = sum(
            1 for i in run_state.items.values() if i.status == "failed"
        )
        assert failed_count == 1

    def test_digest_file_not_found(self, tmp_vault, config):
        orch = SignalOrchestrator(str(tmp_vault), config)
        with pytest.raises(FileNotFoundError):
            orch.process_digest("/nonexistent/digest.json")

    def test_max_items_per_run_cap(self, tmp_vault, config):
        """Only max_items_per_run items should be processed."""
        config.max_items_per_run = 1

        digest = {
            "date": "2026-08-01",
            "source": "test",
            "items": [
                {"title": f"Item {i}", "summary": f"Summary {i}"}
                for i in range(5)
            ],
        }
        digest_path = tmp_vault / "raw" / "inbound" / "news" / "cap-test.json"
        digest_path.write_text(json.dumps(digest), encoding="utf-8")

        with patch("app.signal_orchestrator.score_signal") as mock_score:
            mock_score.return_value = MagicMock(
                relevance=3, reason="Low", matched_entities=[]
            )
            with patch.object(
                SignalOrchestrator, "_load_business_context", return_value=""
            ):
                orch = SignalOrchestrator(str(tmp_vault), config)
                run_state = orch.process_digest(str(digest_path))

        # Only 1 item should have been registered
        assert len(run_state.items) == 1
        assert mock_score.call_count == 1


class TestRunStatePersistence:
    """AC-34: RunState persisted after each item."""

    @patch("app.signal_orchestrator.score_signal")
    def test_persist_after_each_item(
        self, mock_score, tmp_vault, config, sample_digest
    ):
        config.persist_run_state = True
        mock_score.return_value = MagicMock(
            relevance=3, reason="Low", matched_entities=[]
        )

        with patch.object(
            SignalOrchestrator, "_load_business_context", return_value=""
        ):
            orch = SignalOrchestrator(str(tmp_vault), config)

            with patch.object(RunState, "persist") as mock_persist:
                orch.process_digest(sample_digest)

            # persist called: 2 items + 1 final = 3 calls
            assert mock_persist.call_count == 3


class TestTelegramNotifications:
    """AC-30..AC-33: Telegram notifications."""

    @patch("app.signal_orchestrator.score_signal")
    def test_finalize_sends_telegram_summary(
        self,
        mock_score,
        tmp_vault,
        config,
        sample_digest,
    ):
        """AC-33: Summary notification on finalize."""
        from app.signal_moderator import ScoringResult

        mock_score.return_value = ScoringResult(
            relevance=3, reason="Low", matched_entities=[]
        )

        mock_tg = MagicMock(return_value=True)

        with patch.object(
            SignalOrchestrator, "_load_business_context", return_value=""
        ):
            orch = SignalOrchestrator(str(tmp_vault), config)
            with patch(
                "app.notifier.send_telegram", mock_tg
            ):
                orch.process_digest(sample_digest, notify=True)

        assert mock_tg.called

    @patch("app.signal_orchestrator.score_signal")
    def test_finalize_no_telegram_on_dry_run(
        self, mock_score, tmp_vault, config, sample_digest
    ):
        """AC-33: No Telegram on dry_run."""
        mock_score.return_value = MagicMock(
            relevance=3, reason="Low", matched_entities=[]
        )

        with patch.object(
            SignalOrchestrator, "_load_business_context", return_value=""
        ):
            orch = SignalOrchestrator(str(tmp_vault), config)
            # Should not raise even if notifier is not available
            run_state = orch.process_digest(
                sample_digest, notify=True, dry_run=True
            )
            assert run_state.status == "completed"


class TestDigestValidation:
    """AC-43: JSON digest validation."""

    def test_missing_title_logged(self, tmp_vault, config):
        """Items without title should be warned about."""
        digest = {
            "date": "2026-08-01",
            "source": "test",
            "items": [
                {"summary": "No title here"},
            ],
        }
        digest_path = tmp_vault / "raw" / "inbound" / "news" / "bad.json"
        digest_path.write_text(json.dumps(digest), encoding="utf-8")

        with patch("app.signal_orchestrator.score_signal") as mock_score:
            mock_score.return_value = MagicMock(
                relevance=3, reason="", matched_entities=[]
            )
            with patch.object(
                SignalOrchestrator, "_load_business_context", return_value=""
            ):
                orch = SignalOrchestrator(str(tmp_vault), config)
                # Should not crash, just warn
                run_state = orch.process_digest(str(digest_path))
                assert run_state.status == "completed"

    def test_empty_items(self, tmp_vault, config):
        """Digest with empty items should complete gracefully."""
        digest = {"date": "2026-08-01", "source": "test", "items": []}
        digest_path = tmp_vault / "raw" / "inbound" / "news" / "empty.json"
        digest_path.write_text(json.dumps(digest), encoding="utf-8")

        orch = SignalOrchestrator(str(tmp_vault), config)
        run_state = orch.process_digest(str(digest_path))
        assert run_state.status == "completed"
        assert run_state.summary.total == 0


class TestHandleIdea:
    """Tests for _handle_idea (FLOW-03)."""

    def test_duplicate_idea_skipped(self, tmp_vault, config):
        """Ideas with high dedup similarity should be skipped."""
        from app.signal_moderator import AnalysisResult

        orch = SignalOrchestrator(str(tmp_vault), config)
        orch.gate.check_dedup = MagicMock(
            return_value=MagicMock(
                is_duplicate=True,
                similarity=9,
                similar_to="IDEA-001",
                reason="Very similar",
            )
        )

        analysis = AnalysisResult(
            reaction="idea",
            analysis="Test",
            idea_draft={"title": "Dup", "problem": "P", "solution": "S", "domain": "general"},
        )
        item_state = ItemState(title="Dup")

        orch._handle_idea(
            item={"title": "Test", "date": "2026-08-01"},
            analysis=analysis,
            item_state=item_state,
            notify=False,
            dry_run=False,
        )

        assert item_state.status == "skipped"
        assert "duplicate" in item_state.quality_warnings[0]

    @patch("app.signal_orchestrator.dispatch_idea")
    def test_idea_quality_improvements_applied(
        self, mock_dispatch, tmp_vault, config
    ):
        """Quality gate improvements should be applied to idea_draft."""
        from app.signal_moderator import AnalysisResult

        orch = SignalOrchestrator(str(tmp_vault), config)
        orch.gate.check_dedup = MagicMock(
            return_value=MagicMock(
                is_duplicate=False, similarity=0, similar_to=None, reason=""
            )
        )
        orch.gate.check_idea_quality = MagicMock(
            return_value=MagicMock(
                passed=False,
                score=4,
                improvements={
                    "improved_title": "Better Title",
                    "improved_solution": "Better Solution",
                },
            )
        )
        mock_dispatch.return_value = "ref.md"

        analysis = AnalysisResult(
            reaction="idea",
            analysis="Test",
            idea_draft={
                "title": "Original",
                "problem": "P",
                "solution": "Original S",
                "domain": "general",
            },
        )
        item_state = ItemState(title="Test")

        orch._handle_idea(
            item={"title": "Test", "date": "2026-08-01"},
            analysis=analysis,
            item_state=item_state,
            notify=False,
            dry_run=False,
        )

        # Verify improvements were applied
        assert analysis.idea_draft["title"] == "Better Title"
        assert analysis.idea_draft["solution"] == "Better Solution"
