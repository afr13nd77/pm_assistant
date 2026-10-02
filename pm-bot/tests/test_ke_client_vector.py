"""Tests for ke_client vector store proxy functions (BL-237 T-17)."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import ke_client
from app.routers import providers


def _resp(data):
    r = MagicMock()
    r.json.return_value = data
    r.raise_for_status.return_value = None
    return r


# --- ke_client ---

def test_reindex_start():
    with patch("app.ke_client.requests.post", return_value=_resp({"status": "started"})) as p:
        res = ke_client.reindex_start()
    assert res["status"] == "started"
    assert p.call_args.args[0].endswith("/reindex")
    assert p.call_args.kwargs["json"] == {"full": True, "missing": False, "notify": False}


def test_reindex_status():
    with patch("app.ke_client.requests.get", return_value=_resp({"status": "idle"})) as g:
        res = ke_client.reindex_status()
    assert res["status"] == "idle"
    assert g.call_args.args[0].endswith("/reindex/status")


def test_test_embedding():
    # KE принимает POST с text в query params
    with patch("app.ke_client.requests.post", return_value=_resp({"status": "ok"})) as p:
        res = ke_client.test_embedding("abc")
    assert res["status"] == "ok"
    assert p.call_args.args[0].endswith("/test-embedding")
    assert p.call_args.kwargs["params"] == {"text": "abc"}


def test_vector_stats():
    with patch("app.ke_client.requests.get", return_value=_resp({"total": 3})) as g:
        res = ke_client.vector_stats()
    assert res == {"total": 3}
    assert g.call_args.args[0].endswith("/vector/stats")


# --- router ---

@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(providers.router)
    return TestClient(app)


def test_proxy_reindex(client):
    with patch("app.ke_client.reindex_start", return_value={"status": "started"}) as m:
        r = client.post("/api/v1/reindex")
    assert r.status_code == 200 and r.json()["status"] == "started"
    m.assert_called_once()


def test_proxy_reindex_status(client):
    with patch("app.ke_client.reindex_status", return_value={"status": "running"}) as m:
        r = client.get("/api/v1/reindex/status")
    assert r.status_code == 200 and r.json()["status"] == "running"
    m.assert_called_once()


def test_proxy_test_embedding(client):
    with patch("app.ke_client.test_embedding", return_value={"status": "ok", "dim": 768}) as m:
        r = client.post("/api/v1/providers/test-ollama-embedding")
    assert r.status_code == 200 and r.json()["dim"] == 768
    m.assert_called_once()


def test_proxy_vector_stats(client):
    with patch("app.ke_client.vector_stats", return_value={"total": 5}) as m:
        r = client.get("/api/v1/vector/stats")
    assert r.status_code == 200 and r.json() == {"total": 5}
    m.assert_called_once()
