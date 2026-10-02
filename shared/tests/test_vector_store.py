import random

import pytest

pytest.importorskip("lancedb")

from shared import vector_store as vs  # noqa: E402


def _vec(seed=0):
    rnd = random.Random(seed)
    return [rnd.random() for _ in range(vs.EMBEDDING_DIM)]


def _rec(i, **kw):
    r = {
        "id": f"rec-{i}",
        "source_path": f"wiki/{i}.md",
        "type": "idea",
        "domain": "mobile",
        "tier": "active",
        "status": "draft",
        "tags": ["a", "b"],
        "title": f"Title {i}",
        "relevance": 0.5,
        "one_liner": f"one liner {i}",
        "core_digest": f"core digest about payments {i}",
        "search_text": f"Title {i} one liner {i} payments",
        "updated": f"2026-10-0{i % 9 + 1}",
        "embedding_model": "nomic-embed-text",
        "vector": _vec(i),
    }
    r.update(kw)
    return r


@pytest.fixture(autouse=True)
def store(tmp_path):
    vs._reset()
    vs._get_db(str(tmp_path / "lance"))
    yield
    vs._reset()


def test_schema_fields():
    assert len(vs.DIGESTS_SCHEMA) == 23  # 22 fields from spec listing + counted tokens_* separately
    assert vs.DIGESTS_SCHEMA.field("vector").nullable


def test_empty_db_edge_cases():
    assert vs.get_stats() == {"total": 0, "with_vectors": 0, "last_update": "", "model": ""}
    assert vs.get_by_id("x") is None
    assert vs.list_artifacts() == []
    assert vs.hybrid_search("anything", None) == []
    assert vs.hybrid_search("anything", _vec(1)) == []


def test_upsert_and_get_by_id():
    vs.upsert(_rec(1))
    got = vs.get_by_id("rec-1")
    assert got["title"] == "Title 1"
    assert got["tags"] == ["a", "b"]
    assert len(got["vector"]) == vs.EMBEDDING_DIM


def test_upsert_replaces_existing():
    vs.upsert(_rec(1))
    vs.upsert(_rec(1, title="Changed"))
    assert vs.get_stats()["total"] == 1
    assert vs.get_by_id("rec-1")["title"] == "Changed"


def test_upsert_requires_id():
    with pytest.raises(ValueError):
        vs.upsert({"title": "no id"})


def test_upsert_wrong_vector_dim():
    with pytest.raises(ValueError):
        vs.upsert(_rec(1, vector=[0.1, 0.2]))


def test_upsert_batch():
    assert vs.upsert_batch([_rec(i) for i in range(5)]) == 5
    assert vs.get_stats()["total"] == 5
    assert vs.upsert_batch([]) == 0


def test_upsert_batch_duplicate_ids_last_wins():
    vs.upsert_batch([_rec(1, title="first"), _rec(1, title="second")])
    assert vs.get_stats()["total"] == 1
    assert vs.get_by_id("rec-1")["title"] == "second"


def test_delete():
    vs.upsert_batch([_rec(1), _rec(2)])
    vs.delete("rec-1")
    assert vs.get_by_id("rec-1") is None
    assert vs.get_by_id("rec-2") is not None


def test_quote_in_id_is_escaped():
    vs.upsert(_rec(1, id="o'brien"))
    assert vs.get_by_id("o'brien") is not None
    vs.delete("o'brien")
    assert vs.get_by_id("o'brien") is None


def test_null_vector_record():
    vs.upsert(_rec(1, vector=None))
    assert vs.get_by_id("rec-1")["vector"] is None
    assert vs.get_stats()["with_vectors"] == 0


def test_hybrid_search_fts_only():
    vs.upsert_batch([
        _rec(1, search_text="kubernetes deployment guide"),
        _rec(2, search_text="payments refund flow"),
    ])
    res = vs.hybrid_search("kubernetes", None)
    assert [r.id for r in res] == ["rec-1"]
    assert res[0].semantic_score is None


