import json
import logging
import os
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)

_OPERATION_GROUPS: dict[str, str] = {
    # Capture: less critical operations, free models give acceptable results
    "idea": "capture",
    "daily": "capture",
    "jira_ticket": "capture",

    # Transcription: meeting audio/text processing
    "meeting": "transcription",
    "meeting_protocol": "transcription",

    # Analysis: quality-critical operations
    "enrich": "analysis",
    "synthesize": "analysis",
    "report": "analysis",
    "pipeline": "analysis",
}

_DEFAULT_FALLBACK: dict[str, list[str]] = {
    "capture": ["claude"],
    "transcription": ["claude"],
    "analysis": ["claude"],
}

_DEFAULT_LLM_PREFS = {
    "llm_provider": "claude",
    "ollama_url": "",
    "ollama_model": "qwen3.5:latest",
}

_OLLAMA_TIMEOUT_MULTIPLIER = 5
_OPENROUTER_DEFAULT_TIMEOUT = 120

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
        use_ollama = operation in {"idea", "daily", "jira_ticket", "meeting", "digest"}

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


def _migrate_legacy_prefs(prefs: dict) -> dict:
    """Compute fallback chains from legacy fields if new fields are absent.

    Does NOT write to file -- in-memory only.
    """
    if (
        "capture_fallback" in prefs
        and "transcription_fallback" in prefs
        and "analysis_fallback" in prefs
    ):
        logger.debug("_migrate_legacy_prefs: new fields present, no migration needed")
        return prefs

    provider = prefs.get("llm_provider", "claude")
    transcription = prefs.get("transcription_provider", "default")

    if "capture_fallback" not in prefs:
        if provider in ("ollama", "hybrid"):
            prefs["capture_fallback"] = ["ollama", "claude"]
        else:
            prefs["capture_fallback"] = ["claude"]

    if "transcription_fallback" not in prefs:
        if transcription == "openrouter":
            prefs["transcription_fallback"] = ["openrouter", "ollama", "claude"]
        elif provider in ("ollama", "hybrid"):
            prefs["transcription_fallback"] = ["ollama", "claude"]
        else:
            prefs["transcription_fallback"] = ["claude"]

    if "analysis_fallback" not in prefs:
        if provider == "ollama":
            prefs["analysis_fallback"] = ["ollama", "claude"]
        else:
            prefs["analysis_fallback"] = ["claude"]

    logger.info(
        "_migrate_legacy_prefs: migrated from legacy fields "
        "(llm_provider=%s, transcription_provider=%s)",
        provider, transcription,
    )
    return prefs


def _resolve_group(operation: str) -> str:
    """Determine the group for an operation. Unknown operations default to analysis."""
    group = _OPERATION_GROUPS.get(operation, "analysis")
    logger.debug("_resolve_group: operation=%s -> group=%s", operation, group)
    return group


def _resolve_chain(group: str, prefs: dict) -> list[str]:
    """Get the fallback chain for a group from prefs."""
    key = f"{group}_fallback"
    chain = prefs.get(key, _DEFAULT_FALLBACK.get(group, ["claude"]))

    if not isinstance(chain, list) or len(chain) == 0:
        logger.warning("_resolve_chain: invalid chain for %s, using default", group)
        chain = ["claude"]

    valid = [p for p in chain if p in ("claude", "ollama", "openrouter")]
    if not valid:
        logger.warning(
            "_resolve_chain: no valid providers in chain for %s, falling back to claude",
            group,
        )
        valid = ["claude"]

    logger.info("_resolve_chain: group=%s, chain=%s", group, valid)
    return valid


def _is_provider_available(provider: str, prefs: dict) -> bool:
    """Check whether a provider is configured (has required URL/key)."""
    if provider == "claude":
        available = bool(os.getenv("CLAUDE_API_KEY"))
        if not available:
            logger.warning("_is_provider_available: claude skipped (CLAUDE_API_KEY not set)")
        return available

    if provider == "ollama":
        available = bool(prefs.get("ollama_url", ""))
        if not available:
            logger.info("_is_provider_available: ollama skipped (ollama_url not configured)")
        return available

    if provider == "openrouter":
        available = bool(os.getenv("OPENROUTER_API_KEY"))
        if not available:
            logger.info("_is_provider_available: openrouter skipped (OPENROUTER_API_KEY not set)")
        return available

    logger.warning("_is_provider_available: unknown provider '%s', skipping", provider)
    return False


