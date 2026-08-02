"""Централизованный журнал системных операций.

Хранение: SQLite в /vault/.system-log.db
Доступ: из pm-bot, knowledge-engine, ke-cron (все монтируют /vault).
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from pathlib import Path

logger = logging.getLogger(__name__)

DB_FILENAME = ".system-log.db"
_vault_path = Path(os.getenv("VAULT_PATH", "/vault"))
DB_PATH = _vault_path / DB_FILENAME

VALID_PROCESS_TYPES = {
    "decay-recalc", "linter", "health-score", "jira-sync",
    "synthesis", "fetch-meetings", "process-queue", "rebuild-index",
    "weekly-report", "enrichment-reminder", "daily-alert", "llm-call",
    "cowork-context",
    "signal-moderator", "trend-detect",
}

VALID_STATUSES = {"success", "warning", "error", "info"}

_initialized: set[str] = set()

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS system_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')),
    process_type    TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'info',
    summary         TEXT    NOT NULL DEFAULT '',
    details_json    TEXT    NOT NULL DEFAULT '{}',
    duration_ms     INTEGER,
    source          TEXT    NOT NULL DEFAULT 'unknown'
);
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_syslog_ts ON system_log(timestamp DESC);",
    "CREATE INDEX IF NOT EXISTS idx_syslog_type_status ON system_log(process_type, status);",
    "CREATE INDEX IF NOT EXISTS idx_syslog_status ON system_log(status);",
]


def _connect(db_path: Path) -> sqlite3.Connection:
    logger.info("_connect: opening database at %s", db_path)
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        logger.warning("_connect: WAL mode unavailable, falling back to DELETE at %s", db_path)
        conn.execute("PRAGMA journal_mode=DELETE")
    logger.info("_connect: connection established at %s", db_path)
    return conn


def init_db(db_path: Path | None = None) -> None:
    db_path = db_path or DB_PATH
    logger.info("init_db: initializing schema at %s", db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with _connect(db_path) as conn:
            conn.execute(_CREATE_TABLE)
            for idx_sql in _CREATE_INDEXES:
                conn.execute(idx_sql)
            conn.commit()
        _initialized.add(str(db_path))
        cleanup_old(keep_days=90, db_path=db_path)
        logger.info("init_db: schema ready at %s", db_path)
    except Exception as e:
        logger.error("init_db: failed to initialize DB at %s: %s", db_path, e)
        raise


def log_event(
    process_type: str,
    status: str = "info",
    summary: str = "",
    details: dict | None = None,
    duration_ms: int | None = None,
    source: str = "unknown",
    db_path: Path | None = None,
) -> int:
    db_path = db_path or DB_PATH
    logger.info(
        "log_event: process_type=%s status=%s source=%s",
        process_type, status, source,
    )
    try:
        db_key = str(db_path)
        if db_key not in _initialized:
            init_db(db_path)
            _initialized.add(db_key)

        if process_type not in VALID_PROCESS_TYPES:
            logger.warning(
                "log_event: unknown process_type=%s, inserting for forward-compatibility",
                process_type,
            )

        if status not in VALID_STATUSES:
            logger.warning(
                "log_event: invalid status=%s, defaulting to 'info'",
                status,
            )
            status = "info"

        summary = (summary or "")[:500]
        details_json = json.dumps(details or {}, ensure_ascii=False, default=str)

        with _connect(db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO system_log "
                "(process_type, status, summary, details_json, duration_ms, source) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (process_type, status, summary, details_json, duration_ms, source),
            )
            conn.commit()
            row_id = cursor.lastrowid

        logger.info("log_event: inserted id=%d for process_type=%s", row_id, process_type)
        return row_id if row_id is not None else -1
    except Exception as e:
        logger.error("log_event: failed to insert event: %s", e)
        return -1


def query_log(
    period: str = "24h",
    process_type: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db_path: Path | None = None,
) -> dict:
    db_path = db_path or DB_PATH
    logger.info(
        "query_log: period=%s process_type=%s status=%s limit=%d offset=%d",
        period, process_type, status, limit, offset,
    )
    try:
        db_key = str(db_path)
        if db_key not in _initialized:
            init_db(db_path)
            _initialized.add(db_key)

        conditions: list[str] = []
        params: list = []

        period_map = {
            "24h": "-1 day",
            "7d": "-7 days",
            "30d": "-30 days",
        }
        if period in period_map:
            conditions.append("timestamp > datetime('now', ?, 'localtime')")
            params.append(period_map[period])

        if process_type:
            types = [t.strip() for t in process_type.split(",") if t.strip()]
            if len(types) == 1:
                conditions.append("process_type = ?")
                params.append(types[0])
            else:
                placeholders = ", ".join("?" for _ in types)
                conditions.append(f"process_type IN ({placeholders})")
                params.extend(types)

        if status:
            conditions.append("status = ?")
            params.append(status)

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        with _connect(db_path) as conn:
            conn.row_factory = sqlite3.Row

            count_row = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM system_log {where_clause}",
                params,
            ).fetchone()
            total = count_row["cnt"]

            rows = conn.execute(
                f"SELECT id, timestamp, process_type, status, summary, "
                f"details_json, duration_ms, source "
                f"FROM system_log {where_clause} "
                f"ORDER BY timestamp DESC LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()

        entries = []
        for row in rows:
            try:
                details = json.loads(row["details_json"])
            except (json.JSONDecodeError, TypeError):
                details = {}
            entries.append({
                "id": row["id"],
                "timestamp": row["timestamp"],
                "process_type": row["process_type"],
                "status": row["status"],
                "summary": row["summary"],
                "details": details,
                "duration_ms": row["duration_ms"],
                "source": row["source"],
            })

        logger.info("query_log: returning %d entries (total=%d)", len(entries), total)
        return {"total": total, "entries": entries}
    except Exception as e:
        logger.error("query_log: failed: %s", e)
        return {"total": 0, "entries": []}


def get_stats(db_path: Path | None = None) -> dict:
    db_path = db_path or DB_PATH
    logger.info("get_stats: computing stats from %s", db_path)
    try:
        db_key = str(db_path)
        if db_key not in _initialized:
            init_db(db_path)
            _initialized.add(db_key)

        with _connect(db_path) as conn:
            conn.row_factory = sqlite3.Row

            rows = conn.execute(
                "SELECT status, COUNT(*) AS cnt FROM system_log "
                "WHERE timestamp > datetime('now', '-1 day', 'localtime') "
                "GROUP BY status",
            ).fetchall()

            counts = {s: 0 for s in VALID_STATUSES}
            total = 0
            for row in rows:
                counts[row["status"]] = row["cnt"]
                total += row["cnt"]

            last_error_row = conn.execute(
                "SELECT timestamp, process_type, summary FROM system_log "
                "WHERE status = 'error' "
                "ORDER BY timestamp DESC LIMIT 1",
            ).fetchone()

        last_error = None
        if last_error_row:
            last_error = {
                "timestamp": last_error_row["timestamp"],
                "process_type": last_error_row["process_type"],
                "summary": last_error_row["summary"],
            }

        result = {
            "last_24h": {
                "total": total,
                "success": counts["success"],
                "warning": counts["warning"],
                "error": counts["error"],
                "info": counts["info"],
            },
            "last_error": last_error,
        }
        logger.info("get_stats: total=%d last_error=%s", total, last_error is not None)
        return result
    except Exception as e:
        logger.error("get_stats: failed: %s", e)
        return {
            "last_24h": {"total": 0, "success": 0, "warning": 0, "error": 0, "info": 0},
            "last_error": None,
        }


def cleanup_old(keep_days: int = 90, db_path: Path | None = None) -> int:
    db_path = db_path or DB_PATH
    logger.info("cleanup_old: deleting records older than %d days from %s", keep_days, db_path)
    try:
        db_key = str(db_path)
        if db_key not in _initialized:
            init_db(db_path)
            _initialized.add(db_key)

        with _connect(db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM system_log WHERE timestamp < datetime('now', ?, 'localtime')",
                (f"-{keep_days} days",),
            )
            deleted = cursor.rowcount
            conn.commit()

        logger.info("cleanup_old: deleted %d records", deleted)
        return deleted
    except Exception as e:
        logger.error("cleanup_old: failed: %s", e)
        return 0


class LoggedProcess:

    def __init__(
        self,
        process_type: str,
        source: str = "unknown",
        db_path: Path | None = None,
    ) -> None:
        self.process_type = process_type
        self.source = source
        self.db_path = db_path
        self.summary = ""
        self.details: dict = {}
        self.status = "success"
        self._start: int | None = None

    def __enter__(self) -> LoggedProcess:
        self._start = time.monotonic_ns()
        logger.info("LoggedProcess: started process_type=%s source=%s", self.process_type, self.source)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        start = self._start if self._start is not None else time.monotonic_ns()
        duration_ms = (time.monotonic_ns() - start) // 1_000_000
        if exc_type is not None:
            self.status = "error"
            self.summary = str(exc_val)[:500]
            self.details["error"] = str(exc_val)
            self.details["error_type"] = exc_type.__name__
        self.details["duration_ms"] = duration_ms
        log_event(
            process_type=self.process_type,
            status=self.status,
            summary=self.summary,
            details=self.details,
            duration_ms=duration_ms,
            source=self.source,
            db_path=self.db_path,
        )
        logger.info(
            "LoggedProcess: finished process_type=%s status=%s duration_ms=%d",
            self.process_type, self.status, duration_ms,
        )
