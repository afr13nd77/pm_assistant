"""
providers.py — REST API для тестирования подключений к внешним провайдерам (BL-152 T-10).

Эндпоинты проверки доступности Ollama, OpenRouter и CalDAV,
используемые страницей настроек Web UI.
"""

import logging
import os

from fastapi import APIRouter
from pydantic import BaseModel

from ..vault_cache import _caldav_executor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Providers"])


# ---------------------------------------------------------------------------
# Test Ollama connectivity
# ---------------------------------------------------------------------------


class TestOllamaRequest(BaseModel):
    url: str


@router.post("/api/v1/test-ollama")
def test_ollama(body: TestOllamaRequest):
    logger.info("POST /api/v1/test-ollama — url=%s", body.url)
    import httpx

    base = body.url.rstrip("/")
    try:
        with httpx.Client(timeout=5.0) as http:
            ver_resp = http.get(f"{base}/api/version")
            ver_resp.raise_for_status()
            version = ver_resp.json().get("version", "unknown")
            logger.info("test-ollama: version=%s", version)

            tags_resp = http.get(f"{base}/api/tags")
            tags_resp.raise_for_status()
            models_data = tags_resp.json().get("models", [])
            model_names = [m.get("name", "") for m in models_data if m.get("name")]
            logger.info("test-ollama: found %d models", len(model_names))
    except httpx.ConnectError as exc:
        logger.warning("test-ollama: connection failed: %s", exc)
        return {"status": "error", "detail": f"Connection refused: {base}"}
    except httpx.TimeoutException as exc:
        logger.warning("test-ollama: timeout: %s", exc)
        return {"status": "error", "detail": f"Timeout connecting to {base}"}
    except Exception as exc:
        logger.error("test-ollama: unexpected error: %s", exc)
        return {"status": "error", "detail": str(exc)}

    logger.info("POST /api/v1/test-ollama — success, version=%s, models=%s", version, model_names)
    return {"status": "ok", "ollama_version": version, "models": model_names}


# ---------------------------------------------------------------------------
# OpenRouter integration
# ---------------------------------------------------------------------------


class TestOpenRouterRequest(BaseModel):
    model: str = "qwen/qwen3-32b"


@router.get("/api/v1/openrouter-key-status")
def openrouter_key_status():
    logger.info("GET /api/v1/openrouter-key-status — start")
    has_key = bool(os.getenv("OPENROUTER_API_KEY"))
    logger.info("GET /api/v1/openrouter-key-status — has_key=%s", has_key)
    return {"has_key": has_key}


@router.post("/api/v1/test-openrouter")
def test_openrouter(body: TestOpenRouterRequest):
    logger.info("POST /api/v1/test-openrouter — model=%s", body.model)
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        logger.warning("POST /api/v1/test-openrouter — OPENROUTER_API_KEY not set")
        return {"status": "error", "detail": "OPENROUTER_API_KEY is not set in environment"}
    try:
        from shared.openrouter_client import test_connection
        result = test_connection(api_key, body.model)
        logger.info("POST /api/v1/test-openrouter — result=%s", result.get("status"))
        return result
    except Exception as exc:
        logger.error("POST /api/v1/test-openrouter — error: %s", exc)
        return {"status": "error", "detail": str(exc)}


@router.get("/api/v1/openrouter-models")
def openrouter_models():
    logger.info("GET /api/v1/openrouter-models — start")
    from shared import settings as app_settings
    from shared.openrouter_client import list_models

    api_key = os.getenv("OPENROUTER_API_KEY")
    ttl = app_settings.get("cache_ttl.openrouter_models_seconds", 3600)
    result = list_models(api_key, ttl)
    logger.info(
        "GET /api/v1/openrouter-models — source=%s count=%d cached=%s",
        result.get("source"), result.get("count"), result.get("cached"),
    )
    return result


# ---------------------------------------------------------------------------
# Test CalDAV connectivity
# ---------------------------------------------------------------------------


class TestCaldavRequest(BaseModel):
    url: str = "https://caldav.yandex.ru/"
    username: str
    password: str


def _test_caldav_sync(url: str, username: str, password: str) -> dict:
    """Test CalDAV connection synchronously (runs in executor)."""
    import caldav

    logger.info("_test_caldav_sync -- connecting to %s, username=%s", url, username)
    try:
        client = caldav.DAVClient(  # type: ignore[operator]
            url=url,
            username=username,
            password=password,
        )
        principal = client.principal()
        logger.info("_test_caldav_sync -- authenticated successfully")

        calendars = principal.calendars()
        calendar_names = [getattr(c, "name", "") for c in calendars]
        logger.info("_test_caldav_sync -- found %d calendars: %s", len(calendars), calendar_names)

        return {
            "status": "ok",
            "calendars_count": len(calendars),
            "calendar_names": calendar_names,
        }
    except Exception as exc:
        exc_str = str(exc)
        if "401" in exc_str or "unauthorized" in exc_str.lower() or "authorization" in exc_str.lower():
            logger.warning("_test_caldav_sync -- authorization failed: %s", exc)
            return {"status": "error", "detail": f"Authorization failed: {exc_str}"}
        if "timeout" in exc_str.lower() or isinstance(exc, TimeoutError):
            logger.warning("_test_caldav_sync -- timeout: %s", exc)
            return {"status": "error", "detail": "Connection timeout"}
        logger.error("_test_caldav_sync -- unexpected error: %s", exc)
        return {"status": "error", "detail": exc_str}


@router.post("/api/v1/test-caldav")
async def test_caldav(body: TestCaldavRequest):
    logger.info("POST /api/v1/test-caldav -- url=%s, username=%s", body.url, body.username)
    import asyncio

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        _caldav_executor,
        _test_caldav_sync,
        body.url,
        body.username,
        body.password,
    )
    logger.info("POST /api/v1/test-caldav -- result status=%s", result.get("status"))
    return result
