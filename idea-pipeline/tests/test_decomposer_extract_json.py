"""Tests for DecomposerAgent._extract_json and its integration with run()."""

import json
import logging
from unittest.mock import MagicMock, patch

import pytest
from idea_pipeline.agents.decomposer import DecomposerAgent
from idea_pipeline.config import AgentConfig


@pytest.fixture
def agent():
    """Create a DecomposerAgent with mocked dependencies."""
    config = AgentConfig(
        name="decomposer",
        model="test-model",
        max_tokens=4096,
        timeout_seconds=60,
        prompt_file="prompts/decomposer.md",
    )
    client = MagicMock()
    with patch.object(DecomposerAgent, "_load_prompt", return_value="system prompt"):
        return DecomposerAgent(config, client)


class TestExtractJson:
    """Unit tests for _extract_json helper."""

    def test_plain_json_unchanged(self, agent):
        text = '{"tasks": []}'
        assert agent._extract_json(text) == '{"tasks": []}'

    def test_strips_whitespace(self, agent):
        text = '  \n{"tasks": []}\n  '
        assert agent._extract_json(text) == '{"tasks": []}'

    def test_strips_json_code_fence(self, agent):
        text = '```json\n{"tasks": [{"id": 1}]}\n```'
        result = agent._extract_json(text)
        assert result == '{"tasks": [{"id": 1}]}'
        # Verify it's valid JSON
        parsed = json.loads(result)
        assert parsed["tasks"][0]["id"] == 1

    def test_strips_code_fence_no_language_tag(self, agent):
        text = '```\n{"tasks": []}\n```'
        result = agent._extract_json(text)
        assert result == '{"tasks": []}'

    def test_strips_code_fence_with_whitespace_around(self, agent):
        text = '  \n```json\n{"key": "value"}\n```\n  '
        result = agent._extract_json(text)
        assert result == '{"key": "value"}'

    def test_multiline_json_in_code_fence(self, agent):
        text = '```json\n{\n  "tasks": [\n    {"id": 1},\n    {"id": 2}\n  ]\n}\n```'
        result = agent._extract_json(text)
        parsed = json.loads(result)
        assert len(parsed["tasks"]) == 2

    def test_no_false_positive_on_json_with_backticks_inside(self, agent):
        # JSON that contains backticks but is NOT wrapped in a code fence
        text = '{"description": "use ```code``` here"}'
        result = agent._extract_json(text)
        # Should remain unchanged since it doesn't match the fence pattern
        assert result == text

    def test_logs_when_stripping_fences(self, agent, caplog):
        text = '```json\n{"tasks": []}\n```'
        with caplog.at_level(logging.INFO):
            agent._extract_json(text)
        assert "stripped markdown code fences" in caplog.text


class TestRunWithFencedOutput:
    """Integration tests: run() handles fenced JSON from the model."""

    def test_run_parses_fenced_json_first_attempt(self, agent):
        valid_json = '{"tasks": [{"story_points": 3}, {"story_points": 5}]}'
        fenced = f"```json\n{valid_json}\n```"

        # BaseAgent.run returns the fenced output
        with patch(
            "idea_pipeline.agents.base.BaseAgent.run", return_value=fenced
        ):
            result = agent.run("some input")

        # The returned value should be the cleaned JSON (fences stripped)
        parsed = json.loads(result)
        assert len(parsed["tasks"]) == 2

    def test_run_parses_fenced_json_on_retry(self, agent):
        invalid_output = "Here is the result: {broken"
        valid_json = '{"tasks": [{"story_points": 2}]}'
        fenced_retry = f"```json\n{valid_json}\n```"

        with patch(
            "idea_pipeline.agents.base.BaseAgent.run", return_value=invalid_output
        ):
            agent.client.call.return_value = fenced_retry
            result = agent.run("some input")

        parsed = json.loads(result)
        assert len(parsed["tasks"]) == 1

    def test_run_still_fails_on_truly_invalid_json(self, agent):
        invalid_output = "not json at all"

        with patch(
            "idea_pipeline.agents.base.BaseAgent.run", return_value=invalid_output
        ):
            agent.client.call.return_value = "still not json"
            with pytest.raises(ValueError, match="failed to produce valid JSON"):
                agent.run("some input")
