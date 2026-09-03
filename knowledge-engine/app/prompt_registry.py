"""Prompt registry — metadata for all KE prompts."""

import logging

logger = logging.getLogger(__name__)

PROMPT_REGISTRY: dict[str, dict] = {
    "enrich": {"description": "Обогащение идей связями", "variables": []},
    "synthesize": {"description": "Кластеризация и синтез", "variables": []},
    "meeting_protocol": {"description": "Обработка транскриптов (очередь)", "variables": []},
    "digest": {"description": "Генерация LLM-дайджестов", "variables": ["TEMPLATE", "PREVIOUS_DIGEST", "BODY"]},
    "digest_prd": {"description": "Шаблон: PRD", "variables": []},
    "digest_decision": {"description": "Шаблон: решение", "variables": []},
    "digest_sprint": {"description": "Шаблон: спринт-отчёт", "variables": []},
    "digest_meeting": {"description": "Шаблон: встреча", "variables": []},
    "digest_competitor": {"description": "Шаблон: конкурентный анализ", "variables": []},
    "digest_jira": {"description": "Шаблон: Jira-черновик", "variables": []},
    "digest_idea": {"description": "Шаблон: идея", "variables": []},
    "digest_epic": {"description": "Шаблон: эпик", "variables": []},
    "digest_daily": {"description": "Шаблон: дейли-лог", "variables": []},
    "digest_bug": {"description": "Шаблон: баг", "variables": []},
    "digest_knowledge": {"description": "Шаблон: knowledge-файл", "variables": []},
    "digest_userstory": {"description": "Шаблон: user story", "variables": []},
    "signal_score": {"description": "Скоринг новостей", "variables": ["business_context", "memory_context", "news_item"]},
    "signal_report_generate": {"description": "Генерация аналитического отчёта", "variables": ["business_context", "competitor_profile", "memory_history", "news_item"]},
    "signal_extract": {"description": "Извлечение сигналов", "variables": ["business_context", "report_content"]},
    "quality_check": {"description": "Quality gate", "variables": ["title", "problem", "solution", "domain"]},
    "dedup_check": {"description": "Дедупликация идей", "variables": ["candidates_list", "title", "problem", "solution"]},
    "completeness_check": {"description": "Полнота отчёта", "variables": ["original_questions", "report_content_first_3000_tokens"]},
    "report_to_ideas": {"description": "Извлечение идей из отчётов", "variables": ["business_context", "report_content"]},
    "research_report": {"description": "Генерация research-отчётов", "variables": ["business_context", "competitor_context", "topic", "signal_source", "scope", "questions"]},
}

logger.info("prompt_registry loaded: %d entries", len(PROMPT_REGISTRY))
