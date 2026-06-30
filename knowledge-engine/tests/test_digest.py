"""Tests for app.digest.* modules (paths, token_counter, templates, validator, generator)."""

import os
import importlib
from pathlib import Path
from unittest.mock import patch

import frontmatter as fm_lib
import pytest

from app.digest.paths import (
    wiki_to_llm_wiki,
    llm_wiki_to_wiki,
    llm_wiki_index,
    ensure_llm_wiki_structure,
)
from app.digest.token_counter import count_tokens, count_sections
from app.digest.templates import (
    detect_type,
    get_required_fields,
    get_template,
    ARTIFACT_TYPE_MAP,
    ALL_TYPES,
)
from app.digest.validator import validate, ValidationResult
from app.digest.generator import (
    generate_digest,
    generate_bulk,
    regenerate_index,
    _compute_body_hash,
)


def _create_md_file(path: Path, metadata: dict, body: str = "Content here"):
    path.parent.mkdir(parents=True, exist_ok=True)
    post = fm_lib.Post(body, **metadata)
    path.write_text(fm_lib.dumps(post), encoding="utf-8")


# ---------------------------------------------------------------------------
# app.digest.paths
# ---------------------------------------------------------------------------


class TestPaths:
    def test_wiki_to_llm_wiki_converts(self, tmp_path):
        wiki_path = tmp_path / "wiki" / "domains" / "search" / "prds" / "x.md"
        result = wiki_to_llm_wiki(wiki_path, tmp_path)
        assert result == tmp_path / "llm_wiki" / "domains" / "search" / "prds" / "x.md"

    def test_wiki_to_llm_wiki_not_under_wiki_raises(self, tmp_path):
        other_path = tmp_path / "raw" / "inbound" / "ideas" / "x.md"
        with pytest.raises(ValueError):
            wiki_to_llm_wiki(other_path, tmp_path)

    def test_llm_wiki_to_wiki_converts(self, tmp_path):
        llm_wiki_path = tmp_path / "llm_wiki" / "domains" / "search" / "prds" / "x.md"
        result = llm_wiki_to_wiki(llm_wiki_path, tmp_path)
        assert result == tmp_path / "wiki" / "domains" / "search" / "prds" / "x.md"

    def test_llm_wiki_to_wiki_not_under_llm_wiki_raises(self, tmp_path):
        other_path = tmp_path / "wiki" / "domains" / "search" / "prds" / "x.md"
        with pytest.raises(ValueError):
            llm_wiki_to_wiki(other_path, tmp_path)

    def test_llm_wiki_index(self, tmp_path):
        result = llm_wiki_index(tmp_path)
        assert result == tmp_path / "llm_wiki" / "_index.md"

    def test_ensure_llm_wiki_structure_creates_base_dirs(self, tmp_path):
        ensure_llm_wiki_structure(tmp_path)
        assert (tmp_path / "llm_wiki").exists()
        assert (tmp_path / "llm_wiki" / "meetings").exists()
        assert (tmp_path / "llm_wiki" / "daily-logs").exists()
        assert (tmp_path / "llm_wiki" / "reports").exists()

    def test_ensure_llm_wiki_structure_mirrors_domains(self, tmp_path):
        (tmp_path / "wiki" / "domains" / "search" / "ideas").mkdir(parents=True)
        (tmp_path / "wiki" / "domains" / "search" / "prds").mkdir(parents=True)
        (tmp_path / "wiki" / "domains" / "booking" / "epics").mkdir(parents=True)

        ensure_llm_wiki_structure(tmp_path)

        assert (tmp_path / "llm_wiki" / "domains" / "search" / "ideas").exists()
        assert (tmp_path / "llm_wiki" / "domains" / "search" / "prds").exists()
        assert (tmp_path / "llm_wiki" / "domains" / "booking" / "epics").exists()

    def test_ensure_llm_wiki_structure_no_domains_dir(self, tmp_path):
        # wiki/domains does not exist at all -- should not raise
        ensure_llm_wiki_structure(tmp_path)
        assert (tmp_path / "llm_wiki").exists()


