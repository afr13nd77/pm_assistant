"""Интеграционные тесты API-эндпоинтов очереди встреч (BL-145, T-11).

Покрывают additive-эндпоинты api.py:
  - GET  /api/v1/meeting-queue/status  (US-03, публичный контракт BL-144)
  - POST /api/v1/process-queue          (ручной триггер process_pending)

LLM не вызывается: тесты работают на пустой/файловой очереди (нет pending → нет
обращений к провайдерам).
"""

from __future__ import annotations

import datetime
import pathlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient с vault, указанным на временную папку.

    Подменяем shared.vault_paths.VAULT_PATH напрямую (startup-событие в этом
    режиме не запускается), чтобы эндпоинты работали с изолированным vault.
    """
    from app import api
    from shared import vault_paths as _vp

    monkeypatch.setattr(_vp, "VAULT_PATH", pathlib.Path(tmp_path))
    return TestClient(api.app)


# ---------------------------------------------------------------------------
# GET /api/v1/meeting-queue/status
# ---------------------------------------------------------------------------

class TestMeetingQueueStatus:
    def test_empty_queue(self, client):
        """Пустая очередь → 200, counts по нулям, units пуст."""
        resp = client.get("/api/v1/meeting-queue/status")

        assert resp.status_code == 200
        data = resp.json()
        assert set(data.keys()) == {"counts", "units"}
        assert data["counts"] == {
            "pending": 0,
            "processing": 0,
            "done": 0,
            "failed": 0,
        }
        assert data["units"] == []

    def test_lists_pending_unit_with_meta(self, client, tmp_path):
        """Юнит в pending/ → отражён в counts и в units с полями meta."""
        from shared.meeting_queue import enqueue

        unit = enqueue(
            tmp_path,
            raw_text="текст транскрипта встречи",
            source="local",
            subject="Планёрка",
            date=datetime.datetime(2026, 6, 30, 10, 0, 0),
            source_filename="planerka.txt",
        )
        assert unit is not None

        resp = client.get("/api/v1/meeting-queue/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["counts"]["pending"] == 1
        assert len(data["units"]) == 1

        u = data["units"][0]
        assert u["unit_id"] == unit.unit_id
        assert u["source"] == "local"
        assert u["subject"] == "Планёрка"
        assert u["status"] == "pending"
        assert u["attempts"] == 0
        assert u["output_file"] is None
        assert u["last_error"] is None
        assert u["updated_at"] is not None
        # Контракт BL-144: набор ключей юнита стабилен.
        assert set(u.keys()) == {
            "unit_id", "source", "subject", "status",
            "attempts", "output_file", "last_error", "updated_at",
        }


# ---------------------------------------------------------------------------
# POST /api/v1/process-queue
# ---------------------------------------------------------------------------

class TestProcessQueue:
    def test_empty_queue_processed_zero(self, client):
        """Пустая очередь → 200, processed=0 (LLM не дёргается)."""
        resp = client.post("/api/v1/process-queue", json={})

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["processed"] == 0
        assert data["failed"] == 0
        assert data["requeued"] == 0
        assert data["reclaimed"] == 0
        assert data["details"] == []

    def test_explicit_limit_and_notify(self, client):
        """Явные limit/notify принимаются; пустая очередь → processed=0."""
        resp = client.post(
            "/api/v1/process-queue", json={"limit": 1, "notify": False},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["processed"] == 0
