import json
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

DB_FILENAME = "enrichment_reminders.db"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS enrichment_reminders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    idea_id         TEXT    NOT NULL,
    idea_filename   TEXT    NOT NULL,
    readiness_at_send INTEGER NOT NULL,
    empty_sections  TEXT    NOT NULL DEFAULT '',
    sent_at         TEXT    NOT NULL
);
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_reminders_idea_sent
    ON enrichment_reminders(idea_id, sent_at);
"""


def init_db(db_path: Path) -> None:
    logger.info("init_db: initializing schema at %s", db_path)
    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute(_CREATE_TABLE)
            conn.execute(_CREATE_INDEX)
            conn.commit()
        logger.info("init_db: schema ready at %s", db_path)
    except Exception as e:
        logger.error("init_db: failed to initialize DB at %s: %s", db_path, e)
        raise


def was_reminded_recently(db_path: Path, idea_id: str, cooldown_hours: int = 24) -> bool:
    logger.info("was_reminded_recently: checking idea_id=%s cooldown=%dh", idea_id, cooldown_hours)
    try:
        with sqlite3.connect(str(db_path)) as conn:
            cursor = conn.execute(
                "SELECT 1 FROM enrichment_reminders "
                "WHERE idea_id = ? AND sent_at > datetime('now', ?)"
                " LIMIT 1",
                (idea_id, f"-{cooldown_hours} hours"),
            )
            result = cursor.fetchone() is not None
        logger.info("was_reminded_recently: idea_id=%s result=%s", idea_id, result)
        return result
    except Exception as e:
        logger.error("was_reminded_recently: DB error for idea_id=%s: %s", idea_id, e)
        return False


def get_reminded_today(db_path: Path) -> set[str]:
    logger.info("get_reminded_today: querying recent reminders")
    try:
        with sqlite3.connect(str(db_path)) as conn:
            cursor = conn.execute(
                "SELECT DISTINCT idea_id FROM enrichment_reminders "
                "WHERE sent_at > datetime('now', '-24 hours')"
            )
            result = {row[0] for row in cursor.fetchall()}
        logger.info("get_reminded_today: found %d ideas reminded in last 24h", len(result))
        return result
    except Exception as e:
        logger.error("get_reminded_today: DB error: %s", e)
        return set()


def record_reminder(
    db_path: Path,
    idea_id: str,
    idea_filename: str,
    readiness: int,
    empty_sections: list[str],
) -> None:
    logger.info("record_reminder: saving for idea_id=%s readiness=%d%%", idea_id, readiness)
    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute(
                "INSERT INTO enrichment_reminders "
                "(idea_id, idea_filename, readiness_at_send, empty_sections, sent_at) "
                "VALUES (?, ?, ?, ?, datetime('now'))",
                (idea_id, idea_filename, readiness, json.dumps(empty_sections, ensure_ascii=False)),
            )
            conn.commit()
        logger.info("record_reminder: saved for %s", idea_id)
    except Exception as e:
        logger.error("record_reminder: DB error for idea_id=%s: %s", idea_id, e)
        raise


def cleanup_old_records(db_path: Path, keep_days: int = 90) -> int:
    logger.info("cleanup_old_records: deleting records older than %d days", keep_days)
    try:
        with sqlite3.connect(str(db_path)) as conn:
            cursor = conn.execute(
                "DELETE FROM enrichment_reminders WHERE sent_at < datetime('now', ?)",
                (f"-{keep_days} days",),
            )
            deleted = cursor.rowcount
            conn.commit()
        logger.info("cleanup_old_records: deleted %d old records", deleted)
        return deleted
    except Exception as e:
        logger.error("cleanup_old_records: DB error: %s", e)
        return 0
