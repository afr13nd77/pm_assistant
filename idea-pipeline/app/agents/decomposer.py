import json
import logging
import re

from idea_pipeline.agents.base import BaseAgent

from shared import llm_client

logger = logging.getLogger(__name__)


class DecomposerAgent(BaseAgent):
    def _extract_json(self, text: str) -> str:
        """Strip markdown code fences that Claude sometimes wraps around JSON."""
        cleaned = text.strip()
        # Match opening fence: ``` with optional language tag (e.g. ```json)
        pattern = r"^```(?:\w+)?\s*\n?(.*?)```\s*$"
        match = re.match(pattern, cleaned, re.DOTALL)
        if match:
            logger.info(
                "Agent %s: stripped markdown code fences from model output",
                self.config.name,
            )
            cleaned = match.group(1).strip()
        return cleaned

    def run(self, input_text: str, context: dict | None = None) -> str:
        raw_output = super().run(input_text, context)
        raw_output = self._extract_json(raw_output)

        try:
            parsed = json.loads(raw_output)
            tasks = parsed.get("tasks", [])
            total_sp = sum(t.get("story_points", 0) for t in tasks)
            logger.info(
                "Agent %s: valid JSON, tasks=%d, total_story_points=%d",
                self.config.name,
                len(tasks),
                total_sp,
            )
            return raw_output
        except json.JSONDecodeError as first_error:
            logger.warning(
                "Agent %s: invalid JSON from first attempt, retrying with hint: %s",
                self.config.name,
                str(first_error)[:200],
            )

        hint = "\n\nВАЖНО: твой предыдущий ответ не был валидным JSON. Верни СТРОГО валидный JSON. Первый символ — {, последний — }. Никакого текста до или после JSON."
        retry_message = self._build_user_message(input_text, context) + hint

        operation = f"pipeline_{self.config.name}"
        retry_output = llm_client.call(
            operation=operation,
            messages=[{"role": "user", "content": retry_message}],
            max_tokens=self.config.max_tokens,
            system=self.prompt,
            timeout=self.config.timeout_seconds,
        )
        retry_output = self._extract_json(retry_output)

        try:
            parsed = json.loads(retry_output)
            tasks = parsed.get("tasks", [])
            total_sp = sum(t.get("story_points", 0) for t in tasks)
            logger.info(
                "Agent %s: valid JSON on retry, tasks=%d, total_story_points=%d",
                self.config.name,
                len(tasks),
                total_sp,
            )
            return retry_output
        except json.JSONDecodeError as retry_error:
            logger.error(
                "Agent %s: invalid JSON on retry: %s",
                self.config.name,
                str(retry_error)[:200],
            )
            raise ValueError(
                f"Decomposer failed to produce valid JSON after 2 attempts: {retry_error}"
            ) from retry_error
