"""Tests for shared/llm_client.call_transcription()"""

import pytest
from unittest.mock import patch, MagicMock

import shared.llm_client as llm_client


@pytest.fixture(autouse=True)
def _reset_prefs_cache():
    """Reset llm_client prefs cache before each test."""
    llm_client._cached_prefs = None
    llm_client._cached_mtime = 0.0
    yield
    llm_client._cached_prefs = None
    llm_client._cached_mtime = 0.0


class TestCallTranscription:
    def test_default_provider_delegates(self):
        """When transcription_provider=default, delegates to call_with_fallback."""
        prefs = {"transcription_provider": "default"}

        with patch("shared.llm_client._load_llm_prefs", return_value=prefs), \
             patch("shared.llm_client.call_with_fallback", return_value="fallback result") as mock_cwf:
            result = llm_client.call_transcription(
                "meeting", [{"role": "user", "content": "test"}], 4000
            )
            assert result == "fallback result"
            mock_cwf.assert_called_once()

    def test_missing_transcription_provider_defaults_to_default(self):
        """When transcription_provider key is absent, delegates to call_with_fallback."""
        prefs = {}  # no transcription_provider key

        with patch("shared.llm_client._load_llm_prefs", return_value=prefs), \
             patch("shared.llm_client.call_with_fallback", return_value="fallback result") as mock_cwf:
            result = llm_client.call_transcription(
                "meeting", [{"role": "user", "content": "test"}], 4000
            )
            assert result == "fallback result"
            mock_cwf.assert_called_once()

    def test_openrouter_success(self):
        """When transcription_provider=openrouter and key set, calls openrouter_client.call."""
        prefs = {
            "transcription_provider": "openrouter",
            "openrouter_model": "qwen/qwen3-32b",
            "ollama_url": "",
        }

        mock_or_call = MagicMock(return_value="openrouter result")

        with patch("shared.llm_client._load_llm_prefs", return_value=prefs), \
             patch("shared.llm_client.os.getenv", return_value="sk-test"), \
             patch("shared.openrouter_client.call", mock_or_call):
            result = llm_client.call_transcription(
                "meeting", [{"role": "user", "content": "test"}], 4000
            )
            assert result == "openrouter result"
            mock_or_call.assert_called_once()

    def test_openrouter_no_key_falls_back(self):
        """When openrouter selected but no key, falls back to call_with_fallback."""
        prefs = {
            "transcription_provider": "openrouter",
            "openrouter_model": "qwen/qwen3-32b",
        }

        with patch("shared.llm_client._load_llm_prefs", return_value=prefs), \
             patch("shared.llm_client.os.getenv", return_value=None), \
             patch("shared.llm_client.call_with_fallback", return_value="fallback result") as mock_cwf:
            result = llm_client.call_transcription(
                "meeting", [{"role": "user", "content": "test"}], 4000
            )
            assert result == "fallback result"
            mock_cwf.assert_called_once()

    def test_openrouter_failure_falls_back_to_claude(self):
        """When OpenRouter call raises, falls back to Claude API final fallback."""
        prefs = {
            "transcription_provider": "openrouter",
            "openrouter_model": "qwen/qwen3-32b",
            "ollama_url": "",  # no Ollama configured
        }

        mock_or_call = MagicMock(side_effect=RuntimeError("OpenRouter down"))
        mock_claude_response = MagicMock()
        mock_claude_response.content = [MagicMock(text="claude fallback result")]
        mock_claude_client = MagicMock()
        mock_claude_client.messages.create.return_value = mock_claude_response

        with patch("shared.llm_client._load_llm_prefs", return_value=prefs), \
             patch("shared.llm_client.os.getenv", side_effect=lambda k: "sk-test" if k == "OPENROUTER_API_KEY" else "claude-key"), \
             patch("shared.openrouter_client.call", mock_or_call), \
             patch("shared.llm_client.anthropic.Anthropic", return_value=mock_claude_client):
            result = llm_client.call_transcription(
                "meeting", [{"role": "user", "content": "test"}], 4000
            )
            assert result == "claude fallback result"
