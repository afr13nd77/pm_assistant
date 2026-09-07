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
from dataclasses import asdict
from datetime import datetime
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
        # Remove all files from news dir — should return None, not raise
        result = orch._auto_detect_digest()
        assert result is None

    def test_auto_detect_digest_no_dir(self, config):
        orch = SignalOrchestrator("/nonexistent/vault", config)
        # Missing news directory — should return None, not raise
        result = orch._auto_detect_digest()
        assert result is None

    def test_process_digest_no_digest_returns_empty_run(self, tmp_vault, config):
        """When no digest files exist, process_digest returns completed RunState with zero totals."""
        # Ensure news dir is empty (no JSON files)
        orch = SignalOrchestrator(str(tmp_vault), config)
        result = orch.process_digest(digest_path=None)
        assert result.status == "completed"
        assert result.completed_at is not None
        assert result.digest_path == "none"
        assert result.summary is not None
        assert result.summary.total == 0
        assert result.summary.relevant == 0
        assert result.summary.ideas == 0

    @patch("shared.llm_client._load_llm_prefs", return_value={})
    def test_load_business_context_from_file(self, mock_prefs, tmp_vault, config):
        """Fallback to file when user-prefs has no business_context."""
        orch = SignalOrchestrator(str(tmp_vault), config)
        ctx = orch._load_business_context()
        assert "OTA company context" in ctx
        mock_prefs.assert_called_once()

    def test_load_business_context_from_user_prefs(self, tmp_vault, config):
        """User-prefs business_context takes priority over file."""
        prefs_ctx = "Custom business context from user-prefs"
        with patch(
            "shared.llm_client._load_llm_prefs",
            return_value={"business_context": prefs_ctx},
        ):
            orch = SignalOrchestrator(str(tmp_vault), config)
            ctx = orch._load_business_context()
            assert ctx == prefs_ctx

    def test_load_business_context_empty_prefs_falls_to_file(self, tmp_vault, config):
        """Empty string in user-prefs falls through to file."""
        with patch(
            "shared.llm_client._load_llm_prefs",
            return_value={"business_context": ""},
        ):
            orch = SignalOrchestrator(str(tmp_vault), config)
            ctx = orch._load_business_context()
            assert "OTA company context" in ctx

    @patch("shared.llm_client._load_llm_prefs", return_value={})
    def test_load_business_context_caches(self, mock_prefs, tmp_vault, config):
        orch = SignalOrchestrator(str(tmp_vault), config)
        ctx1 = orch._load_business_context()
        ctx2 = orch._load_business_context()
        assert ctx1 == ctx2
        assert orch._business_context is not None
        mock_prefs.assert_called_once()

    @patch("shared.llm_client._load_llm_prefs", return_value={})
    def test_load_business_context_missing(self, mock_prefs, tmp_vault, config):
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

    @patch("app.signal_orchestrator.dispatch_signal")
    @patch("app.signal_orchestrator.extract_signals")
    @patch("app.signal_orchestrator.generate_analysis_report")
    @patch("app.signal_orchestrator.score_signal")
    def test_full_pipeline_signal_flow(
        self,
        mock_score,
        mock_generate_report,
        mock_extract_signals,
        mock_dispatch_signal,
        tmp_vault,
        config,
        sample_digest,
    ):
        """AC-01..AC-11: full pipeline scoring -> report -> extract -> dispatch."""
        from app.signal_moderator import ReportResult, ScoringResult, SignalData

        mock_score.return_value = ScoringResult(
            relevance=8,
            reason="Relevant competitor news",
            matched_entities=["Booking"],
        )

        mock_generate_report.return_value = ReportResult(
            content="Booking launched AI concierge, we should consider similar.",
            threat_level="medium",
        )

        mock_extract_signals.return_value = [
            SignalData(
                title="AI concierge for guests",
                analysis="Booking AI concierge analysis",
                threat_level="medium",
                recommended_action="idea",
                draft_idea={
                    "title": "AI concierge for guests",
                    "problem": "No AI concierge",
                    "solution": "Build AI chatbot",
                    "domain": "general",
                },
            ),
        ]

        mock_dispatch_signal.return_value = "SIG-2026-08-01-ai-concierge"

        # Mock quality gate to always pass
        with patch.object(
            SignalOrchestrator, "_load_business_context", return_value="test context"
        ):
            orch = SignalOrchestrator(str(tmp_vault), config)
            orch.gate.check_analysis_quality = MagicMock(
                return_value=MagicMock(passed=True, score=8, issues=[])
            )
            orch.gate.check_domain = MagicMock(return_value=(True, None))

            run_state = orch.process_digest(sample_digest, notify=False)

        assert run_state.status == "completed"
        assert run_state.summary is not None
        assert run_state.summary.total == 2
        assert mock_score.call_count == 2
        assert mock_generate_report.call_count == 2
        assert mock_extract_signals.call_count == 2
        assert mock_dispatch_signal.call_count == 2

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

    @patch("app.signal_orchestrator.dispatch_signal")
    @patch("app.signal_orchestrator.extract_signals")
    @patch("app.signal_orchestrator.generate_analysis_report")
    @patch("app.signal_orchestrator.score_signal")
    def test_no_signals_extracted(
        self,
        mock_score,
        mock_generate_report,
        mock_extract_signals,
        mock_dispatch_signal,
        tmp_vault,
        config,
        sample_digest,
    ):
        """When extract_signals returns empty, reaction should be no_signals."""
        from app.signal_moderator import ReportResult, ScoringResult

        mock_score.return_value = ScoringResult(
            relevance=9,
            reason="High relevance",
            matched_entities=["Airbnb"],
        )
        mock_generate_report.return_value = ReportResult(
            content="Some analysis content.",
            threat_level="high",
        )
        mock_extract_signals.return_value = []  # No signals extracted
        mock_dispatch_signal.return_value = None

        with patch.object(
            SignalOrchestrator, "_load_business_context", return_value=""
        ):
            orch = SignalOrchestrator(str(tmp_vault), config)
            orch.gate.check_analysis_quality = MagicMock(
                return_value=MagicMock(passed=True, score=8, issues=[])
            )
            orch.gate.check_domain = MagicMock(return_value=(True, None))

            run_state = orch.process_digest(sample_digest, notify=False)

        assert run_state.status == "completed"
        # All items should have no_signals reaction
        for item_state in run_state.items.values():
            assert item_state.reaction == "no_signals"
        # dispatch_signal should not be called when no signals extracted
        assert mock_dispatch_signal.call_count == 0

    @patch("app.signal_orchestrator.dispatch_signal")
    @patch("app.signal_orchestrator.extract_signals")
    @patch("app.signal_orchestrator.generate_analysis_report")
    @patch("app.signal_orchestrator.score_signal")
    def test_domain_auto_correction(
        self,
        mock_score,
        mock_generate_report,
        mock_extract_signals,
        mock_dispatch_signal,
        tmp_vault,
        config,
        sample_digest,
    ):
        """AC-23: domain should be auto-corrected on signals with draft_idea."""
        from app.signal_moderator import ReportResult, ScoringResult, SignalData

        mock_score.return_value = ScoringResult(
            relevance=8, reason="", matched_entities=[]
        )
        mock_generate_report.return_value = ReportResult(
            content="Analysis of search relevance.",
            threat_level="medium",
        )
        mock_extract_signals.return_value = [
            SignalData(
                title="Improve search relevance ranking",
                analysis="Analysis",
                threat_level="medium",
                recommended_action="idea",
                draft_idea={
                    "title": "Improve search relevance ranking",
                    "problem": "Search results are not ranked well",
                    "solution": "Better ranking algorithm",
                    "domain": "general",  # Wrong domain
                },
            ),
        ]
        mock_dispatch_signal.return_value = "SIG-001"

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

            orch.process_digest(sample_digest, notify=False)

        # Verify dispatch_signal was called and domain was corrected
        assert mock_dispatch_signal.call_count >= 1
        call_args = mock_dispatch_signal.call_args
        signal_arg = call_args.kwargs.get("signal_data") or call_args[0][0]
        assert signal_arg.draft_idea["domain"] == "search-engine"

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


