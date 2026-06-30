"""Tests for shared/llm_client.py"""

import os
from unittest.mock import patch

import pytest

from shared.llm_client import (
    _is_provider_available,
    _migrate_legacy_prefs,
    _resolve_chain,
    _resolve_group,
    call,
    call_detailed,
)

# ---------------------------------------------------------------------------
# _migrate_legacy_prefs
# ---------------------------------------------------------------------------

class TestMigrateLegacyPrefs:
    def test_llm_provider_claude_sets_fallbacks(self):
        """llm_provider=claude -> capture and analysis fallback to ['claude']."""
        prefs = {"llm_provider": "claude"}
        result = _migrate_legacy_prefs(prefs)
        assert result["capture_fallback"] == ["claude"]
        assert result["analysis_fallback"] == ["claude"]

    def test_llm_provider_ollama_sets_capture_fallback(self):
        """llm_provider=ollama -> capture_fallback=['ollama','claude']."""
        prefs = {"llm_provider": "ollama", "ollama_url": "http://localhost:11434"}
        result = _migrate_legacy_prefs(prefs)
        assert result["capture_fallback"] == ["ollama", "claude"]

    def test_llm_provider_hybrid_sets_capture_fallback(self):
        """llm_provider=hybrid -> capture_fallback=['ollama','claude'], analysis_fallback=['claude']."""
        prefs = {"llm_provider": "hybrid", "ollama_url": "http://localhost:11434"}
        result = _migrate_legacy_prefs(prefs)
        assert result["capture_fallback"] == ["ollama", "claude"]
        assert result["analysis_fallback"] == ["claude"]

    def test_hybrid_with_openrouter_transcription(self):
        """hybrid + transcription_provider=openrouter -> transcription_fallback=['openrouter','ollama','claude']."""
        prefs = {
            "llm_provider": "hybrid",
            "ollama_url": "http://localhost:11434",
            "transcription_provider": "openrouter",
        }
        result = _migrate_legacy_prefs(prefs)
        assert result["transcription_fallback"] == ["openrouter", "ollama", "claude"]

    def test_already_migrated_prefs_unchanged(self):
        """If all three fallback fields are present, prefs are returned as-is."""
        prefs = {
            "llm_provider": "claude",
            "capture_fallback": ["openrouter", "claude"],
            "transcription_fallback": ["openrouter"],
            "analysis_fallback": ["claude"],
        }
        original_capture = prefs["capture_fallback"][:]
        original_transcription = prefs["transcription_fallback"][:]
        original_analysis = prefs["analysis_fallback"][:]

        result = _migrate_legacy_prefs(prefs)

        assert result["capture_fallback"] == original_capture
        assert result["transcription_fallback"] == original_transcription
        assert result["analysis_fallback"] == original_analysis


# ---------------------------------------------------------------------------
# _resolve_group
# ---------------------------------------------------------------------------

class TestResolveGroup:
    def test_idea_maps_to_capture(self):
        assert _resolve_group("idea") == "capture"

    def test_meeting_maps_to_transcription(self):
        assert _resolve_group("meeting") == "transcription"

    def test_enrich_maps_to_analysis(self):
        assert _resolve_group("enrich") == "analysis"

    def test_unknown_operation_defaults_to_analysis(self):
        assert _resolve_group("unknown_op") == "analysis"


# ---------------------------------------------------------------------------
# _resolve_chain
# ---------------------------------------------------------------------------

class TestResolveChain:
    def test_valid_chain_from_prefs(self):
        """Returns chain as specified in prefs when all providers are valid."""
        prefs = {"capture_fallback": ["openrouter", "claude"]}
        result = _resolve_chain("capture", prefs)
        assert result == ["openrouter", "claude"]

    def test_invalid_provider_filtered_out(self):
        """Unknown providers are removed; valid ones remain."""
        prefs = {"capture_fallback": ["openrouter", "invalid", "claude"]}
        result = _resolve_chain("capture", prefs)
        assert result == ["openrouter", "claude"]

    def test_empty_chain_falls_back_to_claude(self):
        """Empty list in prefs results in ['claude'] default."""
        prefs = {"capture_fallback": []}
        result = _resolve_chain("capture", prefs)
        assert result == ["claude"]

    def test_missing_field_falls_back_to_default(self):
        """When key is absent, the built-in default chain is used."""
        prefs = {}
        result = _resolve_chain("analysis", prefs)
        assert result == ["claude"]


