import logging
import time
from pathlib import Path

from shared import llm_client

logger = logging.getLogger(__name__)

_MIN_RESPONSE_LENGTH = {
    "meeting_protocol": 200,
    "synthesize": 100,
}


def _load_prompt(name: str) -> str:
    path = Path(__file__).parent / "prompts" / f"{name}.txt"
    return path.read_text(encoding="utf-8")


def enrich(idea_text: str, matched_entries: list[dict]) -> str:
    logger.info(f"Enriching idea ({len(idea_text)} chars) with {len(matched_entries)} matched entries")
    prompt = _load_prompt("enrich")

    entries_text = "\n".join(
        f"- {e['path']}: {e['title']} — {e.get('snippet', '')}"
        for e in matched_entries
    )
    if not entries_text:
        entries_text = "(нет найденных заметок)"

    user_content = f"{prompt}\n\n---\n\nИдея:\n{idea_text}\n\nНайденные заметки из vault:\n{entries_text}"

    return _call_claude(user_content, max_tokens=1500, operation="enrich")


def synthesize(ideas_list: list[dict]) -> str:
    logger.info(f"Synthesizing {len(ideas_list)} ideas")
    prompt = _load_prompt("synthesize")

    ideas_text = ""
    for i, idea in enumerate(ideas_list, 1):
        ideas_text += f"\n### Идея {i}: {idea.get('title', 'Без заголовка')}\n"
        ideas_text += f"Файл: {idea.get('filename', '')}\n"
        ideas_text += f"Дата: {idea.get('date', '')}\n"
        ideas_text += f"Теги: {', '.join(idea.get('tags', []))}\n"
        ideas_text += f"Текст:\n{idea.get('body', '')}\n"
        if idea.get('links'):
            ideas_text += f"Связи: {', '.join(idea['links'])}\n"

    user_content = f"{prompt}\n\n---\n\n{ideas_text}"

    return _call_claude(user_content, max_tokens=4000, operation="synthesize")


def process_meeting_transcript(transcript: str) -> str:
    """Process a raw meeting transcript into a structured protocol with frontmatter."""
    logger.info(f"Processing meeting transcript ({len(transcript)} chars)")
    prompt = _load_prompt("meeting_protocol")
    user_content = f"{prompt}\n\n---\n\n{transcript}"
    return _call_claude(user_content, max_tokens=4000, operation="meeting_protocol")


def _call_claude(user_content: str, max_tokens: int, operation: str) -> str:
    timeout = 30 if operation == "enrich" else 60

    for attempt in range(2):
        try:
            logger.info("_call_claude: %s (attempt %d)", operation, attempt + 1)
            start = time.time()

            if operation in ("meeting_protocol", "meeting"):
                result = llm_client.call_transcription(
                    operation=operation,
                    messages=[{"role": "user", "content": user_content}],
                    max_tokens=max_tokens,
                    timeout=timeout,
                )
            else:
                result = llm_client.call_with_fallback(
                    operation=operation,
                    messages=[{"role": "user", "content": user_content}],
                    max_tokens=max_tokens,
                    timeout=timeout,
                )

            elapsed = time.time() - start
            logger.info("_call_claude: %s OK, %d chars in %.1fs", operation, len(result), elapsed)

            min_length = _MIN_RESPONSE_LENGTH.get(operation, 0)
            if min_length and len(result) < min_length:
                msg = (
                    f"Response too short for {operation}: "
                    f"{len(result)} chars < {min_length} minimum"
                )
                logger.warning("_call_claude: %s", msg)
                raise ValueError(msg)

            return result

        except Exception as e:
            if attempt == 0:
                logger.warning("_call_claude: %s failed (attempt 1), retrying in 5s: %s", operation, e)
                time.sleep(5)
            else:
                logger.error("_call_claude: %s failed (attempt 2): %s", operation, e)
                raise

    # Unreachable: the loop always returns or raises, but mypy cannot prove it
    raise RuntimeError(f"_call_claude: {operation} failed after all retries")
