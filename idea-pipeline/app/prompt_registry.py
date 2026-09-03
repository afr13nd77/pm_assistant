"""Prompt registry — metadata for all pipeline prompts."""

import logging

logger = logging.getLogger(__name__)

PROMPT_REGISTRY: dict[str, dict] = {
    "analyst": {"description": "System prompt аналитика", "variables": []},
    "pm": {"description": "System prompt PM-агента", "variables": []},
    "decomposer": {"description": "System prompt декомпозера", "variables": []},
}

logger.info(f"prompt_registry loaded: {len(PROMPT_REGISTRY)} entries")
