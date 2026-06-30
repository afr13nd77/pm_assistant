"""Unit tests for digest context integration in claude_client and reporter.

Tests T-23 (BL-147): context_assembler integration into LLM context points.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from app.context_assembler import AssembledContext


# ---------------------------------------------------------------------------
# _get_digest_context (claude_client.py)
# ---------------------------------------------------------------------------


class TestGetDigestContext:
    """Tests for _get_digest_context helper in claude_client."""

    def test_kill_switch_returns_empty_string(self):
        """When DIGEST_CONTEXT_SOURCE=wiki (default), returns empty string."""
        from app.claude_client import _get_digest_context

        with patch("app.context_assembler.assemble_context") as mock_ac:
            mock_ac.return_value = AssembledContext(fallback_used=True)
            result = _get_digest_context("test idea text")

        assert result == ""

    def test_returns_one_liners_only(self):
        """When only one_liners available, returns one-liners section."""
        from app.claude_client import _get_digest_context

        ctx = AssembledContext(
            one_liners="- [idea-001] Core idea about travel\n",
            core_digests="",
            total_tokens=15,
            sources_used=["idea-001"],
            fallback_used=False,
        )

        with patch("app.context_assembler.assemble_context", return_value=ctx) as mock_ac:
            result = _get_digest_context("test idea text")

        assert "## Контекст из базы знаний (one-liners)" in result
        assert "[idea-001]" in result
        assert "подробности" not in result
        mock_ac.assert_called_once_with(query="test idea text", domain="")

    def test_returns_one_liners_and_core_digests(self):
        """When both one_liners and core_digests available, returns both."""
        from app.claude_client import _get_digest_context

        ctx = AssembledContext(
            one_liners="- [idea-001] Core idea\n",
            core_digests="### idea-001\nDetailed content here.\n\n",
            total_tokens=50,
            sources_used=["idea-001"],
            fallback_used=False,
        )

        with patch("app.context_assembler.assemble_context", return_value=ctx):
            result = _get_digest_context("test idea text")

        assert "## Контекст из базы знаний (one-liners)" in result
        assert "## Контекст из базы знаний (подробности)" in result
        assert "[idea-001]" in result
        assert "Detailed content here." in result

    def test_exception_returns_empty_string(self):
        """If assemble_context raises, returns empty string (no crash)."""
        from app.claude_client import _get_digest_context

        with patch("app.context_assembler.assemble_context", side_effect=RuntimeError("boom")):
            result = _get_digest_context("test idea text")

        assert result == ""

    def test_empty_context_returns_empty_string(self):
        """When assemble_context returns completely empty context, returns empty."""
        from app.claude_client import _get_digest_context

        ctx = AssembledContext(
            one_liners="",
            core_digests="",
            total_tokens=0,
            sources_used=[],
            fallback_used=False,
        )

        with patch("app.context_assembler.assemble_context", return_value=ctx):
            result = _get_digest_context("test idea text")

        assert result == ""

    def test_fallback_used_with_one_liners_still_returns(self):
        """When fallback_used=True but one_liners exist, still returns content."""
        from app.claude_client import _get_digest_context

        ctx = AssembledContext(
            one_liners="- [idea-001] Some fallback one-liner\n",
            core_digests="",
            total_tokens=10,
            sources_used=["idea-001"],
            fallback_used=True,
        )

        with patch("app.context_assembler.assemble_context", return_value=ctx):
            result = _get_digest_context("test idea text")

        # fallback_used=True BUT one_liners exist => should return content
        assert "## Контекст из базы знаний (one-liners)" in result

    def test_import_error_returns_empty_string(self):
        """If context_assembler module cannot be imported, returns empty."""
        from app.claude_client import _get_digest_context

        with patch("app.context_assembler.assemble_context", side_effect=ImportError("no module")):
            result = _get_digest_context("test idea text")

        assert result == ""


# ---------------------------------------------------------------------------
# _build_idea_prompt with digest context (claude_client.py)
# ---------------------------------------------------------------------------


class TestBuildIdeaPromptWithDigest:
    """Tests that _build_idea_prompt correctly injects digest context."""

    @patch("app.claude_client._get_digest_context", return_value="")
    @patch("app.claude_client._load_prompt", return_value="You are a PM assistant.")
    def test_no_digest_context_preserves_format(self, mock_prompt, mock_digest):
        """When no digest context, format is: prompt + --- + raw_text."""
        from app.claude_client import _build_idea_prompt

        result = _build_idea_prompt("my new idea")

        assert result.endswith("---\nmy new idea")
        assert "Контекст из базы знаний" not in result

    @patch("app.claude_client._get_digest_context", return_value="## Контекст из базы знаний (one-liners)\n- [id1] hello")
    @patch("app.claude_client._load_prompt", return_value="You are a PM assistant.")
    def test_digest_context_injected_between_prompt_and_raw(self, mock_prompt, mock_digest):
        """When digest context available, it goes between prompt and raw_text."""
        from app.claude_client import _build_idea_prompt

        result = _build_idea_prompt("my new idea")

        # Structure: prompt + \n\n + digest + \n\n--- + \n + raw_text
        assert "You are a PM assistant." in result
        assert "## Контекст из базы знаний (one-liners)" in result
        assert "---\nmy new idea" in result

        # Verify order: prompt < digest < raw_text
        prompt_pos = result.index("You are a PM assistant.")
        digest_pos = result.index("Контекст из базы знаний")
        raw_pos = result.index("my new idea")
        assert prompt_pos < digest_pos < raw_pos

    @patch("app.claude_client._get_digest_context", return_value="")
    def test_dynamic_domains_still_work(self, mock_digest):
        """Dynamic domain injection works alongside digest context integration."""
        from app.claude_client import _build_idea_prompt

        with patch("app.claude_client._load_prompt", return_value="template {domains_section}"):
            with patch("shared.domain_config") as mock_dc:
                mock_dc.build_prompt_section.return_value = "- flights\n- hotels"
                result = _build_idea_prompt("test idea")

        assert "- flights" in result
        assert "- hotels" in result


# ---------------------------------------------------------------------------
# generate_weekly_report digest context injection (reporter.py)
# ---------------------------------------------------------------------------


class TestGenerateWeeklyReportDigest:
    """Tests that generate_weekly_report correctly injects digest context."""

    @patch("app.reporter.llm_client")
    @patch("app.reporter.vault_paths")
    @patch("app.reporter.scan_folder", return_value=[])
    @patch("app.reporter.scan_all_domain_folders", return_value=[])
    @patch("app.reporter.get_open_tasks", return_value=[])
    @patch("app.reporter._load_prompt", return_value="Generate weekly report.")
    def test_digest_context_injected_when_available(
        self, mock_prompt, mock_tasks, mock_domains, mock_scan, mock_vp, mock_llm
    ):
        """When digest context is available, it is appended to context."""
        from app.reporter import generate_weekly_report

        mock_vp.wiki_meetings.return_value = MagicMock()
        mock_vp.wiki_daily_logs.return_value = MagicMock()

        # Capture the messages sent to LLM
        def capture_llm_call(**kwargs):
            capture_llm_call.last_messages = kwargs.get("messages", [])
            return "# Weekly Report"

        mock_llm.call_with_fallback.side_effect = capture_llm_call
        capture_llm_call.last_messages = []

        digest_ctx = AssembledContext(
            one_liners="- [idea-001] Important context\n",
            total_tokens=10,
            sources_used=["idea-001"],
            fallback_used=False,
        )

        with patch("app.context_assembler.assemble_context", return_value=digest_ctx):
            result = generate_weekly_report()

        assert result == "# Weekly Report"
        # The LLM input should contain the injected digest context
        assert len(capture_llm_call.last_messages) > 0
        content = capture_llm_call.last_messages[0]["content"]
        assert "Контекст из базы знаний" in content
        assert "[idea-001]" in content

    @patch("app.reporter.llm_client")
    @patch("app.reporter.vault_paths")
    @patch("app.reporter.scan_folder", return_value=[])
    @patch("app.reporter.scan_all_domain_folders", return_value=[])
    @patch("app.reporter.get_open_tasks", return_value=[])
    @patch("app.reporter._load_prompt", return_value="Generate weekly report.")
    def test_kill_switch_no_digest_injected(
        self, mock_prompt, mock_tasks, mock_domains, mock_scan, mock_vp, mock_llm
    ):
        """When kill switch active, no digest context is added."""
        from app.reporter import generate_weekly_report

        mock_vp.wiki_meetings.return_value = MagicMock()
        mock_vp.wiki_daily_logs.return_value = MagicMock()

        def capture_llm_call(**kwargs):
            capture_llm_call.last_messages = kwargs.get("messages", [])
            return "# Weekly Report"

        mock_llm.call_with_fallback.side_effect = capture_llm_call
        capture_llm_call.last_messages = []

        # Kill switch: fallback_used=True, empty one_liners
        digest_ctx = AssembledContext(fallback_used=True)

        with patch("app.context_assembler.assemble_context", return_value=digest_ctx):
            result = generate_weekly_report()

        assert result == "# Weekly Report"
        # Verify digest context was NOT injected
        content = capture_llm_call.last_messages[0]["content"]
        assert "Контекст из базы знаний" not in content

    @patch("app.reporter.llm_client")
    @patch("app.reporter.vault_paths")
    @patch("app.reporter.scan_folder", return_value=[])
    @patch("app.reporter.scan_all_domain_folders", return_value=[])
    @patch("app.reporter.get_open_tasks", return_value=[])
    @patch("app.reporter._load_prompt", return_value="Generate weekly report.")
    def test_digest_exception_does_not_break_report(
        self, mock_prompt, mock_tasks, mock_domains, mock_scan, mock_vp, mock_llm
    ):
        """When assemble_context raises, report still works."""
        from app.reporter import generate_weekly_report

        mock_vp.wiki_meetings.return_value = MagicMock()
        mock_vp.wiki_daily_logs.return_value = MagicMock()
        mock_llm.call_with_fallback.return_value = "# Weekly Report"

        with patch("app.context_assembler.assemble_context", side_effect=RuntimeError("boom")):
            result = generate_weekly_report()

        assert result == "# Weekly Report"

    @patch("app.reporter.llm_client")
    @patch("app.reporter.vault_paths")
    @patch("app.reporter.scan_folder", return_value=[])
    @patch("app.reporter.scan_all_domain_folders", return_value=[])
    @patch("app.reporter.get_open_tasks", return_value=[])
    @patch("app.reporter._load_prompt", return_value="Generate weekly report.")
    def test_digest_import_error_does_not_break_report(
        self, mock_prompt, mock_tasks, mock_domains, mock_scan, mock_vp, mock_llm
    ):
        """When context_assembler module unavailable, report still works."""
        from app.reporter import generate_weekly_report

        mock_vp.wiki_meetings.return_value = MagicMock()
        mock_vp.wiki_daily_logs.return_value = MagicMock()
        mock_llm.call_with_fallback.return_value = "# Weekly Report"

        with patch("app.context_assembler.assemble_context", side_effect=ImportError("no module")):
            result = generate_weekly_report()

        assert result == "# Weekly Report"
