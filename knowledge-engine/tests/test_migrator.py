"""Тесты миграции llm_wiki/ → LanceDB (BL-237)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app import migrator

DIGEST = """---
source: wiki/domain/ideas/{name}.md
artifact_type: idea
domain: general
tier: active
status: new
tags: [a, b]
title: Title {name}
relevance: 0.5
body_hash: hash-{name}
validation: passed
---

## ONE-LINER

Short {name}.

## CORE DIGEST

Core text.

## EXTENDED DIGEST

Extended text.

## CHANGELOG

- change 1
"""


class _FakeLP:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def vault(tmp_path):
    wiki = tmp_path / "llm_wiki"
    wiki.mkdir()
    for name in ("one", "two", "three"):
        (wiki / f"{name}.md").write_text(DIGEST.format(name=name), encoding="utf-8")
    (wiki / "_index.md").write_text("# index", encoding="utf-8")
    (wiki / "_cowork-session.md").write_text("# session", encoding="utf-8")
    return tmp_path


@pytest.fixture
def mocks():
    emb = SimpleNamespace(vector=[0.1] * 768, model="m", provider="p", dim=768)
    with patch("shared.system_log.LoggedProcess", _FakeLP), \
         patch("shared.vector_store.upsert") as upsert, \
         patch("shared.vector_store.get_stats", return_value={"total": 3}) as stats, \
         patch("shared.embedding_client.embed", return_value=emb) as embed:
        yield SimpleNamespace(upsert=upsert, stats=stats, embed=embed)


def test_migrate_success(vault, mocks):
    res = migrator.migrate_llm_wiki_to_lancedb(str(vault))
    assert res["status"] == "ok"
    assert res["total_files"] == 3
    assert res["migrated"] == 3
    assert res["errors"] == 0
    assert res["with_vectors"] == 3
    assert mocks.upsert.call_count == 3
    rec = mocks.upsert.call_args_list[0].args[0]
    assert len(rec) == 23
    assert rec["id"].startswith("layer1p-idea-")
    assert rec["tags"] == ["a", "b"]
    assert rec["core_digest"] == "Core text."


def test_migrate_dry_run(vault, mocks):
    res = migrator.migrate_llm_wiki_to_lancedb(str(vault), dry_run=True)
    assert res["status"] == "ok"
    assert res["total_files"] == 3
    mocks.upsert.assert_not_called()
    mocks.embed.assert_not_called()


def test_migrate_skip_index(vault, mocks):
    res = migrator.migrate_llm_wiki_to_lancedb(str(vault), dry_run=True)
    assert "_index.md" not in res["files"]
    assert "_cowork-session.md" not in res["files"]


def test_migrate_no_llm_wiki(tmp_path, mocks):
    res = migrator.migrate_llm_wiki_to_lancedb(str(tmp_path))
    assert res == {"status": "skip", "message": "llm_wiki/ not found"}


def test_migrate_embedding_failure(vault, mocks):
    mocks.embed.return_value = None
    res = migrator.migrate_llm_wiki_to_lancedb(str(vault))
    assert res["migrated"] == 3
    assert res["with_vectors"] == 0
    assert mocks.upsert.call_args_list[0].args[0]["vector"] is None


def test_migrate_partial_error(vault, mocks):
    mocks.upsert.side_effect = [None, RuntimeError("boom"), None]
    res = migrator.migrate_llm_wiki_to_lancedb(str(vault))
    assert res["status"] == "ok"
    assert res["migrated"] == 2
    assert res["errors"] == 1
    assert mocks.upsert.call_count == 3


def test_parse_sections():
    body = "## ONE-LINER\n\nA\n\n## CORE DIGEST\n\nB\n\n## EXTENDED DIGEST\n\nC\n\n## CHANGELOG\n\n- D\n"
    s = migrator._parse_digest_sections(body)
    assert s == {"one_liner": "A", "core_digest": "B", "extended_digest": "C", "changelog": "- D"}
