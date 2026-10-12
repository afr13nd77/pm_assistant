"""Тесты shared.exception_handlers (BL-180)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from shared.exception_handlers import setup_exception_handlers


class _Body(BaseModel):
    x: int


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    setup_exception_handlers(app)

    @app.get("/boom")
    async def boom():
        raise RuntimeError("secret internal")

    @app.get("/http500")
    async def http500():
        raise HTTPException(500, "secret")

    @app.get("/http404")
    async def http404():
        raise HTTPException(404, "Not found")

    @app.post("/validate")
    async def validate(body: _Body):
        return {"x": body.x}

    @app.get("/ok")
    async def ok():
        return {"ok": True}

    return TestClient(app, raise_server_exceptions=False)


def test_unhandled_exception_sanitized(client):
    r = client.get("/boom")
    assert r.status_code == 500
    assert r.json()["detail"] == "Internal server error"
    assert "secret" not in r.text
    assert r.json()["request_id"] == r.headers["X-Request-ID"]


def test_http_500_detail_hidden(client):
    r = client.get("/http500")
    assert r.status_code == 500
    assert "secret" not in r.text
    assert r.json()["detail"] == "Internal server error"
    assert "X-Request-ID" in r.headers


def test_http_404_detail_passed(client):
    r = client.get("/http404")
    assert r.status_code == 404
    assert r.json()["detail"] == "Not found"
    assert "X-Request-ID" in r.headers


def test_unknown_route_404(client):
    r = client.get("/nope")
    assert r.status_code == 404
    assert "X-Request-ID" in r.headers


def test_validation_error(client):
    r = client.post("/validate", json={"x": "abc"})
    assert r.status_code == 422
    body = r.json()
    assert "error" not in body
    assert isinstance(body["detail"], list)
    assert "X-Request-ID" in r.headers


def test_request_id_generated_on_success(client):
    r = client.get("/ok")
    assert r.status_code == 200
    assert r.headers["X-Request-ID"]


@pytest.mark.parametrize("path", ["/ok", "/boom", "/http500", "/http404"])
def test_incoming_request_id_preserved(client, path):
    r = client.get(path, headers={"X-Request-ID": "my-id-123"})
    assert r.headers["X-Request-ID"] == "my-id-123"
    if r.status_code >= 400:
        assert r.json()["request_id"] == "my-id-123"
