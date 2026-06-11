import logging
from pathlib import Path

from idea_pipeline.config import AgentConfig
from idea_pipeline.claude_client import PipelineClaudeClient

logger = logging.getLogger(__name__)


class BaseAgent:
    def __init__(self, config: AgentConfig, claude_client: PipelineClaudeClient) -> None:
        self.config = config
        self.client = claude_client
        self.prompt = self._load_prompt()

    def _load_prompt(self) -> str:
        prompt_path = Path(__file__).parent.parent / self.config.prompt_file
        prompt_text = prompt_path.read_text(encoding="utf-8")
        logger.info(
            "Agent %s: prompt loaded from %s, length=%d chars",
            self.config.name,
            prompt_path,
            len(prompt_text),
        )
        return prompt_text

    def run(self, input_text: str, context: dict | None = None) -> str:
        logger.info(
            "Agent %s: run started, input_len=%d, has_context=%s",
            self.config.name,
            len(input_text),
            context is not None,
        )
        user_message = self._build_user_message(input_text, context)
        output = self.client.call(
            model=self.config.model,
            system_prompt=self.prompt,
            user_message=user_message,
            max_tokens=self.config.max_tokens,
            timeout=self.config.timeout_seconds,
        )
        logger.info(
            "Agent %s: run finished, output_len=%d",
            self.config.name,
            len(output),
        )
        return output

    def _build_user_message(self, input_text: str, context: dict | None = None) -> str:
        return input_text
