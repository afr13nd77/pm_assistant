"""Tests for prompt reload mechanism in BaseAgent and PipelineOrchestrator."""

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from idea_pipeline.agents.base import BaseAgent
from idea_pipeline.config import AgentConfig


def _make_config(prompt_file: str = "prompts/test.txt") -> AgentConfig:
    return AgentConfig(
        name="test",
        model="test-model",
        max_tokens=100,
        timeout_seconds=10,
        prompt_file=prompt_file,
    )


# ── BaseAgent.reload_prompt ─────────────────────────────────────────


class TestReloadPrompt:
    """Unit tests for BaseAgent.reload_prompt()."""

    def test_reload_prompt_updates_content(self, tmp_path: Path) -> None:
        """After editing the prompt file, reload_prompt picks up the new content."""
        prompt_file = tmp_path / "prompts" / "test.txt"
        prompt_file.parent.mkdir(parents=True)
        prompt_file.write_text("original content", encoding="utf-8")

        config = _make_config("prompts/test.txt")

        # Patch _load_prompt to read from tmp_path instead of the real app/ directory.
        def _fake_load(self_agent: BaseAgent) -> str:
            path = tmp_path / self_agent.config.prompt_file
            text = path.read_text(encoding="utf-8")
            return text

        with patch.object(BaseAgent, "_load_prompt", _fake_load):
            agent = BaseAgent(config)
            assert agent.prompt == "original content"

            # Modify the file on disk
            prompt_file.write_text("updated content", encoding="utf-8")

            agent.reload_prompt()
            assert agent.prompt == "updated content"

    def test_reload_prompt_preserves_config(self, tmp_path: Path) -> None:
        """reload_prompt does not change the agent config."""
        prompt_file = tmp_path / "prompts" / "test.txt"
        prompt_file.parent.mkdir(parents=True)
        prompt_file.write_text("content v1", encoding="utf-8")

        config = _make_config("prompts/test.txt")

        def _fake_load(self_agent: BaseAgent) -> str:
            return (tmp_path / self_agent.config.prompt_file).read_text(encoding="utf-8")

        with patch.object(BaseAgent, "_load_prompt", _fake_load):
            agent = BaseAgent(config)
            original_config = agent.config

            prompt_file.write_text("content v2", encoding="utf-8")
            agent.reload_prompt()

            assert agent.config is original_config
            assert agent.config.name == "test"

    def test_reload_prompt_logs_old_and_new_length(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """reload_prompt logs the old and new prompt lengths."""
        prompt_file = tmp_path / "prompts" / "test.txt"
        prompt_file.parent.mkdir(parents=True)
        prompt_file.write_text("short", encoding="utf-8")

        config = _make_config("prompts/test.txt")

        def _fake_load(self_agent: BaseAgent) -> str:
            return (tmp_path / self_agent.config.prompt_file).read_text(encoding="utf-8")

        with patch.object(BaseAgent, "_load_prompt", _fake_load):
            agent = BaseAgent(config)

            prompt_file.write_text("a much longer prompt text here", encoding="utf-8")

            with caplog.at_level(logging.INFO, logger="idea_pipeline.agents.base"):
                agent.reload_prompt()

            assert "old_len=5" in caplog.text
            assert "new_len=30" in caplog.text
            assert "reloaded" in caplog.text

    def test_reload_prompt_file_not_found_raises(self) -> None:
        """reload_prompt raises FileNotFoundError when the prompt file is missing."""
        config = _make_config("prompts/nonexistent.txt")

        with patch.object(BaseAgent, "_load_prompt", return_value="initial"):
            agent = BaseAgent(config)

        # Now call reload_prompt without the mock -- _load_prompt will try the real path
        # which does not exist.
        with pytest.raises(FileNotFoundError):
            agent.reload_prompt()


# ── PipelineOrchestrator.reload_agents ──────────────────────────────


class TestReloadAgents:
    """Tests for PipelineOrchestrator.reload_agents()."""

    def test_reload_agents_calls_all_agents(self) -> None:
        """reload_agents calls reload_prompt on all three agents and returns their names."""
        from idea_pipeline.orchestrator import PipelineOrchestrator

        mock_analyst = MagicMock()
        mock_pm = MagicMock()
        mock_decomposer = MagicMock()

        # Use a MagicMock as the orchestrator instance, but call the real method
        orchestrator = MagicMock(spec=PipelineOrchestrator)
        orchestrator.analyst = mock_analyst
        orchestrator.pm_agent = mock_pm
        orchestrator.decomposer = mock_decomposer

        result = PipelineOrchestrator.reload_agents(orchestrator)

        assert result == ["analyst", "pm", "decomposer"]
        mock_analyst.reload_prompt.assert_called_once()
        mock_pm.reload_prompt.assert_called_once()
        mock_decomposer.reload_prompt.assert_called_once()

    def test_reload_agents_returns_list_of_three(self) -> None:
        """reload_agents always returns exactly 3 agent names."""
        from idea_pipeline.orchestrator import PipelineOrchestrator

        orchestrator = MagicMock(spec=PipelineOrchestrator)
        orchestrator.analyst = MagicMock()
        orchestrator.pm_agent = MagicMock()
        orchestrator.decomposer = MagicMock()

        result = PipelineOrchestrator.reload_agents(orchestrator)

        assert len(result) == 3
        assert isinstance(result, list)

    def test_reload_agents_propagates_error(self) -> None:
        """If an agent's reload_prompt raises, reload_agents propagates the error."""
        from idea_pipeline.orchestrator import PipelineOrchestrator

        orchestrator = MagicMock(spec=PipelineOrchestrator)
        orchestrator.analyst = MagicMock()
        orchestrator.analyst.reload_prompt.side_effect = FileNotFoundError("missing prompt")
        orchestrator.pm_agent = MagicMock()
        orchestrator.decomposer = MagicMock()

        with pytest.raises(FileNotFoundError, match="missing prompt"):
            PipelineOrchestrator.reload_agents(orchestrator)

        # pm and decomposer should NOT have been called because analyst failed first
        orchestrator.pm_agent.reload_prompt.assert_not_called()
        orchestrator.decomposer.reload_prompt.assert_not_called()

    def test_reload_agents_order(self) -> None:
        """reload_agents processes agents in order: analyst, pm, decomposer."""
        from idea_pipeline.orchestrator import PipelineOrchestrator

        call_order: list[str] = []

        orchestrator = MagicMock(spec=PipelineOrchestrator)

        for attr_name, label in [("analyst", "analyst"), ("pm_agent", "pm"), ("decomposer", "decomposer")]:
            mock = MagicMock()
            mock.reload_prompt.side_effect = lambda lbl=label: call_order.append(lbl)
            setattr(orchestrator, attr_name, mock)

        PipelineOrchestrator.reload_agents(orchestrator)

        assert call_order == ["analyst", "pm", "decomposer"]
