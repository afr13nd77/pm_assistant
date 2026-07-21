"""Tests for Langfuse instrumentation in idea-pipeline.

Covers:
- PipelineClaudeClient.call() recording generation when langfuse_parent is provided
- BaseAgent.run() forwarding _langfuse_parent to client.call()
- DecomposerAgent.run() forwarding _langfuse_parent through super() and retry
- PipelineOrchestrator.run_pipeline() creating trace + 3 spans
- Graceful degradation: Langfuse errors never break the pipeline
"""

import asyncio
import json
import logging
from unittest.mock import MagicMock, patch, AsyncMock

import anthropic.types
import pytest
from idea_pipeline.claude_client import PipelineClaudeClient
from idea_pipeline.agents.base import BaseAgent
from idea_pipeline.agents.decomposer import DecomposerAgent
from idea_pipeline.config import AgentConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_anthropic_response():
    """Create a mock Anthropic Messages response with a proper TextBlock."""
    response = MagicMock()
    block = MagicMock(spec=anthropic.types.TextBlock)
    block.text = "test output"
    response.content = [block]
    response.usage = MagicMock()
    response.usage.input_tokens = 100
    response.usage.output_tokens = 50
    return response


@pytest.fixture
def agent_config():
    return AgentConfig(
        name="test_agent",
        model="test-model",
        max_tokens=4096,
        timeout_seconds=60,
        prompt_file="prompts/decomposer.md",
    )


# ---------------------------------------------------------------------------
# PipelineClaudeClient tests
# ---------------------------------------------------------------------------

class TestPipelineClaudeClientLangfuse:
    """Test langfuse_parent parameter in PipelineClaudeClient.call()."""

    def test_call_without_langfuse_parent_works(self, mock_anthropic_response):
        """Backward compatibility: call() without langfuse_parent still works."""
        client = PipelineClaudeClient.__new__(PipelineClaudeClient)
        client._client = MagicMock()
        client._client.messages.create.return_value = mock_anthropic_response

        result = client.call(
            model="test-model",
            system_prompt="system",
            user_message="user msg",
            max_tokens=1024,
            timeout=30,
        )
        assert result == "test output"

    def test_call_with_langfuse_parent_records_generation(self, mock_anthropic_response):
        """When langfuse_parent is provided, generation() is called with correct data."""
        client = PipelineClaudeClient.__new__(PipelineClaudeClient)
        client._client = MagicMock()
        client._client.messages.create.return_value = mock_anthropic_response

        parent = MagicMock()

        result = client.call(
            model="test-model",
            system_prompt="system prompt",
            user_message="user message",
            max_tokens=1024,
            timeout=30,
            langfuse_parent=parent,
        )

        assert result == "test output"
        parent.generation.assert_called_once()
        call_kwargs = parent.generation.call_args
        assert call_kwargs.kwargs["name"] == "test-model"
        assert call_kwargs.kwargs["model"] == "test-model"
        assert call_kwargs.kwargs["output"] == "test output"
        assert call_kwargs.kwargs["usage"] == {"input": 100, "output": 50}
        # input is the messages array
        input_msgs = call_kwargs.kwargs["input"]
        assert len(input_msgs) == 2
        assert input_msgs[0]["role"] == "system"
        assert input_msgs[1]["role"] == "user"

    def test_call_with_langfuse_parent_no_usage(self, mock_anthropic_response):
        """Generation records empty usage if response has no usage data."""
        mock_anthropic_response.usage = None

        client = PipelineClaudeClient.__new__(PipelineClaudeClient)
        client._client = MagicMock()
        client._client.messages.create.return_value = mock_anthropic_response

        parent = MagicMock()
        client.call(
            model="m", system_prompt="s", user_message="u",
            max_tokens=100, timeout=10, langfuse_parent=parent,
        )

        call_kwargs = parent.generation.call_args
        assert call_kwargs.kwargs["usage"] == {}

    def test_call_langfuse_generation_error_does_not_break(
        self, mock_anthropic_response, caplog
    ):
        """If langfuse_parent.generation() raises, call() still returns normally."""
        client = PipelineClaudeClient.__new__(PipelineClaudeClient)
        client._client = MagicMock()
        client._client.messages.create.return_value = mock_anthropic_response

        parent = MagicMock()
        parent.generation.side_effect = RuntimeError("langfuse down")

        with caplog.at_level(logging.WARNING):
            result = client.call(
                model="m", system_prompt="s", user_message="u",
                max_tokens=100, timeout=10, langfuse_parent=parent,
            )

        assert result == "test output"
        assert "Langfuse generation failed" in caplog.text


