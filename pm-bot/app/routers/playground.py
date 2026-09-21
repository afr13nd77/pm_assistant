"""playground.py — эндпоинты LLM playground (BL-152 T-27).

Позволяет вручную протестировать любой из подключённых LLM-провайдеров
(Claude, Ollama, OpenRouter) без fallback-цепочки. Используется страницей
Web UI "Playground".

PlaygroundChatResponse экспортируется и переиспользуется в
app.routers.ai_agent (T-28), т.к. эндпоинт ai-agent/chat возвращает
структурно идентичный ответ.
"""

import logging
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Playground"])


# ---------------------------------------------------------------------------
# Playground — Pydantic models
# ---------------------------------------------------------------------------

class PlaygroundChatRequest(BaseModel):
    provider: str
    model: str | None = None
    messages: list[dict] = Field(..., min_length=1)
    max_tokens: int = Field(default=4096, ge=1, le=16384)


class PlaygroundChatResponse(BaseModel):
    content: str
    provider: str
    model: str
    elapsed_seconds: float
    usage: dict | None = None


# ---------------------------------------------------------------------------
# Playground — GET /api/v1/playground/providers
# ---------------------------------------------------------------------------

@router.get("/api/v1/playground/providers")
def playground_providers():
    """Return list of LLM providers with availability status and models."""
    logger.info("GET /api/v1/playground/providers — start")

    from shared.llm_client import _is_provider_available, _load_llm_prefs
    from shared.openrouter_client import list_models as or_list_models

    prefs = _load_llm_prefs()
    result = []

    # Claude
    claude_available = _is_provider_available("claude", prefs)
    result.append({
        "id": "claude",
        "name": "Claude API",
        "available": claude_available,
        "models": [{"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4"}],
        "default_model": "claude-sonnet-4-6",
        **({"reason": "CLAUDE_API_KEY not set"} if not claude_available else {}),
    })

    # Ollama
    ollama_url = prefs.get("ollama_url", "")
    ollama_model = prefs.get("ollama_model", "qwen3.5:latest")
    ollama_available = _is_provider_available("ollama", prefs)
    ollama_entry = {
        "id": "ollama",
        "name": "Ollama",
        "available": ollama_available,
        "models": [{"id": ollama_model, "name": ollama_model}] if ollama_available else [],
        "default_model": ollama_model,
    }
    if ollama_available:
        ollama_entry["url"] = ollama_url
    else:
        ollama_entry["reason"] = "Ollama URL not configured in Settings"
    result.append(ollama_entry)

    # OpenRouter
    or_available = _is_provider_available("openrouter", prefs)
    or_model = prefs.get("openrouter_model", "qwen/qwen3-32b")
    or_api_key = os.getenv("OPENROUTER_API_KEY")
    or_data = or_list_models(or_api_key)
    or_models = or_data.get("models", [])
    result.append({
        "id": "openrouter",
        "name": "OpenRouter",
        "available": or_available,
        "models": or_models,
        "default_model": or_model,
        **({"reason": "OPENROUTER_API_KEY not set"} if not or_available else {}),
    })

    logger.info(
        "GET /api/v1/playground/providers — returning %d providers, available: %s",
        len(result),
        [p["id"] for p in result if p["available"]],
    )
    return {"providers": result}


# ---------------------------------------------------------------------------
# Playground — POST /api/v1/playground/chat
# ---------------------------------------------------------------------------

_PLAYGROUND_VALID_PROVIDERS = frozenset({"claude", "ollama", "openrouter"})
_PLAYGROUND_TIMEOUTS = {"claude": 60, "ollama": 300, "openrouter": 120}
_PLAYGROUND_DEFAULT_MODELS = {
    "claude": "claude-sonnet-4-6",
    "ollama": "qwen3.5:latest",
    "openrouter": "qwen/qwen3-32b",
}