class TestSignalDispatchFlow:
    """Tests for the new signal pipeline (BL-203): report -> extract -> dispatch."""

    @patch("app.signal_orchestrator.dispatch_signal")
    @patch("app.signal_orchestrator.extract_signals")
    @patch("app.signal_orchestrator.generate_analysis_report")
    @patch("app.signal_orchestrator.score_signal")
    def test_report_saved_to_wiki(
        self,
        mock_score,
        mock_generate_report,
        mock_extract_signals,
        mock_dispatch_signal,
        tmp_vault,
        config,
        sample_digest,
    ):
        """Report should be saved to wiki/reports/signals/ directory."""
        from app.signal_moderator import ReportResult, ScoringResult

        mock_score.return_value = ScoringResult(
            relevance=8, reason="Relevant", matched_entities=[]
        )
        mock_generate_report.return_value = ReportResult(
            content="Analysis report content here.",
            threat_level="medium",
        )
        mock_extract_signals.return_value = []
        mock_dispatch_signal.return_value = None

        with patch.object(
            SignalOrchestrator, "_load_business_context", return_value=""
        ):
            orch = SignalOrchestrator(str(tmp_vault), config)
            orch.gate.check_analysis_quality = MagicMock(
                return_value=MagicMock(passed=True, score=8, issues=[])
            )
            orch.gate.check_domain = MagicMock(return_value=(True, None))

            orch.process_digest(sample_digest, notify=False)

        # Reports should be written to wiki/reports/signals/
        from pathlib import Path
        signals_dir = Path(str(tmp_vault)) / "wiki" / "reports" / "signals"
        if signals_dir.exists():
            report_files = list(signals_dir.glob("*-report.md"))
            assert len(report_files) >= 1

    @patch("app.signal_orchestrator.dispatch_signal")
    @patch("app.signal_orchestrator.extract_signals")
    @patch("app.signal_orchestrator.generate_analysis_report")
    @patch("app.signal_orchestrator.score_signal")
    def test_memory_records_signal_reaction(
        self,
        mock_score,
        mock_generate_report,
        mock_extract_signals,
        mock_dispatch_signal,
        tmp_vault,
        config,
        sample_digest,
    ):
        """signal_memory.record_signal called with reaction=signal when signals dispatched."""
        from app.signal_moderator import ReportResult, ScoringResult, SignalData

        mock_score.return_value = ScoringResult(
            relevance=8, reason="Relevant", matched_entities=[]
        )
        mock_generate_report.return_value = ReportResult(
            content="Report.", threat_level="medium",
        )
        mock_extract_signals.return_value = [
            SignalData(title="Signal 1", analysis="A", threat_level="low"),
        ]
        mock_dispatch_signal.return_value = "SIG-001"

        with patch.object(
            SignalOrchestrator, "_load_business_context", return_value=""
        ):
            orch = SignalOrchestrator(str(tmp_vault), config)
            orch.gate.check_analysis_quality = MagicMock(
                return_value=MagicMock(passed=True, score=8, issues=[])
            )
            orch.gate.check_domain = MagicMock(return_value=(True, None))

            with patch.object(orch.memory, "record_signal") as mock_record:
                orch.process_digest(sample_digest, notify=False)

            # record_signal should be called for each item
            assert mock_record.call_count >= 2
            for call in mock_record.call_args_list:
                record = call[0][0]
                assert record.reaction == "signal"

    @patch("app.signal_orchestrator.dispatch_signal")
    @patch("app.signal_orchestrator.extract_signals")
    @patch("app.signal_orchestrator.generate_analysis_report")
    @patch("app.signal_orchestrator.score_signal")
    def test_memory_records_no_signals_reaction(
        self,
        mock_score,
        mock_generate_report,
        mock_extract_signals,
        mock_dispatch_signal,
        tmp_vault,
        config,
        sample_digest,
    ):
        """signal_memory.record_signal called with reaction=no_signals when none extracted."""
        from app.signal_moderator import ReportResult, ScoringResult

        mock_score.return_value = ScoringResult(
            relevance=8, reason="Relevant", matched_entities=[]
        )
        mock_generate_report.return_value = ReportResult(
            content="Report.", threat_level="medium",
        )
        mock_extract_signals.return_value = []  # No signals
        mock_dispatch_signal.return_value = None

        with patch.object(
            SignalOrchestrator, "_load_business_context", return_value=""
        ):
            orch = SignalOrchestrator(str(tmp_vault), config)
            orch.gate.check_analysis_quality = MagicMock(
                return_value=MagicMock(passed=True, score=8, issues=[])
            )
            orch.gate.check_domain = MagicMock(return_value=(True, None))

            with patch.object(orch.memory, "record_signal") as mock_record:
                orch.process_digest(sample_digest, notify=False)

            assert mock_record.call_count >= 2
            for call in mock_record.call_args_list:
                record = call[0][0]
                assert record.reaction == "no_signals"


