"""Интеграционные тесты API-эндпоинтов Signal Moderator diagnostics (BL-190, T-04).

Покрывают additive-эндпоинты api.py:
  - GET  /api/v1/signals/runs           (список прогонов)
  - GET  /api/v1/signals/runs/{run_id}  (детали прогона)
  - GET  /api/v1/signals/stats          (агрегированная статистика)

LLM не вызывается: тесты работают на tmp-файлах и in-memory SQLite.
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient с vault, указанным на временную папку."""
    from app import api
    from shared import vault_paths as _vp

    monkeypatch.setattr(_vp, "VAULT_PATH", pathlib.Path(tmp_path))
    return TestClient(api.app)


def _make_run_json(
    run_id: str,
    status: str = "completed",
    started_at: str = "2026-08-03T08:00:00",
    completed_at: str = "2026-08-03T08:00:45",
    items: dict | None = None,
    summary: dict | None = None,
) -> dict:
    """Helper: build a valid RunState-compatible dict."""
    if items is None:
        items = {
            "abc123": {
                "title": "Test news",
                "status": "completed",
                "started_at": "2026-08-03T08:00:01",
                "completed_at": "2026-08-03T08:00:10",
                "current_step": "done",
                "result_ref": "ideas/test.md",
                "iterations": 2,
                "errors": [],
                "quality_warnings": [],
                "iterations_history": [
                    {
                        "attempt": 1,
                        "quality_score": 5,
                        "critique": "weak",
                        "escalated": False,
                        "operation": "signal_analyze",
                    }
                ],
                "gate_results": [
                    {
                        "gate": "quality",
                        "passed": True,
                        "score": 7,
                        "failed_criteria": [],
                    }
                ],
                "reaction": "idea",
            }
        }
    if summary is None:
        summary = {
            "total": 1,
            "relevant": 1,
            "ideas": 1,
            "reports": 0,
            "retries": 1,
            "errors": 0,
            "quality_warnings": 0,
        }
    return {
        "run_id": run_id,
        "digest_path": "/vault/raw/inbound/news/digest.json",
        "started_at": started_at,
        "status": status,
        "completed_at": completed_at,
        "items": items,
        "summary": summary,
    }


def _write_run_file(tmp_path: pathlib.Path, run_data: dict) -> pathlib.Path:
    """Write a run JSON file to the expected location under tmp vault."""
    runs_dir = tmp_path / "wiki" / "signals" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / f"{run_data['run_id']}.json"
    path.write_text(json.dumps(run_data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _init_signal_db(db_path: pathlib.Path) -> sqlite3.Connection:
    """Create a SignalMemory-compatible SQLite DB and return the connection."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS signals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT NOT NULL,
            title       TEXT NOT NULL,
            summary     TEXT,
            source      TEXT,
            source_url  TEXT,
            relevance   INTEGER NOT NULL DEFAULT 0,
            reaction    TEXT NOT NULL DEFAULT '',
            result_ref  TEXT,
            entities    TEXT NOT NULL DEFAULT '[]',
            quality_score INTEGER,
            attempts    INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS entity_trends (
            entity          TEXT NOT NULL,
            week            TEXT NOT NULL,
            mention_count   INTEGER NOT NULL DEFAULT 0,
            avg_relevance   REAL NOT NULL DEFAULT 0.0,
            reactions       TEXT NOT NULL DEFAULT '{}',
            top_sources     TEXT NOT NULL DEFAULT '[]',
            PRIMARY KEY (entity, week)
        );

        CREATE TABLE IF NOT EXISTS trend_alerts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            entity      TEXT NOT NULL,
            trend_type  TEXT NOT NULL,
            description TEXT NOT NULL,
            evidence    TEXT NOT NULL DEFAULT '[]',
            detected_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')),
            notified    INTEGER NOT NULL DEFAULT 0,
            acted_on    TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_signals_date ON signals(date);
        CREATE INDEX IF NOT EXISTS idx_signals_entities ON signals(entities);
    """)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# GET /api/v1/signals/runs
# ---------------------------------------------------------------------------


class TestSignalsRuns:
    def test_signals_runs_empty_directory(self, client):
        """runs_dir не существует -> {"status": "ok", "runs": []}."""
        resp = client.get("/api/v1/signals/runs")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["runs"] == []

    def test_signals_runs_returns_sorted_list(self, client, tmp_path):
        """3 run-файла -> отсортированы desc по имени файла."""
        _write_run_file(
            tmp_path,
            _make_run_json("2026-08-01-0800", started_at="2026-08-01T08:00:00",
                           completed_at="2026-08-01T08:00:30"),
        )
        _write_run_file(
            tmp_path,
            _make_run_json("2026-08-03-0800", started_at="2026-08-03T08:00:00",
                           completed_at="2026-08-03T08:00:45"),
        )
        _write_run_file(
            tmp_path,
            _make_run_json("2026-08-02-0800", started_at="2026-08-02T08:00:00",
                           completed_at="2026-08-02T08:00:20"),
        )

        resp = client.get("/api/v1/signals/runs")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["runs"]) == 3
        run_ids = [r["run_id"] for r in data["runs"]]
        assert run_ids == ["2026-08-03-0800", "2026-08-02-0800", "2026-08-01-0800"]

    def test_signals_runs_respects_limit(self, client, tmp_path):
        """limit=1 -> 1 результат."""
        _write_run_file(tmp_path, _make_run_json("2026-08-01-0800"))
        _write_run_file(tmp_path, _make_run_json("2026-08-02-0800"))

        resp = client.get("/api/v1/signals/runs?limit=1")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["runs"]) == 1

    def test_signals_runs_skips_corrupted_files(self, client, tmp_path):
        """Один файл невалидный JSON -> пропускается, остальные возвращаются."""
        _write_run_file(tmp_path, _make_run_json("2026-08-01-0800"))

        # Write corrupted file
        runs_dir = tmp_path / "wiki" / "signals" / "runs"
        corrupted_file = runs_dir / "2026-08-02-0800.json"
        corrupted_file.write_text("{invalid json!!!", encoding="utf-8")

        resp = client.get("/api/v1/signals/runs")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["runs"]) == 1
        assert data["runs"][0]["run_id"] == "2026-08-01-0800"

    def test_signals_runs_includes_items_summary(self, client, tmp_path):
        """items содержат key, title, status, reaction, iterations, errors."""
        _write_run_file(tmp_path, _make_run_json("2026-08-03-0800"))

        resp = client.get("/api/v1/signals/runs")

        assert resp.status_code == 200
        data = resp.json()
        items = data["runs"][0]["items"]
        assert len(items) == 1
        item = items[0]
        assert item["key"] == "abc123"
        assert item["title"] == "Test news"
        assert item["status"] == "completed"
        assert item["reaction"] == "idea"
        assert item["iterations"] == 2
        assert item["errors"] == 0  # len([]) == 0

    def test_signals_runs_calculates_duration_ms(self, client, tmp_path):
        """started_at + completed_at -> корректный duration_ms."""
        _write_run_file(
            tmp_path,
            _make_run_json(
                "2026-08-03-0800",
                started_at="2026-08-03T08:00:00",
                completed_at="2026-08-03T08:00:45",
            ),
        )

        resp = client.get("/api/v1/signals/runs")

        assert resp.status_code == 200
        data = resp.json()
        assert data["runs"][0]["duration_ms"] == 45000