@router.post("/api/v1/playground/chat")
def playground_chat(body: PlaygroundChatRequest):
    """Send a chat request to a specific LLM provider (no fallback)."""
    import time as _t

    logger.info(
        "POST /api/v1/playground/chat — provider=%s, model=%s, messages=%d, max_tokens=%d",
        body.provider, body.model, len(body.messages), body.max_tokens,
    )

    # Validate provider
    if body.provider not in _PLAYGROUND_VALID_PROVIDERS:
        logger.warning("playground/chat: invalid provider: %s", body.provider)
        raise HTTPException(
            status_code=422,
            detail=f"Invalid provider '{body.provider}'. Must be one of: {', '.join(sorted(_PLAYGROUND_VALID_PROVIDERS))}"
        )

    # Check availability
    from shared.llm_client import _call_provider, _is_provider_available, _load_llm_prefs
    prefs = _load_llm_prefs()

    if not _is_provider_available(body.provider, prefs):
        reason_map = {
            "claude": "CLAUDE_API_KEY not set",
            "ollama": "Ollama URL not configured in Settings",
            "openrouter": "OPENROUTER_API_KEY not set",
        }
        logger.warning("playground/chat: provider %s not available", body.provider)
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{body.provider}' is not available: {reason_map.get(body.provider, 'unknown reason')}"
        )

    # Validate messages format
    for i, msg in enumerate(body.messages):
        if "role" not in msg or "content" not in msg:
            logger.warning("playground/chat: message %d missing role or content", i)
            raise HTTPException(
                status_code=422,
                detail=f"Message at index {i} must have 'role' and 'content' fields"
            )
        if msg["role"] not in ("user", "assistant"):
            logger.warning("playground/chat: message %d has invalid role: %s", i, msg["role"])
            raise HTTPException(
                status_code=422,
                detail=f"Message role must be 'user' or 'assistant', got '{msg['role']}'"
            )

    # Validate total input size
    total_chars = sum(len(msg.get("content", "")) for msg in body.messages)
    if total_chars > 100_000:
        logger.warning("playground/chat: input too large: %d chars", total_chars)
        raise HTTPException(
            status_code=413,
            detail=f"Total input size ({total_chars} chars) exceeds limit of 100,000 chars"
        )

    # Resolve model
    model = body.model
    if not model:
        if body.provider == "ollama":
            model = prefs.get("ollama_model", _PLAYGROUND_DEFAULT_MODELS["ollama"])
        elif body.provider == "openrouter":
            model = prefs.get("openrouter_model", _PLAYGROUND_DEFAULT_MODELS["openrouter"])
        else:
            model = _PLAYGROUND_DEFAULT_MODELS.get(body.provider, "claude-sonnet-4-6")
        logger.info("playground/chat: model resolved to default: %s", model)

    # Override model in prefs for _call_provider compatibility
    call_prefs = dict(prefs)
    if body.provider == "ollama" and model:
        call_prefs["ollama_model"] = model
    elif body.provider == "openrouter" and model:
        call_prefs["openrouter_model"] = model

    timeout = _PLAYGROUND_TIMEOUTS.get(body.provider, 60)

    # Call provider
    # T-04: _call_provider now takes a normalized step {provider, model} instead
    # of a bare provider string, so the resolved playground model (including a
    # user-picked OpenRouter model) is threaded through to _call_openrouter.
    start = _t.time()

    # Langfuse trace for playground calls
    from shared.langfuse_client import get_langfuse
    lf = get_langfuse()
    trace = None
    if lf:
        try:
            trace = lf.trace(
                name="playground",
                input=body.messages,
                metadata={
                    "provider": body.provider,
                    "model": model,
                    "max_tokens": body.max_tokens,
                },
                tags=["playground", body.provider],
            )
        except Exception as exc:
            logger.warning("playground_chat: failed to create Langfuse trace: %s", exc)

    try:
        content, _usage = _call_provider(
            step={"provider": body.provider, "model": model},
            prefs=call_prefs,
            messages=body.messages,
            max_tokens=body.max_tokens,
            system=None,
            timeout=timeout,
        )
        elapsed = round(_t.time() - start, 2)
        # Strip reasoning blocks from models like Nemotron/Qwen
        import re as _re
        content = _re.sub(r"<think>.*?</think>", "", content, flags=_re.DOTALL).strip()
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
                    metadata={"provider": body.provider, "elapsed": elapsed},
                    level="DEFAULT",
                )
            except Exception as lf_exc:
                logger.warning("playground_chat: Langfuse generation failed: %s", lf_exc)
        logger.info(
            "POST /api/v1/playground/chat — success, provider=%s, model=%s, elapsed=%.2f, output_len=%d",
            body.provider, model, elapsed, len(content),
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
            "POST /api/v1/playground/chat — provider error: %s, provider=%s, model=%s, elapsed=%.2f",
            error_msg, body.provider, model, elapsed,
        )
        raise HTTPException(
            status_code=502,
            detail=error_msg,
        )
