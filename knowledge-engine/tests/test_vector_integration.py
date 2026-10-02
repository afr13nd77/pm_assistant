"""Integration tests: digest pipeline → LanceDB (BL-237 T-15).

Uses real LanceDB in tmp dir, mock LLM and embedding.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from shared import vector_store
from shared.embedding_client import EmbeddingResult

ROOT = Path(__file__).resolve().parents[2]

# Все 23 поля схемы DIGESTS_SCHEMA
ALL_FIELDS = [f.name for f in vector_store.DIGESTS_SCHEMA]


def _core_digest() -> str:
    """Core digest в формате key-value, проходящий валидацию (200-500 токенов)."""
    lines = [
        "- суть: тестовая идея для проверки полного конвейера генерации дайджестов и записи в векторное хранилище",
        "- статус: active",
        "- domain: general",
    ]
    for i in range(1, 7):
        lines.append(
            f"- деталь_{i}: подробное описание аспекта номер {i} тестовой идеи, "
            f"включающее контекст, мотивацию, ожидаемый результат и возможные риски реализации"
        )
    return "\n".join(lines)


LLM_RESPONSE = (
    "# one-liner\nТестовая идея для проверки конвейера.\n\n"
    f"# core-digest\n{_core_digest()}\n\n"
    "# extended-digest\nРасширенный анализ тестовой идеи с подробностями.\n\n"
    "# changelog\n- Создан дайджест.\n"
)


def _emb(*_a, **_kw) -> EmbeddingResult:
    return EmbeddingResult(vector=[0.1] * 768, model="test-model", provider="test", dim=768)


@pytest.fixture(autouse=True)
def _clean_vector_store(tmp_path, monkeypatch):
    """Сброс singleton vector_store и использование temp-директории."""
    vector_store._reset()
    monkeypatch.setenv("VECTOR_STORE_PATH", str(tmp_path / "lancedb"))
    monkeypatch.setenv("VECTOR_STORE_ENABLED", "1")
    yield
    vector_store._reset()


@pytest.fixture(autouse=True)
def _no_system_log():
    """LoggedProcess пишет в БД логов — в тестах не нужен."""
    with patch("shared.system_log.LoggedProcess") as lp, \
            patch("app.reindexer.LoggedProcess") as lp2:
        for m in (lp, lp2):
            m.return_value.__enter__.return_value = SimpleNamespace(summary="", details={}, status="success")
        yield


def _make_wiki_file(vault: Path, name: str = "test-idea", body: str = "Текст идеи для тестирования.") -> Path:
    d = vault / "wiki" / "domains" / "general" / "ideas"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}.md"
    p.write_text(
        "---\ntitle: Тестовая идея\ndomain: general\ntags: [test, fixture]\n"
        f"status: active\ntier: active\nrelevance: 0.8\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return p


def _record(rid: str, domain: str = "general", rtype: str = "idea", title: str = "Заголовок",
            text: str = "поиск") -> dict:
    return {
        "id": rid, "source_path": f"wiki/{rid}.md", "type": rtype, "domain": domain,
        "tier": "active", "status": "active", "tags": ["t"], "title": title,
        "relevance": 0.5, "one_liner": f"one liner {text}", "core_digest": f"core {text}",
        "extended_digest": "ext", "changelog": "c", "search_text": f"{title} {text}",
        "vector": None, "body_hash": "h", "created": "2026-01-01", "updated": "2026-01-01",
        "embedding_model": "", "embedding_provider": "",
        "tokens_one_liner": 3, "tokens_core": 3, "tokens_extended": 1,
    }


def test_digest_to_lancedb(tmp_path):
    from app.digest.generator import _generate_id, generate_digest

    vault = tmp_path / "vault"
    src = _make_wiki_file(vault)
    with patch("app.digest.generator.llm_call", return_value=LLM_RESPONSE), \
            patch("shared.embedding_client.embed", side_effect=_emb):
        res = generate_digest(src, str(vault), force=True)

    assert res["status"] == "ok", res
    rec = vector_store.get_by_id(_generate_id("idea", src))
    assert rec is not None
    assert len(ALL_FIELDS) == 23
    for f in ALL_FIELDS:
        assert f in rec
        if f == "vector":
            assert rec[f] is not None and len(rec[f]) == 768
        elif f == "tags":
            assert rec[f] == ["test", "fixture"]
        elif f in ("relevance", "tokens_one_liner", "tokens_core", "tokens_extended"):
            assert rec[f] > 0, f
        else:
            assert rec[f] not in ("", None), f
    assert rec["domain"] == "general" and rec["type"] == "idea"


def test_digest_body_hash_skip(tmp_path):
    from app.digest.generator import generate_digest

    vault = tmp_path / "vault"
    src = _make_wiki_file(vault)
    with patch("app.digest.generator.llm_call", return_value=LLM_RESPONSE) as llm, \
            patch("shared.embedding_client.embed", side_effect=_emb):
        r1 = generate_digest(src, str(vault), force=True)
        r2 = generate_digest(src, str(vault))

    assert r1["status"] == "ok"
    assert r2["status"] == "skip"
    assert llm.call_count == 1


def test_digest_null_vector(tmp_path):
    from app.digest.generator import _generate_id, generate_digest

    vault = tmp_path / "vault"
    src = _make_wiki_file(vault)
    with patch("app.digest.generator.llm_call", return_value=LLM_RESPONSE), \
            patch("shared.embedding_client.embed", return_value=None):
        res = generate_digest(src, str(vault), force=True)

    assert res["status"] == "ok", res
    rec = vector_store.get_by_id(_generate_id("idea", src))
    assert rec is not None
    assert rec["vector"] is None
    assert rec["title"] == "Тестовая идея"
    assert rec["one_liner"] and rec["core_digest"] and rec["extended_digest"] and rec["changelog"]
    assert rec["embedding_model"] == ""


def test_search_after_digest():
    for i, dom in enumerate(["alpha", "beta", "gamma"]):
        vector_store.upsert(_record(f"id-{i}", domain=dom, title=f"Бронирование {dom}", text="бронирование отелей"))

    res = vector_store.hybrid_search("бронирование", query_vector=None)
    assert len(res) == 3
    r = res[0]
    assert isinstance(r, vector_store.SearchResult)
    assert r.id.startswith("id-") and r.title and r.domain and r.type == "idea"
    assert r.score > 0 and r.one_liner and r.snippet and r.source_path
    assert r.semantic_score is None


def test_search_with_filters():
    vector_store.upsert(_record("a", domain="alpha", rtype="idea", text="поисковое слово"))
    vector_store.upsert(_record("b", domain="beta", rtype="idea", text="поисковое слово"))
    vector_store.upsert(_record("c", domain="alpha", rtype="prd", text="поисковое слово"))

    by_domain = vector_store.hybrid_search("поисковое", domain="alpha")
    assert {r.id for r in by_domain} == {"a", "c"}

    by_type = vector_store.hybrid_search("поисковое", artifact_type="idea")
    assert {r.id for r in by_type} == {"a", "b"}

    both = vector_store.hybrid_search("поисковое", domain="alpha", artifact_type="prd")
    assert {r.id for r in both} == {"c"}


def test_reindex_fills_db(tmp_path):
    from app.reindexer import reindex_vault

    vault = tmp_path / "vault"
    for n in ("idea-one", "idea-two", "idea-three"):
        _make_wiki_file(vault, n, body=f"Текст идеи {n}.")
    with patch("app.digest.generator.llm_call", return_value=LLM_RESPONSE), \
            patch("shared.embedding_client.embed", side_effect=_emb):
        rep = reindex_vault(str(vault), full=True)

    assert rep["status"] == "ok" and rep["errors"] == 0, rep
    stats = vector_store.get_stats()
    assert stats["total"] == 3
    assert stats["with_vectors"] == 3


def _make_llm_wiki_file(vault: Path, name: str) -> Path:
    d = vault / "llm_wiki" / "domains" / "general" / "ideas"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}.md"
    p.write_text(
        "---\n"
        f"source: wiki/general/ideas/{name}.md\nartifact_type: idea\ndomain: general\n"
        "body_hash: abc123\nvalidation: passed\ntitle: Тестовая идея\ntier: active\n"
        "status: active\ntags: [test]\nrelevance: 0.8\n---\n\n"
        "## ONE-LINER\n\nКраткое описание тестовой идеи.\n\n"
        "## CORE DIGEST\n\nОсновной дайджест тестовой идеи с подробностями.\n\n"
        "## EXTENDED DIGEST\n\nРасширенный анализ тестовой идеи.\n\n"
        "## CHANGELOG\n\n- Создан дайджест.\n",
        encoding="utf-8",
    )
    return p


def test_migration_from_llm_wiki(tmp_path):
    from app.migrator import migrate_llm_wiki_to_lancedb

    vault = tmp_path / "vault"
    for n in ("test-a", "test-b"):
        _make_llm_wiki_file(vault, n)
    with patch("shared.embedding_client.embed", side_effect=_emb):
        res = migrate_llm_wiki_to_lancedb(str(vault))

    assert res["status"] == "ok" and res["errors"] == 0, res
    assert vector_store.get_stats()["total"] == 2
    rec = vector_store.get_by_id("layer1p-idea-test-a")
    assert rec is not None
    assert rec["one_liner"] == "Краткое описание тестовой идеи."
    assert rec["core_digest"].startswith("Основной дайджест")
    assert rec["extended_digest"].startswith("Расширенный анализ")
    assert rec["changelog"].startswith("- Создан")
    assert rec["domain"] == "general" and rec["tags"] == ["test"]
    assert rec["body_hash"] == "abc123"
    assert rec["vector"] is not None


def _load_pm_bot_vault_search():
    """Загрузить pm-bot/app как отдельный пакет (имя `app` занято knowledge-engine)."""
    pkg_dir = ROOT / "pm-bot" / "app"
    name = "pmbot_app"
    if name + ".vault_search" in sys.modules:
        return sys.modules[name + ".vault_search"]
    spec = importlib.util.spec_from_file_location(
        name, pkg_dir / "__init__.py", submodule_search_locations=[str(pkg_dir)]
    )
    pkg = importlib.util.module_from_spec(spec)
    sys.modules[name] = pkg
    try:
        spec.loader.exec_module(pkg)
        return importlib.import_module(name + ".vault_search")
    except Exception:
        sys.modules.pop(name, None)
        raise


def test_search_backward_compat():
    try:
        vs_mod = _load_pm_bot_vault_search()
    except Exception as e:
        pytest.skip(f"pm-bot vault_search not importable here: {e}")

    vector_store.upsert(_record("x1", domain="alpha", title="Бронирование", text="бронирование отелей"))
    vector_store.upsert(_record("x2", domain="beta", title="Оплата", text="бронирование оплата"))
    with patch("shared.embedding_client.embed", side_effect=_emb):
        results = vs_mod.search_vault("бронирование")

    assert results
    for r in results:
        for key in ("title", "domain", "score", "path", "category", "artifact_id", "url", "tags", "date"):
            assert key in r, key
        assert r["title"] and r["domain"] and r["score"] > 0 and r["path"]
