import logging

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import ke_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Research Queue"])


class ResearchRetryProxyRequest(BaseModel):
    filename: str


@router.get("/api/v1/research-queue/status")
def research_queue_status_proxy():
    """Proxy: research queue status from KE."""
    logger.info("GET /api/v1/research-queue/status -- start")
    try:
        data = ke_client.research_queue_status()
        logger.info(
            "GET /api/v1/research-queue/status -- success, pending=%s",
            data.get("summary", {}).get("pending"),
        )
        return data
    except requests.RequestException as exc:
        logger.error("GET /api/v1/research-queue/status -- KE error: %s", exc)
        raise HTTPException(status_code=502, detail=f"KE API error: {exc}")
    except Exception as exc:
        logger.error(
            "GET /api/v1/research-queue/status -- error: %s", exc, exc_info=True
        )
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/v1/research-queue/run")
def research_queue_run_proxy():
    """Proxy: trigger research run via KE."""
    logger.info("POST /api/v1/research-queue/run -- start")
    try:
        data = ke_client.research_queue_run()
        logger.info(
            "POST /api/v1/research-queue/run -- success, completed=%s",
            data.get("completed"),
        )
        return data
    except requests.RequestException as exc:
        logger.error("POST /api/v1/research-queue/run -- KE error: %s", exc)
        raise HTTPException(status_code=502, detail=f"KE API error: {exc}")
    except Exception as exc:
        logger.error(
            "POST /api/v1/research-queue/run -- error: %s", exc, exc_info=True
        )
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/v1/research-queue/retry")
def research_queue_retry_proxy(req: ResearchRetryProxyRequest):
    """Proxy: retry failed research task via KE."""
    logger.info(
        "POST /api/v1/research-queue/retry -- start, filename=%s", req.filename
    )
    try:
        data = ke_client.research_queue_retry(req.filename)
        logger.info("POST /api/v1/research-queue/retry -- success")
        return data
    except requests.RequestException as exc:
        logger.error("POST /api/v1/research-queue/retry -- KE error: %s", exc)
        raise HTTPException(status_code=502, detail=f"KE API error: {exc}")
    except Exception as exc:
        logger.error(
            "POST /api/v1/research-queue/retry -- error: %s", exc, exc_info=True
        )
        raise HTTPException(status_code=500, detail=str(exc))
