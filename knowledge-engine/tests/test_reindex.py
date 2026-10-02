"""Тесты reindex (BL-237, T-08): reindexer, /reindex, /reindex/status, /vector/stats, /test-embedding."""

from __future__ import annotations

import pathlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app import reindexer


@pytest.fixture
def vault(tmp_path):
    wiki = tmp_path / "wiki" / "domain"
    wiki.mkdir(parents=True)
    for name in ("a.md", "b.md", "INDEX.md", "LOG.md", "glossary.md", "_hidden.md"):
        (wiki / name).write_text("---\ntitle: x\n---\nbody\n", encoding="utf-8")
    return tmp_path


@pytest.fixture(autouse=True)
def _no_system_log():
    with patch.object(reindexer, "LoggedProcess") as lp:
        lp.return_value.__enter__.return_value = SimpleNamespace(summary="", details={}, status="success")
        yield


def test_reindex_full(vault):
    with patch.object(reindexer, "vector_store") as vs, \
            patch.object(reindexer, "generate_digest", return_value={"status": "ok"}) as gd:
        res = reindexer.reindex_vault(str(vault), full=True)
    vs.drop_and_recreate.assert_called_once()
    assert gd.call_count == 2
    assert res["status"] == "ok" and res["total"] == 2 and res["processed"] == 2 and res["errors"] == 0
    assert "duration_sec" in res


def test_reindex_missing(vault):
    def get_by_id(i):
        return {"vector": [0.1]} if i.endswith("-a") else {"vector": None}

    with patch.object(reindexer, "vector_store") as vs, \
            patch.object(reindexer, "generate_digest", return_value={"status": "ok"}) as gd:
        vs.get_by_id.side_effect = get_by_id
        res = reindexer.reindex_vault(str(vault), full=True, missing=True)
    vs.drop_and_recreate.assert_not_called()
    assert gd.call_count == 1
    assert gd.call_args[0][0].name == "b.md"
    assert res["skipped"] == 1 and res["processed"] == 1


def test_reindex_skip_filenames(vault):
    with patch.object(reindexer, "vector_store"), \
            patch.object(reindexer, "generate_digest", return_value={"status": "ok"}) as gd:
        reindexer.reindex_vault(str(vault))
    names = {c[0][0].name for c in gd.call_args_list}
    assert names == {"a.md", "b.md"}


def test_reindex_error_handling(vault):
    def gd(path, *a, **k):
        if path.name == "a.md":
            raise RuntimeError("boom")
        return {"status": "ok"}

    with patch.object(reindexer, "vector_store"), \
            patch.object(reindexer, "generate_digest", side_effect=gd):
        res = reindexer.reindex_vault(str(vault))
    assert res["errors"] == 1 and res["processed"] == 1 and res["status"] == "ok"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import api
    from shared import vault_paths as _vp

    monkeypatch.setattr(_vp, "VAULT_PATH", pathlib.Path(tmp_path))
    api._reindex_state.update({"status": "idle", "task_id": None, "processed": 0, "total": 0, "errors": []})
    return TestClient(api.app)


def test_api_reindex_start(client):
    with patch("app.api._run_reindex") as run:
        r = client.post("/reindex", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "started" and body["task_id"]
    run.assert_called_once()
    # повторный запуск, пока running -> 409
    assert client.post("/reindex", json={}).status_code == 409


def test_api_reindex_status(client):
    r = client.get("/reindex/status")
    assert r.status_code == 200
    assert r.json()["status"] == "idle"


def test_api_vector_stats(client):
    with patch("shared.vector_store.get_stats", return_value={"total": 5}):
        r = client.get("/vector/stats")
    assert r.status_code == 200 and r.json() == {"total": 5}


def test_api_test_embedding(client):
    res = MagicMock(provider="ollama", model="m", dim=3)
    with patch("shared.embedding_client.embed", return_value=res):
        r = client.post("/test-embedding", params={"text": "hi"})
    assert r.json() == {"status": "ok", "provider": "ollama", "model": "m", "dim": 3}
    with patch("shared.embedding_client.embed", return_value=None):
        r = client.post("/test-embedding")
    assert r.json()["status"] == "error"
