"""HTTP client for OpenRouter API (OpenAI Chat Completions format).

Used by llm_client.call_transcription() for meeting transcript processing.
"""

import logging
import os
import time
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "qwen/qwen3-next-80b-a3b-instruct:free"
DEFAULT_TIMEOUT = 120
MODELS_LIST_TIMEOUT = 10

AVAILABLE_MODELS: list[dict[str, str]] = [
    {"id": "qwen/qwen3-next-80b-a3b-instruct:free", "name": "Qwen3 Next 80B A3B Instruct (free)"},
    {"id": "openai/gpt-oss-120b:free", "name": "GPT-OSS 120B (free)"},
    {"id": "openai/gpt-oss-20b:free", "name": "GPT-OSS 20B (free)"},
]

# Module-level TTL cache for list_models() (design.md §3.1: in-memory, single-process).
_models_cache: dict | None = None
_models_cache_ts: float = 0.0


def _get_api_key() -> str | None:
    """Return OpenRouter API key from environment, or None."""
    key = os.getenv("OPENROUTER_API_KEY")
    if key:
        logger.debug("_get_api_key: OPENROUTER_API_KEY is set (len=%d)", len(key))
    else:
        logger.debug("_get_api_key: OPENROUTER_API_KEY is not set")
    return key


def _build_headers(api_key: str) -> dict[str, str]:
    """Build HTTP headers for OpenRouter request."""
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://pm-assistant.local",
        "X-OpenRouter-Title": "PM Assistant",
    }


def call(
    messages: list[dict],
    model: str = DEFAULT_MODEL,
    max_tokens: int = 4000,
    timeout: int = DEFAULT_TIMEOUT,
) -> tuple[str, dict]:
    """Send chat completion request to OpenRouter API.

    Returns a tuple of (text_response, usage_dict).
    usage_dict contains: input_tokens, output_tokens, model.

    Raises:
        ValueError: if OPENROUTER_API_KEY is not set.
        requests.RequestException: on network errors.
        RuntimeError: on invalid API response structure.
    """
    api_key = _get_api_key()
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY is not set in environment")

    openai_messages = []
    for msg in messages:
        openai_messages.append({
            "role": msg["role"],
            "content": msg["content"],
        })

    payload = {
        "model": model,
        "messages": openai_messages,
        "max_tokens": max_tokens,
    }

    headers = _build_headers(api_key)

    logger.info(
        "openrouter_client.call: model=%s, messages=%d, max_tokens=%d, timeout=%d",
        model, len(messages), max_tokens, timeout,
    )

    response = requests.post(
        f"{BASE_URL}/chat/completions",
        json=payload,  # type: ignore[arg-type]
        headers=headers,
        timeout=timeout,
    )
    response.raise_for_status()

    raw_body = response.text
    try:
        data = response.json()
    except Exception as json_exc:
        logger.error(
            "openrouter_client.call: response is not valid JSON, model=%s, status=%d, body=%s",
            model, response.status_code, raw_body[:2000],
        )
        raise RuntimeError(
            f"OpenRouter: response is not valid JSON: {json_exc}"
        ) from json_exc

    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        logger.error(
            "openrouter_client.call: unexpected response structure, model=%s, keys=%s, body=%s",
            model, list(data.keys()) if isinstance(data, dict) else type(data).__name__, raw_body[:2000],
        )
        raise RuntimeError(
            f"OpenRouter: unexpected response format: {exc}"
        ) from exc

    raw_usage = data.get("usage", {})
    usage = {
        "input_tokens": raw_usage.get("prompt_tokens"),
        "output_tokens": raw_usage.get("completion_tokens"),
        "model": model,
    }

    logger.info(
        "openrouter_client.call: success, model=%s, output_len=%d, input_tokens=%s, output_tokens=%s",
        model, len(text), usage["input_tokens"], usage["output_tokens"],
    )
    return text, usage


