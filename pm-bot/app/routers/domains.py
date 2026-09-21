"""Domains: агрегированная статистика по доменам vault.

Считает количество артефактов каждого типа на домен и обогащает
результат метаданными (display_name, description, color, jira_labels)
из domain-config.yaml.
"""

import logging
from datetime import datetime

from fastapi import APIRouter

from shared import domain_config
from shared.vault_paths import all_domains, wiki_domain_dir

from ..vault_cache import _cache
from ..vault_scanner import _ARTIFACT_TYPES, _is_service_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Domains"])


@router.get("/api/v1/domains")
def get_domains():
    """List all domains with artifact counts and last_updated.

    For each domain, counts .md files (excluding service files like index.md
    and log.md) in every artifact subdirectory, and finds the most recent
    file modification time across all artifact directories.

    Returns a list of domain objects sorted alphabetically by name.
    """
    logger.info("GET /api/v1/domains -- start")

    cached = _cache.get("domains")
    if cached is not None:
        logger.info("GET /api/v1/domains -- returning cached (%d domains)", len(cached))
        return cached

    domains = all_domains()
    logger.info("GET /api/v1/domains -- found %d domains", len(domains))

    results = []
    for domain in domains:
        logger.debug("GET /api/v1/domains -- processing domain '%s'", domain)
        counts: dict[str, int] = {}
        latest_mtime: float | None = None

        for artifact_type in _ARTIFACT_TYPES:
            try:
                folder = wiki_domain_dir(domain, artifact_type)
            except ValueError as exc:
                logger.error(
                    "GET /api/v1/domains -- invalid artifact_type '%s': %s",
                    artifact_type, exc,
                )
                counts[f"{artifact_type}_count"] = 0
                continue

            if not folder.exists():
                logger.debug(
                    "GET /api/v1/domains -- folder does not exist: %s/%s",
                    domain, artifact_type,
                )
                counts[f"{artifact_type}_count"] = 0
                continue

            md_files = [
                f for f in folder.glob("*.md") if not _is_service_file(f)
            ]
            counts[f"{artifact_type}_count"] = len(md_files)
            logger.debug(
                "GET /api/v1/domains -- %s/%s: %d files",
                domain, artifact_type, len(md_files),
            )

            if md_files:
                try:
                    dir_mtime = folder.stat().st_mtime
                    if latest_mtime is None or dir_mtime > latest_mtime:
                        latest_mtime = dir_mtime
                except OSError as exc:
                    logger.debug(
                        "GET /api/v1/domains -- failed to stat folder %s: %s",
                        folder, exc,
                    )

        total = sum(counts.values())

        if latest_mtime is not None:
            last_updated = datetime.fromtimestamp(latest_mtime).strftime(
                "%Y-%m-%d"
            )
        else:
            last_updated = None

        logger.debug(
            "GET /api/v1/domains -- domain '%s': total=%d, last_updated=%s",
            domain, total, last_updated,
        )

        results.append(
            {
                "name": domain,
                **counts,
                "total_count": total,
                "last_updated": last_updated,
            }
        )

    results.sort(key=lambda d: d["name"])

    # Enrich each domain with metadata from domain-config.yaml
    try:
        config = domain_config.load()
        config_domains = config.get("domains", {})
        for item in results:
            name = item["name"]
            if name in config_domains:
                cfg = config_domains[name]
                item["display_name"] = cfg.get("display_name", name)
                item["description"] = cfg.get("description", "")
                item["color"] = cfg.get("color", "#607D8B")
                item["jira_labels"] = cfg.get("jira_labels", [])
                logger.debug(
                    "GET /api/v1/domains -- enriched domain '%s' from config"
                    " (display_name=%r, color=%r, jira_labels=%r)",
                    name,
                    item["display_name"],
                    item["color"],
                    item["jira_labels"],
                )
            else:
                item["display_name"] = name
                item["description"] = ""
                item["color"] = "#607D8B"
                item["jira_labels"] = []
                logger.debug(
                    "GET /api/v1/domains -- domain '%s' not in config, using defaults",
                    name,
                )
        logger.info(
            "GET /api/v1/domains -- config enrichment complete for %d domains",
            len(results),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "GET /api/v1/domains -- config enrichment failed, using defaults: %s",
            exc,
        )
        for item in results:
            item.setdefault("display_name", item["name"])
            item.setdefault("description", "")
            item.setdefault("color", "#607D8B")
            item.setdefault("jira_labels", [])

    logger.info("GET /api/v1/domains -- returning %d domains", len(results))
    _cache.set("domains", results)
    return results
