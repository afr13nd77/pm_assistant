"""Domain config endpoints: чтение, создание/обновление, сидирование domain-config.yaml."""

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from shared.vault_paths import VAULT_PATH, all_domains

from ..vault_cache import _cache
from ..vault_scanner import _ARTIFACT_TYPES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Config"])


class DomainConfigEntry(BaseModel):
    display_name: str
    description: str = ""
    color: str = "#607D8B"
    jira_labels: list[str] = []


# ---------------------------------------------------------------------------
# Domain config endpoints
# ---------------------------------------------------------------------------

@router.get("/api/v1/domain-config")
def get_domain_config():
    """Return the full domain configuration."""
    logger.info("GET /api/v1/domain-config — start")
    from shared import domain_config

    try:
        config = domain_config.load()
        logger.info(
            "GET /api/v1/domain-config — loaded config with %d domain(s)",
            len(config.get("domains", {})),
        )
    except Exception as exc:
        logger.error("GET /api/v1/domain-config — failed to load config: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    if not config.get("domains"):
        logger.info("GET /api/v1/domain-config — no domains found, returning fallback response")
        return JSONResponse(content={
            "domains": {},
            "_fallback": True,
            "_message": "domain-config.yaml not found or empty",
        })

    logger.info(
        "GET /api/v1/domain-config — returning %d domain(s)", len(config["domains"])
    )
    return config


@router.put("/api/v1/domain-config/{domain_slug}")
def put_domain_config(domain_slug: str, entry: DomainConfigEntry):
    """Create or update a domain config entry."""
    logger.info("PUT /api/v1/domain-config/%s — start", domain_slug)
    from shared import domain_config as _domain_config

    # Check if domain exists before update
    try:
        existing = _domain_config.get_domain(domain_slug)
    except Exception as exc:
        logger.error(
            "PUT /api/v1/domain-config/%s — error checking existing domain: %s",
            domain_slug, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(exc))

    is_new = existing is None
    logger.info(
        "PUT /api/v1/domain-config/%s — is_new=%s", domain_slug, is_new
    )

    try:
        _domain_config.set_domain(domain_slug, entry.model_dump())
        _cache.invalidate()
        logger.info(
            "PUT /api/v1/domain-config/%s — set_domain succeeded", domain_slug
        )
    except ValueError as exc:
        error_msg = str(exc)
        logger.warning(
            "PUT /api/v1/domain-config/%s — validation error: %s", domain_slug, error_msg
        )
        if "already owned by" in error_msg or "already mapped" in error_msg:
            raise HTTPException(status_code=409, detail=error_msg)
        raise HTTPException(status_code=422, detail=error_msg)
    except Exception as exc:
        logger.error(
            "PUT /api/v1/domain-config/%s — unexpected error: %s",
            domain_slug, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(exc))

    # Scaffold domain directories if this is a new domain
    scaffold = False
    if is_new:
        domain_base = VAULT_PATH / "wiki" / "domains" / domain_slug
        if not domain_base.exists():
            logger.info(
                "PUT /api/v1/domain-config/%s — domain dir not found, scaffolding: %s",
                domain_slug, domain_base,
            )
            try:
                for art_type in _ARTIFACT_TYPES:
                    art_dir = domain_base / art_type
                    art_dir.mkdir(parents=True, exist_ok=True)
                    logger.info(
                        "PUT /api/v1/domain-config/%s — created dir: %s",
                        domain_slug, art_dir,
                    )
                scaffold = True
                logger.info(
                    "PUT /api/v1/domain-config/%s — scaffold complete (%d dirs created)",
                    domain_slug, len(_ARTIFACT_TYPES),
                )
            except Exception as exc:
                logger.error(
                    "PUT /api/v1/domain-config/%s — scaffold failed: %s",
                    domain_slug, exc, exc_info=True,
                )
        else:
            logger.info(
                "PUT /api/v1/domain-config/%s — domain dir already exists, skipping scaffold",
                domain_slug,
            )

    status_code = 201 if is_new else 200
    action = "created" if is_new else "updated"
    logger.info(
        "PUT /api/v1/domain-config/%s — returning status=%d action=%s scaffold=%s",
        domain_slug, status_code, action, scaffold,
    )
    return JSONResponse(
        content={
            "status": "ok",
            "domain": domain_slug,
            "action": action,
            "scaffold": scaffold,
        },
        status_code=status_code,
    )


@router.post("/api/v1/domain-config/seed")
def seed_domain_config():
    """Seed config from hardcoded defaults + filesystem domains. Idempotent."""
    logger.info("POST /api/v1/domain-config/seed — start")
    from shared import domain_config as _domain_config

    # Hardcoded label→domain map (mirrors knowledge-engine mapper defaults)
    LABEL_TO_DOMAIN = {
        "dictionary": "static-metadata",
        "suggester": "suggester",
        "search": "search-engine",
        "partner_search": "partner-search-engine",
    }
    logger.info(
        "POST /api/v1/domain-config/seed — hardcoded map has %d label(s)", len(LABEL_TO_DOMAIN)
    )

    existing = all_domains()
    logger.info(
        "POST /api/v1/domain-config/seed — found %d filesystem domain(s)", len(existing)
    )

    path = _domain_config.config_path()
    already_exists = path.exists()
    logger.info(
        "POST /api/v1/domain-config/seed — config already_exists=%s at %s",
        already_exists, path,
    )

    try:
        config = _domain_config.seed_from_defaults(LABEL_TO_DOMAIN, existing)
        _cache.invalidate()
        domains_count = len(config.get("domains", {}))
        logger.info(
            "POST /api/v1/domain-config/seed — seed_from_defaults returned %d domain(s)",
            domains_count,
        )
    except Exception as exc:
        logger.error(
            "POST /api/v1/domain-config/seed — seed_from_defaults failed: %s",
            exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(exc))

    action = "already_exists" if already_exists else "seeded"
    logger.info(
        "POST /api/v1/domain-config/seed — done, action=%s domains_count=%d",
        action, domains_count,
    )
    return {
        "status": "ok",
        "action": action,
        "domains_count": domains_count,
    }