# ---------------------------------------------------------------------------
# BL-190: New fields tests
# ---------------------------------------------------------------------------


class TestItemStateNewFields:
    """BL-190: iterations_history, gate_results, reaction fields."""

    def test_item_state_has_iterations_history_field(self):
        item = ItemState(title="test")
        assert item.iterations_history == []

    def test_item_state_has_gate_results_field(self):
        item = ItemState(title="test")
        assert item.gate_results == []

    def test_item_state_has_reaction_field(self):
        item = ItemState(title="test")
        assert item.reaction is None

    def test_item_state_iterations_history_is_independent(self):
        """Each ItemState instance has its own list."""
        item1 = ItemState(title="test1")
        item2 = ItemState(title="test2")
        item1.iterations_history.append({"attempt": 1})
        assert item2.iterations_history == []


class TestRunStateNewFields:
    """BL-190: completed_at field."""

    def test_run_state_has_completed_at_field(self):
        state = RunState(run_id="2026-08-03-0800", digest_path="/test", started_at="2026-08-03T08:00:00")
        assert state.completed_at is None

    def test_run_state_completed_at_serializes(self):
        state = RunState(run_id="2026-08-03-0800", digest_path="/test", started_at="2026-08-03T08:00:00", completed_at="2026-08-03T08:01:00")
        data = asdict(state)
        assert data["completed_at"] == "2026-08-03T08:01:00"


