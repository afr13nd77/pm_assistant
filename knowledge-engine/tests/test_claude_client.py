"""Unit tests for claude_client.process_meeting_transcript()."""

import logging
from unittest.mock import patch, MagicMock

import pytest

from app.claude_client import process_meeting_transcript


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
