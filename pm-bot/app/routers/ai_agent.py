"""ai_agent.py — эндпоинт AI-ассистента продакт-менеджера (BL-152 T-28).

Отправляет запрос в LLM-провайдер с бизнес-контекстом проекта и телом
текущей идеи в system prompt. Используется страницей идеи Web UI для
доработки идеи в диалоге с ассистентом.

Переиспользует PlaygroundChatResponse из app.routers.playground (T-27),
т.к. форма ответа идентична playground/chat.
"""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .playground import PlaygroundChatResponse
from .user_prefs import _AI_AGENT_VALID_PROVIDERS, _load_business_context_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["AI Agent"])


# ---------------------------------------------------------------------------
# AI Agent — Pydantic models & constants
# ---------------------------------------------------------------------------


class AiAgentChatRequest(BaseModel):
    provider: str
    model: str | None = None
    messages: list[dict] = Field(..., min_length=1)
    idea_id: str = ""
    idea_body: str = ""
    max_tokens: int = Field(default=8192, ge=1, le=16384)


_AI_AGENT_TIMEOUTS = {"claude": 90, "ollama": 300, "openrouter": 120}
_AI_AGENT_DEFAULT_MODELS = {
    "claude": "claude-sonnet-4-6",
    "ollama": "qwen3.5:latest",
    "openrouter": "qwen/qwen3-32b",
}

_AI_AGENT_SYSTEM_PROMPT = """Ты -- AI-ассистент продакт-менеджера. Помогаешь дорабатывать идеи продукта.

## Бизнес-контекст проекта
{business_context}

## Текущая идея
{idea_body}

## Инструкции
- Отвечай конкретно и по существу
- Используй markdown для структурирования ответа
- Учитывай бизнес-контекст при анализе
- Предлагай метрики, где это уместно
- Если идея содержит проблему -- помоги усилить её конкретикой
- Если идея содержит решение -- помоги найти слабые места и улучшить
"""


# ---------------------------------------------------------------------------
# AI Agent — POST /api/v1/ai-agent/chat
# ---------------------------------------------------------------------------


