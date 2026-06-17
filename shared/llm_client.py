import json
import logging
import os
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)

# Operations routed to Ollama in hybrid mode
_HYBRID_OLLAMA_OPS = frozenset({
    "idea", "daily", "jira_ticket", "meeting",
})

_DEFAULT_LLM_PREFS = {
    "llm_provider": "claude",
    "ollama_url": "",
    "ollama_model": "qwen3.5:latest",
}

_cached_prefs: dict | None = None
_cached_mtime: float = 0.0


def _load_llm_prefs() -> dict:
    """Load LLM prefs from .pm-user-prefs.json with file mtime caching."""
    global _cached_prefs, _cached_mtime

    vault_path = os.getenv("VAULT_PATH", "")
    prefs_path = Path(vault_path) / ".pm-user-prefs.json"

    if not prefs_path.exists():
        logger.info("_load_llm_prefs: prefs file not found, using defaults")
        return dict(_DEFAULT_LLM_PREFS)

    try:
        mtime = prefs_path.stat().st_mtime
        if _cached_prefs is not None and mtime == _cached_mtime:
            logger.debug("_load_llm_prefs: returning cached prefs")
            return _cached_prefs

        data = json.loads(prefs_path.read_text(encoding="utf-8"))
        _cached_prefs = data
        _cached_mtime = mtime
        logger.info("_load_llm_prefs: loaded prefs, llm_provider=%s", data.get("llm_provider", "claude"))
        return data
    except Exception as e:
        logger.warning("_load_llm_prefs: failed to read prefs: %s, using defaults", e)
        return dict(_DEFAULT_LLM_PREFS)


def invalidate_cache():
    """Force reload of prefs on next call. Called after prefs are written via API."""
    global _cached_prefs, _cached_mtime
    _cached_prefs = None
    _cached_mtime = 0.0
    logger.info("invalidate_cache: LLM prefs cache cleared")


def get_client(operation: str) -> tuple[anthropic.Anthropic, str, dict]:
    """Return (client, model, extra_kwargs) for the given operation.

    extra_kwargs may contain thinking={"type":"disabled"} for Ollama.
    """
    prefs = _load_llm_prefs()
    provider = prefs.get("llm_provider", "claude")
    ollama_url = prefs.get("ollama_url", "")
    ollama_model = prefs.get("ollama_model", "qwen3.5:latest")

    use_ollama = False

    if provider == "ollama" and ollama_url:
        use_ollama = True
    elif provider == "hybrid" and ollama_url:
        use_ollama = operation in _HYBRID_OLLAMA_OPS

    if use_ollama:
        logger.info("get_client: operation=%s, provider=ollama, url=%s, model=%s",
                     operation, ollama_url, ollama_model)
        client = anthropic.Anthropic(base_url=ollama_url, api_key="ollama")
        extra = {"thinking": {"type": "disabled"}}
        return client, ollama_model, extra

    logger.info("get_client: operation=%s, provider=claude", operation)
    api_key = os.getenv("CLAUDE_API_KEY")
    client = anthropic.Anthropic(api_key=api_key)
    return client, "claude-sonnet-4-6", {}


def call_with_fallback(
    operation: str,
    messages: list[dict],
    max_tokens: int,
    system: str | None = None,
    timeout: int | None = None,
) -> str:
    """Call LLM with automatic fallback from Ollama to Claude API on failure."""
    client, model, extra_kwargs = get_client(operation)

    is_ollama = model != "claude-sonnet-4-6"
    ollama_timeout = timeout * 5 if (is_ollama and timeout) else timeout
    if is_ollama and timeout:
        logger.info("call_with_fallback: Ollama timeout adjusted: %ds → %ds", timeout, ollama_timeout)

    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
        **extra_kwargs,
    }
    if system:
        kwargs["system"] = system
    if ollama_timeout:
        kwargs["timeout"] = ollama_timeout

    try:
        logger.info("call_with_fallback: calling model=%s, operation=%s", model, operation)
        response = client.messages.create(**kwargs)
        result = response.content[0].text
        logger.info("call_with_fallback: success, operation=%s, model=%s, output_len=%d",
                     operation, model, len(result))
        return result
    except Exception as exc:
        # Only fallback if we were using Ollama
        if model != "claude-sonnet-4-6":
            logger.warning(
                "call_with_fallback: Ollama failed for operation=%s, error=%s. Falling back to Claude API",
                operation, exc,
            )
            api_key = os.getenv("CLAUDE_API_KEY")
            if not api_key:
                logger.error("call_with_fallback: CLAUDE_API_KEY not set, cannot fallback")
                raise

            fallback_client = anthropic.Anthropic(api_key=api_key)
            fallback_kwargs: dict = {
                "model": "claude-sonnet-4-6",
                "max_tokens": max_tokens,
                "messages": messages,
            }
            if system:
                fallback_kwargs["system"] = system
            if timeout:
                fallback_kwargs["timeout"] = timeout

            try:
                response = fallback_client.messages.create(**fallback_kwargs)
                result = response.content[0].text
                logger.info("call_with_fallback: fallback success, operation=%s, output_len=%d",
                             operation, len(result))
                return result
            except Exception as fallback_exc:
                logger.error("call_with_fallback: fallback also failed, operation=%s, error=%s",
                              operation, fallback_exc)
                raise

        logger.error("call_with_fallback: Claude API failed, operation=%s, error=%s", operation, exc)
        raise