# ---------------------------------------------------------------------------
# app.digest.token_counter
# ---------------------------------------------------------------------------


class TestTokenCounter:
    def test_count_tokens_empty(self):
        assert count_tokens("") == 0

    def test_count_tokens_english(self):
        assert count_tokens("hello world") > 0

    def test_count_tokens_cyrillic(self):
        assert count_tokens("Привет мир") > 0

    def test_count_sections_full_body(self):
        body = (
            "# one-liner\n"
            "Short summary\n"
            "\n"
            "# core-digest\n"
            "- суть: something\n"
            "- статус: active\n"
            "\n"
            "# extended-digest\n"
            "Long description here\n"
            "\n"
            "# changelog\n"
            "- Initial generation\n"
        )
        counts = count_sections(body)
        assert set(counts.keys()) == {
            "one_liner",
            "core_digest",
            "extended_digest",
            "changelog",
            "total",
        }
        assert counts["one_liner"] > 0
        assert counts["core_digest"] > 0
        assert counts["extended_digest"] > 0
        assert counts["changelog"] > 0
        assert counts["total"] > 0
        assert counts["total"] == (
            counts["one_liner"]
            + counts["core_digest"]
            + counts["extended_digest"]
            + counts["changelog"]
        )

    def test_count_sections_missing_changelog(self):
        body = (
            "# one-liner\n"
            "Short summary\n"
            "\n"
            "# core-digest\n"
            "- суть: something\n"
            "\n"
            "# extended-digest\n"
            "Long description here\n"
        )
        counts = count_sections(body)
        assert counts["changelog"] == 0
        assert counts["one_liner"] > 0
        assert counts["core_digest"] > 0
        assert counts["extended_digest"] > 0


# ---------------------------------------------------------------------------
# app.digest.templates
# ---------------------------------------------------------------------------


class TestTemplates:
    def test_detect_type_from_frontmatter(self):
        path = Path("wiki/domains/search/ideas/x.md")
        result = detect_type(path, {"type": "prd"})
        assert result == "prd"

    def test_detect_type_from_path_prds(self):
        path = Path("wiki/domains/search/prds/x.md")
        result = detect_type(path, {})
        assert result == "prd"

    def test_detect_type_from_path_meetings(self):
        path = Path("wiki/meetings/2026-06-30-meeting.md")
        result = detect_type(path, {})
        assert result == "meeting"

    def test_detect_type_fallback(self):
        path = Path("wiki/domains/search/notes/x.md")
        result = detect_type(path, {})
        assert result == "idea"

    def test_detect_type_invalid_frontmatter_type_falls_through(self):
        path = Path("wiki/domains/search/prds/x.md")
        result = detect_type(path, {"type": "not-a-real-type"})
        assert result == "prd"

    def test_get_required_fields_prd(self):
        assert get_required_fields("prd") == [
            "статус",
            "цель",
            "ключевые_требования",
            "зависимости",
        ]

    def test_get_required_fields_unknown(self):
        assert get_required_fields("unknown") == []

    def test_get_template_existing(self):
        result = get_template("prd")
        assert isinstance(result, str)
        assert result != ""

    def test_get_template_nonexistent(self):
        result = get_template("nonexistent_type")
        assert result == ""

    def test_artifact_type_map_contains_expected_keys(self):
        assert ARTIFACT_TYPE_MAP["ideas"] == "idea"
        assert ARTIFACT_TYPE_MAP["prds"] == "prd"

    def test_all_types_contains_prd_and_idea(self):
        assert "prd" in ALL_TYPES
        assert "idea" in ALL_TYPES


# ---------------------------------------------------------------------------
# app.digest.validator
# ---------------------------------------------------------------------------