# ---------------------------------------------------------------------------
# GET /api/v1/signals/runs/{run_id}
# ---------------------------------------------------------------------------


class TestSignalsRunDetail:
    def test_signals_run_detail_found(self, client, tmp_path):
        """valid run_id -> 200 с полными данными."""
        _write_run_file(tmp_path, _make_run_json("2026-08-03-0800"))

        resp = client.get("/api/v1/signals/runs/2026-08-03-0800")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["run_status"] == "completed"
        assert data["run_id"] == "2026-08-03-0800"
        assert data["digest_path"] == "/vault/raw/inbound/news/digest.json"
        assert "items" in data
        assert "summary" in data

    def test_signals_run_detail_not_found_404(self, client):
        """invalid run_id -> 404."""
        resp = client.get("/api/v1/signals/runs/nonexistent-run")

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_signals_run_detail_includes_iterations_history(self, client, tmp_path):
        """В ответе есть iterations_history в items."""
        _write_run_file(tmp_path, _make_run_json("2026-08-03-0800"))

        resp = client.get("/api/v1/signals/runs/2026-08-03-0800")

        assert resp.status_code == 200
        data = resp.json()
        item = data["items"]["abc123"]
        assert "iterations_history" in item
        assert len(item["iterations_history"]) == 1
        assert item["iterations_history"][0]["attempt"] == 1
        assert item["iterations_history"][0]["quality_score"] == 5

    def test_signals_run_detail_includes_gate_results(self, client, tmp_path):
        """В ответе есть gate_results в items."""
        _write_run_file(tmp_path, _make_run_json("2026-08-03-0800"))

        resp = client.get("/api/v1/signals/runs/2026-08-03-0800")

        assert resp.status_code == 200
        data = resp.json()
        item = data["items"]["abc123"]
        assert "gate_results" in item
        assert len(item["gate_results"]) == 1
        assert item["gate_results"][0]["gate"] == "quality"
        assert item["gate_results"][0]["passed"] is True


# ---------------------------------------------------------------------------
# GET /api/v1/signals/stats
# ---------------------------------------------------------------------------


