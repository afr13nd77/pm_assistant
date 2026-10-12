"""Тесты pydantic-моделей."""
import pytest
from pydantic import ValidationError

from idea_pipeline.models import (
    HealthResponse,
    PipelineRunRequest,
    PipelineStatusResponse,
)


def test_valid_text():
    r = PipelineRunRequest(text="a valid idea text")
    assert r.start_from == "analyst"
    assert r.domain == "general"
    assert r.notify_chat_id is None


def test_with_domain_and_notify():
    r = PipelineRunRequest(
        text="a valid idea text", domain="travel", notify_chat_id="123", start_from="pm"
    )
    assert r.domain == "travel"
    assert r.notify_chat_id == "123"
    assert r.start_from == "pm"


def test_valid_file_path():
    assert PipelineRunRequest(file_path="notes/idea.md").file_path == "notes/idea.md"


@pytest.mark.parametrize("kwargs", [
    {},
    {"text": ""},
    {"text": "          "},
    {"text": "short"},
    {"text": "x" * 5001},
    {"text": "valid idea text", "file_path": "a.md"},
    {"file_path": "../a.md"},
    {"file_path": "a.txt"},
    {"text": "valid idea text", "start_from": "bogus"},
])
def test_invalid_request(kwargs):
    with pytest.raises(ValidationError):
        PipelineRunRequest(**kwargs)


def test_status_response():
    s = PipelineStatusResponse(
        pipeline_id="p1", status="running", slug="s", vault_dir="/v",
        created_at="t1", updated_at="t2", artifacts=["a.md"],
    )
    assert s.error is None and s.failed_stage is None
    assert s.artifacts == ["a.md"]


def test_status_response_failed():
    s = PipelineStatusResponse(
        pipeline_id="p1", status="failed", slug="s", vault_dir="/v",
        created_at="t1", updated_at="t2", artifacts=[], error="boom", failed_stage="pm",
    )
    assert s.error == "boom" and s.failed_stage == "pm"


def test_health_response():
    h = HealthResponse(status="ok", version="1.0", vault_accessible=True, claude_api_configured=False)
    assert h.status == "ok" and h.vault_accessible is True and h.claude_api_configured is False


def test_health_missing_field():
    with pytest.raises(ValidationError):
        HealthResponse(status="ok")