class TestValidator:
    def _valid_core_digest(self):
        return (
            "- статус: draft\n"
            "- цель: тестовая цель\n"
            "- ключевые_требования: требование 1\n"
            "- зависимости: нет\n"
        )

    def test_validate_all_pass(self, tmp_path):
        source_path = tmp_path / "wiki" / "domains" / "search" / "prds" / "x.md"
        _create_md_file(source_path, {"type": "prd"})

        digest_data = {
            "frontmatter": {},
            "one_liner": "Короткое описание",
            "core_digest": self._valid_core_digest(),
            "extended_digest": "Расширенное описание " * 10,
            "changelog": "- Первичная генерация",
            "artifact_type": "prd",
        }
        token_counts = {"one_liner": 10, "core_digest": 300, "extended_digest": 500}

        result = validate(digest_data, source_path, str(tmp_path), token_counts)

        assert isinstance(result, ValidationResult)
        assert result.valid is True
        assert result.errors == []

    def test_validate_token_budget_exceeded(self, tmp_path):
        source_path = tmp_path / "wiki" / "domains" / "search" / "prds" / "x.md"
        _create_md_file(source_path, {"type": "prd"})

        digest_data = {
            "frontmatter": {},
            "one_liner": "Очень длинное однострочное описание " * 5,
            "core_digest": self._valid_core_digest(),
            "extended_digest": "Расширенное описание " * 10,
            "changelog": "- Первичная генерация",
            "artifact_type": "prd",
        }
        token_counts = {"one_liner": 50, "core_digest": 300, "extended_digest": 500}

        result = validate(digest_data, source_path, str(tmp_path), token_counts)

        assert result.valid is False
        assert any("exceeds token budget" in e for e in result.errors)

    def test_validate_missing_required_field(self, tmp_path):
        source_path = tmp_path / "wiki" / "domains" / "search" / "prds" / "x.md"
        _create_md_file(source_path, {"type": "prd"})

        core_digest_missing_status = (
            "- цель: тестовая цель\n"
            "- ключевые_требования: требование 1\n"
            "- зависимости: нет\n"
        )
        digest_data = {
            "frontmatter": {},
            "one_liner": "Короткое описание",
            "core_digest": core_digest_missing_status,
            "extended_digest": "Расширенное описание " * 10,
            "changelog": "- Первичная генерация",
            "artifact_type": "prd",
        }
        token_counts = {"one_liner": 10, "core_digest": 300, "extended_digest": 500}

        result = validate(digest_data, source_path, str(tmp_path), token_counts)

        assert result.valid is False
        assert any("missing required field: статус" in e for e in result.errors)

    def test_validate_empty_changelog(self, tmp_path):
        source_path = tmp_path / "wiki" / "domains" / "search" / "prds" / "x.md"
        _create_md_file(source_path, {"type": "prd"})

        digest_data = {
            "frontmatter": {},
            "one_liner": "Короткое описание",
            "core_digest": self._valid_core_digest(),
            "extended_digest": "Расширенное описание " * 10,
            "changelog": "",
            "artifact_type": "prd",
        }
        token_counts = {"one_liner": 10, "core_digest": 300, "extended_digest": 500}

        result = validate(digest_data, source_path, str(tmp_path), token_counts)

        assert result.valid is False
        assert any("changelog section is empty" in e for e in result.errors)

    def test_validate_key_value_format_violation(self, tmp_path):
        source_path = tmp_path / "wiki" / "domains" / "search" / "prds" / "x.md"
        _create_md_file(source_path, {"type": "prd"})

        # Less than 70% of lines start with "- "
        bad_core_digest = (
            "статус: draft\n"
            "цель: тестовая цель\n"
            "ключевые_требования: требование 1\n"
            "- зависимости: нет\n"
        )
        digest_data = {
            "frontmatter": {},
            "one_liner": "Короткое описание",
            "core_digest": bad_core_digest,
            "extended_digest": "Расширенное описание " * 10,
            "changelog": "- Первичная генерация",
            "artifact_type": "",  # no required fields, isolates this check
        }
        token_counts = {"one_liner": 10, "core_digest": 300, "extended_digest": 500}

        result = validate(digest_data, source_path, str(tmp_path), token_counts)

        assert result.valid is False
        assert any("not in key-value format" in e for e in result.errors)

    def test_validate_source_not_exists(self, tmp_path):
        source_path = tmp_path / "wiki" / "domains" / "search" / "prds" / "missing.md"
        # Note: source_path is NOT created

        digest_data = {
            "frontmatter": {},
            "one_liner": "Короткое описание",
            "core_digest": self._valid_core_digest(),
            "extended_digest": "Расширенное описание " * 10,
            "changelog": "- Первичная генерация",
            "artifact_type": "prd",
        }
        token_counts = {"one_liner": 10, "core_digest": 300, "extended_digest": 500}

        result = validate(digest_data, source_path, str(tmp_path), token_counts)

        assert result.valid is False
        assert any("source file does not exist" in e for e in result.errors)