class TestSignalsStats:
    def test_signals_stats_empty_db(self, client, tmp_path, monkeypatch):
        """Нет DB -> нулевые значения."""
        # Point config to non-existent db
        db_path = str(tmp_path / "nonexistent" / "signal_memory.db")

        def fake_load_config():
            from app.signal_orchestrator import ModeratorConfig
            cfg = ModeratorConfig()
            cfg.memory_db_path = db_path
            return cfg

        import app.signal_orchestrator as orch_mod
        monkeypatch.setattr(orch_mod, "load_config_from_settings", fake_load_config)

        resp = client.get("/api/v1/signals/stats")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["runs_count"] == 0
        assert data["avg_quality_score"] is None
        assert data["escalation_rate"] == 0.0
        assert data["total_signals"] == 0
        assert data["top_entities"] == []

    def test_signals_stats_with_data(self, client, tmp_path, monkeypatch):
        """Данные есть -> корректные значения."""
        db_path = tmp_path / "data" / "signal_memory.db"
        conn = _init_signal_db(db_path)

        today = datetime.now().strftime("%Y-%m-%d")
        conn.execute(
            "INSERT INTO signals (date, title, relevance, reaction, quality_score, attempts) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (today, "News A", 8, "idea", 7, 1),
        )
        conn.execute(
            "INSERT INTO signals (date, title, relevance, reaction, quality_score, attempts) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (today, "News B", 6, "report", 5, 2),
        )
        conn.commit()

        # Write a run file for runs_count
        _write_run_file(tmp_path, _make_run_json(
            datetime.now().strftime("%Y-%m-%d") + "-0800",
        ))

        def fake_load_config():
            from app.signal_orchestrator import ModeratorConfig
            cfg = ModeratorConfig()
            cfg.memory_db_path = str(db_path)
            return cfg

        import app.signal_orchestrator as orch_mod
        monkeypatch.setattr(orch_mod, "load_config_from_settings", fake_load_config)

        resp = client.get("/api/v1/signals/stats")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["total_signals"] == 2
        assert data["avg_quality_score"] == 6.0
        assert data["escalation_rate"] == 0.5  # 1 out of 2 has attempts > 1
        assert data["runs_count"] == 1

    def test_signals_stats_top_entities(self, client, tmp_path, monkeypatch):
        """entity_trends -> top 10."""
        db_path = tmp_path / "data" / "signal_memory.db"
        conn = _init_signal_db(db_path)

        # Insert entity trends
        conn.execute(
            "INSERT INTO entity_trends (entity, week, mention_count, avg_relevance) "
            "VALUES (?, ?, ?, ?)",
            ("Booking.com", "2026-W30", 5, 7.5),
        )
        conn.execute(
            "INSERT INTO entity_trends (entity, week, mention_count, avg_relevance) "
            "VALUES (?, ?, ?, ?)",
            ("Booking.com", "2026-W31", 3, 8.0),
        )
        conn.execute(
            "INSERT INTO entity_trends (entity, week, mention_count, avg_relevance) "
            "VALUES (?, ?, ?, ?)",
            ("Airbnb", "2026-W31", 2, 6.0),
        )
        conn.commit()

        # Need at least one signal for the query to not fail
        today = datetime.now().strftime("%Y-%m-%d")
        conn.execute(
            "INSERT INTO signals (date, title, relevance, reaction, quality_score, attempts) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (today, "Test", 5, "skip", 5, 1),
        )
        conn.commit()

        def fake_load_config():
            from app.signal_orchestrator import ModeratorConfig
            cfg = ModeratorConfig()
            cfg.memory_db_path = str(db_path)
            return cfg

        import app.signal_orchestrator as orch_mod
        monkeypatch.setattr(orch_mod, "load_config_from_settings", fake_load_config)

        resp = client.get("/api/v1/signals/stats")

        assert resp.status_code == 200
        data = resp.json()
        top = data["top_entities"]
        assert len(top) == 2
        assert top[0]["entity"] == "Booking.com"
        assert top[0]["mention_count"] == 8  # 5 + 3
        assert top[1]["entity"] == "Airbnb"
        assert top[1]["mention_count"] == 2

    def test_signals_stats_respects_days_param(self, client, tmp_path, monkeypatch):
        """days=1 -> фильтр по дате."""
        db_path = tmp_path / "data" / "signal_memory.db"
        conn = _init_signal_db(db_path)

        today = datetime.now().strftime("%Y-%m-%d")
        old_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")

        conn.execute(
            "INSERT INTO signals (date, title, relevance, reaction, quality_score, attempts) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (today, "Recent news", 8, "idea", 7, 1),
        )
        conn.execute(
            "INSERT INTO signals (date, title, relevance, reaction, quality_score, attempts) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (old_date, "Old news", 6, "skip", 5, 1),
        )
        conn.commit()

        def fake_load_config():
            from app.signal_orchestrator import ModeratorConfig
            cfg = ModeratorConfig()
            cfg.memory_db_path = str(db_path)
            return cfg

        import app.signal_orchestrator as orch_mod
        monkeypatch.setattr(orch_mod, "load_config_from_settings", fake_load_config)

        resp = client.get("/api/v1/signals/stats?days=1")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_signals"] == 1
        assert data["avg_quality_score"] == 7.0
