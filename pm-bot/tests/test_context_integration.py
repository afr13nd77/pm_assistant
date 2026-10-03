"""Integration tests: LanceDB → context assembly (BL-237 T-15).

Uses real LanceDB in tmp dir, mock embedding.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app import context_assembler
from app.context_assembler import AssembledContext, assemble_context, enrich_creative_recall
from shared import vector_store
from shared.embedding_client import EmbeddingResult


def _emb(*_a, **_kw) -> EmbeddingResult:
    return EmbeddingResult(vector=[0.1] * 1024, model="test-model", provider="test", dim=1024)


@pytest.fixture(autouse=True)
def _clean_vector_store(tmp_path, monkeypatch):
    """Сброс singleton vector_store и использование temp-директории."""
    vector_store._reset()
    monkeypatch.setenv("EMBEDDING_DIM", "1024")
    monkeypatch.setattr(vector_store, "EMBEDDING_DIM", 1024)
    monkeypatch.setenv("VECTOR_STORE_PATH", str(tmp_path / "lancedb"))
    monkeypatch.delenv("VECTOR_STORE_ENABLED", raising=False)
    monkeypatch.delenv("DIGEST_CONTEXT_SOURCE", raising=False)
    yield
    vector_store._reset()


@pytest.fixture(autouse=True)
def _no_touch():
    """ke_client.touch ходит по HTTP в KE — в тестах подменяем."""
    with patch("app.ke_client.touch", return_value={}) as m:
        yield m


def _record(i: int, domain: str = "general", core: str | None = None, tokens_core: int = 0) -> dict:
    rid = f"layer1p-idea-item-{i}"
    return {
        "id": rid, "source_path": f"wiki/domains/{domain}/ideas/item-{i}.md", "type": "idea",
        "domain": domain, "tier": "active", "status": "active", "tags": ["t"],
        "title": f"Бронирование {i}", "relevance": 0.5,
        "one_liner": f"Краткое описание бронирования номер {i}",
        "core_digest": core if core is not None else f"- суть: бронирование отелей вариант {i}",
        "extended_digest": f"Расширенный анализ бронирования {i}",
        "changelog": "- создан", "search_text": f"Бронирование {i} бронирование отелей",
        "vector": [0.1] * 1024, "body_hash": f"h{i}", "created": "2026-01-01", "updated": "2026-01-01",
        "embedding_model": "test-model", "embedding_provider": "test",
        "tokens_one_liner": 8, "tokens_core": tokens_core, "tokens_extended": 0,
    }


def test_context_assembly_lancedb(monkeypatch):
    monkeypatch.setenv("DIGEST_CONTEXT_SOURCE", "lancedb")
    vector_store.upsert_batch([_record(i) for i in range(10)])

    with patch("shared.embedding_client.embed", side_effect=_emb):
        ctx = assemble_context("бронирование отелей", "general")

    assert isinstance(ctx, AssembledContext)
    assert ctx.fallback_used is False
    assert ctx.one_liners and ctx.core_digests and ctx.extended_digests
    assert ctx.total_tokens > 0
    assert ctx.sources_used
    assert "layer1p-idea-item-" in ctx.one_liners


def test_context_budget_limits(monkeypatch):
    monkeypatch.setenv("DIGEST_CONTEXT_SOURCE", "lancedb")
    big = "token " * 5000  # примерно 5000 токенов на запись
    vector_store.upsert_batch([_record(i, core=big) for i in range(6)])

    with patch("shared.embedding_client.embed", side_effect=_emb):
        ctx = assemble_context("бронирование отелей", "general")

    assert ctx.fallback_used is False
    assert ctx.core_digests
    assert ctx.total_tokens <= 19000
    # Бюджет core-digests (10000) ограничивает количество блоков
    assert ctx.core_digests.count("### layer1p-idea-item-") < 6


def test_context_fallback_on_error(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGEST_CONTEXT_SOURCE", "lancedb")
    # Путь, в котором нельзя создать директорию БД (родитель — обычный файл)
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("VECTOR_STORE_PATH", str(blocker / "lancedb"))
    vector_store._reset()

    with patch("shared.embedding_client.embed", side_effect=_emb):
        ctx = assemble_context("бронирование", "general")

    assert isinstance(ctx, AssembledContext)
    assert ctx.fallback_used is True
    assert ctx.one_liners == "" and ctx.core_digests == ""


def test_context_kill_switch(monkeypatch):
    # Наполняем LanceDB, затем включаем kill switch
    monkeypatch.setenv("DIGEST_CONTEXT_SOURCE", "lancedb")
    vector_store.upsert_batch([_record(i) for i in range(3)])
    monkeypatch.setenv("DIGEST_CONTEXT_SOURCE", "wiki")

    with patch("shared.embedding_client.embed", side_effect=_emb):
        ctx = assemble_context("бронирование отелей", "general")

    assert ctx.fallback_used is True
    assert ctx.one_liners == "" and ctx.core_digests == "" and ctx.extended_digests == ""
    assert ctx.total_tokens == 0
    assert vector_store.get_stats()["total"] == 3
    assert context_assembler._resolve_context_source() == "wiki"


def test_enrich_creative_recall_lancedb(monkeypatch):
    monkeypatch.setenv("DIGEST_CONTEXT_SOURCE", "lancedb")
    vector_store.upsert_batch([_record(i) for i in range(3)])

    items = [
        {"id": "layer1p-idea-item-1", "title": "Бронирование 1", "domain": "general",
         "filepath": "wiki/domains/general/ideas/item-1.md"},
        {"id": "unknown-id", "title": "Нет дайджеста", "domain": "general", "filepath": ""},
    ]
    result = enrich_creative_recall(items)

    assert result[0]["one_liner"] == "Краткое описание бронирования номер 1"
    # Без записи в LanceDB — fallback на title
    assert result[1]["one_liner"] == "Нет дайджеста"
