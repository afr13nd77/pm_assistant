"""HTTP client for OpenRouter API (OpenAI Chat Completions format).

Used by llm_client.call_transcription() for meeting transcript processing.
"""

import logging
import os

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "qwen/qwen3-next-80b-a3b-instruct:free"
DEFAULT_TIMEOUT = 120

AVAILABLE_MODELS: list[dict[str, str]] = [
    {"id": "qwen/qwen3-next-80b-a3b-instruct:free", "name": "Qwen3 Next 80B A3B Instruct (free)"},
    {"id": "openai/gpt-oss-120b:free", "name": "GPT-OSS 120B (free)"},
    {"id": "openai/gpt-oss-20b:free", "name": "GPT-OSS 20B (free)"},
    {"id": "openrouter/owl-alpha", "name": "Owl Alpha"},
]


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
) -> str:
    """Send chat completion request to OpenRouter API.

    Returns the model's text response.

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
        json=payload,
        headers=headers,
        timeout=timeout,
    )
    response.raise_for_status()

    data = response.json()

    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        logger.error(
            "openrouter_client.call: unexpected response structure: %s",
            data,
        )
        raise RuntimeError(
            f"OpenRouter: unexpected response format: {exc}"
        ) from exc

    logger.info(
        "openrouter_client.call: success, model=%s, output_len=%d",
        model, len(text),
    )
    return text


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


# Prevent pytest from collecting test_connection() as a test case
# (it is a utility function, not a unit test)
test_connection.__test__ = False