# ---------------------------------------------------------------------------
# _is_provider_available
# ---------------------------------------------------------------------------

class TestIsProviderAvailable:
    def test_claude_available_when_key_set(self):
        """claude is available when CLAUDE_API_KEY is non-empty."""
        with patch.dict(os.environ, {"CLAUDE_API_KEY": "test-key"}):
            assert _is_provider_available("claude", {}) is True

    def test_claude_unavailable_when_key_empty(self):
        """claude is unavailable when CLAUDE_API_KEY is empty string."""
        with patch.dict(os.environ, {"CLAUDE_API_KEY": ""}, clear=False):
            # Ensure key exists but is empty
            os.environ["CLAUDE_API_KEY"] = ""
            assert _is_provider_available("claude", {}) is False

    def test_ollama_available_when_url_set(self):
        """ollama is available when prefs contain a non-empty ollama_url."""
        prefs = {"ollama_url": "http://localhost:11434"}
        assert _is_provider_available("ollama", prefs) is True

    def test_openrouter_unavailable_when_key_not_set(self):
        """openrouter is unavailable when OPENROUTER_API_KEY is not set."""
        env = {k: v for k, v in os.environ.items() if k != "OPENROUTER_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            assert _is_provider_available("openrouter", {}) is False


# ---------------------------------------------------------------------------
# call
# ---------------------------------------------------------------------------

class TestCall:
    _MESSAGES = [{"role": "user", "content": "hello"}]

    def test_first_provider_success_returns_result(self):
        """When the first provider succeeds, its result is returned immediately."""
        prefs = {
            "llm_provider": "claude",
            "capture_fallback": ["claude"],
            "transcription_fallback": ["claude"],
            "analysis_fallback": ["claude"],
        }
        with patch("shared.llm_client._load_llm_prefs", return_value=prefs), \
             patch("shared.llm_client._is_provider_available", return_value=True), \
             patch("shared.llm_client._call_provider", return_value="ok-response") as mock_call:
            result = call("idea", self._MESSAGES, max_tokens=100)
            assert result == "ok-response"
            mock_call.assert_called_once()

    def test_fallback_to_second_provider_on_first_failure(self):
        """When the first provider raises, the second provider is tried."""
        prefs = {
            "llm_provider": "claude",
            "capture_fallback": ["ollama", "claude"],
            "transcription_fallback": ["claude"],
            "analysis_fallback": ["claude"],
        }
        call_results = [Exception("ollama down"), "fallback-response"]
        call_iter = iter(call_results)

        def fake_call_provider(provider, *args, **kwargs):
            val = next(call_iter)
            if isinstance(val, Exception):
                raise val
            return val

        with patch("shared.llm_client._load_llm_prefs", return_value=prefs), \
             patch("shared.llm_client._is_provider_available", return_value=True), \
             patch("shared.llm_client._call_provider", side_effect=fake_call_provider):
            result = call("idea", self._MESSAGES, max_tokens=100)
            assert result == "fallback-response"

    def test_all_providers_fail_raises_runtime_error(self):
        """RuntimeError is raised when every provider in the chain fails."""
        prefs = {
            "llm_provider": "claude",
            "capture_fallback": ["claude"],
            "transcription_fallback": ["claude"],
            "analysis_fallback": ["claude"],
        }
        with patch("shared.llm_client._load_llm_prefs", return_value=prefs), \
             patch("shared.llm_client._is_provider_available", return_value=True), \
             patch("shared.llm_client._call_provider", side_effect=Exception("always fails")):
            with pytest.raises(RuntimeError, match="All providers failed"):
                call("idea", self._MESSAGES, max_tokens=100)

    def test_unavailable_provider_is_skipped(self):
        """Providers that are not available are skipped without calling _call_provider."""
        prefs = {
            "llm_provider": "claude",
            "capture_fallback": ["ollama", "claude"],
            "transcription_fallback": ["claude"],
            "analysis_fallback": ["claude"],
        }

        def availability(provider, _prefs):
            return provider == "claude"  # ollama is unavailable

        with patch("shared.llm_client._load_llm_prefs", return_value=prefs), \
             patch("shared.llm_client._is_provider_available", side_effect=availability), \
             patch("shared.llm_client._call_provider", return_value="claude-result") as mock_call:
            result = call("idea", self._MESSAGES, max_tokens=100)
            assert result == "claude-result"
            # _call_provider must have been called only once and with claude
            assert mock_call.call_count == 1
            assert mock_call.call_args[0][0] == "claude"


# ---------------------------------------------------------------------------
# call_detailed
# ---------------------------------------------------------------------------

class TestCallDetailed:
    _MESSAGES = [{"role": "user", "content": "hello"}]

    def test_first_provider_success_record(self):
        """First provider succeeds: used==first, providers holds the chain, no errors."""
        prefs = {
            "llm_provider": "claude",
            "capture_fallback": ["claude"],
            "transcription_fallback": ["claude"],
            "analysis_fallback": ["claude"],
        }
        with patch("shared.llm_client._load_llm_prefs", return_value=prefs), \
             patch("shared.llm_client._is_provider_available", return_value=True), \
             patch("shared.llm_client._call_provider", return_value="ok-response"):
            text, record = call_detailed("idea", self._MESSAGES, max_tokens=100)
            assert text == "ok-response"
            assert record["used"] == "claude"
            assert record["providers"] == ["claude"]
            assert record["errors"] == []

    def test_fallback_to_second_provider_record(self):
        """First provider fails, second succeeds: used==second, errors has the first."""
        prefs = {
            "llm_provider": "claude",
            "capture_fallback": ["ollama", "claude"],
            "transcription_fallback": ["claude"],
            "analysis_fallback": ["claude"],
        }
        call_results = [Exception("ollama down"), "fallback-response"]
        call_iter = iter(call_results)

        def fake_call_provider(provider, *args, **kwargs):
            val = next(call_iter)
            if isinstance(val, Exception):
                raise val
            return val

        with patch("shared.llm_client._load_llm_prefs", return_value=prefs), \
             patch("shared.llm_client._is_provider_available", return_value=True), \
             patch("shared.llm_client._call_provider", side_effect=fake_call_provider):
            text, record = call_detailed("idea", self._MESSAGES, max_tokens=100)
            assert text == "fallback-response"
            assert record["used"] == "ollama" or record["used"] == "claude"
            # Second provider in the chain is the one that succeeded
            assert record["used"] == "claude"
            assert record["providers"] == ["ollama", "claude"]
            assert len(record["errors"]) == 1
            failed_provider, failed_msg = record["errors"][0]
            assert failed_provider == "ollama"
            assert "ollama down" in failed_msg

    def test_used_always_set_on_success(self):
        """provider_record['used'] is always populated (non-empty) on success."""
        prefs = {
            "llm_provider": "claude",
            "capture_fallback": ["openrouter", "claude"],
            "transcription_fallback": ["claude"],
            "analysis_fallback": ["claude"],
        }

        def availability(provider, _prefs):
            return provider == "claude"  # openrouter unavailable

        with patch("shared.llm_client._load_llm_prefs", return_value=prefs), \
             patch("shared.llm_client._is_provider_available", side_effect=availability), \
             patch("shared.llm_client._call_provider", return_value="claude-result"):
            text, record = call_detailed("idea", self._MESSAGES, max_tokens=100)
            assert text == "claude-result"
            assert record["used"]  # non-empty
            assert record["used"] == "claude"

    def test_all_providers_fail_raises_runtime_error(self):
        """RuntimeError when every provider fails (same contract as call())."""
        prefs = {
            "llm_provider": "claude",
            "capture_fallback": ["claude"],
            "transcription_fallback": ["claude"],
            "analysis_fallback": ["claude"],
        }
        with patch("shared.llm_client._load_llm_prefs", return_value=prefs), \
             patch("shared.llm_client._is_provider_available", return_value=True), \
             patch("shared.llm_client._call_provider", side_effect=Exception("always fails")):
            with pytest.raises(RuntimeError, match="All providers failed"):
                call_detailed("idea", self._MESSAGES, max_tokens=100)

    def test_call_delegates_to_call_detailed(self):
        """call() returns exactly call_detailed()[0] — behaviour unchanged."""
        prefs = {
            "llm_provider": "claude",
            "capture_fallback": ["claude"],
            "transcription_fallback": ["claude"],
            "analysis_fallback": ["claude"],
        }
        with patch("shared.llm_client._load_llm_prefs", return_value=prefs), \
             patch("shared.llm_client._is_provider_available", return_value=True), \
             patch("shared.llm_client._call_provider", return_value="ok-response"):
            text_only = call("idea", self._MESSAGES, max_tokens=100)
            text_detailed, _ = call_detailed("idea", self._MESSAGES, max_tokens=100)
            assert text_only == text_detailed == "ok-response"