@router.post("/api/v1/ai-agent/chat")
def ai_agent_chat(body: AiAgentChatRequest):
    """Send a chat request to an LLM provider with business context and idea body."""
    import time as _t

    logger.info(
        "POST /api/v1/ai-agent/chat -- provider=%s, model=%s, messages=%d, "
        "idea_id=%s, max_tokens=%d",
        body.provider, body.model, len(body.messages),
        body.idea_id, body.max_tokens,
    )

    # 1. Валидация провайдера
    if body.provider not in _AI_AGENT_VALID_PROVIDERS:
        logger.warning("ai-agent/chat: invalid provider: %s", body.provider)
        raise HTTPException(
            status_code=422,
            detail=f"Invalid provider '{body.provider}'. "
                   f"Must be one of: {', '.join(sorted(_AI_AGENT_VALID_PROVIDERS))}"
        )

    # 2. Проверка доступности
    from shared.llm_client import _call_provider, _is_provider_available, _load_llm_prefs
    prefs = _load_llm_prefs()

    if not _is_provider_available(body.provider, prefs):
        reason_map = {
            "claude": "CLAUDE_API_KEY not set",
            "ollama": "Ollama URL not configured in Settings",
            "openrouter": "OPENROUTER_API_KEY not set",
        }
        logger.warning("ai-agent/chat: provider %s not available", body.provider)
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{body.provider}' is not available: "
                   f"{reason_map.get(body.provider, 'unknown reason')}"
        )

    # 3. Валидация сообщений
    for i, msg in enumerate(body.messages):
        if "role" not in msg or "content" not in msg:
            raise HTTPException(status_code=422, detail=f"Message {i}: missing role or content")
        if msg["role"] not in ("user", "assistant"):
            raise HTTPException(status_code=422, detail=f"Message {i}: invalid role '{msg['role']}'")

    # 4. Лимит размера (system + messages)
    total_chars = sum(len(msg.get("content", "")) for msg in body.messages)
    total_chars += len(body.idea_body)
    if total_chars > 100_000:
        raise HTTPException(status_code=413, detail=f"Total input ({total_chars} chars) exceeds 100K limit")

    # 5. Resolve model
    model = body.model
    if not model:
        if body.provider == "ollama":
            model = prefs.get("ollama_model", _AI_AGENT_DEFAULT_MODELS["ollama"])
        elif body.provider == "openrouter":
            model = prefs.get("ai_agent_model") or prefs.get("openrouter_model",
                              _AI_AGENT_DEFAULT_MODELS["openrouter"])
        else:
            model = _AI_AGENT_DEFAULT_MODELS.get(body.provider, "claude-sonnet-4-6")
        logger.info("ai-agent/chat: model resolved to default: %s", model)

    # 6. Override model в prefs для совместимости _call_provider
    call_prefs = dict(prefs)
    if body.provider == "ollama" and model:
        call_prefs["ollama_model"] = model
    elif body.provider == "openrouter" and model:
        call_prefs["openrouter_model"] = model

    # 7. Загрузка business-context (prefs first, file fallback)
    business_context = prefs.get("business_context", "")
    if not business_context:
        business_context = _load_business_context_file()
        logger.info("ai-agent/chat: business_context loaded from file fallback (%d chars)", len(business_context))

    # 8. Формирование system prompt
    system_prompt = _AI_AGENT_SYSTEM_PROMPT.format(
        business_context=business_context or "(бизнес-контекст не найден)",
        idea_body=body.idea_body or "(текст идеи не передан)",
    )

    timeout = _AI_AGENT_TIMEOUTS.get(body.provider, 90)
    start = _t.time()

    # 9. Langfuse trace
    from shared.langfuse_client import get_langfuse
    lf = get_langfuse()
    trace = None
    if lf:
        try:
            trace = lf.trace(
                name="ai-agent-chat",
                input=body.messages,
                metadata={
                    "idea_id": body.idea_id,
                    "provider": body.provider,
                    "model": model,
                    "max_tokens": body.max_tokens,
                },
                tags=["ai-agent", body.provider],
            )
        except Exception as exc:
            logger.warning("ai-agent/chat: Langfuse trace failed: %s", exc)

    # 10. Вызов провайдера
    try:
        content, _usage = _call_provider(
            step={"provider": body.provider, "model": model},
            prefs=call_prefs,
            messages=body.messages,
            max_tokens=body.max_tokens,
            system=system_prompt,
            timeout=timeout,
        )
        elapsed = round(_t.time() - start, 2)

        # Strip reasoning blocks
        import re as _re
        content = _re.sub(r"<think>.*?</think>", "", content, flags=_re.DOTALL).strip()

        # Langfuse generation
        if trace:
            try:
                lf_usage = {}
                if isinstance(_usage, dict):
                    if _usage.get("input_tokens") is not None:
                        lf_usage["input"] = _usage["input_tokens"]
                    if _usage.get("output_tokens") is not None:
                        lf_usage["output"] = _usage["output_tokens"]
                trace.generation(
                    name=f"{body.provider}:{model}",
                    model=model,
                    input=body.messages,
                    output=content,
                    usage=lf_usage if lf_usage else None,
                    metadata={
                        "provider": body.provider,
                        "idea_id": body.idea_id,
                        "elapsed": elapsed,
                    },
                    level="DEFAULT",
                )
            except Exception as lf_exc:
                logger.warning("ai-agent/chat: Langfuse generation failed: %s", lf_exc)

        logger.info(
            "POST /api/v1/ai-agent/chat -- success, provider=%s, model=%s, "
            "elapsed=%.2f, output_len=%d, idea_id=%s",
            body.provider, model, elapsed, len(content), body.idea_id,
        )
        return PlaygroundChatResponse(
            content=content,
            provider=body.provider,
            model=model,
            elapsed_seconds=elapsed,
            usage=None,
        )
    except Exception as exc:
        elapsed = round(_t.time() - start, 2)
        error_msg = str(exc)
        if trace:
            try:
                trace.generation(
                    name=f"{body.provider}:{model}",
                    model=model,
                    input=body.messages,
                    output=error_msg,
                    level="ERROR",
                    status_message=error_msg,
                )
            except Exception:
                pass
        logger.error(
            "POST /api/v1/ai-agent/chat -- error: %s, provider=%s, model=%s, "
            "elapsed=%.2f, idea_id=%s",
            error_msg, body.provider, model, elapsed, body.idea_id,
        )
        raise HTTPException(status_code=502, detail=error_msg)
