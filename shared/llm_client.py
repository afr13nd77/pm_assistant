import json
import logging
import os
from pathlib import Path

import anthropic

from shared import openrouter_client
from shared.langfuse_client import get_langfuse

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

    # Pipeline: idea processing agents (analyst -> PM -> decomposer)
    "pipeline_analyst": "pipeline",
    "pipeline_pm": "pipeline",
    "pipeline_decomposer": "pipeline",

    # Digest: heavy prompts (full artifact body, up to 100K tokens)
    "digest":                      "digest",

    # Signal Moderator: triage operations (cheap, many per run)
    "signal_score":                "signal_triage",
    "quality_check":               "signal_triage",
    "dedup_check":                 "signal_triage",
    # Signal Moderator: deep analysis (large prompts up to 13K chars)
    "completeness_check":          "signal_deep",
    # Signal Moderator: analysis operations (medium, 1-3 per run)
    "signal_analyze":              "signal_analysis",
    "report_to_ideas":             "signal_analysis",
    "trend_detect":                "signal_analysis",
    "research_report":             "signal_analysis",
    "signal_report_generate":      "signal_analysis",
    "signal_extract":              "signal_analysis",
    # Signal Moderator: escalation (agent loop last iteration)
    "signal_analyze_escalation":   "signal_escalation",
}

_DEFAULT_FALLBACK: dict[str, list] = {
    "capture": ["claude"],
    "transcription": ["claude"],
    "analysis": ["claude"],
    "pipeline": ["claude"],
    "digest": ["ollama", "claude"],
    "signal_triage": [{"provider": "openrouter", "model": "openai/gpt-oss-20b:free"}, "openrouter", "claude"],
    "signal_deep": ["openrouter", "claude"],
    "signal_analysis": ["openrouter", "claude"],
    "signal_escalation": ["openrouter", "claude"],
}

_DEFAULT_LLM_PREFS = {
    "llm_provider": "claude",
    "ollama_url": "",
    "ollama_model": "qwen3.5:latest",
}

_OLLAMA_TIMEOUT_MULTIPLIER = 5
_OPENROUTER_DEFAULT_TIMEOUT = 120

# T-05 (design.md §6.3): short fixed backoff applied only between two ADJACENT
# openrouter steps in a fallback chain, when the first one failed with a 429
# (rate limit). Keeps us from immediately hammering the same rate-limited
# provider with the very next request.
OPENROUTER_429_BACKOFF_SECONDS = 0.7

_cached_prefs: dict | None = None
_cached_mtime: float = 0.0


def _load_llm_prefs() -> dict:
    """Load LLM prefs from .pm-user-prefs.json with file mtime caching."""
    global _cached_prefs, _cached_mtime

    data_dir = os.getenv("PM_BOT_DATA_PATH", os.getenv("VAULT_PATH", ""))
    prefs_path = Path(data_dir) / ".pm-user-prefs.json"

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
        and "pipeline_fallback" in prefs
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

    if "pipeline_fallback" not in prefs:
        if provider == "ollama":
            prefs["pipeline_fallback"] = ["ollama", "claude"]
        else:
            prefs["pipeline_fallback"] = ["claude"]

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


def _default_model_for(provider: str, prefs: dict) -> str | None:
    """Return the default model for a fallback-chain step lacking one (design.md §2.1).

    - openrouter: prefs["openrouter_model"] if set (legacy global model),
      else openrouter_client.DEFAULT_MODEL as a last resort.
    - claude/ollama: these providers are single-model -- they take their
      model from their own prefs fields, so no per-step default applies.
    - unknown provider: None.
    """
    if provider == "openrouter":
        model = prefs.get("openrouter_model")
        if model:
            logger.debug("_default_model_for: openrouter -> prefs.openrouter_model=%s", model)
            return model
        logger.debug(
            "_default_model_for: openrouter -> openrouter_client.DEFAULT_MODEL=%s",
            openrouter_client.DEFAULT_MODEL,
        )
        return openrouter_client.DEFAULT_MODEL

    if provider in ("claude", "ollama"):
        return None

    logger.warning("_default_model_for: unknown provider '%s', returning None", provider)
    return None


