"""Unit tests for claude_client (knowledge-engine + pm-bot)."""

import logging
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from app.claude_client import process_meeting_transcript


def _load_pmbot_claude_client():
    """Load pm-bot/app/claude_client module explicitly.

    pytest prepends knowledge-engine to sys.path so ``app.claude_client``
    resolves to the knowledge-engine version.  This helper temporarily
    adjusts sys.path so we can import pm-bot's version under a distinct
    module key.
    """
    project_root = Path(__file__).resolve().parents[2]
    pmbot_path = str(project_root / "pm-bot")

    saved_modules = {}
    for key in list(sys.modules):
        if key == "app" or key.startswith("app."):
            saved_modules[key] = sys.modules.pop(key)

    sys.path.insert(0, pmbot_path)
    try:
        from app import claude_client as pmbot_cc
        # Keep a reference so we can use it for patching
        pmbot_cc._MODULE_KEY = "app.claude_client"
        return pmbot_cc
    finally:
        sys.path.remove(pmbot_path)
        # Restore original modules so knowledge-engine tests keep working
        for key in list(sys.modules):
            if key == "app" or key.startswith("app."):
                del sys.modules[key]
        sys.modules.update(saved_modules)


# Load pm-bot's claude_client once at import time under a separate name
_pmbot_cc = _load_pmbot_claude_client()


class TestProcessMeetingTranscript:
    """Tests for process_meeting_transcript()."""

    @patch("app.claude_client._call_claude")
    @patch("app.claude_client._load_prompt")
    def test_calls_claude_with_correct_params(self, mock_load_prompt, mock_call_claude):
        """Should load meeting_protocol prompt, combine with transcript, and call Claude."""
        mock_load_prompt.return_value = "You are a meeting protocol assistant."
        mock_call_claude.return_value = "---\ntitle: Test Meeting\n---\n# Protocol"

        transcript = "Alice: Hello\nBob: Hi\nAlice: Let's discuss the roadmap."

        result = process_meeting_transcript(transcript)

        mock_load_prompt.assert_called_once_with("meeting_protocol")
        mock_call_claude.assert_called_once_with(
            "You are a meeting protocol assistant.\n\n---\n\n" + transcript,
            max_tokens=4000,
            operation="meeting_protocol",
        )
        assert result == "---\ntitle: Test Meeting\n---\n# Protocol"

    @patch("app.claude_client._call_claude")
    @patch("app.claude_client._load_prompt")
    def test_logs_transcript_length(self, mock_load_prompt, mock_call_claude, caplog):
        """Should log transcript length, not content."""
        mock_load_prompt.return_value = "prompt"
        mock_call_claude.return_value = "result"
        transcript = "A" * 5000

        with caplog.at_level(logging.INFO, logger="app.claude_client"):
            process_meeting_transcript(transcript)

        assert "Processing meeting transcript (5000 chars)" in caplog.text

    @patch("app.claude_client._call_claude")
    @patch("app.claude_client._load_prompt")
    def test_empty_transcript(self, mock_load_prompt, mock_call_claude):
        """Should handle empty transcript gracefully."""
        mock_load_prompt.return_value = "prompt text"
        mock_call_claude.return_value = "---\ntitle: Empty\n---\n# No content"

        result = process_meeting_transcript("")

        mock_call_claude.assert_called_once_with(
            "prompt text\n\n---\n\n",
            max_tokens=4000,
            operation="meeting_protocol",
        )
        assert result == "---\ntitle: Empty\n---\n# No content"

    @patch("app.claude_client._call_claude")
    @patch("app.claude_client._load_prompt")
    def test_propagates_claude_api_error(self, mock_load_prompt, mock_call_claude):
        """Should propagate exceptions from _call_claude."""
        mock_load_prompt.return_value = "prompt"
        mock_call_claude.side_effect = Exception("API timeout")

        with pytest.raises(Exception, match="API timeout"):
            process_meeting_transcript("some transcript")

    @patch("app.claude_client._call_claude")
    @patch("app.claude_client._load_prompt")
    def test_large_transcript(self, mock_load_prompt, mock_call_claude):
        """Should handle large transcripts and log their length."""
        mock_load_prompt.return_value = "prompt"
        mock_call_claude.return_value = "protocol"
        large_transcript = "Speaker: line\n" * 10000  # ~150KB

        result = process_meeting_transcript(large_transcript)

        assert result == "protocol"
        # Verify the full transcript was passed through
        call_args = mock_call_claude.call_args
        assert large_transcript in call_args[0][0]


