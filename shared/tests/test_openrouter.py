"""Tests for shared/openrouter_client.py"""

import pytest
from unittest.mock import patch, MagicMock

from shared.openrouter_client import call, test_connection, AVAILABLE_MODELS


class TestCall:
    def test_call_success(self):
        """Mock successful API call, verify content extraction."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Hello world"}}]
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("shared.openrouter_client.os.getenv", return_value="sk-test-key"), \
             patch("shared.openrouter_client.requests.post", return_value=mock_resp):
            result = call([{"role": "user", "content": "test"}])
            assert result == "Hello world"

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
