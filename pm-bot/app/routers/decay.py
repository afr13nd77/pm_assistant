import logging

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import ke_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Decay"])


class DecayTouchRequest(BaseModel):
    filepath: str


class DecaySetTierRequest(BaseModel):
    filepath: str
    tier: str


@router.post("/api/v1/decay/touch")
def decay_touch(req: DecayTouchRequest):
    """Reset decay timer for a vault artifact via knowledge-engine."""
    logger.info("POST /api/v1/decay/touch — start, filepath=%s", req.filepath)
    try:
        result = ke_client.touch(req.filepath)
        logger.info("POST /api/v1/decay/touch — success: %s", result)
        return result
    except requests.RequestException as exc:
        logger.error("POST /api/v1/decay/touch — ke_client.touch failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"KE API error: {exc}")
    except Exception as exc:
        logger.error("POST /api/v1/decay/touch — error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/v1/decay/set-tier")
def decay_set_tier(req: DecaySetTierRequest):
    """Set decay tier for a vault artifact via knowledge-engine."""
    logger.info("POST /api/v1/decay/set-tier — start, filepath=%s, tier=%s", req.filepath, req.tier)
    try:
        result = ke_client.set_tier(req.filepath, req.tier)
        logger.info("POST /api/v1/decay/set-tier — success: %s", result)
        return result
    except requests.RequestException as exc:
        logger.error("POST /api/v1/decay/set-tier — ke_client.set_tier failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"KE API error: {exc}")
    except Exception as exc:
        logger.error("POST /api/v1/decay/set-tier — error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/v1/decay/snapshot")
def get_decay_snapshot():
    """Get full decay state snapshot via knowledge-engine."""
    logger.info("GET /api/v1/decay/snapshot — start")
    try:
        result = ke_client.decay_snapshot()
        total = result.get("total", 0) if isinstance(result, dict) else 0
        logger.info("GET /api/v1/decay/snapshot — success, total=%d", total)
        return result
    except requests.RequestException as exc:
        logger.error("GET /api/v1/decay/snapshot — ke_client failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"KE API error: {exc}")
    except Exception as exc:
        logger.error("GET /api/v1/decay/snapshot — error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
