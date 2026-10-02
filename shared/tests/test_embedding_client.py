import json
import sys
from unittest.mock import MagicMock, patch

import pytest

from shared import embedding_client as ec

PREFS = {
    "ollama_url": "http://ollama:11434/",
    "embedding_fallback": ["ollama", "openrouter"],
    "embedding_model_ollama": "nomic-embed-text",
    "embedding_model_openrouter": "text-embedding-3-small",
    "embedding_dim": 4,
}
VEC = [0.1, 0.2, 0.3, 0.4]


@pytest.fixture(autouse=True)
def _no_system_log():
    with patch.object(ec, "_log_event"):
        yield


@pytest.fixture
def prefs():
    with patch.object(ec, "_load_embedding_prefs", return_value=dict(PREFS)) as m:
        yield m


@pytest.fixture
def api_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")


def _ollama_resp(vec=VEC):
    r = MagicMock()
    r.json.return_value = {"embeddings": [vec]}
    return r


def _fake_openai(client):
    """Подмена модуля openai (пакет может быть не установлен)."""
    return patch.dict(sys.modules, {"openai": MagicMock(OpenAI=MagicMock(return_value=client))})


def _openai_client(vectors):
    client = MagicMock()
    client.embeddings.create.return_value = MagicMock(
        data=[MagicMock(embedding=v) for v in vectors]
    )
    return client


def test_embed_ollama_success(prefs, api_key):
    with patch.object(ec._requests, "post", return_value=_ollama_resp()) as post:
        res = ec.embed("hello")
    assert res == ec.EmbeddingResult(vector=VEC, model="nomic-embed-text", provider="ollama", dim=4)
    assert post.call_args.args[0] == "http://ollama:11434/api/embed"
    assert post.call_args.kwargs["json"] == {"model": "nomic-embed-text", "input": "hello"}


def test_embed_ollama_fail_falls_back_to_openrouter(prefs, api_key):
    client = _openai_client([VEC])
    with patch.object(ec._requests, "post", side_effect=ConnectionError("down")), \
            _fake_openai(client):
        res = ec.embed("hello")
    assert res.provider == "openrouter"
    assert res.model == "text-embedding-3-small"
    assert res.vector == VEC


def test_embed_all_fail_returns_none(prefs, api_key):
    client = MagicMock()
    client.embeddings.create.side_effect = RuntimeError("boom")
    with patch.object(ec._requests, "post", side_effect=ConnectionError("down")), \
            _fake_openai(client):
        assert ec.embed("hello") is None


def test_embed_empty_ollama_url_skips_to_openrouter(api_key):
    p = dict(PREFS, ollama_url="")
    client = _openai_client([VEC])
    with patch.object(ec, "_load_embedding_prefs", return_value=p), \
            patch.object(ec._requests, "post") as post, \
            _fake_openai(client):
        res = ec.embed("hello")
    post.assert_not_called()
    assert res.provider == "openrouter"


def test_embed_no_openrouter_key_skips_openrouter(prefs, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with patch.object(ec._requests, "post", side_effect=ConnectionError("down")):
        assert ec.embed("hello") is None


def test_embed_no_providers_available(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with patch.object(ec, "_load_embedding_prefs", return_value=dict(PREFS, ollama_url="")):
        assert ec.embed("x") is None


def test_embed_http_error_triggers_fallback(prefs, api_key):
    bad = MagicMock()
    bad.raise_for_status.side_effect = RuntimeError("500")
    client = _openai_client([VEC])
    with patch.object(ec._requests, "post", return_value=bad), \
            _fake_openai(client):
        assert ec.embed("x").provider == "openrouter"


def test_embed_chain_order_respected(api_key):
    p = dict(PREFS, embedding_fallback=["openrouter", "ollama"])
    client = _openai_client([VEC])
    with patch.object(ec, "_load_embedding_prefs", return_value=p), \
            patch.object(ec._requests, "post") as post, \
            _fake_openai(client):
        res = ec.embed("x")
    assert res.provider == "openrouter"
    post.assert_not_called()


def test_openrouter_receives_dimensions(prefs, api_key):
    client = _openai_client([VEC])
    with _fake_openai(client):
        ec._call_openrouter_embed("x", PREFS)
    kwargs = client.embeddings.create.call_args.kwargs
    assert kwargs["dimensions"] == 4
    assert kwargs["model"] == "text-embedding-3-small"
    assert kwargs["input"] == ["x"]


def test_embed_batch_ollama_success(prefs, api_key):
    with patch.object(ec._requests, "post", return_value=_ollama_resp()) as post:
        res = ec.embed_batch(["a", "b", "c"])
    assert len(res) == 3 and all(r.provider == "ollama" for r in res)
    assert post.call_count == 3


def test_embed_batch_partial_failure_falls_back_for_failed_items(prefs, api_key):
    def post(url, json, timeout):
        if json["input"] == "b":
            raise ConnectionError("fail")
        return _ollama_resp()

    client = _openai_client([[9.0, 9.0, 9.0, 9.0]])
    with patch.object(ec._requests, "post", side_effect=post), \
            _fake_openai(client):
        res = ec.embed_batch(["a", "b", "c"])
    assert [r.provider for r in res] == ["ollama", "openrouter", "ollama"]
    assert client.embeddings.create.call_args.kwargs["input"] == ["b"]


def test_embed_batch_all_fail_gives_none_list(prefs, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with patch.object(ec._requests, "post", side_effect=ConnectionError("x")):
        assert ec.embed_batch(["a", "b"]) == [None, None]


def test_embed_batch_openrouter_chunks_by_100(api_key):
    p = dict(PREFS, embedding_fallback=["openrouter"])
    texts = [f"t{i}" for i in range(250)]
    client = MagicMock()
    client.embeddings.create.side_effect = lambda input, **kw: MagicMock(
        data=[MagicMock(embedding=VEC) for _ in input]
    )
    with patch.object(ec, "_load_embedding_prefs", return_value=p), \
            _fake_openai(client):
        res = ec.embed_batch(texts)
    assert client.embeddings.create.call_count == 3
    assert len(res) == 250 and all(r is not None for r in res)


def test_embed_batch_empty():
    assert ec.embed_batch([]) == []


def test_load_prefs_from_file(tmp_path, monkeypatch):
    (tmp_path / ".pm-user-prefs.json").write_text(json.dumps({
        "ollama_url": "http://x:1", "embedding_dim": 512,
        "embedding_fallback": ["openrouter"],
    }), encoding="utf-8")
    monkeypatch.setenv("PM_BOT_DATA_PATH", str(tmp_path))
    prefs = ec._load_embedding_prefs()
    assert prefs["ollama_url"] == "http://x:1"
    assert prefs["embedding_dim"] == 512
    assert prefs["embedding_fallback"] == ["openrouter"]
    assert prefs["embedding_model_ollama"] == "nomic-embed-text"


def test_load_prefs_defaults_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("PM_BOT_DATA_PATH", str(tmp_path))
    prefs = ec._load_embedding_prefs()
    assert prefs["embedding_fallback"] == ["ollama", "openrouter"]
    assert prefs["embedding_dim"] == 768
    assert prefs["ollama_url"] == ""


def test_load_prefs_defaults_on_corrupt_file(tmp_path, monkeypatch):
    (tmp_path / ".pm-user-prefs.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("PM_BOT_DATA_PATH", str(tmp_path))
    assert ec._load_embedding_prefs()["embedding_dim"] == 768