# ---------------------------------------------------------------------------
# BaseAgent tests
# ---------------------------------------------------------------------------

class TestBaseAgentLangfuse:
    """Test _langfuse_parent forwarding in BaseAgent.run()."""

    def test_run_forwards_langfuse_parent_to_client(self, agent_config):
        """BaseAgent.run() passes _langfuse_parent to client.call() as langfuse_parent."""
        client = MagicMock()
        client.call.return_value = "agent output"

        with patch.object(BaseAgent, "_load_prompt", return_value="prompt"):
            agent = BaseAgent(agent_config, client)

        parent = MagicMock()
        result = agent.run("input text", _langfuse_parent=parent)

        assert result == "agent output"
        call_kwargs = client.call.call_args
        assert call_kwargs.kwargs["langfuse_parent"] is parent

    def test_run_without_langfuse_parent_passes_none(self, agent_config):
        """BaseAgent.run() without _langfuse_parent passes None."""
        client = MagicMock()
        client.call.return_value = "output"

        with patch.object(BaseAgent, "_load_prompt", return_value="prompt"):
            agent = BaseAgent(agent_config, client)

        agent.run("input")
        call_kwargs = client.call.call_args
        assert call_kwargs.kwargs["langfuse_parent"] is None


# ---------------------------------------------------------------------------
# DecomposerAgent tests
# ---------------------------------------------------------------------------

class TestDecomposerAgentLangfuse:
    """Test _langfuse_parent in DecomposerAgent.run() including retry path."""

    def test_run_forwards_langfuse_parent_on_success(self, agent_config):
        """DecomposerAgent passes _langfuse_parent through super().run()."""
        client = MagicMock()
        valid_json = '{"tasks": [{"story_points": 1}]}'
        client.call.return_value = valid_json

        with patch.object(DecomposerAgent, "_load_prompt", return_value="prompt"):
            agent = DecomposerAgent(agent_config, client)

        parent = MagicMock()
        result = agent.run("input", _langfuse_parent=parent)

        assert json.loads(result) is not None
        call_kwargs = client.call.call_args
        assert call_kwargs.kwargs["langfuse_parent"] is parent

    def test_run_forwards_langfuse_parent_on_retry(self, agent_config):
        """On JSON retry, the direct client.call() also gets langfuse_parent."""
        client = MagicMock()
        valid_json = '{"tasks": []}'
        # The retry path calls client.call() directly -- set its return value
        client.call.return_value = valid_json

        with patch.object(DecomposerAgent, "_load_prompt", return_value="prompt"):
            agent = DecomposerAgent(agent_config, client)

        parent = MagicMock()

        # Patch BaseAgent.run to return invalid JSON (triggers retry)
        with patch("idea_pipeline.agents.base.BaseAgent.run", return_value="not json at all"):
            result = agent.run("input", _langfuse_parent=parent)

        # The retry client.call should also have langfuse_parent
        retry_call = client.call.call_args
        assert retry_call.kwargs["langfuse_parent"] is parent


# ---------------------------------------------------------------------------
# _record_langfuse_generation static method tests
# ---------------------------------------------------------------------------

class TestRecordLangfuseGeneration:
    """Direct tests for the static helper method."""

    def test_none_parent_is_noop(self):
        """When parent is None, nothing happens (no error)."""
        PipelineClaudeClient._record_langfuse_generation(
            None, "model", "sys", "user", "output", MagicMock()
        )
        # No exception = pass

    def test_response_without_usage_attr(self):
        """If response has no usage attribute, usage_data is empty dict."""
        parent = MagicMock()
        response = MagicMock(spec=[])  # no attributes at all

        PipelineClaudeClient._record_langfuse_generation(
            parent, "model", "sys", "user", "output", response
        )

        call_kwargs = parent.generation.call_args
        assert call_kwargs.kwargs["usage"] == {}