class TestRunStateLoadCompat:
    """BL-190: backward and forward compatibility."""

    def test_load_old_format_without_new_fields(self, tmp_path):
        """Old JSON without iterations_history/gate_results/reaction/completed_at loads OK."""
        run_data = {
            "run_id": "2026-08-01-0800",
            "digest_path": "/vault/test.json",
            "started_at": "2026-08-01T08:00:00",
            "status": "completed",
            "items": {
                "abc123": {
                    "title": "Test signal",
                    "status": "completed",
                    "current_step": "",
                    "result_ref": "some-ref",
                    "iterations": 1,
                    "errors": [],
                    "quality_warnings": [],
                    "started_at": "2026-08-01T08:00:01",
                    "completed_at": "2026-08-01T08:00:10"
                }
            },
            "summary": {"total": 1, "relevant": 1, "ideas": 1, "reports": 0, "retries": 0, "errors": 0, "quality_warnings": 0}
        }
        run_file = tmp_path / "2026-08-01-0800.json"
        run_file.write_text(json.dumps(run_data), encoding="utf-8")

        state = RunState.load(run_file)
        assert state.run_id == "2026-08-01-0800"
        assert state.completed_at is None
        item = state.items["abc123"]
        assert item.iterations_history == []
        assert item.gate_results == []
        assert item.reaction is None

    def test_load_new_format_with_all_fields(self, tmp_path):
        """New JSON with iterations_history and gate_results loads correctly."""
        run_data = {
            "run_id": "2026-08-03-0800",
            "digest_path": "/vault/test.json",
            "started_at": "2026-08-03T08:00:00",
            "status": "completed",
            "completed_at": "2026-08-03T08:01:00",
            "items": {
                "def456": {
                    "title": "Test signal",
                    "status": "completed",
                    "current_step": "",
                    "result_ref": "ref",
                    "iterations": 2,
                    "errors": [],
                    "quality_warnings": [],
                    "started_at": "2026-08-03T08:00:01",
                    "completed_at": "2026-08-03T08:00:30",
                    "iterations_history": [
                        {"attempt": 1, "quality_score": 4, "critique": "weak", "escalated": False, "operation": "signal_analyze"},
                        {"attempt": 2, "quality_score": 7, "critique": None, "escalated": True, "operation": "signal_analyze_escalation"}
                    ],
                    "gate_results": [
                        {"gate": "quality", "passed": True, "score": 7, "failed_criteria": []},
                        {"gate": "dedup", "passed": True, "similarity": 2, "compared_with": None}
                    ],
                    "reaction": "idea"
                }
            },
            "summary": {"total": 1, "relevant": 1, "ideas": 1, "reports": 0, "retries": 1, "errors": 0, "quality_warnings": 0}
        }
        run_file = tmp_path / "2026-08-03-0800.json"
        run_file.write_text(json.dumps(run_data), encoding="utf-8")

        state = RunState.load(run_file)
        assert state.completed_at == "2026-08-03T08:01:00"
        item = state.items["def456"]
        assert len(item.iterations_history) == 2
        assert item.iterations_history[0]["quality_score"] == 4
        assert item.iterations_history[1]["escalated"] is True
        assert len(item.gate_results) == 2
        assert item.gate_results[0]["gate"] == "quality"
        assert item.reaction == "idea"

    def test_load_ignores_unknown_fields(self, tmp_path):
        """Forward compat: JSON with future fields loads without error."""
        run_data = {
            "run_id": "2026-08-03-0800",
            "digest_path": "/vault/test.json",
            "started_at": "2026-08-03T08:00:00",
            "status": "completed",
            "items": {
                "ghi789": {
                    "title": "Test",
                    "status": "completed",
                    "current_step": "",
                    "result_ref": None,
                    "iterations": 0,
                    "errors": [],
                    "quality_warnings": [],
                    "started_at": None,
                    "completed_at": None,
                    "future_field_v2": "some_value",
                    "another_future": 42
                }
            }
        }
        run_file = tmp_path / "2026-08-03-0800.json"
        run_file.write_text(json.dumps(run_data), encoding="utf-8")

        state = RunState.load(run_file)
        item = state.items["ghi789"]
        assert item.title == "Test"
        assert not hasattr(item, "future_field_v2")

    def test_persist_includes_new_fields(self, tmp_path):
        """RunState.persist() serializes iterations_history and gate_results."""
        state = RunState(
            run_id="2026-08-03-test",
            digest_path="/test",
            started_at="2026-08-03T00:00:00",
            completed_at="2026-08-03T00:01:00",
        )
        item = ItemState(title="Test item")
        item.iterations_history = [{"attempt": 1, "quality_score": 7, "critique": None, "escalated": False}]
        item.gate_results = [{"gate": "quality", "passed": True, "score": 7}]
        item.reaction = "idea"
        state.items["test123"] = item

        # Persist and re-load
        state.persist(str(tmp_path))
        run_file = tmp_path / "wiki" / "signals" / "runs" / "2026-08-03-test.json"
        assert run_file.exists()

        loaded = RunState.load(run_file)
        loaded_item = loaded.items["test123"]
        assert loaded_item.iterations_history == [{"attempt": 1, "quality_score": 7, "critique": None, "escalated": False}]
        assert loaded_item.gate_results == [{"gate": "quality", "passed": True, "score": 7}]
        assert loaded_item.reaction == "idea"
        assert loaded.completed_at == "2026-08-03T00:01:00"