def call_transcription(
    operation: str,
    messages: list[dict],
    max_tokens: int,
    system: str | None = None,
    timeout: int | None = None,
) -> str:
    """Call LLM for transcription with OpenRouter -> Ollama -> Claude fallback chain."""
    prefs = _load_llm_prefs()
    transcription_provider = prefs.get("transcription_provider", "default")

    if transcription_provider != "openrouter":
        logger.info(
            "call_transcription: provider=default, delegating to call_with_fallback"
        )
        return call_with_fallback(operation, messages, max_tokens, system, timeout)

    # --- OpenRouter attempt ---
    openrouter_model = prefs.get("openrouter_model", "qwen/qwen3-32b")

    try:
        from shared import openrouter_client

        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            logger.warning(
                "call_transcription: OPENROUTER_API_KEY not set, "
                "falling back to default provider"
            )
            return call_with_fallback(operation, messages, max_tokens, system, timeout)

        openrouter_messages = list(messages)
        if system:
            openrouter_messages.insert(0, {"role": "system", "content": system})

        or_timeout = timeout or 120
        logger.info(
            "call_transcription: trying OpenRouter, model=%s, timeout=%d",
            openrouter_model, or_timeout,
        )

        result = openrouter_client.call(
            messages=openrouter_messages,
            model=openrouter_model,
            max_tokens=max_tokens,
            timeout=or_timeout,
        )
        logger.info(
            "call_transcription: OpenRouter success, operation=%s, output_len=%d",
            operation, len(result),
        )
        return result

    except Exception as or_exc:
        logger.warning(
            "call_transcription: OpenRouter failed for operation=%s: %s. "
            "Falling back to Ollama/Claude",
            operation, or_exc,
        )

    # --- Ollama attempt (if configured) ---
    ollama_url = prefs.get("ollama_url", "")
    if ollama_url:
        try:
            ollama_model = prefs.get("ollama_model", "qwen3.5:latest")
            ollama_client = anthropic.Anthropic(base_url=ollama_url, api_key="ollama")

            ollama_timeout = (timeout or 60) * 5
            kwargs: dict = {
                "model": ollama_model,
                "max_tokens": max_tokens,
                "messages": messages,
                "thinking": {"type": "disabled"},
            }
            if system:
                kwargs["system"] = system
            kwargs["timeout"] = ollama_timeout

            logger.info(
                "call_transcription: trying Ollama fallback, model=%s, timeout=%d",
                ollama_model, ollama_timeout,
            )
            response = ollama_client.messages.create(**kwargs)
            result = response.content[0].text
            logger.info(
                "call_transcription: Ollama fallback success, operation=%s, output_len=%d",
                operation, len(result),
            )
            return result

        except Exception as ollama_exc:
            logger.warning(
                "call_transcription: Ollama fallback also failed for operation=%s: %s. "
                "Falling back to Claude API",
                operation, ollama_exc,
            )

    # --- Claude API final fallback ---
    logger.info("call_transcription: final fallback to Claude API")
    api_key_claude = os.getenv("CLAUDE_API_KEY")
    if not api_key_claude:
        logger.error("call_transcription: CLAUDE_API_KEY not set, cannot fallback")
        raise RuntimeError("All transcription providers failed and CLAUDE_API_KEY is not set")

    claude_client = anthropic.Anthropic(api_key=api_key_claude)
    claude_kwargs: dict = {
        "model": "claude-sonnet-4-6",
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system:
        claude_kwargs["system"] = system
    if timeout:
        claude_kwargs["timeout"] = timeout

    response = claude_client.messages.create(**claude_kwargs)
    result = response.content[0].text
    logger.info(
        "call_transcription: Claude fallback success, operation=%s, output_len=%d",
        operation, len(result),
    )
    return result
