"""Тесты для shared/system_log.py."""
import json
import sqlite3

import pytest
from pathlib import Path

from shared.system_log import (
    init_db, log_event, query_log, get_stats, cleanup_old,
    LoggedProcess, VALID_PROCESS_TYPES, VALID_STATUSES,
)


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------

class TestInitDb:
    def test_init_db_creates_table(self, tmp_path):
        """init_db создаёт файл БД и таблицу system_log."""
        db_path = tmp_path / ".system-log.db"
        init_db(db_path)

        assert db_path.exists()

        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='system_log'"
        )
        tables = cursor.fetchall()
        conn.close()

        assert len(tables) == 1
        assert tables[0][0] == "system_log"

    def test_init_db_idempotent(self, tmp_path):
        """Повторный вызов init_db не вызывает ошибку."""
        db_path = tmp_path / ".system-log.db"
        init_db(db_path)
        init_db(db_path)  # второй вызов не должен упасть

        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='system_log'"
        )
        assert cursor.fetchone()[0] == 1
        conn.close()


# ---------------------------------------------------------------------------
# log_event
# ---------------------------------------------------------------------------

class TestLogEvent:
    def test_log_event_success(self, tmp_path):
        """log_event возвращает положительный id, запись читается через query_log."""
        db_path = tmp_path / ".system-log.db"

        row_id = log_event(
            process_type="linter",
            status="success",
            summary="All checks passed",
            source="test",
            db_path=db_path,
        )

        assert row_id > 0

        result = query_log(period="24h", db_path=db_path)
        assert result["total"] == 1
        assert result["entries"][0]["process_type"] == "linter"
        assert result["entries"][0]["status"] == "success"
        assert result["entries"][0]["summary"] == "All checks passed"

    def test_log_event_error_status(self, tmp_path):
        """log_event с status='error' корректно сохраняет статус."""
        db_path = tmp_path / ".system-log.db"

        log_event(
            process_type="health-score",
            status="error",
            summary="Connection refused",
            source="test",
            db_path=db_path,
        )

        result = query_log(period="24h", status="error", db_path=db_path)
        assert result["total"] == 1
        assert result["entries"][0]["status"] == "error"
        assert result["entries"][0]["summary"] == "Connection refused"

    def test_log_event_with_details(self, tmp_path):
        """log_event с details dict: данные корректно сериализуются и читаются обратно."""
        db_path = tmp_path / ".system-log.db"
        details = {"items_processed": 42, "errors": ["timeout", "404"]}

        log_event(
            process_type="synthesis",
            status="warning",
            summary="Partial completion",
            details=details,
            source="test",
            db_path=db_path,
        )

        result = query_log(period="24h", db_path=db_path)
        entry = result["entries"][0]
        assert entry["details"]["items_processed"] == 42
        assert entry["details"]["errors"] == ["timeout", "404"]

    def test_log_event_invalid_type_still_writes(self, tmp_path):
        """Неизвестный process_type всё равно создаёт запись (с warning в лог)."""
        db_path = tmp_path / ".system-log.db"

        row_id = log_event(
            process_type="unknown-process",
            status="success",
            summary="Forward compat test",
            source="test",
            db_path=db_path,
        )

        assert row_id > 0

        result = query_log(period="24h", db_path=db_path)
        assert result["total"] == 1
        assert result["entries"][0]["process_type"] == "unknown-process"

    def test_log_event_invalid_status_defaults_info(self, tmp_path):
        """Невалидный status заменяется на 'info'."""
        db_path = tmp_path / ".system-log.db"

        log_event(
            process_type="linter",
            status="banana",
            summary="Invalid status test",
            source="test",
            db_path=db_path,
        )

        result = query_log(period="24h", db_path=db_path)
        assert result["entries"][0]["status"] == "info"


# ---------------------------------------------------------------------------
# query_log
# ---------------------------------------------------------------------------