# ---------------------------------------------------------------------------
# BL-119: Tests for dynamic domain functions from pm-bot/app/claude_client.py
# ---------------------------------------------------------------------------


class TestGetValidDomains:
    """Tests for _get_valid_domains() — dynamic domain loading with fallback."""

    def test_get_valid_domains_from_config(self):
        """domain_config.get_valid_domains() returns domains -> same result."""
        with patch("shared.domain_config.get_valid_domains", return_value=("a", "b", "c")):
            result = _pmbot_cc._get_valid_domains()
        assert result == ("a", "b", "c")

    def test_get_valid_domains_fallback(self):
        """domain_config.get_valid_domains() raises Exception -> fallback."""
        mock_dc = MagicMock()
        mock_dc.get_valid_domains.side_effect = Exception("config broken")
        with patch.dict(sys.modules, {"shared.domain_config": mock_dc}):
            result = _pmbot_cc._get_valid_domains()
        assert result == _pmbot_cc._FALLBACK_DOMAINS


class TestBuildIdeaPrompt:
    """Tests for _build_idea_prompt() — dynamic prompt building with fallback."""

    def test_build_idea_prompt_dynamic(self):
        """build_prompt_section() succeeds -> prompt contains dynamic section."""
        static_template = (
            "Some header.\n\n"
            "{domains_section}\n\n"
            "Верни ТОЛЬКО JSON внутри блока"
        )
        with patch("shared.domain_config.build_prompt_section", return_value="- dom1\n- dom2"):
            with patch.object(_pmbot_cc, "_load_prompt", return_value=static_template):
                result = _pmbot_cc._build_idea_prompt("test")

        assert "- dom1\n- dom2" in result
        assert "test" in result
        # The placeholder should be replaced, not present
        assert "{domains_section}" not in result

    def test_build_idea_prompt_fallback(self):
        """build_prompt_section() raises Exception -> static prompt from idea.txt."""
        mock_dc = MagicMock()
        mock_dc.build_prompt_section.side_effect = Exception("config broken")
        static_prompt = "Static idea prompt from file"
        with patch.dict(sys.modules, {"shared.domain_config": mock_dc}):
            with patch.object(_pmbot_cc, "_load_prompt", return_value=static_prompt):
                result = _pmbot_cc._build_idea_prompt("test")

        assert static_prompt in result
        assert "test" in result


class TestInjectDomainsSection:
    """Tests for _inject_domains_section() — three injection strategies."""

    def test_inject_domains_placeholder(self):
        """Template with {domains_section} placeholder -> replaced."""
        template = "Header\n{domains_section}\nFooter"
        section = "- alpha\n- beta"
        result = _pmbot_cc._inject_domains_section(template, section)
        assert "- alpha\n- beta" in result
        assert "{domains_section}" not in result
        assert "Header\n" in result
        assert "\nFooter" in result

    def test_inject_domains_regex(self):
        """Template with static domain block -> regex replaces it."""
        template = (
            "Preamble.\n"
            "Определи домен идеи по содержанию сообщения. Доступные домены:\n"
            "- domain1\n"
            "- domain2\n"
            "Верни ТОЛЬКО JSON"
        )
        section = "- new-dom1\n- new-dom2"
        result = _pmbot_cc._inject_domains_section(template, section)
        assert "- new-dom1" in result
        assert "- new-dom2" in result
        # Old domains should be gone
        assert "- domain1" not in result
        assert "- domain2" not in result
        # Header and footer preserved
        assert "Preamble." in result
        assert "Верни ТОЛЬКО JSON" in result

    def test_inject_domains_append(self):
        """Template without markers but with JSON marker -> section inserted before it."""
        template = "Some instructions.\nВерни ТОЛЬКО JSON в формате..."
        section = "- appended-dom1\n- appended-dom2"
        result = _pmbot_cc._inject_domains_section(template, section)
        assert "- appended-dom1" in result
        assert "- appended-dom2" in result
        assert "Верни ТОЛЬКО JSON" in result
        # The domain section should appear before the JSON marker
        dom_pos = result.index("- appended-dom1")
        json_pos = result.index("Верни ТОЛЬКО JSON")
        assert dom_pos < json_pos