def _normalize_step(el, prefs: dict) -> dict | None:
    """Normalize one fallback-chain element to the canonical {provider, model} form.

    Accepts the legacy plain-string form ("openrouter") or the new object
    form ({"provider": ..., "model": ...}). In-memory only -- does not
    mutate the caller's prefs or write anything to disk (same convention
    as _migrate_legacy_prefs).

    Returns None (and logs a warning) for unsupported/malformed elements
    instead of raising, so a single bad entry doesn't crash chain resolution.
    """
    if isinstance(el, str):
        return {"provider": el, "model": _default_model_for(el, prefs)}

    if isinstance(el, dict):
        provider = el.get("provider")
        if not provider:
            logger.warning("_normalize_step: dict step missing 'provider', skipping: %s", el)
            return None
        return {
            "provider": provider,
            "model": el.get("model") or _default_model_for(provider, prefs),
        }

    logger.warning(
        "_normalize_step: unsupported step type %s, skipping: %r",
        type(el).__name__, el,
    )
    return None


def _resolve_chain(group: str, prefs: dict) -> list[dict]:
    """Get the normalized fallback chain for a group from prefs.

    Returns a list of normalized steps [{"provider": ..., "model": ...}, ...].
    Each raw element in prefs may be a legacy provider-name string or a
    new-format {"provider", "model"} object -- both are normalized via
    _normalize_step() (design.md §2.1, §3.2). Normalization happens purely
    in memory; the prefs dict / file on disk are never rewritten here.
    """
    key = f"{group}_fallback"
    chain = prefs.get(key, _DEFAULT_FALLBACK.get(group, ["claude"]))

    if not isinstance(chain, list) or len(chain) == 0:
        logger.warning("_resolve_chain: invalid chain for %s, using default", group)
        chain = ["claude"]

    raw_steps = [_normalize_step(el, prefs) for el in chain]
    steps: list[dict] = [s for s in raw_steps if s is not None and s["provider"] in ("claude", "ollama", "openrouter")]

    if not steps:
        logger.warning(
            "_resolve_chain: no valid providers in chain for %s, falling back to claude",
            group,
        )
        fallback = _normalize_step("claude", prefs)
        steps = [fallback] if fallback is not None else [{"provider": "claude", "model": ""}]

    logger.info(
        "_resolve_chain: group=%s, chain=%s",
        group, [s["provider"] for s in steps],
    )
    return steps


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


def _is_rate_limit_error(exc: Exception) -> bool:
    """Detect an HTTP 429 (rate limit) error raised from an OpenRouter call.

    `openrouter_client.call()` calls `response.raise_for_status()`, which
    raises `requests.HTTPError` carrying the original `response` object with
    `.status_code`. We check that first; as a defensive fallback (e.g. if the
    response object is missing, or the error text was wrapped by another
    layer), we also match on the textual markers OpenRouter/requests use for
    429 responses (design.md §6.3, T-05).
    """
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None) if response is not None else None
    if status_code == 429:
        return True

    text = str(exc)
    return "429" in text or "Too Many Requests" in text


def _call_claude(
    messages: list[dict],
    max_tokens: int,
    system: str | None,
    timeout: int | None,
) -> tuple[str, dict]:
    """Call Claude API via Anthropic SDK.

    Returns (text, usage_dict) where usage_dict contains
    input_tokens, output_tokens, and model.
    """
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
    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "model": kwargs["model"],
    }
    logger.info(
        "_call_claude: success, output_len=%d, input_tokens=%s, output_tokens=%s",
        len(result), usage["input_tokens"], usage["output_tokens"],
    )
    return result, usage


def _call_ollama(
    prefs: dict,
    messages: list[dict],
    max_tokens: int,
    system: str | None,
    timeout: int | None,
) -> tuple[str, dict]:
    """Call Ollama via Anthropic-compatible API.

    Returns (text, usage_dict). usage_dict always contains 'model';
    input_tokens/output_tokens are None when the Ollama response
    does not include usage information.
    """
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
    usage: dict = {"model": ollama_model}
    if hasattr(response, "usage") and response.usage:
        usage["input_tokens"] = getattr(response.usage, "input_tokens", None)
        usage["output_tokens"] = getattr(response.usage, "output_tokens", None)
    else:
        usage["input_tokens"] = None
        usage["output_tokens"] = None
    logger.info(
        "_call_ollama: success, output_len=%d, input_tokens=%s, output_tokens=%s",
        len(result), usage["input_tokens"], usage["output_tokens"],
    )
    return result, usage


