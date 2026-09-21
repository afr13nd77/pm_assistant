import logging
import os

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Settings"])


class SettingsModel(BaseModel):
    vault_path: str = ""
    transcripts_path: str = ""


@router.get("/api/v1/settings")
def get_settings():
    """Read current settings from environment."""
    logger.info("GET /api/v1/settings — start")

    settings = {
        "vault_path": os.getenv("VAULT_PATH", "/vault"),
        "transcripts_path": os.getenv("TRANSCRIPTS_INBOX", "/transcripts/inbox"),
    }

    logger.info("GET /api/v1/settings — done")
    return settings


@router.post("/api/v1/settings")
def save_settings(settings: SettingsModel):
    """Save settings (prompts managed via /api/v1/prompts/*)."""
    logger.info("POST /api/v1/settings — start")
    logger.info("POST /api/v1/settings — done")
    return {"status": "ok"}
