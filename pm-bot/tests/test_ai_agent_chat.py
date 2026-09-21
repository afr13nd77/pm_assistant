"""Unit-tests for POST /api/v1/ai-agent/chat endpoint.

Covers validation, model resolution, system prompt assembly,
response stripping, Langfuse tracing, and error handling.
"""

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def vault_dir(tmp_path):
    """Temporary vault directory with minimal structure."""
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    return tmp_path


@pytest.fixture
def prefs_file(vault_dir):
    """Path where user prefs JSON will live."""
    return vault_dir / ".pm-user-prefs.json"


@pytest.fixture
def client(vault_dir):
    """FastAPI TestClient with VAULT_PATH pointed at tmp dir."""
    with patch("shared.vault_paths.VAULT_PATH", vault_dir):
        from fastapi.testclient import TestClient

        from app.vault_api import app
        yield TestClient(app)


def _chat_payload(**overrides) -> dict:
    """Helper: build a valid request body with sensible defaults."""
    base = {
        "provider": "claude",
        "messages": [{"role": "user", "content": "Hello"}],
        "idea_id": "test-idea-1",
        "idea_body": "Test idea body",
    }
    base.update(overrides)
    return base


# Patch targets -- functions imported locally inside ai_agent_chat(),
# so they must be patched at the source module, not at app.vault_api.
_P_CALL = "shared.llm_client._call_provider"
_P_AVAIL = "shared.llm_client._is_provider_available"
_P_PREFS = "shared.llm_client._load_llm_prefs"
_P_LF = "shared.langfuse_client.get_langfuse"
# _load_business_context_file is imported (module-level, not local import)
# into app.routers.ai_agent from app.routers.user_prefs, so it must be
# patched where it is looked up: app.routers.ai_agent.
_P_CTX = "app.routers.ai_agent._load_business_context_file"


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------


class TestAiAgentChatSuccess:

    def test_ai_agent_chat_success(self, client):
        """Happy path: mock _call_provider returns valid content;
        response contains content, provider, model, elapsed_seconds."""
        with patch(_P_CALL, return_value=("AI response", {})) as mock_call, \
             patch(_P_AVAIL, return_value=True), \
             patch(_P_PREFS, return_value={}), \
             patch(_P_CTX, return_value="ctx"), \
             patch(_P_LF, return_value=None):
            resp = client.post("/api/v1/ai-agent/chat", json=_chat_payload())
        assert resp.status_code == 200
        data = resp.json()
        assert data["content"] == "AI response"
        assert data["provider"] == "claude"
        assert "model" in data
        assert isinstance(data["elapsed_seconds"], float)
        mock_call.assert_called_once()


# ---------------------------------------------------------------------------
# 2-6. Validation
# ---------------------------------------------------------------------------


class TestAiAgentChatValidation:

    def test_ai_agent_chat_invalid_provider(self, client):
        """provider='invalid' must return 422 with 'Invalid provider'."""
        resp = client.post(
            "/api/v1/ai-agent/chat",
            json=_chat_payload(provider="invalid"),
        )
        assert resp.status_code == 422
        assert "Invalid provider" in resp.json()["detail"]

    def test_ai_agent_chat_provider_unavailable(self, client):
        """Provider exists but is not available (no API key) -> 400."""
        with patch(_P_AVAIL, return_value=False), \
             patch(_P_PREFS, return_value={}):
            resp = client.post(
                "/api/v1/ai-agent/chat",
                json=_chat_payload(),
            )
        assert resp.status_code == 400
        assert "not available" in resp.json()["detail"]

    def test_ai_agent_chat_empty_messages(self, client):
        """messages=[] triggers pydantic min_length=1 validation -> 422."""
        resp = client.post(
            "/api/v1/ai-agent/chat",
            json=_chat_payload(messages=[]),
        )
        assert resp.status_code == 422

    def test_ai_agent_chat_invalid_message_format(self, client):
        """Message without 'role' key -> 422."""
        with patch(_P_AVAIL, return_value=True), \
             patch(_P_PREFS, return_value={}):
            resp = client.post(
                "/api/v1/ai-agent/chat",
                json=_chat_payload(messages=[{"content": "no role"}]),
            )
        assert resp.status_code == 422
        assert "missing role" in resp.json()["detail"]

    def test_ai_agent_chat_invalid_message_role(self, client):
        """role='system' is not allowed -> 422."""
        with patch(_P_AVAIL, return_value=True), \
             patch(_P_PREFS, return_value={}):
            resp = client.post(
                "/api/v1/ai-agent/chat",
                json=_chat_payload(messages=[{"role": "system", "content": "hi"}]),
            )
        assert resp.status_code == 422
        assert "invalid role" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 7. Size limit
# ---------------------------------------------------------------------------


class TestAiAgentChatSizeLimit:

    def test_ai_agent_chat_size_limit(self, client):
        """idea_body + messages > 100K chars -> 413."""
        big_body = "x" * 100_001
        with patch(_P_AVAIL, return_value=True), \
             patch(_P_PREFS, return_value={}):
            resp = client.post(
                "/api/v1/ai-agent/chat",
                json=_chat_payload(idea_body=big_body),
            )
        assert resp.status_code == 413
        assert "100K" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 8. Model resolution
# ---------------------------------------------------------------------------


