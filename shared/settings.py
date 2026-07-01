"""Centralized settings for pm_assistant monorepo."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {
    "timeouts": {
        "enrich": 30,
        "synthesize": 120,
        "fetch_meetings": 120,
        "jira_sync": 120,
        "jira_import": 60,
        "jira_create": 120,
        "jira_projects": 30,
        "jira_epics": 30,
        "jira_issue_types": 30,
        "lint": 60,
        "status": 60,
        "rebuild_index": 60,
        "ingest_clippings": 120,
        "health": 60,
        "default": 60,
    },
    "cooldowns": {
        "enrichment_reminder_hours": 24,
        "health_history_days": 90,
        "enrichment_cleanup_days": 90,
    },
    "cache_ttl": {
        "vault_api_seconds": 30,
        "jira_cache_seconds": 300,
        "domains_cache_seconds": 60,
        "openrouter_models_seconds": 3600,
    },
    "rate_limits": {
        "telegram_messages_per_second": 1,
        "telegram_retry_after_default": 5,
        "telegram_max_queue_size": 50,
    },
    "paths": {
        "db_dir": "/data",
    },
    "ports": {
        "ke_api": 8001,
    },
    "queue": {
        "max_attempts": 5,
        "stuck_threshold_seconds": 1800,
        "process_timeout": 180,
        "batch_limit": 0,
    },
}

_settings_cache: dict[str, Any] | None = None


def _deep_merge(base: dict, override: dict) -> dict:
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_settings(path: str | None = None) -> dict[str, Any]:
    global _settings_cache

    search_paths = []
    if path:
        search_paths.append(Path(path))
    env_path = os.getenv("SETTINGS_PATH")
    if env_path:
        search_paths.append(Path(env_path))
    search_paths.append(Path("/app/settings.yaml"))
    search_paths.append(Path("./settings.yaml"))

    for p in search_paths:
        if p.is_file():
            try:
                with open(p) as f:
                    user_settings = yaml.safe_load(f) or {}
                merged = _deep_merge(DEFAULTS, user_settings)
                logger.info("settings loaded from %s", p)
                _settings_cache = merged
                return merged
            except (yaml.YAMLError, OSError) as exc:
                logger.warning("failed to load settings from %s: %s, using defaults", p, exc)
                _settings_cache = DEFAULTS.copy()
                return _settings_cache

    logger.warning("no settings.yaml found, using defaults")
    _settings_cache = DEFAULTS.copy()
    return _settings_cache


def get_settings() -> dict[str, Any]:
    if _settings_cache is not None:
        return _settings_cache
    return load_settings()


def get(key: str, default: Any = None) -> Any:
    settings = get_settings()
    parts = key.split(".")
    current: Any = settings
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return default
    return current
