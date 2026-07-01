"""Tests for shared/llm_client.py"""

import os
from unittest.mock import patch

import pytest
import requests

from shared import openrouter_client
from shared.llm_client import (
    OPENROUTER_429_BACKOFF_SECONDS,
    _call_openrouter,
    _call_provider,
    _default_model_for,
    _is_provider_available,
    _is_rate_limit_error,
    _migrate_legacy_prefs,
    _normalize_step,
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
    """T-03: _resolve_chain now returns normalized steps [{provider, model}, ...]
    instead of plain provider-name strings (design.md §2.1, §3.2)."""

    def test_valid_chain_from_prefs(self):
        """Returns chain as specified in prefs, normalized to step objects."""
        prefs = {"capture_fallback": ["openrouter", "claude"]}
        result = _resolve_chain("capture", prefs)
        assert result == [
            {"provider": "openrouter", "model": openrouter_client.DEFAULT_MODEL},
            {"provider": "claude", "model": None},
        ]

    def test_invalid_provider_filtered_out(self):
        """Unknown providers are removed; valid ones remain, as step objects."""
        prefs = {"capture_fallback": ["openrouter", "invalid", "claude"]}
        result = _resolve_chain("capture", prefs)
        assert result == [
            {"provider": "openrouter", "model": openrouter_client.DEFAULT_MODEL},
            {"provider": "claude", "model": None},
        ]

    def test_empty_chain_falls_back_to_claude(self):
        """Empty list in prefs results in [{'provider': 'claude', 'model': None}] default."""
        prefs = {"capture_fallback": []}
        result = _resolve_chain("capture", prefs)
        assert result == [{"provider": "claude", "model": None}]

    def test_missing_field_falls_back_to_default(self):
        """When key is absent, the built-in default chain is used, normalized."""
        prefs = {}
        result = _resolve_chain("analysis", prefs)
        assert result == [{"provider": "claude", "model": None}]

    def test_legacy_string_chain_resolves_to_list_of_dicts(self):
        """AC-04/FLOW-04: a legacy chain of provider-name strings normalizes
        to a list[dict] of {provider, model} steps -- shape check for T-03."""
        prefs = {"transcription_fallback": ["openrouter", "ollama", "claude"]}
        result = _resolve_chain("transcription", prefs)
        assert isinstance(result, list)
        assert all(isinstance(step, dict) for step in result)
        assert [step["provider"] for step in result] == ["openrouter", "ollama", "claude"]

    def test_legacy_openrouter_string_uses_global_openrouter_model(self):
        """Critical backward-compat case: legacy chain ["openrouter", ...] must
        resolve to the single global prefs['openrouter_model'] -- executing
        exactly as it does today (design.md §3.2, AC-04)."""
        prefs = {
            "openrouter_model": "qwen/qwen3-32b",
            "capture_fallback": ["openrouter", "ollama", "claude"],
        }
        result = _resolve_chain("capture", prefs)
        assert result[0] == {"provider": "openrouter", "model": "qwen/qwen3-32b"}
        assert result[1] == {"provider": "ollama", "model": None}
        assert result[2] == {"provider": "claude", "model": None}

    def test_object_step_with_explicit_model_is_preserved(self):
        """New-format object step with an explicit model keeps that model."""
        prefs = {
            "openrouter_model": "qwen/qwen3-32b",
            "capture_fallback": [
                {"provider": "openrouter", "model": "openai/gpt-oss-120b:free"},
                {"provider": "claude"},
            ],
        }
        result = _resolve_chain("capture", prefs)
        assert result == [
            {"provider": "openrouter", "model": "openai/gpt-oss-120b:free"},
            {"provider": "claude", "model": None},
        ]


# ---------------------------------------------------------------------------
# _default_model_for
# ---------------------------------------------------------------------------

class TestDefaultModelFor:
    def test_openrouter_uses_prefs_model_when_set(self):
        prefs = {"openrouter_model": "qwen/qwen3-32b"}
        assert _default_model_for("openrouter", prefs) == "qwen/qwen3-32b"

    def test_openrouter_falls_back_to_client_default_when_absent(self):
        prefs = {}
        assert _default_model_for("openrouter", prefs) == openrouter_client.DEFAULT_MODEL

    def test_openrouter_falls_back_to_client_default_when_empty_string(self):
        prefs = {"openrouter_model": ""}
        assert _default_model_for("openrouter", prefs) == openrouter_client.DEFAULT_MODEL

    def test_claude_has_no_default_model(self):
        assert _default_model_for("claude", {"openrouter_model": "x"}) is None

    def test_ollama_has_no_default_model(self):
        assert _default_model_for("ollama", {"ollama_model": "qwen3.5:latest"}) is None

    def test_unknown_provider_returns_none(self):
        assert _default_model_for("mystery", {}) is None


# ---------------------------------------------------------------------------
# _normalize_step
# ---------------------------------------------------------------------------

class TestNormalizeStep:
    def test_legacy_string_openrouter_becomes_object_with_default_model(self):
        prefs = {"openrouter_model": "qwen/qwen3-32b"}
        result = _normalize_step("openrouter", prefs)
        assert result == {"provider": "openrouter", "model": "qwen/qwen3-32b"}

    def test_legacy_string_claude_becomes_object_with_none_model(self):
        result = _normalize_step("claude", {})
        assert result == {"provider": "claude", "model": None}

    def test_legacy_string_ollama_becomes_object_with_none_model(self):
        result = _normalize_step("ollama", {})
        assert result == {"provider": "ollama", "model": None}

    def test_object_step_with_explicit_model_keeps_it(self):
        prefs = {"openrouter_model": "qwen/qwen3-32b"}
        el = {"provider": "openrouter", "model": "openai/gpt-oss-120b:free"}
        result = _normalize_step(el, prefs)
        assert result == {"provider": "openrouter", "model": "openai/gpt-oss-120b:free"}

    def test_object_step_without_model_gets_default(self):
        prefs = {"openrouter_model": "qwen/qwen3-32b"}
        el = {"provider": "openrouter"}
        result = _normalize_step(el, prefs)
        assert result == {"provider": "openrouter", "model": "qwen/qwen3-32b"}

    def test_object_step_with_empty_model_gets_default(self):
        """Empty-string model on the step is treated as absent (falsy)."""
        prefs = {"openrouter_model": "qwen/qwen3-32b"}
        el = {"provider": "openrouter", "model": ""}
        result = _normalize_step(el, prefs)
        assert result == {"provider": "openrouter", "model": "qwen/qwen3-32b"}

    def test_object_step_claude_model_ignored_in_favor_of_none(self):
        el = {"provider": "claude"}
        result = _normalize_step(el, {})
        assert result == {"provider": "claude", "model": None}

    def test_dict_missing_provider_returns_none(self):
        assert _normalize_step({"model": "x"}, {}) is None

    def test_unsupported_type_returns_none(self):
        assert _normalize_step(123, {}) is None


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

        def fake_call_provider(step, *args, **kwargs):
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
            # _call_provider must have been called only once, with the claude step
            assert mock_call.call_count == 1
            assert mock_call.call_args[0][0] == {"provider": "claude", "model": None}


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

        def fake_call_provider(step, *args, **kwargs):
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


# ---------------------------------------------------------------------------
# _call_openrouter / _call_provider — T-04: model comes from the step, not
# the global prefs["openrouter_model"] (design.md §1.4, §3.5, fixes BL-155
# root cause: _call_openrouter previously always used a single global model).
# ---------------------------------------------------------------------------

class TestCallOpenrouterModelSelection:
    _MESSAGES = [{"role": "user", "content": "hello"}]

    def test_call_openrouter_uses_explicit_model_param_over_prefs(self):
        """A model passed explicitly takes precedence over prefs['openrouter_model']."""
        prefs = {"openrouter_model": "global-fallback-model"}
        with patch("shared.openrouter_client.call", return_value="resp") as mock_call:
            result = _call_openrouter(prefs, self._MESSAGES, 100, None, None, model="step-model")
            assert result == "resp"
            assert mock_call.call_args.kwargs["model"] == "step-model"

    def test_call_openrouter_falls_back_to_prefs_when_model_not_given(self):
        """Backward compatibility: no model arg -> behaves exactly as before T-04."""
        prefs = {"openrouter_model": "global-fallback-model"}
        with patch("shared.openrouter_client.call", return_value="resp") as mock_call:
            result = _call_openrouter(prefs, self._MESSAGES, 100, None, None)
            assert result == "resp"
            assert mock_call.call_args.kwargs["model"] == "global-fallback-model"

    def test_call_openrouter_falls_back_to_hardcoded_default_when_nothing_set(self):
        """No model arg, no prefs['openrouter_model'] -> hardcoded default (unchanged)."""
        with patch("shared.openrouter_client.call", return_value="resp") as mock_call:
            _call_openrouter({}, self._MESSAGES, 100, None, None)
            assert mock_call.call_args.kwargs["model"] == "qwen/qwen3-32b"

    def test_call_provider_threads_step_model_into_call_openrouter(self):
        """_call_provider(step, ...) passes step['model'] through to _call_openrouter."""
        prefs = {"openrouter_model": "global-fallback-model"}
        step = {"provider": "openrouter", "model": "step-model"}
        with patch("shared.openrouter_client.call", return_value="resp") as mock_call:
            result = _call_provider(step, prefs, self._MESSAGES, 100, None, None)
            assert result == "resp"
            assert mock_call.call_args.kwargs["model"] == "step-model"

    def test_call_provider_claude_still_takes_step_object(self):
        """claude/ollama accept the same step-shaped argument (uniform signature),
        but keep resolving their own model from their own prefs fields."""
        with patch("shared.llm_client._call_claude", return_value="claude-resp") as mock_claude:
            result = _call_provider({"provider": "claude", "model": None}, {}, self._MESSAGES, 100, None, None)
            assert result == "claude-resp"
            mock_claude.assert_called_once()

    def test_call_provider_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            _call_provider({"provider": "mystery", "model": None}, {}, self._MESSAGES, 100, None, None)


class TestMultiModelOpenrouterFallback:
    """Key regression test for BL-155: a fallback chain with two OpenRouter
    steps must use each step's OWN model, not the single global
    prefs['openrouter_model'], when falling back from the first to the
    second step (design.md §1.4, AC-05)."""

    _MESSAGES = [{"role": "user", "content": "hello"}]

    def test_two_openrouter_steps_with_different_models_use_correct_model_each(self):
        prefs = {
            "llm_provider": "claude",
            # Deliberately different from either step's model -- if the bug
            # from BL-155 were still present, _call_openrouter would ignore
            # the step and always request this model instead.
            "openrouter_model": "should-not-be-used",
            "capture_fallback": [
                {"provider": "openrouter", "model": "model-A"},
                {"provider": "openrouter", "model": "model-B"},
            ],
            "transcription_fallback": ["claude"],
            "analysis_fallback": ["claude"],
        }

        def fake_openrouter_call(messages, model, max_tokens, timeout=None, **kwargs):
            if model == "model-A":
                raise RuntimeError("model-A rate limited")
            if model == "model-B":
                return "response-from-model-B"
            raise AssertionError(f"unexpected model requested: {model}")

        with patch("shared.llm_client._load_llm_prefs", return_value=prefs), \
             patch("shared.llm_client._is_provider_available", return_value=True), \
             patch("shared.openrouter_client.call", side_effect=fake_openrouter_call) as mock_call:
            text, record = call_detailed("idea", self._MESSAGES, max_tokens=100)

        assert text == "response-from-model-B"
        assert record["used"] == "openrouter"
        assert record["providers"] == ["openrouter", "openrouter"]
        assert len(record["errors"]) == 1
        failed_provider, failed_msg = record["errors"][0]
        # T-05 (design.md §6.4): error key for openrouter steps is "openrouter:<model>".
        assert failed_provider == "openrouter:model-A"
        assert "model-A rate limited" in failed_msg

        # Root-cause proof (BL-155): each attempt requested its OWN step
        # model, never the global prefs["openrouter_model"].
        requested_models = [c.kwargs["model"] for c in mock_call.call_args_list]
        assert requested_models == ["model-A", "model-B"]
        assert "should-not-be-used" not in requested_models

    def test_falls_through_to_claude_only_after_both_openrouter_models_fail(self):
        """AC-05 (second clause): [openrouter(A), openrouter(B), claude] --
        if model A fails AND model B also fails, only THEN does the chain
        move on to claude. Claude must NOT be attempted while an untried
        OpenRouter model still remains in the chain."""
        prefs = {
            "llm_provider": "claude",
            "openrouter_model": "should-not-be-used",
            "capture_fallback": [
                {"provider": "openrouter", "model": "model-A"},
                {"provider": "openrouter", "model": "model-B"},
                {"provider": "claude"},
            ],
            "transcription_fallback": ["claude"],
            "analysis_fallback": ["claude"],
        }

        def fake_openrouter_call(messages, model, max_tokens, timeout=None, **kwargs):
            # Both OpenRouter models fail -- model A with a rate limit,
            # model B with an unrelated error.
            if model == "model-A":
                raise _make_http_error(429)
            if model == "model-B":
                raise RuntimeError("model-B down")
            raise AssertionError(f"unexpected model requested: {model}")

        with patch("shared.llm_client._load_llm_prefs", return_value=prefs), \
             patch("shared.llm_client._is_provider_available", return_value=True), \
             patch("shared.openrouter_client.call", side_effect=fake_openrouter_call) as mock_call, \
             patch("shared.llm_client._call_claude", return_value="claude-response") as mock_claude, \
             patch("time.sleep"):
            text, record = call_detailed("idea", self._MESSAGES, max_tokens=100)

        assert text == "claude-response"
        assert record["used"] == "claude"
        assert record["used_step_index"] == 2
        assert record["providers"] == ["openrouter", "openrouter", "claude"]

        # Both OpenRouter models were attempted (in order) BEFORE claude.
        requested_models = [c.kwargs["model"] for c in mock_call.call_args_list]
        assert requested_models == ["model-A", "model-B"]
        mock_claude.assert_called_once()

        # Both failures recorded with the "openrouter:<model>" key format.
        error_keys = [key for key, _ in record["errors"]]
        assert error_keys == ["openrouter:model-A", "openrouter:model-B"]


# ---------------------------------------------------------------------------
# T-05: _is_rate_limit_error, provider_record chain/used_model/used_step_index,
# errors[] key format "provider:model", and 429 backoff between adjacent
# openrouter steps (design.md §2.4, §6.3, §6.4).
# ---------------------------------------------------------------------------

def _make_http_error(status_code: int) -> requests.HTTPError:
    """Build a requests.HTTPError carrying a fake Response(status_code=...),
    mirroring what openrouter_client.call() raises via response.raise_for_status()."""
    response = requests.Response()
    response.status_code = status_code
    return requests.HTTPError(f"{status_code} error", response=response)


class TestIsRateLimitError:
    def test_http_error_with_429_status_code_detected(self):
        assert _is_rate_limit_error(_make_http_error(429)) is True

    def test_http_error_with_other_status_code_not_detected(self):
        assert _is_rate_limit_error(_make_http_error(500)) is False

    def test_plain_exception_with_429_text_detected(self):
        assert _is_rate_limit_error(Exception("429 Too Many Requests")) is True

    def test_plain_exception_without_429_marker_not_detected(self):
        assert _is_rate_limit_error(Exception("connection reset")) is False


class TestProviderRecordChainFields:
    """provider_record additively gains chain/used_model/used_step_index;
    providers/used keep their previous form (design.md §2.4)."""

    _MESSAGES = [{"role": "user", "content": "hello"}]

    def test_chain_used_model_and_used_step_index_on_success(self):
        prefs = {
            "llm_provider": "claude",
            "capture_fallback": [
                {"provider": "openrouter", "model": "model-A"},
                {"provider": "openrouter", "model": "model-B"},
            ],
            "transcription_fallback": ["claude"],
            "analysis_fallback": ["claude"],
        }

        def fake_openrouter_call(messages, model, max_tokens, timeout=None, **kwargs):
            if model == "model-A":
                raise RuntimeError("model-A down")
            return "response-from-model-B"

        with patch("shared.llm_client._load_llm_prefs", return_value=prefs), \
             patch("shared.llm_client._is_provider_available", return_value=True), \
             patch("shared.openrouter_client.call", side_effect=fake_openrouter_call):
            text, record = call_detailed("idea", self._MESSAGES, max_tokens=100)

        assert text == "response-from-model-B"
        assert record["chain"] == [
            {"provider": "openrouter", "model": "model-A"},
            {"provider": "openrouter", "model": "model-B"},
        ]
        assert record["used_model"] == "model-B"
        assert record["used_step_index"] == 1
        # Existing keys keep their pre-T-05 form
        assert record["providers"] == ["openrouter", "openrouter"]
        assert record["used"] == "openrouter"

    def test_used_model_is_none_for_claude(self):
        prefs = {
            "llm_provider": "claude",
            "capture_fallback": ["claude"],
            "transcription_fallback": ["claude"],
            "analysis_fallback": ["claude"],
        }
        with patch("shared.llm_client._load_llm_prefs", return_value=prefs), \
             patch("shared.llm_client._is_provider_available", return_value=True), \
             patch("shared.llm_client._call_provider", return_value="claude-response"):
            text, record = call_detailed("idea", self._MESSAGES, max_tokens=100)

        assert record["used_model"] is None
        assert record["used_step_index"] == 0
        assert record["chain"] == [{"provider": "claude", "model": None}]


class TestErrorKeyFormat:
    """errors[] key for openrouter steps is 'openrouter:<model>' (design.md §6.4)."""

    _MESSAGES = [{"role": "user", "content": "hello"}]

    def test_openrouter_error_key_includes_model(self):
        prefs = {
            "llm_provider": "claude",
            "capture_fallback": [
                {"provider": "openrouter", "model": "qwen/qwen3-32b"},
                {"provider": "claude"},
            ],
            "transcription_fallback": ["claude"],
            "analysis_fallback": ["claude"],
        }

        def fake_call_provider(step, *args, **kwargs):
            if step["provider"] == "openrouter":
                raise RuntimeError("boom")
            return "claude-response"

        with patch("shared.llm_client._load_llm_prefs", return_value=prefs), \
             patch("shared.llm_client._is_provider_available", return_value=True), \
             patch("shared.llm_client._call_provider", side_effect=fake_call_provider):
            text, record = call_detailed("idea", self._MESSAGES, max_tokens=100)

        assert text == "claude-response"
        assert len(record["errors"]) == 1
        failed_key, failed_msg = record["errors"][0]
        assert failed_key == "openrouter:qwen/qwen3-32b"
        assert "boom" in failed_msg

    def test_claude_error_key_is_plain_provider_name(self):
        prefs = {
            "llm_provider": "claude",
            "capture_fallback": ["claude", "ollama"],
            "transcription_fallback": ["claude"],
            "analysis_fallback": ["claude"],
        }

        def fake_call_provider(step, *args, **kwargs):
            if step["provider"] == "claude":
                raise RuntimeError("no balance")
            return "ollama-response"

        with patch("shared.llm_client._load_llm_prefs", return_value=prefs), \
             patch("shared.llm_client._is_provider_available", return_value=True), \
             patch("shared.llm_client._call_provider", side_effect=fake_call_provider):
            text, record = call_detailed("idea", self._MESSAGES, max_tokens=100)

        assert text == "ollama-response"
        failed_key, _ = record["errors"][0]
        assert failed_key == "claude"


class TestOpenrouter429Backoff:
    """Short backoff between ADJACENT openrouter steps after a 429
    (design.md §6.3). time.sleep is mocked so the test stays fast."""

    _MESSAGES = [{"role": "user", "content": "hello"}]

    def test_backoff_applied_between_adjacent_openrouter_steps_after_429(self):
        prefs = {
            "llm_provider": "claude",
            "capture_fallback": [
                {"provider": "openrouter", "model": "model-A"},
                {"provider": "openrouter", "model": "model-B"},
            ],
            "transcription_fallback": ["claude"],
            "analysis_fallback": ["claude"],
        }

        def fake_openrouter_call(messages, model, max_tokens, timeout=None, **kwargs):
            if model == "model-A":
                raise _make_http_error(429)
            return "response-from-model-B"

        with patch("shared.llm_client._load_llm_prefs", return_value=prefs), \
             patch("shared.llm_client._is_provider_available", return_value=True), \
             patch("shared.openrouter_client.call", side_effect=fake_openrouter_call), \
             patch("time.sleep") as mock_sleep:
            text, record = call_detailed("idea", self._MESSAGES, max_tokens=100)

        assert text == "response-from-model-B"
        mock_sleep.assert_called_once()
        (delay,), _ = mock_sleep.call_args
        assert 0.5 <= delay <= 1.0
        assert delay == OPENROUTER_429_BACKOFF_SECONDS

    def test_no_backoff_when_next_step_is_different_provider(self):
        prefs = {
            "llm_provider": "claude",
            "capture_fallback": [
                {"provider": "openrouter", "model": "model-A"},
                {"provider": "claude"},
            ],
            "transcription_fallback": ["claude"],
            "analysis_fallback": ["claude"],
        }

        def fake_call_provider(step, *args, **kwargs):
            if step["provider"] == "openrouter":
                raise _make_http_error(429)
            return "claude-response"

        with patch("shared.llm_client._load_llm_prefs", return_value=prefs), \
             patch("shared.llm_client._is_provider_available", return_value=True), \
             patch("shared.llm_client._call_provider", side_effect=fake_call_provider), \
             patch("time.sleep") as mock_sleep:
            text, record = call_detailed("idea", self._MESSAGES, max_tokens=100)

        assert text == "claude-response"
        mock_sleep.assert_not_called()

    def test_no_backoff_when_error_is_not_429(self):
        prefs = {
            "llm_provider": "claude",
            "capture_fallback": [
                {"provider": "openrouter", "model": "model-A"},
                {"provider": "openrouter", "model": "model-B"},
            ],
            "transcription_fallback": ["claude"],
            "analysis_fallback": ["claude"],
        }

        def fake_openrouter_call(messages, model, max_tokens, timeout=None, **kwargs):
            if model == "model-A":
                raise RuntimeError("400 Bad Request: invalid model")
            return "response-from-model-B"

        with patch("shared.llm_client._load_llm_prefs", return_value=prefs), \
             patch("shared.llm_client._is_provider_available", return_value=True), \
             patch("shared.openrouter_client.call", side_effect=fake_openrouter_call), \
             patch("time.sleep") as mock_sleep:
            text, record = call_detailed("idea", self._MESSAGES, max_tokens=100)

        assert text == "response-from-model-B"
        mock_sleep.assert_not_called()
