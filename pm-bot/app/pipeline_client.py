import logging
import os

import requests

logger = logging.getLogger(__name__)

PIPELINE_API_URL = os.getenv("PIPELINE_API_URL", "http://idea-pipeline:8100")
PIPELINE_API_KEY = os.getenv("PIPELINE_API_KEY", "")
REQUEST_TIMEOUT = 10


def _headers() -> dict:
    headers = {"Content-Type": "application/json"}
    if PIPELINE_API_KEY:
        headers["X-Pipeline-Key"] = PIPELINE_API_KEY
    return headers


def run_pipeline(text: str | None = None, file_path: str | None = None, start_from: str = "analyst", notify_chat_id: str | None = None) -> dict:
    """Launch a new pipeline. Returns API response dict."""
    url = f"{PIPELINE_API_URL}/pipeline/run"
    payload = {"start_from": start_from}
    if text is not None:
        payload["text"] = text
    if file_path is not None:
        payload["file_path"] = file_path
    if notify_chat_id is not None:
        payload["notify_chat_id"] = notify_chat_id

    logger.info("pipeline_client.run_pipeline: url=%s, start_from=%s, has_text=%s, has_file=%s",
                url, start_from, text is not None, file_path is not None)

    resp = requests.post(url, json=payload, headers=_headers(), timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    logger.info("pipeline_client.run_pipeline: status=%d, pipeline_id=%s",
                resp.status_code, data.get("pipeline_id"))
    return data


def get_status(pipeline_id: str) -> dict:
    """Get pipeline status. Returns API response dict."""
    url = f"{PIPELINE_API_URL}/pipeline/{pipeline_id}"
    logger.info("pipeline_client.get_status: url=%s", url)

    resp = requests.get(url, headers=_headers(), timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    logger.info("pipeline_client.get_status: status=%d, pipeline_status=%s",
                resp.status_code, data.get("status"))
    return data


def resume_pipeline(pipeline_id: str, start_from: str) -> dict:
    """Resume pipeline from a specific stage. Returns API response dict."""
    url = f"{PIPELINE_API_URL}/pipeline/{pipeline_id}/resume"
    payload = {"start_from": start_from}

    logger.info("pipeline_client.resume_pipeline: url=%s, start_from=%s", url, start_from)

    resp = requests.post(url, json=payload, headers=_headers(), timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    logger.info("pipeline_client.resume_pipeline: status=%d", resp.status_code)
    return data


def list_pipelines(limit: int = 20, status: str | None = None) -> dict:
    """List pipeline runs. Returns API response dict."""
    url = f"{PIPELINE_API_URL}/pipeline/"
    params = {"limit": limit}
    if status:
        params["status"] = status

    logger.info("pipeline_client.list_pipelines: url=%s, limit=%d, status=%s",
                url, limit, status)

    resp = requests.get(url, params=params, headers=_headers(), timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    logger.info("pipeline_client.list_pipelines: status=%d, total=%s",
                resp.status_code, data.get("total"))
    return data
