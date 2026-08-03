from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from shared.llm_client import call_detailed

logger = logging.getLogger(__name__)


def extract_ideas(
    report_path: Path,
    vault_path: str,
    business_context: str,
    config: Any,
) -> list[dict]:
    """Извлечь actionable идеи из аналитического отчёта (AC-38).

    Args:
        report_path: путь к отчёту в vault
        vault_path: корень vault
        business_context: содержимое business-context-brief.md
        config: ModeratorConfig с настройками

    Returns:
        list[dict] совместимый с write_idea()
    """
    logger.info(f"Extracting ideas from report: {report_path}")

    report_content = _load_report(report_path)
    if not report_content.strip():
        logger.warning(f"Empty report, skipping idea extraction: {report_path}")
        return []

    prompt = _build_extraction_prompt(report_content, business_context)
    if not prompt.strip():
        logger.error(f"Failed to build extraction prompt (template missing?)")
        return []

    messages = [{"role": "user", "content": prompt}]

    try:
        logger.info(f"Calling LLM for idea extraction, operation=report_to_ideas")
        response, meta = call_detailed(
            operation="report_to_ideas",
            messages=messages,
            max_tokens=2000,
            timeout=60,
        )
        logger.info(f"LLM call succeeded, provider={meta.get('used', 'unknown')}")
    except Exception as e:
        logger.error(f"LLM call failed for idea extraction: {e}")
        return []

    parsed = _parse_json_response(response)
    if not parsed:
        logger.error(f"Failed to parse LLM response for idea extraction")
        return []

    ideas = parsed.get("ideas", [])
    no_ideas_reason = parsed.get("no_ideas_reason", "")

    if not ideas:
        logger.info(
            f"No ideas extracted from {report_path.name}: "
            f"{no_ideas_reason or 'no reason provided'}"
        )
        return []

    # Enrich each idea with source metadata (AC-39)
    for idea in ideas:
        idea["source"] = "report"
        idea["report_ref"] = report_path.name

    logger.info(f"Extracted {len(ideas)} ideas from {report_path.name}")
    return ideas


def extract_ideas_full(
    report_path: Path,
    vault_path: str,
    business_context: str,
    config: Any,
) -> tuple[list[dict], str]:
    """Извлечь actionable идеи из аналитического отчёта (AC-38), включая причину отсутствия идей.

    Расширенная версия extract_ideas(): вместо тихого проглатывания ошибок LLM-вызова
    пробрасывает исключение вызывающему коду, а также возвращает no_ideas_reason.

    Args:
        report_path: путь к отчёту в vault
        vault_path: корень vault
        business_context: содержимое business-context-brief.md
        config: ModeratorConfig с настройками

    Returns:
        tuple[list[dict], str]: (ideas, no_ideas_reason) — ideas совместим с write_idea()

    Raises:
        Exception: при ошибке вызова LLM (call_detailed)
        ValueError: если не удалось распарсить ответ LLM
    """
    logger.info(f"Extracting ideas (full) from report: {report_path}")

    report_content = _load_report(report_path)
    if not report_content.strip():
        logger.warning(f"Empty report, skipping idea extraction: {report_path}")
        return [], "empty report"

    prompt = _build_extraction_prompt(report_content, business_context)
    if not prompt.strip():
        logger.error(f"Cannot build extraction prompt: template missing")
        return [], "prompt template missing"

    messages = [{"role": "user", "content": prompt}]

    logger.info(f"Calling LLM for idea extraction, operation=report_to_ideas")
    response, meta = call_detailed(
        operation="report_to_ideas",
        messages=messages,
        max_tokens=2000,
        timeout=60,
    )
    logger.info(f"LLM call succeeded, provider={meta.get('used', 'unknown')}")

    parsed = _parse_json_response(response)
    if not parsed:
        logger.error(f"Failed to parse LLM response for idea extraction")
        raise ValueError("Failed to parse LLM response for idea extraction")

    ideas = parsed.get("ideas", [])
    no_ideas_reason = parsed.get("no_ideas_reason", "")

    # Enrich each idea with source metadata (AC-39)
    for idea in ideas:
        idea["source"] = "report"
        idea["report_ref"] = report_path.name

    logger.info(
        f"extract_ideas_full: {len(ideas)} ideas, "
        f"reason={no_ideas_reason[:80] if no_ideas_reason else 'N/A'}"
    )
    return ideas, no_ideas_reason


def _load_report(path: Path) -> str:
    """Прочитать отчёт, убрать frontmatter, ограничить ~3000 токенов."""
    logger.info(f"Loading report: {path}")
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to read report {path}: {e}")
        return ""

    # Strip frontmatter (--- ... ---)
    content = re.sub(
        r"^---\s*\n.*?\n---\s*\n", "", content, count=1, flags=re.DOTALL
    )

    # Limit to ~3000 tokens (~12000 chars)
    max_chars = 12000
    if len(content) > max_chars:
        content = content[:max_chars] + "\n\n[...report truncated...]"
        logger.info(f"Report truncated to {max_chars} chars")

    logger.info(f"Report loaded: {len(content)} chars")
    return content.strip()


def _load_prompt(name: str) -> str:
    """Загрузить промпт из knowledge-engine/app/prompts/{name}.txt"""
    prompts_dir = Path(__file__).parent / "prompts"
    path = prompts_dir / f"{name}.txt"
    logger.info(f"Loading prompt: {path}")
    try:
        content = path.read_text(encoding="utf-8")
        logger.info(f"Prompt loaded: {name} ({len(content)} chars)")
        return content
    except FileNotFoundError:
        logger.error(f"Prompt file not found: {path}")
        return ""


def _build_extraction_prompt(
    report_content: str, business_context: str
) -> str:
    """Собрать промпт из шаблона report_to_ideas.txt."""
    logger.info(f"Building extraction prompt from template report_to_ideas")
    template = _load_prompt("report_to_ideas")
    if not template:
        logger.error(f"Cannot build prompt: template report_to_ideas.txt is empty or missing")
        return ""

    prompt = template.replace("{business_context}", business_context)
    prompt = prompt.replace("{report_content}", report_content)
    logger.info(f"Extraction prompt built: {len(prompt)} chars")
    return prompt


def _parse_json_response(text: str) -> dict | None:
    """Извлечь JSON из LLM-ответа. Поддержка markdown code blocks."""
    logger.info(f"Parsing JSON from LLM response ({len(text)} chars)")

    # Try direct parse
    try:
        result = json.loads(text)
        logger.info(f"JSON parsed directly")
        return result
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(1))
            logger.info(f"JSON parsed from markdown code block")
            return result
        except json.JSONDecodeError:
            pass

    # Try finding JSON object
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(0))
            logger.info(f"JSON parsed from embedded object")
            return result
        except json.JSONDecodeError:
            pass

    logger.error(f"Cannot parse JSON from response: {text[:200]}...")
    return None