class TestQueryLog:
    def test_query_log_filter_type_and_status(self, tmp_path):
        """Фильтрация по process_type и status работает корректно."""
        db_path = tmp_path / ".system-log.db"

        log_event("linter", "success", "ok", source="test", db_path=db_path)
        log_event("linter", "error", "fail", source="test", db_path=db_path)
        log_event("synthesis", "success", "done", source="test", db_path=db_path)

        # Фильтр по type
        result = query_log(process_type="linter", period="24h", db_path=db_path)
        assert result["total"] == 2

        # Фильтр по status
        result = query_log(status="error", period="24h", db_path=db_path)
        assert result["total"] == 1
        assert result["entries"][0]["process_type"] == "linter"

        # Фильтр по type + status
        result = query_log(
            process_type="linter", status="success", period="24h", db_path=db_path
        )
        assert result["total"] == 1
        assert result["entries"][0]["summary"] == "ok"

    def test_query_log_pagination(self, tmp_path):
        """Пагинация: limit и offset возвращают правильный срез, total = общее количество."""
        db_path = tmp_path / ".system-log.db"

        for i in range(5):
            log_event(
                "linter", "success", f"event-{i}", source="test", db_path=db_path
            )

        result = query_log(limit=2, offset=2, period="24h", db_path=db_path)

        assert result["total"] == 5
        assert len(result["entries"]) == 2


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------

class TestGetStats:
    def test_get_stats_counts(self, tmp_path):
        """get_stats корректно считает success/error за последние 24 часа."""
        db_path = tmp_path / ".system-log.db"

        log_event("linter", "success", "ok1", source="test", db_path=db_path)
        log_event("synthesis", "success", "ok2", source="test", db_path=db_path)
        log_event("health-score", "error", "fail", source="test", db_path=db_path)

        stats = get_stats(db_path=db_path)

        assert stats["last_24h"]["total"] == 3
        assert stats["last_24h"]["success"] == 2
        assert stats["last_24h"]["error"] == 1
        assert stats["last_error"] is not None
        assert stats["last_error"]["process_type"] == "health-score"


# ---------------------------------------------------------------------------
# cleanup_old
# ---------------------------------------------------------------------------

class TestCleanupOld:
    def test_cleanup_old_deletes_expired(self, tmp_path):
        """cleanup_old удаляет записи с timestamp старше keep_days дней."""
        db_path = tmp_path / ".system-log.db"
        init_db(db_path)

        # Вставляем запись с timestamp 100 дней назад через прямой SQL
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO system_log (timestamp, process_type, status, summary, source) "
            "VALUES (datetime('now', '-100 days', 'localtime'), 'linter', 'success', 'old record', 'test')"
        )
        conn.commit()
        conn.close()

        # Вставляем свежую запись через API
        log_event("linter", "success", "fresh record", source="test", db_path=db_path)

        # Проверяем что обе записи на месте
        result = query_log(period="30d", db_path=db_path)
        # Свежая запись попадёт в 30d, старая — нет (100 дней назад > 30 дней)

        # Удаляем записи старше 90 дней
        deleted = cleanup_old(keep_days=90, db_path=db_path)
        assert deleted == 1

        # Проверяем что осталась только свежая
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT COUNT(*) FROM system_log")
        remaining = cursor.fetchone()[0]
        conn.close()
        assert remaining == 1


# ---------------------------------------------------------------------------
# LoggedProcess
# ---------------------------------------------------------------------------

class TestLoggedProcess:
    def test_logged_process_success(self, tmp_path):
        """LoggedProcess при нормальном выходе записывает status='success'."""
        db_path = tmp_path / ".system-log.db"

        with LoggedProcess("linter", source="test", db_path=db_path) as proc:
            proc.summary = "Lint completed"
            proc.details["files_checked"] = 10

        result = query_log(period="24h", db_path=db_path)
        assert result["total"] == 1

        entry = result["entries"][0]
        assert entry["status"] == "success"
        assert entry["summary"] == "Lint completed"
        assert entry["details"]["files_checked"] == 10
        assert "duration_ms" in entry["details"]

    def test_logged_process_error(self, tmp_path):
        """LoggedProcess при исключении записывает status='error' с error_type в details."""
        db_path = tmp_path / ".system-log.db"

        with pytest.raises(ValueError):
            with LoggedProcess("synthesis", source="test", db_path=db_path) as proc:
                proc.summary = "Should be overwritten"
                raise ValueError("something went wrong")

        result = query_log(period="24h", db_path=db_path)
        assert result["total"] == 1

        entry = result["entries"][0]
        assert entry["status"] == "error"
        assert "something went wrong" in entry["summary"]
        assert entry["details"]["error_type"] == "ValueError"
        assert entry["details"]["error"] == "something went wrong"
