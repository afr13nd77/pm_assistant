"""Prompt registry — metadata for all pm-bot prompts."""

import logging

logger = logging.getLogger(__name__)

PROMPT_REGISTRY: dict[str, dict] = {
    "idea": {"description": "Обработка идей из Telegram", "variables": []},
    "meeting": {"description": "Обработка транскриптов встреч", "variables": []},
    "daily": {"description": "Обработка daily-заметок", "variables": []},
    "jira_ticket": {"description": "Генерация Jira-черновиков", "variables": []},
    "weekly_report": {"description": "Еженедельный отчёт", "variables": []},
}

logger.info("prompt_registry loaded: %d entries", len(PROMPT_REGISTRY))
