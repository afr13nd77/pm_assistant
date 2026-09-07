"""Unit tests for pipeline_client.py (BL-197, T-21).

Tests:
  get_prompts     -- GET /api/v1/prompts
  save_prompt     -- POST /api/v1/prompts/{name}
  reset_prompt    -- POST /api/v1/prompts/{name}/reset
  run_pipeline    -- POST /pipeline/run
  get_status      -- GET /pipeline/{pipeline_id}
  resume_pipeline -- POST /pipeline/{pipeline_id}/resume
  list_pipelines  -- GET /pipeline/
  error handling  -- ConnectionError, Timeout propagation
"""

from unittest.mock import MagicMock, patch

import pytest
import requests

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _mock_settings():
    """Mock shared.settings.get to return a default timeout."""
    with patch("app.pipeline_client.get_setting", return_value=30):
        yield


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch):
    """Ensure stable env vars for all tests."""
    monkeypatch.setenv("PIPELINE_API_URL", "http://test-pipeline:8100")
    monkeypatch.setenv("PIPELINE_API_KEY", "test-key-123")
    # Reload module-level constants after env change
    import app.pipeline_client as mod
    monkeypatch.setattr(mod, "PIPELINE_API_URL", "http://test-pipeline:8100")
    monkeypatch.setattr(mod, "PIPELINE_API_KEY", "test-key-123")


