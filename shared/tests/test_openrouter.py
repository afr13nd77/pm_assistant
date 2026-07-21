"""Tests for shared/openrouter_client.py"""

from unittest.mock import MagicMock, patch

import pytest

import shared.openrouter_client as openrouter_client
from shared.openrouter_client import AVAILABLE_MODELS, call, list_models, test_connection


class TestCall:
    def test_call_success_returns_tuple(self):
        """Mock successful API call, verify tuple[str, dict] return."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Hello world"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 25},
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("shared.openrouter_client.os.getenv", return_value="sk-test-key"), \
             patch("shared.openrouter_client.requests.post", return_value=mock_resp):
            result = call([{"role": "user", "content": "test"}])
            assert isinstance(result, tuple)
            assert len(result) == 2
            text, usage = result
            assert text == "Hello world"

    def test_call_usage_contains_required_fields(self):
        """usage dict must contain input_tokens, output_tokens, model."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 42, "completion_tokens": 17},
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("shared.openrouter_client.os.getenv", return_value="sk-test-key"), \
             patch("shared.openrouter_client.requests.post", return_value=mock_resp):
            text, usage = call([{"role": "user", "content": "test"}], model="test/model")
            assert usage["input_tokens"] == 42
            assert usage["output_tokens"] == 17
            assert usage["model"] == "test/model"

    def test_call_usage_graceful_when_usage_absent(self):
        """When API response has no 'usage' field, usage dict has None tokens."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "no usage"}}],
            # No "usage" key at all
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("shared.openrouter_client.os.getenv", return_value="sk-test-key"), \
             patch("shared.openrouter_client.requests.post", return_value=mock_resp):
            text, usage = call([{"role": "user", "content": "test"}], model="test/model")
            assert text == "no usage"
            assert usage["input_tokens"] is None
            assert usage["output_tokens"] is None
            assert usage["model"] == "test/model"

    def test_call_no_api_key(self):
        """ValueError when OPENROUTER_API_KEY not set."""
        with patch("shared.openrouter_client.os.getenv", return_value=None):
            with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
                call([{"role": "user", "content": "test"}])

    def test_call_invalid_response(self):
        """RuntimeError on unexpected response structure."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"unexpected": "structure"}
        mock_resp.raise_for_status = MagicMock()

        with patch("shared.openrouter_client.os.getenv", return_value="sk-test"), \
             patch("shared.openrouter_client.requests.post", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="unexpected response"):
                call([{"role": "user", "content": "test"}])

    def test_call_http_error(self):
        """requests.HTTPError on bad status code."""
        import requests as req
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = req.HTTPError("500 Server Error")

        with patch("shared.openrouter_client.os.getenv", return_value="sk-test"), \
             patch("shared.openrouter_client.requests.post", return_value=mock_resp):
            with pytest.raises(req.HTTPError):
                call([{"role": "user", "content": "test"}])


class TestTestConnection:
    def test_success(self):
        """Model found in response."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [{"id": "qwen/qwen3-32b", "name": "Qwen3 32B"}]
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("shared.openrouter_client.requests.get", return_value=mock_resp):
            result = test_connection("sk-test", "qwen/qwen3-32b")
            assert result["status"] == "ok"
            assert result["model"] == "qwen/qwen3-32b"

    def test_auth_fail(self):
        """401 returns error status."""
        import requests as req
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.raise_for_status.side_effect = req.HTTPError(response=mock_resp)

        with patch("shared.openrouter_client.requests.get", return_value=mock_resp):
            result = test_connection("bad-key")
            assert result["status"] == "error"
            assert "Auth failed" in result["detail"]

    def test_model_not_found(self):
        """Model not in list returns error."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [{"id": "other/model", "name": "Other"}]
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("shared.openrouter_client.requests.get", return_value=mock_resp):
            result = test_connection("sk-test", "qwen/qwen3-32b")
            assert result["status"] == "error"
            assert "not found" in result["detail"]


class TestAvailableModels:
    def test_models_count(self):
        assert len(AVAILABLE_MODELS) == 6

    def test_models_have_required_fields(self):
        for m in AVAILABLE_MODELS:
            assert "id" in m
            assert "name" in m