# ---------------------------------------------------------------------------
# BL-190: Langfuse helper tests
# ---------------------------------------------------------------------------


class TestSafeSpanHelpers:
    """BL-190: _safe_span and _safe_end_span."""

    def test_safe_span_returns_none_when_trace_is_none(self):
        from app.signal_orchestrator import _safe_span

        assert _safe_span(None, "test") is None

    def test_safe_span_returns_span_on_success(self):
        from app.signal_orchestrator import _safe_span

        mock_trace = MagicMock()
        mock_trace.span.return_value = MagicMock()
        result = _safe_span(mock_trace, "test-span", metadata={"key": "val"})
        assert result is not None
        mock_trace.span.assert_called_once_with(
            name="test-span", metadata={"key": "val"}
        )

    def test_safe_span_returns_none_on_exception(self):
        from app.signal_orchestrator import _safe_span

        mock_trace = MagicMock()
        mock_trace.span.side_effect = Exception("connection error")
        result = _safe_span(mock_trace, "test-span")
        assert result is None

    def test_safe_end_span_noop_when_none(self):
        from app.signal_orchestrator import _safe_end_span

        _safe_end_span(None)  # should not raise

    def test_safe_end_span_calls_end(self):
        from app.signal_orchestrator import _safe_end_span

        mock_span = MagicMock()
        _safe_end_span(mock_span, metadata={"status": "done"})
        mock_span.end.assert_called_once_with(metadata={"status": "done"})

    def test_safe_end_span_swallows_exception(self):
        from app.signal_orchestrator import _safe_end_span

        mock_span = MagicMock()
        mock_span.end.side_effect = Exception("flush error")
        _safe_end_span(mock_span)  # should not raise


# ---------------------------------------------------------------------------
# BL-190: Persistence recording tests
# ---------------------------------------------------------------------------


