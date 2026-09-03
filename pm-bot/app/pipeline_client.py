"""HTTP client for Idea Pipeline API."""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

from shared.settings import get as get_setting

logger = logging.getLogger(__name__)

PIPELINE_API_URL = os.getenv("PIPELINE_API_URL", "http://idea-pipeline:8100")
PIPELINE_API_KEY = os.getenv("PIPELINE_API_KEY", "")


def _get_timeout(operation: str) -> int:
    """Get timeout for operation from settings."""
    return get_setting(f"timeouts.{operation}", get_setting("timeouts.default", 60))


def _headers() -> dict:
    """Build request headers with optional API key."""
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if PIPELINE_API_KEY:
        headers["X-Pipeline-Key"] = PIPELINE_API_KEY
    return headers


def _post(path: str, timeout: int, json: dict | None = None) -> dict:
    """POST request to Pipeline API."""
    url = f"{PIPELINE_API_URL}{path}"
    logger.info("pipeline_client POST %s", url)
    resp = requests.post(url, json=json or {}, headers=_headers(), timeout=timeout)
    resp.raise_for_status()
    result = resp.json()
    logger.info("pipeline_client POST %s -> status=%s", url, result.get("status", "ok"))
    return result


def _get(path: str, timeout: int, params: dict | None = None) -> Any:
    """GET request to Pipeline API."""
    url = f"{PIPELINE_API_URL}{path}"
    logger.info("pipeline_client GET %s", url)
    resp = requests.get(url, params=params, headers=_headers(), timeout=timeout)
    resp.raise_for_status()
    result = resp.json()
    status = result.get("status", "ok") if isinstance(result, dict) else "ok"
    logger.info("pipeline_client GET %s -> status=%s, type=%s", url, status, type(result).__name__)
    return result


# ---------------------------------------------------------------------------
# 1. POST /pipeline/run
# ---------------------------------------------------------------------------

def run_pipeline(
    text: str | None = None,
    file_path: str | None = None,
    start_from: str = "analyst",
    notify_chat_id: str | None = None,
) -> dict:
    """Launch a new pipeline. Returns API response dict."""
    payload: dict[str, Any] = {"start_from": start_from}
    if text is not None:
        payload["text"] = text
    if file_path is not None:
        payload["file_path"] = file_path
    if notify_chat_id is not None:
        payload["notify_chat_id"] = notify_chat_id

    logger.info(
        "run_pipeline: start_from=%s, has_text=%s, has_file=%s",
        start_from, text is not None, file_path is not None,
    )
    return _post("/pipeline/run", _get_timeout("pipeline_run"), json=payload)


# ---------------------------------------------------------------------------
# 2. GET /pipeline/{pipeline_id}
# ---------------------------------------------------------------------------

def get_status(pipeline_id: str) -> dict:
    """Get pipeline status. Returns API response dict."""
    logger.info("get_status: pipeline_id=%s", pipeline_id)
    return _get(f"/pipeline/{pipeline_id}", _get_timeout("default"))


# ---------------------------------------------------------------------------
# 3. POST /pipeline/{pipeline_id}/resume
# ---------------------------------------------------------------------------

def resume_pipeline(pipeline_id: str, start_from: str) -> dict:
    """Resume pipeline from a specific stage. Returns API response dict."""
    logger.info("resume_pipeline: pipeline_id=%s, start_from=%s", pipeline_id, start_from)
    return _post(
        f"/pipeline/{pipeline_id}/resume",
        _get_timeout("pipeline_run"),
        json={"start_from": start_from},
    )


# ---------------------------------------------------------------------------
# 4. GET /pipeline/
# ---------------------------------------------------------------------------

def list_pipelines(limit: int = 20, status: str | None = None) -> dict:
    """List pipeline runs. Returns API response dict."""
    params: dict[str, int | str] = {"limit": limit}
    if status:
        params["status"] = status

    logger.info("list_pipelines: limit=%d, status=%s", limit, status)
    return _get("/pipeline/", _get_timeout("default"), params=params)


# ---------------------------------------------------------------------------
# 5. GET /api/v1/prompts
# ---------------------------------------------------------------------------

def get_prompts() -> dict:
    """Get all pipeline prompts."""
    logger.info("get_prompts: fetching pipeline prompts")
    return _get("/api/v1/prompts", _get_timeout("default"))


# ---------------------------------------------------------------------------
# 6. POST /api/v1/prompts/{name}
# ---------------------------------------------------------------------------

def save_prompt(name: str, content: str) -> dict:
    """Save a pipeline prompt by name."""
    logger.info("save_prompt: name=%s, content_len=%d", name, len(content))
    return _post(
        f"/api/v1/prompts/{name}",
        _get_timeout("default"),
        json={"content": content},
    )


# ---------------------------------------------------------------------------
# 7. POST /api/v1/prompts/{name}/reset
# ---------------------------------------------------------------------------

def reset_prompt(name: str) -> dict:
    """Reset a pipeline prompt to default."""
    logger.info("reset_prompt: name=%s", name)
    return _post(f"/api/v1/prompts/{name}/reset", _get_timeout("default"))
