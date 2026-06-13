import json
import logging
import re
from pathlib import Path

from shared import llm_client

logger = logging.getLogger(__name__)

def _load_prompt(name: str) -> str:
    path = Path(__file__).parent / "prompts" / f"{name}.txt"
    return path.read_text(encoding="utf-8")


_IDEA_REQUIRED_KEYS = ("title", "domain", "problem", "solution", "usp", "metric", "tags")
_FALLBACK_DOMAINS = ("static-metadata", "suggester", "search-engine", "general")


def _get_valid_domains() -> tuple[str, ...]:
    """Return valid domain slugs from domain-config.yaml with fallback."""
    try:
        from shared import domain_config
        domains = domain_config.get_valid_domains()
        if domains:
            logger.info(
                "_get_valid_domains: loaded %d domain(s) from config", len(domains)
            )
            return domains
    except Exception as exc:
        logger.warning(
            "_get_valid_domains: failed to load config, using fallback: %s", exc
        )

    logger.info(
        "_get_valid_domains: domain-config.yaml not found or empty, "
        "using hardcoded defaults (%d domains)",
        len(_FALLBACK_DOMAINS),
    )
    return _FALLBACK_DOMAINS


def _extract_json_from_response(text: str) -> dict | None:
    """Extract and parse a JSON object from a ```json ... ``` code block."""
    pattern = r"```json\s*\n(.*?)\n\s*```"
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        logger.warning("_extract_json_from_response: no ```json block found in response")
        return None
    json_str = match.group(1).strip()
    try:
        data = json.loads(json_str)
        logger.info("_extract_json_from_response: successfully parsed JSON")
        return data
    except json.JSONDecodeError as e:
        logger.warning("_extract_json_from_response: json.loads failed: %s", e)
        return None


def _build_fallback_idea(raw_text: str) -> dict:
    """Build a fallback idea dict when JSON parsing fails."""
    title = raw_text[:50].strip()
    if len(raw_text) > 50 and " " in title:
        title = title[:title.rfind(" ")]
    logger.warning("_build_fallback_idea: using fallback, title=%s", title)
    return {
        "title": title,
        "domain": "general",
        "problem": raw_text,
        "solution": "",
        "usp": "",
        "metric": "",
        "tags": ["idea"],
    }


def _validate_idea_data(data: dict) -> dict:
    """Validate and normalize the parsed idea dict."""
    result = {}
    for key in _IDEA_REQUIRED_KEYS:
        result[key] = data.get(key, "")

    valid_domains = _get_valid_domains()
    if result["domain"] not in valid_domains:
        logger.warning(
            "_validate_idea_data: invalid domain '%s' (not in %s), "
            "falling back to 'general'",
            result["domain"], valid_domains,
        )
        result["domain"] = "general"

    if not isinstance(result["tags"], list):
        result["tags"] = ["idea"]
    if "idea" not in result["tags"]:
        result["tags"].insert(0, "idea")

    if result["title"]:
        words = result["title"].split()
        if len(words) > 10:
            result["title"] = " ".join(words[:10])

    for key in ("title", "problem", "solution", "usp", "metric"):
        if not isinstance(result[key], str):
            result[key] = str(result[key]) if result[key] else ""

    logger.info("_validate_idea_data: validated, domain=%s, title=%s", result["domain"], result["title"][:40])
    return result


def _inject_domains_section(template: str, domains_section: str) -> str:
    """Replace the static domain list in the prompt template with dynamic one."""
    # Strategy 1: explicit placeholder
    placeholder = "{domains_section}"
    if placeholder in template:
        logger.info("_inject_domains_section: found placeholder, replacing")
        return template.replace(placeholder, domains_section)

    # Strategy 2: regex replace of static domain block
    pattern = (
        r"(Определи домен идеи по содержанию сообщения\. Доступные домены:\n)"
        r"(- .+\n?)+"
    )
    match = re.search(pattern, template)
    if match:
        header = match.group(1)
        replacement = header + domains_section + "\n"
        result = template[:match.start()] + replacement + template[match.end():]
        logger.info("_inject_domains_section: replaced static block via regex")
        return result

    # Strategy 3: append before JSON format block
    logger.warning(
        "_inject_domains_section: could not locate domain block in template, "
        "appending section before JSON block"
    )
    json_marker = "Верни ТОЛЬКО JSON"
    if json_marker in template:
        idx = template.index(json_marker)
        injected = (
            f"Определи домен идеи по содержанию сообщения. "
            f"Доступные домены:\n{domains_section}\n\n"
        )
        return template[:idx] + injected + template[idx:]

    return template