def _call_claude(
    messages: list[dict],
    max_tokens: int,
    system: str | None,
    timeout: int | None,
) -> str:
    """Call Claude API via Anthropic SDK."""
    api_key = os.getenv("CLAUDE_API_KEY")
    client = anthropic.Anthropic(api_key=api_key)
    kwargs: dict = {
        "model": "claude-sonnet-4-6",
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system:
        kwargs["system"] = system
    if timeout:
        kwargs["timeout"] = timeout

    logger.info("_call_claude: model=claude-sonnet-4-6, max_tokens=%d", max_tokens)
    response = client.messages.create(**kwargs)
    result = response.content[0].text
    logger.info("_call_claude: success, output_len=%d", len(result))
    return result


def _call_ollama(
    prefs: dict,
    messages: list[dict],
    max_tokens: int,
    system: str | None,
    timeout: int | None,
) -> str:
    """Call Ollama via Anthropic-compatible API."""
    ollama_url = prefs.get("ollama_url", "")
    ollama_model = prefs.get("ollama_model", "qwen3.5:latest")

    client = anthropic.Anthropic(base_url=ollama_url, api_key="ollama")
    ollama_timeout = (timeout or 60) * _OLLAMA_TIMEOUT_MULTIPLIER

    kwargs: dict = {
        "model": ollama_model,
        "max_tokens": max_tokens,
        "messages": messages,
        "thinking": {"type": "disabled"},
    }
    if system:
        kwargs["system"] = system
    kwargs["timeout"] = ollama_timeout

    logger.info("_call_ollama: model=%s, timeout=%d", ollama_model, ollama_timeout)
    response = client.messages.create(**kwargs)
    result = response.content[0].text
    logger.info("_call_ollama: success, output_len=%d", len(result))
    return result


def _call_openrouter(
    prefs: dict,
    messages: list[dict],
    max_tokens: int,
    system: str | None,
    timeout: int | None,
) -> str:
    """Call OpenRouter via shared.openrouter_client."""
    from shared import openrouter_client

    openrouter_model = prefs.get("openrouter_model", "qwen/qwen3-32b")

    or_messages = list(messages)
    if system:
        or_messages.insert(0, {"role": "system", "content": system})

    or_timeout = timeout or _OPENROUTER_DEFAULT_TIMEOUT
    logger.info("_call_openrouter: model=%s, timeout=%d", openrouter_model, or_timeout)

    result = openrouter_client.call(
        messages=or_messages,
        model=openrouter_model,
        max_tokens=max_tokens,
        timeout=or_timeout,
    )
    logger.info("_call_openrouter: success, output_len=%d", len(result))
    return result


def _call_provider(
    provider: str,
    prefs: dict,
    messages: list[dict],
    max_tokens: int,
    system: str | None,
    timeout: int | None,
) -> str:
    """Dispatch a call to a specific provider. Raises on error."""
    if provider == "claude":
        return _call_claude(messages, max_tokens, system, timeout)

    if provider == "ollama":
        return _call_ollama(prefs, messages, max_tokens, system, timeout)

    if provider == "openrouter":
        return _call_openrouter(prefs, messages, max_tokens, system, timeout)

    raise ValueError(f"Unknown provider: {provider}")


def call_detailed(
    operation: str,
    messages: list[dict],
    max_tokens: int,
    system: str | None = None,
    timeout: int | None = None,
) -> tuple[str, dict]:
    """Unified entry point for LLM calls; returns (text, provider_record).

    Identical fallback behaviour to call(), but additionally reports which
    providers were resolved, which one succeeded, and what errors occurred.

    1. Determines the operation group (capture/transcription/analysis)
    2. Reads the fallback chain for the group from prefs
    3. Iterates providers, skipping unavailable ones
    4. On error, falls back to the next provider
    5. If all providers fail, raises RuntimeError

    Returns:
        (text, provider_record) where provider_record = {
            'providers': <resolved fallback chain>,
            'used': <name of the provider that succeeded>,
            'errors': [(provider_name, str(exc)), ...],
        }
    """
    prefs = _load_llm_prefs()
    prefs = _migrate_legacy_prefs(prefs)

    group = _resolve_group(operation)
    chain = _resolve_chain(group, prefs)

    logger.info("call_detailed: operation=%s, group=%s, chain=%s", operation, group, chain)

    import time as _time
    _t0 = _time.monotonic_ns()

    errors: list[tuple[str, str]] = []

    for i, provider in enumerate(chain):
        if not _is_provider_available(provider, prefs):
            logger.info(
                "call_detailed: skipping %s (not available), operation=%s",
                provider, operation,
            )
            continue

        try:
            logger.info(
                "call_detailed: trying provider=%s (%d/%d), operation=%s",
                provider, i + 1, len(chain), operation,
            )
            result = _call_provider(provider, prefs, messages, max_tokens, system, timeout)
            provider_record = {
                "providers": chain,
                "used": provider,
                "errors": errors,
            }
            logger.info(
                "call_detailed: success, operation=%s, provider=%s, output_len=%d",
                operation, provider, len(result),
            )
            _duration = (_time.monotonic_ns() - _t0) // 1_000_000
            try:
                from shared.system_log import log_event
                log_event(
                    process_type="llm-call",
                    status="success",
                    summary=f"{operation} via {provider}",
                    details={
                        "operation": operation,
                        "group": group,
                        "provider_chain": chain,
                        "used_provider": provider,
                        "fallback_count": len(errors),
                        "errors": [{"provider": p, "error": e} for p, e in errors],
                        "output_len": len(result),
                    },
                    duration_ms=_duration,
                    source="llm-client",
                )
            except Exception:
                pass
            return result, provider_record

        except Exception as exc:
            errors.append((provider, str(exc)))
            remaining = [p for p in chain[i + 1:] if _is_provider_available(p, prefs)]
            if remaining:
                logger.warning(
                    "call_detailed: %s failed for operation=%s: %s. Falling back to %s",
                    provider, operation, exc, remaining[0],
                )
            else:
                logger.error(
                    "call_detailed: %s failed for operation=%s: %s. No more providers in chain.",
                    provider, operation, exc,
                )

    _duration = (_time.monotonic_ns() - _t0) // 1_000_000
    try:
        from shared.system_log import log_event
        log_event(
            process_type="llm-call",
            status="error",
            summary=f"{operation}: all providers failed",
            details={
                "operation": operation,
                "group": group,
                "provider_chain": chain,
                "errors": [{"provider": p, "error": e} for p, e in errors],
            },
            duration_ms=_duration,
            source="llm-client",
        )
    except Exception:
        pass
    error_summary = "; ".join(f"{p}: {e}" for p, e in errors)
    raise RuntimeError(
        f"All providers failed for operation={operation} "
        f"(group={group}, chain={chain}): {error_summary}"
    )


def call(
    operation: str,
    messages: list[dict],
    max_tokens: int,
    system: str | None = None,
    timeout: int | None = None,
) -> str:
    """Unified entry point for LLM calls with configurable fallback chain.

    Thin wrapper over call_detailed() — returns only the response text.
    External behaviour is unchanged.
    """
    return call_detailed(operation, messages, max_tokens, system, timeout)[0]


def call_with_fallback(
    operation: str,
    messages: list[dict],
    max_tokens: int,
    system: str | None = None,
    timeout: int | None = None,
) -> str:
    """DEPRECATED: use call(). Kept for backward compatibility."""
    logger.debug("call_with_fallback: delegating to call(), operation=%s", operation)
    return call(operation, messages, max_tokens, system, timeout)


def call_transcription(
    operation: str,
    messages: list[dict],
    max_tokens: int,
    system: str | None = None,
    timeout: int | None = None,
) -> str:
    """DEPRECATED: use call(). Kept for backward compatibility."""
    logger.debug("call_transcription: delegating to call(), operation=%s", operation)
    return call(operation, messages, max_tokens, system, timeout)