# ---------------------------------------------------------------------------
# app.digest.generator
# ---------------------------------------------------------------------------

_LLM_RESPONSE = (
    "# one-liner\n"
    "Тестовая идея для юнит-тестов\n"
    "\n"
    "# core-digest\n"
    "- суть: тестовая идея\n"
    "- статус: draft\n"
    "- domain: test\n"
    "\n"
    "# extended-digest\n"
    "Расширенное описание тестовой идеи для юнит-тестирования модуля digest.\n"
    "\n"
    "# changelog\n"
    "- Первичная генерация дайджеста\n"
)

_FAKE_COUNTS = {
    "one_liner": 10,
    "core_digest": 300,
    "extended_digest": 100,
    "total": 410,
    "changelog": 5,
}


class TestComputeBodyHash:
    def test_hash_is_16_hex_chars(self):
        h = _compute_body_hash("some body text")
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)

    def test_same_body_same_hash(self):
        h1 = _compute_body_hash("identical content")
        h2 = _compute_body_hash("identical content")
        assert h1 == h2

    def test_different_body_different_hash(self):
        h1 = _compute_body_hash("content A")
        h2 = _compute_body_hash("content B")
        assert h1 != h2


class TestGenerateDigest:
    def _make_source(self, tmp_path, body="Тестовая идея, требующая дайджеста."):
        source_path = tmp_path / "wiki" / "domains" / "test" / "ideas" / "test-idea.md"
        _create_md_file(
            source_path,
            {"статус": "draft", "domain": "test"},
            body=body,
        )
        return source_path

    def test_generate_digest_ok(self, tmp_path):
        source_path = self._make_source(tmp_path)

        with patch("app.digest.generator.llm_call", return_value=_LLM_RESPONSE) as mock_llm, \
             patch("app.digest.generator.count_sections", return_value=_FAKE_COUNTS), \
             patch("app.digest.generator.validate", return_value=ValidationResult(valid=True)):
            result = generate_digest(source_path, vault_path=str(tmp_path))

        assert mock_llm.called
        assert result["status"] == "ok"
        assert "llm_wiki" in result["digest_path"]
        assert len(result["body_hash"]) == 16
        assert Path(result["digest_path"]).exists()

    def test_generate_digest_skip_on_matching_hash(self, tmp_path):
        source_path = self._make_source(tmp_path)
        # Read the body that was actually written to compute matching hash.
        meta, body = fm_lib.load(str(source_path)).metadata, fm_lib.load(str(source_path)).content
        existing_hash = _compute_body_hash(body)

        digest_path = tmp_path / "llm_wiki" / "domains" / "test" / "ideas" / "test-idea.md"
        _create_md_file(
            digest_path,
            {
                "id": "layer1p-idea-test-idea",
                "type": "idea",
                "domain": "test",
                "updated": "2026-06-30",
                "body_hash": existing_hash,
            },
            body="# one-liner\nexisting\n",
        )

        # No LLM mock needed: skip happens before any LLM call.
        result = generate_digest(source_path, vault_path=str(tmp_path))

        assert result["status"] == "skip"
        assert result["digest_path"] == str(digest_path)

    def test_generate_digest_force_regenerates_despite_matching_hash(self, tmp_path):
        source_path = self._make_source(tmp_path)
        meta, body = fm_lib.load(str(source_path)).metadata, fm_lib.load(str(source_path)).content
        existing_hash = _compute_body_hash(body)

        digest_path = tmp_path / "llm_wiki" / "domains" / "test" / "ideas" / "test-idea.md"
        _create_md_file(
            digest_path,
            {
                "id": "layer1p-idea-test-idea",
                "type": "idea",
                "domain": "test",
                "updated": "2026-06-30",
                "body_hash": existing_hash,
            },
            body="# one-liner\nexisting\n",
        )

        with patch("app.digest.generator.llm_call", return_value=_LLM_RESPONSE) as mock_llm, \
             patch("app.digest.generator.count_sections", return_value=_FAKE_COUNTS), \
             patch("app.digest.generator.validate", return_value=ValidationResult(valid=True)):
            result = generate_digest(source_path, vault_path=str(tmp_path), force=True)

        assert mock_llm.called
        assert result["status"] == "ok"


