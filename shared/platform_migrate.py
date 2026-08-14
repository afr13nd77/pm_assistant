"""One-time migration of platform state files from vault to dedicated volumes.

Called at startup by pm-bot and knowledge-engine. If a file exists in
VAULT_PATH (old location) but not in its new location, it is copied over.
Original files in vault are NOT deleted — the user can remove them manually.
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

_VAULT_PATH = Path(os.getenv("VAULT_PATH", "/vault"))

_MIGRATIONS = [
    # (filename, env_var_for_new_location, default_new_path)
    (".system-log.db", "PLATFORM_DATA_PATH", "/platform-data"),
    (".system-log.db-wal", "PLATFORM_DATA_PATH", "/platform-data"),
    (".system-log.db-shm", "PLATFORM_DATA_PATH", "/platform-data"),
    (".jira-sync-state.json", "PLATFORM_DATA_PATH", "/platform-data"),
    (".pm-user-prefs.json", "PM_BOT_DATA_PATH", "/data"),
    (".health-history.json", "KE_DATA_PATH", "/data"),
    (".meeting-fetcher-state.json", "KE_DATA_PATH", "/data"),
    (".enrichment-reminders.db", "PM_BOT_DATA_PATH", "/data"),
]


def migrate_platform_files() -> None:
    """Copy platform state files from vault to their new volume locations."""
    for filename, env_var, default_path in _MIGRATIONS:
        old = _VAULT_PATH / filename
        new_dir = Path(os.getenv(env_var, default_path))
        new = new_dir / filename

        if not old.exists():
            continue
        if new.exists():
            logger.debug("migrate_platform_files: %s already at %s, skipping", filename, new)
            continue

        try:
            new_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(old), str(new))
            logger.info("migrate_platform_files: copied %s → %s", old, new)
        except Exception as exc:
            logger.warning("migrate_platform_files: failed to copy %s: %s", filename, exc)
