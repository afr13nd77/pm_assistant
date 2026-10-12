"""Тесты ApiKeyMiddleware."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from idea_pipeline.auth import ApiKeyMiddleware


def _client(api_key=None, monkeypatch=None):
    app = FastAPI()
    app.add_middleware(ApiKeyMiddleware, api_key=api_key)

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/data")
    def data():
        return {"data": 1}

    return TestClient(app)


def test_no_key_returns_401():
    assert _client("secret").get("/data").status_code == 401


def test_wrong_key_returns_401():
    r = _client("secret").get("/data", headers={"X-Pipeline-Key": "bad"})
    assert r.status_code == 401
    assert r.json()["error"] == "unauthorized"


def test_correct_key_returns_200():
    r = _client("secret").get("/data", headers={"X-Pipeline-Key": "secret"})
    assert r.status_code == 200


def test_health_excluded():
    assert _client("secret").get("/health").status_code == 200


def test_disabled_when_env_not_set(monkeypatch):
    monkeypatch.delenv("PIPELINE_API_KEY", raising=False)
    assert _client(None).get("/data").status_code == 200


def test_key_from_env(monkeypatch):
    monkeypatch.setenv("PIPELINE_API_KEY", "envkey")
    c = _client(None)
    assert c.get("/data").status_code == 401
    assert c.get("/data", headers={"X-Pipeline-Key": "envkey"}).status_code == 200