class TestGenerateBulk:
    def test_generate_bulk_counts_total_and_generated(self, tmp_path):
        ideas_dir = tmp_path / "wiki" / "domains" / "test" / "ideas"
        _create_md_file(ideas_dir / "idea-1.md", {"статус": "draft", "domain": "test"})
        _create_md_file(ideas_dir / "idea-2.md", {"статус": "draft", "domain": "test"})

        with patch("app.digest.generator.vault_paths.VAULT_PATH", tmp_path), \
             patch("app.digest.generator.generate_digest", return_value={"status": "ok"}) as mock_gen, \
             patch("app.digest.generator.time.sleep"):
            result = generate_bulk()

        assert result["total"] == 2
        assert result["generated"] == 2
        assert mock_gen.call_count == 2


class TestRegenerateIndex:
    def test_regenerate_index_creates_index_with_entries(self, tmp_path):
        # Original wiki/ artifacts (provide tier/relevance for index sorting)
        wiki1 = tmp_path / "wiki" / "domains" / "test" / "ideas" / "idea-1.md"
        wiki2 = tmp_path / "wiki" / "domains" / "test" / "ideas" / "idea-2.md"
        _create_md_file(wiki1, {"tier": "active", "relevance": 0.9})
        _create_md_file(wiki2, {"tier": "core", "relevance": 1.0})

        digest1 = tmp_path / "llm_wiki" / "domains" / "test" / "ideas" / "idea-1.md"
        digest2 = tmp_path / "llm_wiki" / "domains" / "test" / "ideas" / "idea-2.md"
        _create_md_file(
            digest1,
            {
                "id": "layer1p-idea-idea-1",
                "type": "idea",
                "domain": "test",
                "updated": "2026-06-30",
                "token_count": {"one_liner": 10, "core_digest": 200, "extended_digest": 50, "total": 260},
                "body_hash": "aaaaaaaaaaaaaaaa",
                "source": "wiki/domains/test/ideas/idea-1.md",
            },
            body="# one-liner\nIdea one summary\n",
        )
        _create_md_file(
            digest2,
            {
                "id": "layer1p-idea-idea-2",
                "type": "idea",
                "domain": "test",
                "updated": "2026-06-30",
                "token_count": {"one_liner": 10, "core_digest": 200, "extended_digest": 50, "total": 260},
                "body_hash": "bbbbbbbbbbbbbbbb",
                "source": "wiki/domains/test/ideas/idea-2.md",
            },
            body="# one-liner\nIdea two summary\n",
        )

        result = regenerate_index(str(tmp_path))

        assert result["status"] == "ok"
        assert result["entries"] == 2

        index_path = tmp_path / "llm_wiki" / "_index.md"
        assert index_path.exists()
        content = index_path.read_text(encoding="utf-8")
        assert "layer1p-idea-idea-1" in content
        assert "layer1p-idea-idea-2" in content

    def test_regenerate_index_no_llm_wiki_dir(self, tmp_path):
        result = regenerate_index(str(tmp_path))
        assert result["status"] == "ok"
        assert result["entries"] == 0
        assert (tmp_path / "llm_wiki" / "_index.md").exists()