def test_connection(api_key: str, model: str = DEFAULT_MODEL) -> dict:
    """Test OpenRouter API connectivity and model availability.

    Returns {"status": "ok", ...} or {"status": "error", "detail": "..."}.
    """
    logger.info("test_connection: testing key (len=%d), model=%s", len(api_key), model)
    headers = _build_headers(api_key)

    try:
        resp = requests.get(
            f"{BASE_URL}/models",
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
    except requests.ConnectionError as exc:
        logger.warning("test_connection: connection failed: %s", exc)
        return {"status": "error", "detail": f"Connection failed: {exc}"}
    except requests.Timeout:
        logger.warning("test_connection: timeout")
        return {"status": "error", "detail": "Timeout connecting to OpenRouter"}
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response else "unknown"
        if status_code == 401:
            logger.warning("test_connection: auth failed (401)")
            return {"status": "error", "detail": "Auth failed: Invalid API key"}
        logger.warning("test_connection: HTTP error %s: %s", status_code, exc)
        return {"status": "error", "detail": f"HTTP error {status_code}"}
    except Exception as exc:
        logger.error("test_connection: unexpected error: %s", exc)
        return {"status": "error", "detail": str(exc)}

    data = resp.json()
    models_list = data.get("data", [])
    model_found = None
    for m in models_list:
        if m.get("id") == model:
            model_found = m
            break

    if model_found:
        model_name = model_found.get("name", model)
        logger.info("test_connection: success, model=%s (%s)", model, model_name)
        return {
            "status": "ok",
            "model": model,
            "model_name": model_name,
        }

    logger.info("test_connection: model %s not in /models listing, trying probe request", model)
    try:
        probe_resp = requests.post(
            f"{BASE_URL}/chat/completions",
            headers=headers,
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Hi"}],
                "max_tokens": 1,
            },
            timeout=15,
        )
        if probe_resp.status_code == 200:
            logger.info("test_connection: probe success, model=%s is available", model)
            return {
                "status": "ok",
                "model": model,
                "model_name": model,
            }
        error_detail = probe_resp.json().get("error", {}).get("message", probe_resp.text[:200])
        logger.warning("test_connection: probe failed %d: %s", probe_resp.status_code, error_detail)
        return {"status": "error", "detail": f"Model '{model}': {error_detail}"}
    except Exception as exc:
        logger.warning("test_connection: probe error for %s: %s", model, exc)
        return {"status": "error", "detail": f"Model '{model}' not found on OpenRouter"}


def _fallback_models_result() -> dict:
    """Build the fallback response payload from AVAILABLE_MODELS.

    Not cached as live (design.md §3.1) -- next call will retry the network
    if TTL for the (absent) live cache has expired, so we don't stay stuck
    in degraded mode longer than necessary.
    """
    return {
        "models": AVAILABLE_MODELS,
        "source": "fallback",
        "cached": False,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(AVAILABLE_MODELS),
    }


def list_models(api_key: str | None, ttl_seconds: int = 3600) -> dict:
    """Return the list of available OpenRouter models with TTL cache + fallback.

    Behavior (design.md §1.2, §2.3, §3.1):
    - If a live cache entry exists and is not older than ttl_seconds, return it
      (with cached=True).
    - If api_key is empty/None, skip the network call entirely and return the
      AVAILABLE_MODELS fallback.
    - Otherwise call GET {BASE_URL}/models using the same headers/parsing
      pattern as test_connection(). On success, cache the result and return it
      (source="live", cached=False). On any error (timeout, ConnectionError,
      non-200 status, parse error), log a warning and return the fallback.

    Returns:
        {"models": [{"id": ..., "name": ...}, ...], "source": "live"|"fallback",
         "cached": bool, "fetched_at": iso8601, "count": int}
    """
    global _models_cache, _models_cache_ts

    now = time.time()
    cache_age = now - _models_cache_ts
    cache_hit = _models_cache is not None and cache_age < ttl_seconds

    logger.info(
        "list_models: operation=list_models, cache_hit=%s, ttl_seconds=%d",
        cache_hit, ttl_seconds,
    )

    if cache_hit and _models_cache is not None:
        result = dict(_models_cache)
        result["cached"] = True
        logger.info(
            "list_models: returning cached result, count=%d, age=%.1fs",
            result["count"], cache_age,
        )
        return result

    if not api_key:
        logger.warning("list_models: no api_key provided, using fallback (no network call)")
        return _fallback_models_result()

    headers = _build_headers(api_key)

    try:
        resp = requests.get(
            f"{BASE_URL}/models",
            headers=headers,
            timeout=MODELS_LIST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        raw_models = data["data"]
        models = [
            {"id": m["id"], "name": m.get("name") or m["id"]}
            for m in raw_models
        ]
    except requests.Timeout as exc:
        logger.warning("list_models: timeout fetching /models, using fallback: %s", exc)
        return _fallback_models_result()
    except requests.ConnectionError as exc:
        logger.warning("list_models: connection error fetching /models, using fallback: %s", exc)
        return _fallback_models_result()
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        logger.warning("list_models: HTTP error %s fetching /models, using fallback: %s", status_code, exc)
        return _fallback_models_result()
    except Exception as exc:
        logger.warning("list_models: unexpected error fetching /models, using fallback: %s", exc)
        return _fallback_models_result()

    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = {
        "models": models,
        "source": "live",
        "cached": False,
        "fetched_at": fetched_at,
        "count": len(models),
    }

    _models_cache = dict(result)
    _models_cache_ts = now

    logger.info("list_models: live fetch success, count=%d", len(models))
    return result


# Prevent pytest from collecting test_connection() as a test case
# (it is a utility function, not a unit test)
test_connection.__test__ = False  # type: ignore[attr-defined]
