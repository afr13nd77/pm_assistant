import logging

from idea_pipeline.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class AnalystAgent(BaseAgent):
    def _build_user_message(self, input_text: str, context: dict | None = None) -> str:
        vault_entries = (context or {}).get("vault_entries", [])
        logger.info(
            "AnalystAgent._build_user_message: vault_entries_count=%d",
            len(vault_entries),
        )
        if not vault_entries:
            return input_text
        lines = [input_text, "", "---", "", "Контекст из vault:"]
        for entry in vault_entries:
            lines.append(
                f"- **{entry['title']}** ({entry['path']}): {entry['snippet']}"
            )
        return "\n".join(lines)