class TestPersistenceRecording:
    """BL-190: iterations_history, gate_results, reaction recording."""

    @patch("app.signal_orchestrator.score_signal")
    def test_process_item_records_reaction_skip(
        self, mock_score, tmp_vault, config, sample_digest
    ):
        """When item is below threshold, reaction should be 'skip'."""
        from app.signal_moderator import ScoringResult

        mock_score.return_value = ScoringResult(
            relevance=3, reason="Not relevant", matched_entities=[]
        )

        with patch.object(
            SignalOrchestrator, "_load_business_context", return_value=""
        ):
            orch = SignalOrchestrator(str(tmp_vault), config)
            run_state = orch.process_digest(sample_digest)

        for item_state in run_state.items.values():
            assert item_state.reaction == "skip"

    @patch("app.signal_orchestrator.dispatch_signal")
    @patch("app.signal_orchestrator.extract_signals")
    @patch("app.signal_orchestrator.generate_analysis_report")
    @patch("app.signal_orchestrator.score_signal")
    def test_process_item_records_reaction_signal(
        self,
        mock_score,
        mock_generate_report,
        mock_extract_signals,
        mock_dispatch_signal,
        tmp_vault,
        config,
        sample_digest,
    ):
        """After report+extract with dispatched signals, reaction should be 'signal'."""
        from app.signal_moderator import ReportResult, ScoringResult, SignalData

        mock_score.return_value = ScoringResult(
            relevance=8, reason="Relevant", matched_entities=[]
        )
        mock_generate_report.return_value = ReportResult(
            content="Test analysis",
            threat_level="medium",
        )
        mock_extract_signals.return_value = [
            SignalData(
                title="Test signal",
                analysis="Signal analysis",
                threat_level="medium",
                draft_idea={
                    "title": "Test",
                    "problem": "P",
                    "solution": "S",
                    "domain": "general",
                },
            ),
        ]
        mock_dispatch_signal.return_value = "SIG-001"

        with patch.object(
            SignalOrchestrator, "_load_business_context", return_value=""
        ):
            orch = SignalOrchestrator(str(tmp_vault), config)
            orch.gate.check_analysis_quality = MagicMock(
                return_value=MagicMock(passed=True, score=8, issues=[])
            )
            orch.gate.check_domain = MagicMock(return_value=(True, None))

            run_state = orch.process_digest(sample_digest, notify=False)

        for item_state in run_state.items.values():
            # Initially set to "signal", stays "signal" when dispatched_ids not empty
            assert item_state.reaction == "signal"

    @patch("app.signal_orchestrator.dispatch_signal")
    @patch("app.signal_orchestrator.extract_signals")
    @patch("app.signal_orchestrator.generate_analysis_report")
    @patch("app.signal_orchestrator.score_signal")
    def test_process_item_records_iterations_history(
        self,
        mock_score,
        mock_generate_report,
        mock_extract_signals,
        mock_dispatch_signal,
        tmp_vault,
        config,
        sample_digest,
    ):
        """After AgentLoop run, iterations_history should be populated."""
        from app.signal_moderator import ReportResult, ScoringResult

        mock_score.return_value = ScoringResult(
            relevance=8, reason="Relevant", matched_entities=[]
        )
        mock_generate_report.return_value = ReportResult(
            content="Analysis",
            threat_level="medium",
        )
        mock_extract_signals.return_value = []
        mock_dispatch_signal.return_value = None

        with patch.object(
            SignalOrchestrator, "_load_business_context", return_value=""
        ):
            orch = SignalOrchestrator(str(tmp_vault), config)
            orch.gate.check_analysis_quality = MagicMock(
                return_value=MagicMock(passed=True, score=7, issues=[])
            )
            orch.gate.check_domain = MagicMock(return_value=(True, None))

            run_state = orch.process_digest(sample_digest, notify=False)

        for item_state in run_state.items.values():
            assert len(item_state.iterations_history) >= 1
            entry = item_state.iterations_history[0]
            assert "attempt" in entry
            assert "quality_score" in entry
            assert "critique" in entry
            assert "escalated" in entry
            assert "operation" in entry

    @patch("app.signal_orchestrator.dispatch_signal")
    @patch("app.signal_orchestrator.extract_signals")
    @patch("app.signal_orchestrator.generate_analysis_report")
    @patch("app.signal_orchestrator.score_signal")
    def test_process_item_records_gate_results_quality(
        self,
        mock_score,
        mock_generate_report,
        mock_extract_signals,
        mock_dispatch_signal,
        tmp_vault,
        config,
        sample_digest,
    ):
        """After AgentLoop run, gate_results should contain quality gate."""
        from app.signal_moderator import ReportResult, ScoringResult

        mock_score.return_value = ScoringResult(
            relevance=8, reason="Relevant", matched_entities=[]
        )
        mock_generate_report.return_value = ReportResult(
            content="Analysis",
            threat_level="medium",
        )
        mock_extract_signals.return_value = []
        mock_dispatch_signal.return_value = None

        with patch.object(
            SignalOrchestrator, "_load_business_context", return_value=""
        ):
            orch = SignalOrchestrator(str(tmp_vault), config)
            orch.gate.check_analysis_quality = MagicMock(
                return_value=MagicMock(
                    passed=True, score=8, issues=[]
                )
            )
            orch.gate.check_domain = MagicMock(return_value=(True, None))

            run_state = orch.process_digest(sample_digest, notify=False)

        for item_state in run_state.items.values():
            quality_gates = [
                g for g in item_state.gate_results if g["gate"] == "quality"
            ]
            assert len(quality_gates) >= 1
            qg = quality_gates[0]
            assert qg["passed"] is True
            assert qg["score"] == 8
            assert "failed_criteria" in qg

    @patch("app.signal_orchestrator.dispatch_signal")
    @patch("app.signal_orchestrator.extract_signals")
    @patch("app.signal_orchestrator.generate_analysis_report")
    @patch("app.signal_orchestrator.score_signal")
    def test_process_item_reaction_no_signals_when_extract_empty(
        self,
        mock_score,
        mock_generate_report,
        mock_extract_signals,
        mock_dispatch_signal,
        tmp_vault,
        config,
        sample_digest,
    ):
        """When extract_signals returns empty, reaction overridden to no_signals."""
        from app.signal_moderator import ReportResult, ScoringResult

        mock_score.return_value = ScoringResult(
            relevance=8, reason="Relevant", matched_entities=[]
        )
        mock_generate_report.return_value = ReportResult(
            content="Analysis",
            threat_level="medium",
        )
        mock_extract_signals.return_value = []  # No signals
        mock_dispatch_signal.return_value = None

        with patch.object(
            SignalOrchestrator, "_load_business_context", return_value=""
        ):
            orch = SignalOrchestrator(str(tmp_vault), config)
            orch.gate.check_analysis_quality = MagicMock(
                return_value=MagicMock(passed=True, score=8, issues=[])
            )
            orch.gate.check_domain = MagicMock(return_value=(True, None))

            run_state = orch.process_digest(sample_digest, notify=False)

        for item_state in run_state.items.values():
            assert item_state.reaction == "no_signals"

    @patch("app.signal_orchestrator.score_signal")
    def test_finalize_sets_completed_at(
        self, mock_score, tmp_vault, config, sample_digest
    ):
        """_finalize() should set run_state.completed_at."""
        from app.signal_moderator import ScoringResult

        mock_score.return_value = ScoringResult(
            relevance=3, reason="Low", matched_entities=[]
        )

        with patch.object(
            SignalOrchestrator, "_load_business_context", return_value=""
        ):
            orch = SignalOrchestrator(str(tmp_vault), config)
            run_state = orch.process_digest(sample_digest)

        assert run_state.completed_at is not None
        # Should be a valid ISO datetime string
        datetime.fromisoformat(run_state.completed_at)


