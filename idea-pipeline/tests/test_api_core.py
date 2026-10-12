"""Тесты core API endpoints idea-pipeline (BL-178, T-05)."""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

VALID_TEXT = "Idea about a smart notification digest for PMs"


@pytest.fixture()
def mock_orchestrator():
    orch = MagicMock()
    orch.is_running = False
    orch.running_pipeline_id = None
    return orch


@pytest.fixture()
def api(mock_orchestrator, tmp_path):
    """Подменяет _store (реальный in-memory), _orchestrator и vault_writer."""
    import idea_pipeline.api as api_module
    from idea_pipeline.state import PipelineStore

    store = PipelineStore()
    orig = (api_module._store, api_module._orchestrator, api_module._vault_path)
    api_module._store = store
    api_module._orchestrator = mock_orchestrator
    api_module._vault_path = tmp_path

    ctx = {"ideas_dir": tmp_path / "ideas"}
    with patch.dict(os.environ, {"PIPELINE_API_KEY": ""}, clear=False), patch.object(
        api_module.vault_writer, "get_pipeline_context", return_value=ctx
    ), patch.object(api_module.vault_writer, "write_input"), patch.object(
        api_module.vault_paths, "raw_ideas", return_value=tmp_path / "raw"
    ):
        yield api_module
    api_module._store, api_module._orchestrator, api_module._vault_path = orig


@pytest.fixture()
def client(api):
    return TestClient(api.app, raise_server_exceptions=False)


def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_run_valid_input(client, mock_orchestrator):
    resp = client.post("/pipeline/run", json={"text": VALID_TEXT})
    assert resp.status_code == 202
    body = resp.json()
    assert body["pipeline_id"]
    assert body["status"] == "pending"
    mock_orchestrator.run_pipeline.assert_called_once()
    assert mock_orchestrator.run_pipeline.call_args.args[1] == VALID_TEXT


@pytest.mark.parametrize("payload", [{"text": ""}, {"text": "   "}, {}])
def test_run_empty_input_422(client, payload):
    resp = client.post("/pipeline/run", json=payload)
    assert resp.status_code == 422


def test_run_conflict_when_running(client, mock_orchestrator):
    mock_orchestrator.is_running = True
    mock_orchestrator.running_pipeline_id = "other-id"
    resp = client.post("/pipeline/run", json={"text": VALID_TEXT})
    assert resp.status_code == 409
    assert "other-id" in resp.json()["detail"]
    mock_orchestrator.run_pipeline.assert_not_called()


def test_get_pipeline_status(client, api):
    run = api._store.create(slug="my-slug", vault_dir="/v/ideas")
    api._store.add_artifact(run.pipeline_id, "a.md")
    resp = client.get(f"/pipeline/{run.pipeline_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["pipeline_id"] == run.pipeline_id
    assert body["slug"] == "my-slug"
    assert body["status"] == "pending"
    assert body["artifacts"] == ["a.md"]


def test_get_pipeline_not_found(client):
    resp = client.get("/pipeline/does-not-exist")
    assert resp.status_code == 404


def test_list_pipelines(client, api):
    api._store.create(slug="one")
    api._store.create(slug="two")
    resp = client.get("/pipeline/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert {r["slug"] for r in body["runs"]} == {"one", "two"}


def test_list_pipelines_empty(client):
    resp = client.get("/pipeline/")
    assert resp.status_code == 200
    assert resp.json() == {"runs": [], "total": 0}


def test_resume_pipeline(client, api, mock_orchestrator):
    run = api._store.create(slug="resume-slug", vault_dir="/v/ideas")
    resp = client.post(f"/pipeline/{run.pipeline_id}/resume", json={"start_from": "analyst"})
    assert resp.status_code == 202
    body = resp.json()
    assert body["pipeline_id"] == run.pipeline_id
    assert "analyst" in body["message"]
    mock_orchestrator.run_pipeline.assert_called_once()
    assert mock_orchestrator.run_pipeline.call_args.args[0] == run.pipeline_id


def test_resume_not_found(client):
    resp = client.post("/pipeline/nope/resume", json={"start_from": "analyst"})
    assert resp.status_code == 404


def test_resume_conflict_when_running(client, api, mock_orchestrator):
    run = api._store.create(slug="busy")
    mock_orchestrator.is_running = True
    resp = client.post(f"/pipeline/{run.pipeline_id}/resume", json={"start_from": "analyst"})
    assert resp.status_code == 409