def _build_idea_prompt(raw_text: str) -> str:
    """Build the full idea prompt with dynamic domain section."""
    try:
        from shared import domain_config
        domains_section = domain_config.build_prompt_section()
        if domains_section:
            prompt_template = _load_prompt("idea")
            prompt = _inject_domains_section(prompt_template, domains_section)
            logger.info(
                "_build_idea_prompt: using dynamic domains section (%d domains)",
                domains_section.count("\n") + 1,
            )
            return f"{prompt}\n\n---\n{raw_text}"
    except Exception as exc:
        logger.warning(
            "_build_idea_prompt: failed to build dynamic prompt, "
            "using static: %s", exc,
        )

    logger.info("_build_idea_prompt: using static prompt from idea.txt")
    prompt = _load_prompt("idea")
    return f"{prompt}\n\n---\n{raw_text}"


def process_idea(raw_text: str) -> dict:
    """Send raw text to Claude, return structured idea dict."""
    logger.info("process_idea: processing raw_text, len=%d", len(raw_text))
    prompt_with_text = _build_idea_prompt(raw_text)
    try:
        response_text = llm_client.call_with_fallback(
            operation="idea",
            messages=[{"role": "user", "content": prompt_with_text}],
            max_tokens=1000,
        )
        logger.info("process_idea: received response, len=%d", len(response_text))
    except Exception as e:
        logger.error("process_idea: LLM call failed: %s", e)
        raise

    data = _extract_json_from_response(response_text)
    if data is None:
        try:
            data = json.loads(response_text.strip())
            logger.info("process_idea: parsed response as raw JSON (no code fence)")
        except (json.JSONDecodeError, ValueError):
            logger.warning("process_idea: all JSON extraction failed, using fallback")
            return _build_fallback_idea(raw_text)

    if not isinstance(data, dict):
        logger.warning("process_idea: parsed JSON is not a dict, using fallback")
        return _build_fallback_idea(raw_text)

    return _validate_idea_data(data)


def process_meeting(transcript: str) -> str:
    """Поток 2: извлекает решения и action items из транскрипта."""
    prompt = _load_prompt("meeting")
    try:
        response_text = llm_client.call_with_fallback(
            operation="meeting",
            messages=[{"role": "user", "content": f"{prompt}\n\n---\n{transcript}"}],
            max_tokens=2000,
        )
        logger.info("process_meeting: received response, len=%d", len(response_text))
        return response_text
    except Exception as e:
        logger.error("process_meeting: LLM call failed: %s", e)
        raise

def process_jira_ticket(raw_text: str) -> str:
    """Поток 3: генерирует структурированный Jira-тикет."""
    prompt = _load_prompt("jira_ticket")
    try:
        response_text = llm_client.call_with_fallback(
            operation="jira_ticket",
            messages=[{"role": "user", "content": f"{prompt}\n\n---\n{raw_text}"}],
            max_tokens=1500,
        )
        logger.info("process_jira_ticket: received response, len=%d", len(response_text))
        return response_text
    except Exception as e:
        logger.error("process_jira_ticket: LLM call failed: %s", e)
        raise

def process_daily(text: str) -> str:
    """Поток 4: структурирует ежедневную заметку в дневной лог."""
    prompt = _load_prompt("daily")
    try:
        response_text = llm_client.call_with_fallback(
            operation="daily",
            messages=[{"role": "user", "content": f"{prompt}\n\n---\n{text}"}],
            max_tokens=1500,
        )
        logger.info("process_daily: received response, len=%d", len(response_text))
        return response_text
    except Exception as e:
        logger.error("process_daily: LLM call failed: %s", e)
        raise
