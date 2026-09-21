"""Системные эндпоинты: статус сервера и журнал операций."""

import logging
import os
from datetime import datetime

from fastapi import APIRouter, HTTPException

from ..vault_cache import _cache
from shared.vault_paths import VAULT_PATH

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["System"])


# ---------------------------------------------------------------------------
# System status endpoint
# ---------------------------------------------------------------------------

@router.get("/api/v1/system/status")
async def system_status():
    """Return system health: bot online flag, Jira sync time, STT status, vault freshness."""
    cached = _cache.get("system_status")
    if cached is not None:
        logger.info("system_status — returning cached")
        return cached

    # bot_online: the fact that this endpoint responds means the server is alive
    bot_online = True

    # stt_enabled: from environment variable
    stt_enabled = os.getenv("STT_ENABLED", "0").strip().lower() in ("1", "true", "yes")

    # vault_last_updated: check mtime of key directories instead of walking all files
    vault_last_updated = None
    try:
        check_dirs = [
            VAULT_PATH / "wiki" / "domains",
            VAULT_PATH / "wiki" / "meetings",
            VAULT_PATH / "wiki" / "reports",
        ]
        for d in check_dirs:
            if d.exists():
                try:
                    mtime = d.stat().st_mtime
                    if vault_last_updated is None or mtime > vault_last_updated:
                        vault_last_updated = mtime
                except OSError:
                    pass
    except Exception as exc:
        logger.warning("system_status — vault check error: %s", exc)

    vault_last_updated_iso = (
        datetime.utcfromtimestamp(vault_last_updated).isoformat() + "Z"
        if vault_last_updated is not None else None
    )

    # jira_last_sync: read from marker file written by Jira sync job
    jira_marker = VAULT_PATH / ".jira_last_sync"
    jira_last_sync = None
    if jira_marker.exists():
        try:
            content = jira_marker.read_text(encoding="utf-8").strip()
            jira_last_sync = content if content else None
        except Exception as exc:
            logger.warning("system_status — jira marker read error: %s", exc)

    logger.info(
        "system_status — bot_online=%s stt=%s vault_updated=%s jira_sync=%s",
        bot_online, stt_enabled, vault_last_updated_iso, jira_last_sync,
    )
    result = {
        "bot_online": bot_online,
        "jira_last_sync": jira_last_sync,
        "stt_enabled": stt_enabled,
        "vault_last_updated": vault_last_updated_iso,
    }
    _cache.set("system_status", result)
    return result


# ---------------------------------------------------------------------------
# System Log endpoints
# ---------------------------------------------------------------------------


@router.get("/api/v1/system-log")
async def get_system_log(
    period: str = "24h",
    process_type: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    """Журнал системных операций с фильтрацией и пагинацией."""
    logger.info(
        "GET /api/v1/system-log — period=%s process_type=%s status=%s limit=%d offset=%d",
        period, process_type, status, limit, offset,
    )
    try:
        from shared.system_log import query_log
        result = query_log(
            period=period,
            process_type=process_type,
            status=status,
            limit=limit,
            offset=offset,
        )
        logger.info("GET /api/v1/system-log — returning %d entries (total=%d)", len(result["entries"]), result["total"])
        return result
    except Exception as exc:
        logger.error("GET /api/v1/system-log — error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/v1/system-log/stats")
async def get_system_log_stats():
    """Статистика ошибок за 24ч для overview badge."""
    logger.info("GET /api/v1/system-log/stats")
    try:
        from shared.system_log import get_stats
        result = get_stats()
        logger.info("GET /api/v1/system-log/stats — total=%d errors=%d", result["last_24h"]["total"], result["last_24h"]["error"])
        return result
    except Exception as exc:
        logger.error("GET /api/v1/system-log/stats — error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
