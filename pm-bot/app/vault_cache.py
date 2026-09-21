"""
vault_cache.py — in-memory TTL cache and shared concurrency primitives for vault_api.py.

Содержит:
  _VaultCache — простой TTL-кэш для результатов сканирования vault
  _cache — синглтон кэша, используемый endpoints vault_api.py
  _caldav_executor — пул потоков для CalDAV-запросов
  _jira_sync_lock — блокировка на время синхронизации Jira
  _PLATFORM_DATA — путь к директории данных платформы (state-файлы)
"""

import logging
import os
import threading
import time as _time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PLATFORM_DATA = Path(os.getenv("PLATFORM_DATA_PATH", os.getenv("VAULT_PATH", "/vault")))

# ---------------------------------------------------------------------------
# In-memory TTL cache for vault scan results
# ---------------------------------------------------------------------------


class _VaultCache:
    """Simple TTL cache for expensive vault scan + parse results."""

    def __init__(self, ttl_seconds: float = 5.0):
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str):
        entry = self._store.get(key)
        if entry is None:
            return None
        ts, value = entry
        if (_time.time() - ts) > self._ttl:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value):
        self._store[key] = (_time.time(), value)

    def invalidate(self, prefix: str = ""):
        if not prefix:
            self._store.clear()
        else:
            keys_to_del = [k for k in self._store if k.startswith(prefix)]
            for k in keys_to_del:
                del self._store[k]


_cache = _VaultCache(ttl_seconds=30.0)

_caldav_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="caldav")

_jira_sync_lock = threading.Lock()
