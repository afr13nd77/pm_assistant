"""Unit-тесты tools: shared.vector_store и shared.embedding_client замоканы."""
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.vector_store import SearchResult  # noqa: E402

from mcp_server import tools  # noqa: E402


def _sr(i):
    return SearchResult(f"a{i}", f"T{i}", "d", "t", 0.5, f"one{i}", "snip", None, "p.md")


def test_search_tool():
    with patch.object(tools.embedding_client, "embed", return_value=SimpleNamespace(vector=[0.1])), \
         patch.object(tools.vector_store, "hybrid_search", return_value=[_sr(1)]) as hs:
        r = tools.search("q", limit=999)
    assert r["total"] == 1 and r["results"][0]["id"] == "a1"
    assert hs.call_args.args[1] == [0.1] and hs.call_args.args[2] == 50


def test_search_fts_only():
    with patch.object(tools.embedding_client, "embed", side_effect=RuntimeError("x")), \
         patch.object(tools.vector_store, "hybrid_search", return_value=[_sr(1)]) as hs:
        r = tools.search("q")
    assert r["total"] == 1 and hs.call_args.args[1] is None


def test_get_context():
    full = {"core_digest": "core text", "extended_digest": "ext text"}
    with patch.object(tools.embedding_client, "embed", return_value=None), \
         patch.object(tools.vector_store, "hybrid_search", return_value=[_sr(1), _sr(2)]), \
         patch.object(tools.vector_store, "get_by_id", return_value=full):
        r = tools.get_context("topic")
    assert "ONE-LINERS" in r["context"] and "core text" in r["context"]
    assert {s["id"] for s in r["sources_used"]} == {"a1", "a2"}
    assert r["total_tokens"] == sum(r["sections"].values()) > 0


def test_get_context_budget():
    with patch.object(tools.embedding_client, "embed", return_value=None), \
         patch.object(tools.vector_store, "hybrid_search", return_value=[_sr(1)]), \
         patch.object(tools.vector_store, "get_by_id", return_value={"core_digest": "x" * 4000}):
        r = tools.get_context("topic", token_budget=100)
    assert r["total_tokens"] <= 100


def test_list_artifacts():
    rows = [{"id": "a", "vector": [1], "search_text": "s", "title": "T"}]
    with patch.object(tools.vector_store, "list_artifacts", return_value=rows) as la:
        r = tools.list_artifacts(domain="d", limit=5, offset=10)
    assert r["artifacts"] == [{"id": "a", "title": "T"}]
    assert la.call_args.args == ("d", None, None, None, 5, 10)


def test_get_artifact():
    row = {"id": "a", "title": "T", "core_digest": "c", "vector": [1]}
    with patch.object(tools.vector_store, "get_by_id", return_value=row):
        r = tools.get_artifact("a")
    assert r["id"] == "a" and r["core_digest"] == "c" and "vector" not in r


def test_get_artifact_not_found():
    with patch.object(tools.vector_store, "get_by_id", return_value=None):
        r = tools.get_artifact("zz")
    assert "error" in r and r["id"] == "zz"