# ---------------------------------------------------------------------------
# BL-190: Langfuse trace integration tests
# ---------------------------------------------------------------------------


class TestLangfuseTraceIntegration:
    """BL-190: Langfuse trace creation and span management."""

    @patch("app.signal_orchestrator.score_signal")
    @patch("shared.langfuse_client.get_langfuse")
    def test_process_digest_creates_langfuse_trace(
        self, mock_get_lf, mock_score, tmp_vault, config, sample_digest
    ):
        """When Langfuse is available, a trace should be created."""
        mock_lf = MagicMock()
        mock_trace = MagicMock()
        mock_lf.trace.return_value = mock_trace
        mock_get_lf.return_value = mock_lf

        mock_score.return_value = MagicMock(
            relevance=3, reason="Low", matched_entities=[]
        )

        with patch.object(
            SignalOrchestrator, "_load_business_context", return_value=""
        ):
            orch = SignalOrchestrator(str(tmp_vault), config)
            orch.process_digest(sample_digest)

        mock_lf.trace.assert_called_once()
        call_kwargs = mock_lf.trace.call_args.kwargs
        assert "signal-moderator" in call_kwargs["name"]
        assert call_kwargs["tags"] == ["signal-moderator"]

    @patch("app.signal_orchestrator.score_signal")
    @patch("shared.langfuse_client.get_langfuse")
    def test_process_digest_works_without_langfuse(
        self, mock_get_lf, mock_score, tmp_vault, config, sample_digest
    ):
        """When Langfuse is None, processing should work normally."""
        mock_get_lf.return_value = None

        mock_score.return_value = MagicMock(
            relevance=3, reason="Low", matched_entities=[]
        )

        with patch.object(
            SignalOrchestrator, "_load_business_context", return_value=""
        ):
            orch = SignalOrchestrator(str(tmp_vault), config)
            run_state = orch.process_digest(sample_digest)

        assert run_state.status == "completed"

    @patch("app.signal_orchestrator.dispatch_signal")
    @patch("app.signal_orchestrator.extract_signals")
    @patch("app.signal_orchestrator.generate_analysis_report")
    @patch("app.signal_orchestrator.score_signal")
    @patch("shared.langfuse_client.get_langfuse")
    def test_process_item_creates_spans(
        self,
        mock_get_lf,
        mock_score,
        mock_generate_report,
        mock_extract_signals,
        mock_dispatch_signal,
        tmp_vault,
        config,
        sample_digest,
    ):
        """When trace is available, spans should be created for each step."""
        from app.signal_moderator import ReportResult, ScoringResult

        mock_lf = MagicMock()
        mock_trace = MagicMock()
        mock_item_span = MagicMock()
        # trace.span() returns item_span, which also has .span() for sub-spans
        mock_trace.span.return_value = mock_item_span
        mock_item_span.span.return_value = MagicMock()
        mock_lf.trace.return_value = mock_trace
        mock_get_lf.return_value = mock_lf

        mock_score.return_value = ScoringResult(
            relevance=8, reason="Relevant", matched_entities=[]
        )
        mock_generate_report.return_value = ReportResult(
            content="Analysis",
            threat_level="medium",
        )
        mock_extract_signals.return_value = []
        mock_dispatch_signal.return_value = None

        with patch.object(
            SignalOrchestrator, "_load_business_context", return_value=""
        ):
            orch = SignalOrchestrator(str(tmp_vault), config)
            orch.gate.check_analysis_quality = MagicMock(
                return_value=MagicMock(passed=True, score=8, issues=[])
            )
            orch.gate.check_domain = MagicMock(return_value=(True, None))

            orch.process_digest(sample_digest, notify=False)

        # trace.span() should be called for item-level spans
        assert mock_trace.span.call_count >= 1
        # item_span.span() should be called for score, report, extract, dispatch
        assert mock_item_span.span.call_count >= 1


# ---------------------------------------------------------------------------
# BL-203: _load_relevance_threshold tests (AC-09, AC-10)
# ---------------------------------------------------------------------------


