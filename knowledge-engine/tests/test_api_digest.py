"""Интеграционные тесты API-эндпоинтов digest (BL-147, T-22).

Покрывают additive-эндпоинты api.py:
  - POST /api/v1/digest/generate  (генерация дайджеста для одного файла)
  - POST /api/v1/digest/bulk      (массовая генерация)
  - GET  /api/v1/digest/status    (статистика покрытия)

LLM не вызывается: тесты работают на пустом vault или проверяют маршрутизацию
запросов / структуру ответов. Для generate/bulk используется mock generate_digest
и generate_bulk, чтобы не зависеть от LLM-провайдера.
"""

from __future__ import annotations

import pathlib
import textwrap

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient с vault, указанным на временную папку."""
    from app import api
    from shared import vault_paths as _vp

    monkeypatch.setattr(_vp, "VAULT_PATH", pathlib.Path(tmp_path))
    return TestClient(api.app)


# ---------------------------------------------------------------------------
# GET /api/v1/digest/status
# ---------------------------------------------------------------------------

class TestDigestStatus:
    def test_empty_vault(self, client):
        """Пустой vault → 200, все счётчики по нулям, coverage 0.0."""
        resp = client.get("/api/v1/digest/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["total_wiki_artifacts"] == 0
        assert data["total_digests"] == 0
        assert data["valid_digests"] == 0
        assert data["failed_digests"] == 0
        assert data["missing_digests"] == 0
        assert data["coverage_percent"] == 0.0

    def test_wiki_without_digests(self, client, tmp_path):
        """Wiki-артефакты есть, llm_wiki пуст → missing = total_wiki, coverage 0."""
        wiki_dir = tmp_path / "wiki" / "dev"
        wiki_dir.mkdir(parents=True)
        (wiki_dir / "artifact-one.md").write_text("# Test 1\n", encoding="utf-8")
        (wiki_dir / "artifact-two.md").write_text("# Test 2\n", encoding="utf-8")
        # index.md и log.md должны игнорироваться
        (wiki_dir / "index.md").write_text("# Index\n", encoding="utf-8")
        (wiki_dir / "log.md").write_text("# Log\n", encoding="utf-8")

        resp = client.get("/api/v1/digest/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_wiki_artifacts"] == 2
        assert data["total_digests"] == 0
        assert data["missing_digests"] == 2
        assert data["coverage_percent"] == 0.0

    def test_full_coverage(self, client, tmp_path):
        """Wiki + llm_wiki с валидными дайджестами → coverage 100%."""
        wiki_dir = tmp_path / "wiki" / "dev"
        wiki_dir.mkdir(parents=True)
        (wiki_dir / "artifact-one.md").write_text("# Test 1\n", encoding="utf-8")

        llm_wiki_dir = tmp_path / "llm_wiki" / "dev"
        llm_wiki_dir.mkdir(parents=True)
        digest_content = textwrap.dedent("""\
            ---
            validation: passed
            source: wiki/dev/artifact-one.md
            ---
            # Digest
        """)
        (llm_wiki_dir / "artifact-one.md").write_text(digest_content, encoding="utf-8")
        # _index.md должен игнорироваться
        (llm_wiki_dir / "_index.md").write_text("# Index\n", encoding="utf-8")

        resp = client.get("/api/v1/digest/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_wiki_artifacts"] == 1
        assert data["total_digests"] == 1
        assert data["valid_digests"] == 1
        assert data["failed_digests"] == 0
        assert data["missing_digests"] == 0
        assert data["coverage_percent"] == 100.0

    def test_partial_coverage_with_failed(self, client, tmp_path):
        """Частичное покрытие + failed дайджест → корректные счётчики."""
        wiki_dir = tmp_path / "wiki" / "dev"
        wiki_dir.mkdir(parents=True)
        (wiki_dir / "a.md").write_text("# A\n", encoding="utf-8")
        (wiki_dir / "b.md").write_text("# B\n", encoding="utf-8")
        (wiki_dir / "c.md").write_text("# C\n", encoding="utf-8")

        llm_wiki_dir = tmp_path / "llm_wiki" / "dev"
        llm_wiki_dir.mkdir(parents=True)

        passed_content = textwrap.dedent("""\
            ---
            validation: passed
            ---
            # Digest A
        """)
        (llm_wiki_dir / "a.md").write_text(passed_content, encoding="utf-8")

        failed_content = textwrap.dedent("""\
            ---
            validation: failed
            ---
            # Digest B
        """)
        (llm_wiki_dir / "b.md").write_text(failed_content, encoding="utf-8")

        resp = client.get("/api/v1/digest/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_wiki_artifacts"] == 3
        assert data["total_digests"] == 2
        assert data["valid_digests"] == 1
        assert data["failed_digests"] == 1
        assert data["missing_digests"] == 1
        assert data["coverage_percent"] == 66.7

    def test_response_keys(self, client):
        """Проверка контракта: набор ключей ответа стабилен."""
        resp = client.get("/api/v1/digest/status")

        assert resp.status_code == 200
        assert set(resp.json().keys()) == {
            "status",
            "total_wiki_artifacts",
            "total_digests",
            "valid_digests",
            "failed_digests",
            "missing_digests",
            "coverage_percent",
        }


# ---------------------------------------------------------------------------
# POST /api/v1/digest/generate
# ---------------------------------------------------------------------------

class TestDigestGenerate:
    def test_generate_calls_generator(self, client, monkeypatch):
        """Эндпоинт вызывает generate_digest и возвращает результат."""
        mock_result = {"status": "ok", "digest_path": "llm_wiki/dev/test.md"}

        def fake_generate(source_path, vault_path, force=False):
            assert isinstance(source_path, pathlib.Path)
            assert force is True
            return mock_result

        import app.digest.generator as gen_mod
        monkeypatch.setattr(gen_mod, "generate_digest", fake_generate)

        resp = client.post(
            "/api/v1/digest/generate",
            json={"filepath": "wiki/dev/test.md", "force": True},
        )

        assert resp.status_code == 200
        assert resp.json() == mock_result

    def test_generate_default_force_false(self, client, monkeypatch):
        """force по умолчанию = False."""
        captured = {}

        def fake_generate(source_path, vault_path, force=False):
            captured["force"] = force
            return {"status": "ok"}

        import app.digest.generator as gen_mod
        monkeypatch.setattr(gen_mod, "generate_digest", fake_generate)

        resp = client.post(
            "/api/v1/digest/generate",
            json={"filepath": "wiki/dev/test.md"},
        )

        assert resp.status_code == 200
        assert captured["force"] is False

    def test_generate_error_returns_500(self, client, monkeypatch):
        """Ошибка в generate_digest → 500 с detail."""
        def fake_generate(source_path, vault_path, force=False):
            raise RuntimeError("LLM unavailable")

        import app.digest.generator as gen_mod
        monkeypatch.setattr(gen_mod, "generate_digest", fake_generate)

        resp = client.post(
            "/api/v1/digest/generate",
            json={"filepath": "wiki/dev/test.md"},
        )

        assert resp.status_code == 500
        assert "LLM unavailable" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/v1/digest/bulk
# ---------------------------------------------------------------------------

class TestDigestBulk:
    def test_bulk_calls_generator(self, client, monkeypatch):
        """Эндпоинт вызывает generate_bulk с корректными параметрами."""
        mock_result = {"status": "ok", "generated": 5, "skipped": 2, "failed": 0}

        def fake_bulk(vault_path, domain=None, artifact_type=None, force=False):
            assert domain == "dev"
            assert artifact_type == "notes"
            assert force is True
            return mock_result

        import app.digest.generator as gen_mod
        monkeypatch.setattr(gen_mod, "generate_bulk", fake_bulk)

        resp = client.post(
            "/api/v1/digest/bulk",
            json={"domain": "dev", "type": "notes", "force": True},
        )

        assert resp.status_code == 200
        assert resp.json() == mock_result

    def test_bulk_defaults(self, client, monkeypatch):
        """Все параметры опциональны, по умолчанию None/False."""
        captured = {}

        def fake_bulk(vault_path, domain=None, artifact_type=None, force=False):
            captured.update({"domain": domain, "artifact_type": artifact_type, "force": force})
            return {"status": "ok", "generated": 0, "skipped": 0, "failed": 0}

        import app.digest.generator as gen_mod
        monkeypatch.setattr(gen_mod, "generate_bulk", fake_bulk)

        resp = client.post("/api/v1/digest/bulk", json={})

        assert resp.status_code == 200
        assert captured["domain"] is None
        assert captured["artifact_type"] is None
        assert captured["force"] is False

    def test_bulk_error_returns_500(self, client, monkeypatch):
        """Ошибка в generate_bulk → 500."""
        def fake_bulk(vault_path, domain=None, artifact_type=None, force=False):
            raise RuntimeError("bulk generation failed")

        import app.digest.generator as gen_mod
        monkeypatch.setattr(gen_mod, "generate_bulk", fake_bulk)

        resp = client.post("/api/v1/digest/bulk", json={})

        assert resp.status_code == 500
        assert "bulk generation failed" in resp.json()["detail"]