def _call_openrouter(
    prefs: dict,
    messages: list[dict],
    max_tokens: int,
    system: str | None,
    timeout: int | None,
    model: str | None = None,
) -> tuple[str, dict]:
    """Call OpenRouter via shared.openrouter_client.

    Returns (text, usage_dict) -- usage_dict is forwarded directly from
    openrouter_client.call() and contains input_tokens, output_tokens, model.

    `model` is the model resolved for this specific fallback-chain step
    (design.md §1.4, §3.5, T-04) -- it takes precedence so that a chain
    with multiple OpenRouter steps can use a different model per step.
    If not provided (e.g. legacy direct callers), falls back to the
    global prefs["openrouter_model"] as before.
    """
    from shared import openrouter_client

    openrouter_model = model or prefs.get("openrouter_model", "qwen/qwen3-32b")

    or_messages = list(messages)
    if system:
        or_messages.insert(0, {"role": "system", "content": system})

    or_timeout = timeout or _OPENROUTER_DEFAULT_TIMEOUT
    logger.info("_call_openrouter: model=%s, timeout=%d", openrouter_model, or_timeout)

    result, usage = openrouter_client.call(
        messages=or_messages,
        model=openrouter_model,
        max_tokens=max_tokens,
        timeout=or_timeout,
    )
    if not result:
        raise RuntimeError(f"OpenRouter model {openrouter_model} returned empty response")
    logger.info(
        "_call_openrouter: success, output_len=%d, input_tokens=%s, output_tokens=%s",
        len(result), usage.get("input_tokens"), usage.get("output_tokens"),
    )
    return result, usage