def test_hybrid_search_finds_null_vector_record_via_fts():
    vs.upsert(_rec(1, vector=None, search_text="unique zeppelin keyword"))
    res = vs.hybrid_search("zeppelin", _vec(5))
    assert "rec-1" in [r.id for r in res]


def test_hybrid_search_vector_plus_fts():
    vs.upsert_batch([_rec(i, search_text=f"payments item {i}") for i in range(6)])
    res = vs.hybrid_search("payments", _vec(3), limit=4)
    assert 0 < len(res) <= 4
    assert res[0].id == "rec-3"  # exact vector match ranks first in vector list
    assert res[0].semantic_score is not None
    scores = [r.score for r in res]
    assert scores == sorted(scores, reverse=True)


def test_hybrid_search_vector_only_hits_without_fts_match():
    vs.upsert(_rec(1, search_text="alpha"))
    res = vs.hybrid_search("nomatchword", _vec(1))
    assert [r.id for r in res] == ["rec-1"]


def test_search_result_format():
    long = "x" * 500
    vs.upsert(_rec(1, core_digest=long, search_text="searchable thing"))
    r = vs.hybrid_search("searchable", None)[0]
    assert isinstance(r, vs.SearchResult)
    assert r.title == "Title 1" and r.domain == "mobile" and r.type == "idea"
    assert r.one_liner == "one liner 1" and r.source_path == "wiki/1.md"
    assert len(r.snippet) == 200
    assert r.score > 0


def test_min_score_filters():
    vs.upsert(_rec(1, search_text="gadget"))
    assert vs.hybrid_search("gadget", None, min_score=10.0) == []


def test_search_metadata_filters():
    vs.upsert_batch([
        _rec(1, domain="mobile", type="idea", status="draft", search_text="common term"),
        _rec(2, domain="web", type="meeting", status="done", search_text="common term"),
    ])
    assert [r.id for r in vs.hybrid_search("common", None, domain="web")] == ["rec-2"]
    assert [r.id for r in vs.hybrid_search("common", None, artifact_type="idea")] == ["rec-1"]
    assert [r.id for r in vs.hybrid_search("common", None, status="done")] == ["rec-2"]
    res = vs.hybrid_search("common", _vec(1), domain="mobile")
    assert [r.id for r in res] == ["rec-1"]


def test_list_artifacts_filters_and_pagination():
    vs.upsert_batch([
        _rec(i, tier="core" if i < 3 else "warm", domain="mobile" if i % 2 else "web")
        for i in range(10)
    ])
    assert len(vs.list_artifacts(limit=100)) == 10
    assert len(vs.list_artifacts(tier="core")) == 3
    assert all(r["domain"] == "web" for r in vs.list_artifacts(domain="web"))
    p1 = vs.list_artifacts(limit=4, offset=0)
    p2 = vs.list_artifacts(limit=4, offset=4)
    p3 = vs.list_artifacts(limit=4, offset=8)
    ids = [r["id"] for r in p1 + p2 + p3]
    assert len(ids) == 10 and len(set(ids)) == 10


def test_get_stats():
    vs.upsert_batch([_rec(1), _rec(2, vector=None, updated="2026-12-31")])
    s = vs.get_stats()
    assert s["total"] == 2
    assert s["with_vectors"] == 1
    assert s["last_update"] == "2026-12-31"
    assert s["model"] == "nomic-embed-text"


def test_drop_and_recreate():
    vs.upsert_batch([_rec(1), _rec(2)])
    vs.drop_and_recreate()
    assert vs.get_stats()["total"] == 0
    vs.upsert(_rec(3))
    assert vs.get_stats()["total"] == 1


def test_env_path(tmp_path, monkeypatch):
    vs._reset()
    p = tmp_path / "envstore"
    monkeypatch.setenv("VECTOR_STORE_PATH", str(p))
    vs.upsert(_rec(1))
    assert p.exists()
    assert vs.get_by_id("rec-1") is not None