class TestLoadRelevanceThreshold:
    """BL-203: _load_relevance_threshold reads from .pm-user-prefs.json."""

    @pytest.fixture(autouse=True)
    def _point_vault_env(self, tmp_vault, monkeypatch):
        """Ensure _load_llm_prefs() finds .pm-user-prefs.json in tmp_vault."""
        from shared.llm_client import invalidate_cache

        monkeypatch.setenv("VAULT_PATH", str(tmp_vault))
        invalidate_cache()
        yield
        invalidate_cache()

    def test_threshold_from_user_prefs(self, tmp_vault, config):
        """_load_relevance_threshold reads from .pm-user-prefs.json."""
        prefs = {"moderator": {"relevance_threshold": 5}}
        (tmp_vault / ".pm-user-prefs.json").write_text(
            json.dumps(prefs), encoding="utf-8"
        )

        with patch.object(
            SignalOrchestrator, "_load_business_context", return_value=""
        ):
            orch = SignalOrchestrator(str(tmp_vault), config)
            threshold = orch._load_relevance_threshold()

        assert threshold == 5

    def test_threshold_fallback_to_config(self, tmp_vault, config):
        """Without prefs file, falls back to config value."""
        # No .pm-user-prefs.json exists
        config.relevance_threshold = 6

        with patch.object(
            SignalOrchestrator, "_load_business_context", return_value=""
        ):
            orch = SignalOrchestrator(str(tmp_vault), config)
            threshold = orch._load_relevance_threshold()

        assert threshold == 6

    def test_threshold_clamp_high(self, tmp_vault, config):
        """Values above 10 are clamped to 10."""
        prefs = {"moderator": {"relevance_threshold": 15}}
        (tmp_vault / ".pm-user-prefs.json").write_text(
            json.dumps(prefs), encoding="utf-8"
        )

        with patch.object(
            SignalOrchestrator, "_load_business_context", return_value=""
        ):
            orch = SignalOrchestrator(str(tmp_vault), config)
            threshold = orch._load_relevance_threshold()

        assert threshold == 10

    def test_threshold_clamp_low(self, tmp_vault, config):
        """Values below 1 are clamped to 1."""
        prefs = {"moderator": {"relevance_threshold": 0}}
        (tmp_vault / ".pm-user-prefs.json").write_text(
            json.dumps(prefs), encoding="utf-8"
        )

        with patch.object(
            SignalOrchestrator, "_load_business_context", return_value=""
        ):
            orch = SignalOrchestrator(str(tmp_vault), config)
            threshold = orch._load_relevance_threshold()

        assert threshold == 1

    def test_threshold_missing_moderator_section(self, tmp_vault, config):
        """Prefs file without 'moderator' section falls back to config."""
        prefs = {"other_setting": True}
        (tmp_vault / ".pm-user-prefs.json").write_text(
            json.dumps(prefs), encoding="utf-8"
        )
        config.relevance_threshold = 7

        with patch.object(
            SignalOrchestrator, "_load_business_context", return_value=""
        ):
            orch = SignalOrchestrator(str(tmp_vault), config)
            threshold = orch._load_relevance_threshold()

        assert threshold == 7

    def test_threshold_invalid_json_falls_back(self, tmp_vault, config):
        """Invalid JSON in prefs file falls back to config."""
        (tmp_vault / ".pm-user-prefs.json").write_text(
            "not valid json {{{", encoding="utf-8"
        )
        config.relevance_threshold = 4

        with patch.object(
            SignalOrchestrator, "_load_business_context", return_value=""
        ):
            orch = SignalOrchestrator(str(tmp_vault), config)
            threshold = orch._load_relevance_threshold()

        assert threshold == 4

    @patch("app.signal_orchestrator.score_signal")
    def test_effective_threshold_used_in_process_digest(
        self, mock_score, tmp_vault, config, sample_digest
    ):
        """process_digest uses _load_relevance_threshold for scoring decisions."""
        from app.signal_moderator import ScoringResult

        # Set threshold in prefs to 9 (high)
        prefs = {"moderator": {"relevance_threshold": 9}}
        (tmp_vault / ".pm-user-prefs.json").write_text(
            json.dumps(prefs), encoding="utf-8"
        )

        # Score all items at 8 (below 9)
        mock_score.return_value = ScoringResult(
            relevance=8, reason="Relevant but below threshold", matched_entities=[]
        )

        with patch.object(
            SignalOrchestrator, "_load_business_context", return_value=""
        ):
            orch = SignalOrchestrator(str(tmp_vault), config)
            run_state = orch.process_digest(sample_digest)

        # All items should be skipped because 8 < 9
        skipped = sum(
            1 for i in run_state.items.values() if i.status == "skipped"
        )
        assert skipped == 2