class TestListModels:
    def setup_method(self):
        """Reset module-level cache before every test to avoid cross-test leakage."""
        openrouter_client._models_cache = None
        openrouter_client._models_cache_ts = 0.0

    def teardown_method(self):
        openrouter_client._models_cache = None
        openrouter_client._models_cache_ts = 0.0

    def test_live_success(self):
        """Live fetch parses data[] into {id, name} and returns source=live."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [
                {"id": "qwen/qwen3-32b", "name": "Qwen3 32B"},
                {"id": "no-name/model"},
            ]
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("shared.openrouter_client.requests.get", return_value=mock_resp):
            result = list_models("sk-test", ttl_seconds=3600)

        assert result["source"] == "live"
        assert result["cached"] is False
        assert result["count"] == 2
        assert result["models"][0] == {"id": "qwen/qwen3-32b", "name": "Qwen3 32B"}
        assert result["models"][1] == {"id": "no-name/model", "name": "no-name/model"}
        assert "fetched_at" in result

    def test_fallback_on_timeout(self):
        """Timeout during live fetch falls back to AVAILABLE_MODELS."""
        import requests as req

        with patch("shared.openrouter_client.requests.get", side_effect=req.Timeout("timed out")):
            result = list_models("sk-test", ttl_seconds=3600)

        assert result["source"] == "fallback"
        assert result["cached"] is False
        assert result["models"] == AVAILABLE_MODELS
        assert result["count"] == len(AVAILABLE_MODELS)

    def test_fallback_on_connection_error(self):
        """ConnectionError during live fetch falls back to AVAILABLE_MODELS."""
        import requests as req

        with patch("shared.openrouter_client.requests.get", side_effect=req.ConnectionError("refused")):
            result = list_models("sk-test", ttl_seconds=3600)

        assert result["source"] == "fallback"
        assert result["models"] == AVAILABLE_MODELS

    def test_fallback_on_http_error(self):
        """Non-200 status (e.g. 401) falls back to AVAILABLE_MODELS."""
        import requests as req

        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.raise_for_status.side_effect = req.HTTPError(response=mock_resp)

        with patch("shared.openrouter_client.requests.get", return_value=mock_resp):
            result = list_models("sk-test", ttl_seconds=3600)

        assert result["source"] == "fallback"
        assert result["models"] == AVAILABLE_MODELS

    def test_fallback_on_empty_api_key_no_network_call(self):
        """Empty/None api_key must not trigger a network call."""
        with patch("shared.openrouter_client.requests.get") as mock_get:
            result = list_models(None, ttl_seconds=3600)

        mock_get.assert_not_called()
        assert result["source"] == "fallback"
        assert result["models"] == AVAILABLE_MODELS

    def test_fallback_on_timeout_logs_warning(self, caplog):
        """AC-02: a warning with error detail is written to the log when the
        live fetch fails and the fallback list is returned."""
        import logging

        import requests as req

        with caplog.at_level(logging.WARNING, logger="shared.openrouter_client"):
            with patch("shared.openrouter_client.requests.get", side_effect=req.Timeout("timed out")):
                result = list_models("sk-test", ttl_seconds=3600)

        assert result["source"] == "fallback"
        warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("timed out" in w and "fallback" in w for w in warnings)

    def test_fallback_on_empty_api_key_logs_warning(self, caplog):
        """AC-02: missing api_key also logs a warning explaining the fallback."""
        import logging

        with caplog.at_level(logging.WARNING, logger="shared.openrouter_client"):
            result = list_models(None, ttl_seconds=3600)

        assert result["source"] == "fallback"
        warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("fallback" in w for w in warnings)

    def test_cache_hit_within_ttl_no_repeat_call(self):
        """Second call within TTL is served from cache, no second HTTP call."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [{"id": "qwen/qwen3-32b", "name": "Qwen3 32B"}]
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("shared.openrouter_client.requests.get", return_value=mock_resp) as mock_get:
            first = list_models("sk-test", ttl_seconds=3600)
            second = list_models("sk-test", ttl_seconds=3600)

        assert mock_get.call_count == 1
        assert first["cached"] is False
        assert second["cached"] is True
        assert second["source"] == "live"
        assert second["models"] == first["models"]