class TestAiAgentChatModelResolve:

    def test_ai_agent_chat_model_resolve_claude(self, client):
        """When model is not set and provider=claude, model resolves to default."""
        with patch(_P_CALL, return_value=("ok", {})) as mock_call, \
             patch(_P_AVAIL, return_value=True), \
             patch(_P_PREFS, return_value={}), \
             patch(_P_CTX, return_value=""), \
             patch(_P_LF, return_value=None):
            resp = client.post(
                "/api/v1/ai-agent/chat",
                json=_chat_payload(model=None),
            )
        assert resp.status_code == 200
        # Verify _call_provider received the default claude model
        call_kwargs = mock_call.call_args
        step = call_kwargs.kwargs.get("step") or call_kwargs[0][0]
        if isinstance(step, dict):
            assert "claude" in step["model"]
        # Response must have model field populated
        assert resp.json()["model"] is not None
        assert resp.json()["model"] != ""


# ---------------------------------------------------------------------------
# 9. System prompt includes context
# ---------------------------------------------------------------------------


class TestAiAgentChatSystemPrompt:

    def test_ai_agent_chat_system_prompt_includes_context(self, client):
        """System prompt passed to _call_provider must include business context
        and idea_body."""
        with patch(_P_CALL, return_value=("ok", {})) as mock_call, \
             patch(_P_AVAIL, return_value=True), \
             patch(_P_PREFS, return_value={}), \
             patch(_P_CTX, return_value="TEST_CONTEXT"), \
             patch(_P_LF, return_value=None):
            resp = client.post(
                "/api/v1/ai-agent/chat",
                json=_chat_payload(idea_body="MY_IDEA_TEXT"),
            )
        assert resp.status_code == 200
        call_kwargs = mock_call.call_args
        system = call_kwargs.kwargs.get("system", "")
        assert "TEST_CONTEXT" in system
        assert "MY_IDEA_TEXT" in system


# ---------------------------------------------------------------------------
# 10. Strip <think> blocks
# ---------------------------------------------------------------------------


class TestAiAgentChatStripThink:

    def test_ai_agent_chat_strips_think(self, client):
        """Response must strip <think>...</think> reasoning blocks."""
        raw_content = "<think>reasoning here</think>Clean answer"
        with patch(_P_CALL, return_value=(raw_content, {})), \
             patch(_P_AVAIL, return_value=True), \
             patch(_P_PREFS, return_value={}), \
             patch(_P_CTX, return_value=""), \
             patch(_P_LF, return_value=None):
            resp = client.post(
                "/api/v1/ai-agent/chat",
                json=_chat_payload(),
            )
        assert resp.status_code == 200
        assert resp.json()["content"] == "Clean answer"


# ---------------------------------------------------------------------------
# 11. Langfuse trace
# ---------------------------------------------------------------------------


class TestAiAgentChatLangfuse:

    def test_ai_agent_chat_langfuse_trace(self, client):
        """When Langfuse is available, trace() and generation() must be called."""
        mock_trace = MagicMock()
        mock_lf = MagicMock()
        mock_lf.trace.return_value = mock_trace

        with patch(_P_CALL, return_value=("ok", {"input_tokens": 10, "output_tokens": 5})), \
             patch(_P_AVAIL, return_value=True), \
             patch(_P_PREFS, return_value={}), \
             patch(_P_CTX, return_value=""), \
             patch(_P_LF, return_value=mock_lf):
            resp = client.post(
                "/api/v1/ai-agent/chat",
                json=_chat_payload(),
            )
        assert resp.status_code == 200
        mock_lf.trace.assert_called_once()
        trace_kwargs = mock_lf.trace.call_args.kwargs
        assert trace_kwargs["name"] == "ai-agent-chat"
        mock_trace.generation.assert_called_once()


# ---------------------------------------------------------------------------
# 12. Provider error -> 502
# ---------------------------------------------------------------------------


class TestAiAgentChatProviderError:

    def test_ai_agent_chat_provider_error(self, client):
        """When _call_provider raises an exception, endpoint returns 502."""
        with patch(_P_CALL, side_effect=RuntimeError("LLM timeout")), \
             patch(_P_AVAIL, return_value=True), \
             patch(_P_PREFS, return_value={}), \
             patch(_P_CTX, return_value=""), \
             patch(_P_LF, return_value=None):
            resp = client.post(
                "/api/v1/ai-agent/chat",
                json=_chat_payload(),
            )
        assert resp.status_code == 502
        assert "LLM timeout" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 13-14. _load_business_context_file
# ---------------------------------------------------------------------------


class TestLoadBusinessContextFile:

    def test_load_business_context_file_exists(self, tmp_path):
        """When file exists with frontmatter, should return stripped content."""
        concepts_dir = tmp_path / "wiki" / "concepts"
        concepts_dir.mkdir(parents=True)
        context_file = concepts_dir / "business-context-brief.md"
        context_file.write_text(
            "---\ntitle: Context\ntags: [biz]\n---\nThis is the real content.\n",
            encoding="utf-8",
        )
        with patch.dict("os.environ", {"VAULT_PATH": str(tmp_path)}):
            from app.routers.user_prefs import _load_business_context_file
            result = _load_business_context_file()
        assert result == "This is the real content."

    def test_load_business_context_file_missing(self, tmp_path):
        """When file does not exist, should return empty string."""
        with patch.dict("os.environ", {"VAULT_PATH": str(tmp_path)}):
            from app.routers.user_prefs import _load_business_context_file
            result = _load_business_context_file()
        assert result == ""


# ---------------------------------------------------------------------------
# 15. User prefs ai_agent defaults
# ---------------------------------------------------------------------------


class TestUserPrefsAiAgentDefaults:

    def test_user_prefs_ai_agent_defaults(self, client):
        """GET /api/v1/user-prefs must include ai_agent_provider='claude'
        and ai_agent_model='' when no prefs file exists."""
        resp = client.get("/api/v1/user-prefs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ai_agent_provider"] == "claude"
        assert data["ai_agent_model"] == ""