def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    """Build a mock requests.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


# ---------------------------------------------------------------------------
# get_prompts
# ---------------------------------------------------------------------------

class TestGetPrompts:

    @patch("app.pipeline_client.requests.get")
    def test_get_prompts_success(self, mock_get):
        """Should return prompts dict from Pipeline API."""
        from app.pipeline_client import get_prompts

        expected = {"prompts": [
            {"name": "analyst", "content": "Analyze the idea"},
            {"name": "designer", "content": "Design the solution"},
        ]}
        mock_get.return_value = _mock_response(expected)

        result = get_prompts()

        assert result == expected
        assert len(result["prompts"]) == 2
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args
        assert "/api/v1/prompts" in call_kwargs[1].get("url", "") or \
               "/api/v1/prompts" in str(call_kwargs)

    @patch("app.pipeline_client.requests.get")
    def test_get_prompts_sends_headers(self, mock_get):
        """Should include API key and Content-Type headers."""
        from app.pipeline_client import get_prompts

        mock_get.return_value = _mock_response({"prompts": []})

        get_prompts()

        call_kwargs = mock_get.call_args
        headers = call_kwargs[1]["headers"] if "headers" in call_kwargs[1] else call_kwargs.kwargs["headers"]
        assert headers["Content-Type"] == "application/json"
        assert headers["X-Pipeline-Key"] == "test-key-123"


# ---------------------------------------------------------------------------
# save_prompt
# ---------------------------------------------------------------------------

class TestSavePrompt:

    @patch("app.pipeline_client.requests.post")
    def test_save_prompt_success(self, mock_post):
        """Should POST prompt content and return response."""
        from app.pipeline_client import save_prompt

        expected = {"status": "ok", "name": "analyst"}
        mock_post.return_value = _mock_response(expected)

        result = save_prompt("analyst", "New prompt content")

        assert result == expected
        assert result["status"] == "ok"
        assert result["name"] == "analyst"
        mock_post.assert_called_once()

        call_kwargs = mock_post.call_args
        assert "/api/v1/prompts/analyst" in str(call_kwargs)
        json_body = call_kwargs[1].get("json", call_kwargs.kwargs.get("json"))
        assert json_body == {"content": "New prompt content"}

    @patch("app.pipeline_client.requests.post")
    def test_save_prompt_sends_headers(self, mock_post):
        """Should include API key header."""
        from app.pipeline_client import save_prompt

        mock_post.return_value = _mock_response({"status": "ok", "name": "test"})

        save_prompt("test", "content")

        call_kwargs = mock_post.call_args
        headers = call_kwargs[1]["headers"] if "headers" in call_kwargs[1] else call_kwargs.kwargs["headers"]
        assert headers["X-Pipeline-Key"] == "test-key-123"


# ---------------------------------------------------------------------------
# reset_prompt
# ---------------------------------------------------------------------------

class TestResetPrompt:

    @patch("app.pipeline_client.requests.post")
    def test_reset_prompt_success(self, mock_post):
        """Should POST to reset endpoint and return response."""
        from app.pipeline_client import reset_prompt

        expected = {"status": "ok", "name": "analyst", "content": "default content"}
        mock_post.return_value = _mock_response(expected)

        result = reset_prompt("analyst")

        assert result == expected
        assert result["status"] == "ok"
        mock_post.assert_called_once()

        call_kwargs = mock_post.call_args
        assert "/api/v1/prompts/analyst/reset" in str(call_kwargs)


# ---------------------------------------------------------------------------
# run_pipeline
# ---------------------------------------------------------------------------

class TestRunPipeline:

    @patch("app.pipeline_client.requests.post")
    def test_run_pipeline_with_text(self, mock_post):
        """Should send text in payload."""
        from app.pipeline_client import run_pipeline

        expected = {"status": "running", "pipeline_id": "abc-123"}
        mock_post.return_value = _mock_response(expected)

        result = run_pipeline(text="My idea", start_from="analyst")

        assert result == expected
        call_kwargs = mock_post.call_args
        json_body = call_kwargs[1].get("json", call_kwargs.kwargs.get("json"))
        assert json_body["text"] == "My idea"
        assert json_body["start_from"] == "analyst"

    @patch("app.pipeline_client.requests.post")
    def test_run_pipeline_with_file(self, mock_post):
        """Should send file_path in payload."""
        from app.pipeline_client import run_pipeline

        mock_post.return_value = _mock_response({"status": "running", "pipeline_id": "def-456"})

        run_pipeline(file_path="/vault/ideas/test.md", start_from="designer")

        call_kwargs = mock_post.call_args
        json_body = call_kwargs[1].get("json", call_kwargs.kwargs.get("json"))
        assert json_body["file_path"] == "/vault/ideas/test.md"
        assert json_body["start_from"] == "designer"
        assert "text" not in json_body

    @patch("app.pipeline_client.requests.post")
    def test_run_pipeline_with_notify(self, mock_post):
        """Should include notify_chat_id when provided."""
        from app.pipeline_client import run_pipeline

        mock_post.return_value = _mock_response({"status": "running", "pipeline_id": "ghi-789"})

        run_pipeline(text="idea", notify_chat_id="12345")

        call_kwargs = mock_post.call_args
        json_body = call_kwargs[1].get("json", call_kwargs.kwargs.get("json"))
        assert json_body["notify_chat_id"] == "12345"


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------

class TestGetStatus:

    @patch("app.pipeline_client.requests.get")
    def test_get_status_success(self, mock_get):
        """Should GET pipeline status by ID."""
        from app.pipeline_client import get_status

        expected = {
            "status": "completed",
            "pipeline_id": "abc-123",
            "stages": {"analyst": "done", "designer": "done"},
        }
        mock_get.return_value = _mock_response(expected)

        result = get_status("abc-123")

        assert result == expected
        assert result["status"] == "completed"
        call_kwargs = mock_get.call_args
        assert "/pipeline/abc-123" in str(call_kwargs)


# ---------------------------------------------------------------------------
# resume_pipeline
# ---------------------------------------------------------------------------

class TestResumePipeline:

    @patch("app.pipeline_client.requests.post")
    def test_resume_pipeline_success(self, mock_post):
        """Should POST resume with start_from stage."""
        from app.pipeline_client import resume_pipeline

        expected = {"status": "running", "pipeline_id": "abc-123"}
        mock_post.return_value = _mock_response(expected)

        result = resume_pipeline("abc-123", "designer")

        assert result == expected
        call_kwargs = mock_post.call_args
        assert "/pipeline/abc-123/resume" in str(call_kwargs)
        json_body = call_kwargs[1].get("json", call_kwargs.kwargs.get("json"))
        assert json_body == {"start_from": "designer"}


# ---------------------------------------------------------------------------
# list_pipelines
# ---------------------------------------------------------------------------

class TestListPipelines:

    @patch("app.pipeline_client.requests.get")
    def test_list_pipelines_default(self, mock_get):
        """Should GET pipeline list with default params."""
        from app.pipeline_client import list_pipelines

        expected = {"pipelines": [], "total": 0}
        mock_get.return_value = _mock_response(expected)

        result = list_pipelines()

        assert result == expected
        call_kwargs = mock_get.call_args
        params = call_kwargs[1].get("params", call_kwargs.kwargs.get("params"))
        assert params["limit"] == 20
        assert "status" not in params

    @patch("app.pipeline_client.requests.get")
    def test_list_pipelines_with_filter(self, mock_get):
        """Should pass status filter in params."""
        from app.pipeline_client import list_pipelines

        mock_get.return_value = _mock_response({"pipelines": [], "total": 0})

        list_pipelines(limit=5, status="completed")

        call_kwargs = mock_get.call_args
        params = call_kwargs[1].get("params", call_kwargs.kwargs.get("params"))
        assert params["limit"] == 5
        assert params["status"] == "completed"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:

    @patch("app.pipeline_client.requests.get")
    def test_connection_error_propagates(self, mock_get):
        """ConnectionError should propagate to caller."""
        from app.pipeline_client import get_prompts

        mock_get.side_effect = requests.exceptions.ConnectionError("Connection refused")

        with pytest.raises(requests.exceptions.ConnectionError, match="Connection refused"):
            get_prompts()

    @patch("app.pipeline_client.requests.get")
    def test_timeout_propagates(self, mock_get):
        """Timeout should propagate to caller."""
        from app.pipeline_client import get_prompts

        mock_get.side_effect = requests.exceptions.Timeout("Request timed out")

        with pytest.raises(requests.exceptions.Timeout, match="Request timed out"):
            get_prompts()

    @patch("app.pipeline_client.requests.post")
    def test_connection_error_on_post(self, mock_post):
        """ConnectionError on POST should propagate."""
        from app.pipeline_client import save_prompt

        mock_post.side_effect = requests.exceptions.ConnectionError("Pipeline down")

        with pytest.raises(requests.exceptions.ConnectionError, match="Pipeline down"):
            save_prompt("analyst", "content")

    @patch("app.pipeline_client.requests.post")
    def test_timeout_on_post(self, mock_post):
        """Timeout on POST should propagate."""
        from app.pipeline_client import run_pipeline

        mock_post.side_effect = requests.exceptions.Timeout("Slow response")

        with pytest.raises(requests.exceptions.Timeout, match="Slow response"):
            run_pipeline(text="idea")

    @patch("app.pipeline_client.requests.get")
    def test_http_error_propagates(self, mock_get):
        """HTTPError from raise_for_status should propagate."""
        from app.pipeline_client import get_status

        resp = MagicMock()
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError("500 Server Error")
        mock_get.return_value = resp

        with pytest.raises(requests.exceptions.HTTPError, match="500 Server Error"):
            get_status("bad-id")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

class TestHelpers:

    def test_headers_with_api_key(self):
        """_headers should include API key when set."""
        from app.pipeline_client import _headers

        headers = _headers()
        assert headers["Content-Type"] == "application/json"
        assert headers["X-Pipeline-Key"] == "test-key-123"

    def test_headers_without_api_key(self, monkeypatch):
        """_headers should omit API key when empty."""
        import app.pipeline_client as mod
        monkeypatch.setattr(mod, "PIPELINE_API_KEY", "")

        headers = mod._headers()
        assert headers["Content-Type"] == "application/json"
        assert "X-Pipeline-Key" not in headers

    def test_get_timeout_uses_settings(self):
        """_get_timeout should call get_setting with correct key."""
        with patch("app.pipeline_client.get_setting", return_value=45) as mock_setting:
            from app.pipeline_client import _get_timeout

            result = _get_timeout("pipeline_run")
            assert result == 45
            mock_setting.assert_called()