def _call_provider(
    step: dict,
    prefs: dict,
    messages: list[dict],
    max_tokens: int,
    system: str | None,
    timeout: int | None,
) -> tuple[str, dict]:
    """Dispatch a call to a specific provider. Raises on error.

    Returns (text, usage_dict) from the underlying provider function.

    `step` is a normalized fallback-chain step {"provider": ..., "model": ...}
    (see _normalize_step/_resolve_chain, design.md §2.1). claude/ollama are
    single-model providers and keep taking their model from their own prefs
    fields (unchanged in substance) -- they accept the same step-shaped
    argument purely for a uniform call signature. openrouter uses
    step["model"] so that multiple OpenRouter steps in one chain can each
    use a different model (T-04, fixes BL-155 root cause).
    """
    provider = step["provider"]

    if provider == "claude":
        return _call_claude(messages, max_tokens, system, timeout)

    if provider == "ollama":
        return _call_ollama(prefs, messages, max_tokens, system, timeout)

    if provider == "openrouter":
        return _call_openrouter(prefs, messages, max_tokens, system, timeout, model=step.get("model"))

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
    4. On error, falls back to the next provider (T-05: a short fixed
       backoff is inserted before the next attempt if it is an ADJACENT
       openrouter step and the previous openrouter step failed with a 429 --
       design.md §6.3)
    5. If all providers fail, raises RuntimeError

    Returns:
        (text, provider_record) where provider_record = {
            'providers': <resolved fallback chain, list[str] of provider names -- unchanged form>,
            'chain': <resolved fallback chain, list[{"provider", "model"}] -- NEW, T-05>,
            'used': <name of the provider that succeeded -- unchanged form>,
            'used_model': <model of the winning step, None for claude/ollama -- NEW, T-05>,
            'used_step_index': <0-based index of the winning step in 'chain' -- NEW, T-05>,
            'errors': [(error_key, str(exc)), ...],
                # error_key is "provider" for claude/ollama (unchanged), and
                # "openrouter:<model>" for openrouter steps (T-05, design.md §6.4) --
                # e.g. ("openrouter:qwen/qwen3-32b", "429 Too Many Requests")
        }
    """
    prefs = _load_llm_prefs()
    prefs = _migrate_legacy_prefs(prefs)

    group = _resolve_group(operation)
    # T-03: _resolve_chain returns normalized steps [{"provider", "model"}, ...].
    # T-04: step["model"] is now threaded through _call_provider/_call_openrouter
    # (see below), so a chain with multiple openrouter steps can each use a
    # different model instead of the single global prefs["openrouter_model"].
    # `chain` (list[str] of provider names) is kept as-is for
    # _is_provider_available()/logging/the 'providers' key of provider_record.
    # T-05 additionally threads the full `steps` (with models) into
    # provider_record as 'chain', plus 'used_model'/'used_step_index', and
    # applies a short backoff between adjacent openrouter steps after a 429.
    steps = _resolve_chain(group, prefs)
    chain = [step["provider"] for step in steps]

    logger.info("call_detailed: operation=%s, group=%s, chain=%s", operation, group, chain)

    import time as _time
    _t0 = _time.monotonic_ns()

    # T-06: Langfuse trace for the entire call_detailed() operation
    lf = get_langfuse()
    trace = None
    if lf:
        try:
            trace = lf.trace(
                name=operation,
                input=messages if system is None else [{"role": "system", "content": system}] + messages,
                metadata={
                    "operation": operation,
                    "group": group,
                    "provider_chain": chain,
                },
                tags=[group, operation],
            )
        except Exception as exc:
            logger.warning("call_detailed: failed to create Langfuse trace: %s", exc)
            trace = None

    errors: list[tuple[str, str]] = []
    # T-05: set when an openrouter step just failed with a 429 -- consumed
    # (and reset) at the start of the next attempted step if that step is
    # also openrouter, to insert a short backoff before hammering it again.
    pending_openrouter_429_backoff = False

    for i, step in enumerate(steps):
        provider = step["provider"]
        if not _is_provider_available(provider, prefs):
            logger.info(
                "call_detailed: skipping %s (not available), operation=%s",
                provider, operation,
            )
            continue

        if pending_openrouter_429_backoff and provider == "openrouter":
            logger.info(
                "call_detailed: applying %.1fs backoff before next openrouter step "
                "(model=%s) after previous openrouter step hit 429, operation=%s",
                OPENROUTER_429_BACKOFF_SECONDS, step.get("model"), operation,
            )
            _time.sleep(OPENROUTER_429_BACKOFF_SECONDS)
        pending_openrouter_429_backoff = False

        try:
            logger.info(
                "call_detailed: trying provider=%s (%d/%d), operation=%s",
                provider, i + 1, len(chain), operation,
            )
            result, usage = _call_provider(step, prefs, messages, max_tokens, system, timeout)
            used_model = step.get("model")
            provider_record = {
                "providers": chain,
                "chain": steps,
                "used": provider,
                "used_model": used_model,
                "used_step_index": i,
                "errors": errors,
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "model": usage.get("model"),
            }
            logger.info(
                "call_detailed: success, operation=%s, provider=%s, model=%s, "
                "output_len=%d, input_tokens=%s, output_tokens=%s",
                operation, provider, used_model, len(result),
                usage.get("input_tokens"), usage.get("output_tokens"),
            )
            # T-06: record successful generation in Langfuse
            if trace:
                try:
                    lf_usage = {}
                    if usage.get("input_tokens") is not None:
                        lf_usage["input"] = usage["input_tokens"]
                    if usage.get("output_tokens") is not None:
                        lf_usage["output"] = usage["output_tokens"]
                    trace.generation(
                        name=f"{provider}:{usage.get('model', 'unknown')}",
                        model=usage.get("model", "unknown"),
                        input=messages if system is None else [{"role": "system", "content": system}] + messages,
                        output=result,
                        usage=lf_usage if lf_usage else None,
                        metadata={
                            "provider": provider,
                            "step_index": i,
                            "fallback_errors_before": len(errors),
                        },
                        level="DEFAULT",
                    )
                except Exception as lf_exc:
                    logger.warning("call_detailed: failed to record Langfuse generation: %s", lf_exc)
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
                        "chain_steps": steps,
                        "used_provider": provider,
                        "used_model": used_model,
                        "fallback_count": len(errors),
                        "fallback_errors": [{"provider": p, "error": e} for p, e in errors],
                        "output_len": len(result),
                        "input_tokens": usage.get("input_tokens"),
                        "output_tokens": usage.get("output_tokens"),
                    },
                    duration_ms=_duration,
                    source="llm-client",
                )
            except Exception:
                pass
            return result, provider_record

        except Exception as exc:
            if provider == "openrouter":
                error_key = f"openrouter:{step.get('model')}"
                if _is_rate_limit_error(exc):
                    pending_openrouter_429_backoff = True
                    logger.warning(
                        "call_detailed: openrouter step model=%s hit a 429 rate limit, "
                        "operation=%s", step.get("model"), operation,
                    )
            else:
                error_key = provider
            errors.append((error_key, str(exc)))
            # T-06: record failed generation in Langfuse
            if trace:
                try:
                    trace.generation(
                        name=f"{provider}:{step.get('model', 'unknown')}",
                        model=step.get("model", "unknown"),
                        input=messages if system is None else [{"role": "system", "content": system}] + messages,
                        metadata={
                            "provider": provider,
                            "step_index": i,
                            "error": str(exc),
                        },
                        level="ERROR",
                        status_message=str(exc)[:500],
                    )
                except Exception as lf_exc:
                    logger.warning("call_detailed: failed to record error generation: %s", lf_exc)
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
                "chain_steps": steps,
                "errors": [{"provider": p, "error": e} for p, e in errors],
            },
            duration_ms=_duration,
            source="llm-client",
        )
    except Exception:
        pass
    # T-06: update Langfuse trace with final failure status
    if trace:
        try:
            trace.update(
                metadata={"final_status": "all_providers_failed", "errors": len(errors)},
                level="ERROR",
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
