"""Tests for ingest module -- knowledge-engine/app/ingest.py.

Covers all 19 unit tests from design.md section 13.1:
  detect_domain, generate_knowledge_id, generate_concept_id,
  is_already_ingested, ingest_one, ingest_batch,
  _build_wiki_content.
"""

import importlib
import logging
import os
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_vault(tmp_path: Path):
    """Reload vault_paths so VAULT_PATH points to tmp_path."""
    with patch.dict(os.environ, {"VAULT_PATH": str(tmp_path)}):
        from app import vault_paths
        importlib.reload(vault_paths)
    return tmp_path


def _import_ingest(tmp_path: Path):
    """Set up vault and return a freshly-reloaded ingest module."""
    _setup_vault(tmp_path)
    from app import ingest
    importlib.reload(ingest)
    return ingest


def _make_clipping(directory: Path, name: str, tags=None, body="Sample body"):
    """Create a clipping .md file with frontmatter."""
    tags = tags or ["clippings"]
    tags_yaml = "\n".join(f'  - "{t}"' for t in tags)
    content = f"""---
title: "{name}"
source: "https://example.com/{name}"
created: 2026-05-15
tags:
{tags_yaml}
---

{body}
"""
    filepath = directory / f"{name}.md"
    filepath.write_text(content, encoding="utf-8")
    return filepath


def _make_wiki_knowledge_file(vault_root: Path, domain: str, file_id: str,
                               source_file_rel: str):
    """Create a wiki knowledge file with source_file in frontmatter."""
    knowledge_dir = vault_root / "wiki" / "domains" / domain / "knowledge"
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    content = f"""---
id: {file_id}
type: knowledge
domain: {domain}
source_file: {source_file_rel}
status: inbox
---

# Test Knowledge
"""
    filepath = knowledge_dir / f"{file_id}.md"
    filepath.write_text(content, encoding="utf-8")
    return filepath


@pytest.fixture
def vault(tmp_path):
    """Create a minimal vault structure and configure vault_paths."""
    vault_root = tmp_path / "vault"
    raw_clippings = vault_root / "raw" / "inbound" / "clippings"
    raw_clippings.mkdir(parents=True)
    wiki_domains = vault_root / "wiki" / "domains"
    wiki_domains.mkdir(parents=True)
    wiki_concepts = vault_root / "wiki" / "concepts"
    wiki_concepts.mkdir(parents=True)

    _setup_vault(vault_root)
    return vault_root


# ---------------------------------------------------------------------------
# detect_domain
# ---------------------------------------------------------------------------


class TestDetectDomain:
    """Tests for detect_domain function."""

    def test_detect_domain_by_tag(self, vault):
        """Tags ['clippings', 'static'] -> domain 'static-metadata' via tag. (AC-02)"""
        ing = _import_ingest(vault)
        # Monkeypatch _merged_tag_map to avoid needing real domain-config.yaml
        with patch.object(ing, "_merged_tag_map", return_value=dict(ing.TAG_TO_DOMAIN)):
            domain, method = ing.detect_domain(
                {"tags": ["clippings", "static"]},
                "Some body text",
            )
        assert domain == "static-metadata"
        assert method == "tag"

    def test_detect_domain_by_keyword(self, vault):
        """Body containing keyword -> domain 'suggester' via keyword. (AC-03)"""
        ing = _import_ingest(vault)
        with patch.object(ing, "_merged_tag_map", return_value=dict(ing.TAG_TO_DOMAIN)):
            domain, method = ing.detect_domain(
                {"tags": ["clippings"]},
                "This article is about the subsystem and how the подсказчик works.",
            )
        assert domain == "suggester"
        assert method == "keyword"

    def test_detect_domain_none(self, vault):
        """No tag or keyword match -> domain 'none'. (AC-04)"""
        ing = _import_ingest(vault)
        with patch.object(ing, "_merged_tag_map", return_value=dict(ing.TAG_TO_DOMAIN)):
            domain, method = ing.detect_domain(
                {"tags": ["clippings"]},
                "Completely unrelated content about cooking recipes.",
            )
        assert domain == "none"
        assert method == "none"

    def test_detect_domain_ignores_clippings_tag(self, vault):
        """The 'clippings' tag itself must not be used for domain detection."""
        ing = _import_ingest(vault)
        # Only 'clippings' tag present -- should fall through to keyword/none
        with patch.object(ing, "_merged_tag_map", return_value=dict(ing.TAG_TO_DOMAIN)):
            domain, method = ing.detect_domain(
                {"tags": ["clippings"]},
                "No keywords here either.",
            )
        assert domain == "none"
        assert method == "none"

    def test_detect_domain_multiple_match_warning(self, vault, caplog):
        """Multiple domains matched via tags -> highest priority wins + warning logged. (FLOW-01/5d)"""
        ing = _import_ingest(vault)
        # Tags that map to different domains: "static" -> static-metadata, "search" -> search-engine
        with patch.object(ing, "_merged_tag_map", return_value=dict(ing.TAG_TO_DOMAIN)):
            with caplog.at_level(logging.WARNING, logger="app.ingest"):
                domain, method = ing.detect_domain(
                    {"tags": ["clippings", "static", "search"]},
                    "Body text",
                )
        assert domain == "static-metadata"
        assert method == "tag"
        assert any("multiple domains matched" in rec.message.lower() for rec in caplog.records)
        assert any("highest priority" in rec.message.lower() for rec in caplog.records)

    def test_detect_domain_priority_partner_over_static(self, vault, caplog):
        """Tags ['clippings', 'b2b', 'api', 'static'] -> partner-search-engine wins (priority 100 > 80)."""
        ing = _import_ingest(vault)
        with patch.object(ing, "_merged_tag_map", return_value=dict(ing.TAG_TO_DOMAIN)):
            with caplog.at_level(logging.WARNING, logger="app.ingest"):
                domain, method = ing.detect_domain(
                    {"tags": ["clippings", "b2b", "api", "static"]},
                    "Body text",
                )
        assert domain == "partner-search-engine"
        assert method == "tag"
        assert any("multiple domains matched" in rec.message.lower() for rec in caplog.records)

    def test_detect_domain_priority_search_over_suggester(self, vault, caplog):
        """Tags ['clippings', 'search', 'suggester'] -> search-engine wins (priority 70 > 50)."""
        ing = _import_ingest(vault)
        with patch.object(ing, "_merged_tag_map", return_value=dict(ing.TAG_TO_DOMAIN)):
            with caplog.at_level(logging.WARNING, logger="app.ingest"):
                domain, method = ing.detect_domain(
                    {"tags": ["clippings", "search", "suggester"]},
                    "Body text",
                )
        assert domain == "search-engine"
        assert method == "tag"
        assert any("multiple domains matched" in rec.message.lower() for rec in caplog.records)

    def test_detect_domain_keyword_priority_search_over_suggester(self, vault, caplog):
        """Body with both 'подсказчик' and 'поиск' should pick search-engine (priority 80 > 60)."""
        ing = _import_ingest(vault)
        with patch.object(ing, "_merged_tag_map", return_value=dict(ing.TAG_TO_DOMAIN)):
            with caplog.at_level(logging.WARNING, logger="app.ingest"):
                domain, method = ing.detect_domain(
                    {"tags": ["clippings"]},
                    "подсказчик для поиска по объектам с фильтрацией",
                )
        assert domain == "search-engine"
        assert method == "keyword"
        assert any("multiple domains matched" in rec.message.lower() for rec in caplog.records)


# ---------------------------------------------------------------------------
# generate_knowledge_id
# ---------------------------------------------------------------------------


class TestGenerateKnowledgeId:
    """Tests for generate_knowledge_id function."""

    def test_generate_knowledge_id_empty_dir(self, vault):
        """Empty directory -> K-DOMAIN-0001."""
        ing = _import_ingest(vault)
        knowledge_dir = vault / "wiki" / "domains" / "static-metadata" / "knowledge"
        knowledge_dir.mkdir(parents=True)

        result = ing.generate_knowledge_id("static-metadata", knowledge_dir)
        assert result == "K-STATIC-METADATA-0001"

    def test_generate_knowledge_id_existing(self, vault):
        """3 existing files -> K-DOMAIN-0004."""
        ing = _import_ingest(vault)
        knowledge_dir = vault / "wiki" / "domains" / "suggester" / "knowledge"
        knowledge_dir.mkdir(parents=True)

        for i in range(1, 4):
            (knowledge_dir / f"K-SUGGESTER-{i:04d}.md").write_text(
                f"---\nid: K-SUGGESTER-{i:04d}\n---\n", encoding="utf-8"
            )

        result = ing.generate_knowledge_id("suggester", knowledge_dir)
        assert result == "K-SUGGESTER-0004"


# ---------------------------------------------------------------------------
# generate_concept_id
# ---------------------------------------------------------------------------


class TestGenerateConceptId:
    """Tests for generate_concept_id function."""

    def test_generate_concept_id(self, vault):
        """Empty concepts dir -> C-0001."""
        ing = _import_ingest(vault)
        concepts_dir = vault / "wiki" / "concepts"
        # concepts_dir already exists from vault fixture

        result = ing.generate_concept_id(concepts_dir)
        assert result == "C-0001"


# ---------------------------------------------------------------------------
# is_already_ingested
# ---------------------------------------------------------------------------


class TestIsAlreadyIngested:
    """Tests for is_already_ingested function."""

    def test_is_already_ingested_true(self, vault):
        """File with matching source_file found -> True."""
        ing = _import_ingest(vault)
        source_rel = "raw/inbound/clippings/test-article.md"
        _make_wiki_knowledge_file(vault, "static-metadata", "K-STATIC-METADATA-0001", source_rel)

        result = ing.is_already_ingested(source_rel, vault)
        assert result is True

    def test_is_already_ingested_false(self, vault):
        """No matching source_file -> False."""
        ing = _import_ingest(vault)

        result = ing.is_already_ingested("raw/inbound/clippings/nonexistent.md", vault)
        assert result is False


# ---------------------------------------------------------------------------
# ingest_one
# ---------------------------------------------------------------------------


class TestIngestOne:
    """Tests for ingest_one function."""

    def test_ingest_one_success(self, vault):
        """Full cycle: creates wiki file with correct frontmatter. (AC-01, AC-08)"""
        ing = _import_ingest(vault)
        clippings_dir = vault / "raw" / "inbound" / "clippings"
        filepath = _make_clipping(
            clippings_dir, "my-article",
            tags=["clippings", "static"],
            body="This is some knowledge about hotel property types.",
        )

        with patch.object(ing, "_merged_tag_map", return_value=dict(ing.TAG_TO_DOMAIN)):
            result = ing.ingest_one(filepath, vault)

        assert result["status"] == "ok"
        assert result["domain"] == "static-metadata"
        assert "id" in result
        assert result["id"].startswith("K-STATIC-METADATA-")

        # Verify the wiki file was created
        target_path = Path(result["target_path"])
        assert target_path.exists()

        content = target_path.read_text(encoding="utf-8")
        # Check frontmatter fields
        assert "id: K-STATIC-METADATA-" in content
        assert "type: knowledge" in content
        assert "domain: static-metadata" in content
        assert "source:" in content
        assert "source_file:" in content
        assert "ingested_at:" in content
        assert "status: inbox" in content

    def test_ingest_one_no_frontmatter(self, vault):
        """File without valid frontmatter -> skip with warning. (AC-07)"""
        ing = _import_ingest(vault)
        clippings_dir = vault / "raw" / "inbound" / "clippings"
        filepath = clippings_dir / "no-frontmatter.md"
        # Write a file with no YAML frontmatter at all -- just plain text
        # python-frontmatter will parse it as empty metadata + full body,
        # but the body check will pass. To trigger the "invalid frontmatter"
        # path, we need something that causes read_frontmatter to raise.
        # Actually, python-frontmatter is lenient -- it won't raise for
        # missing frontmatter. Instead it returns empty metadata.
        # For this test, we need to monkeypatch read_frontmatter to raise.
        filepath.write_text("Just plain text, no frontmatter", encoding="utf-8")

        from app.frontmatter_utils import read_frontmatter as real_rf

        def _raise_on_read(fp):
            raise ValueError("no frontmatter detected")

        with patch.object(ing, "_merged_tag_map", return_value=dict(ing.TAG_TO_DOMAIN)):
            with patch("app.ingest.read_frontmatter", side_effect=_raise_on_read):
                result = ing.ingest_one(filepath, vault)

        assert result["status"] == "skip"
        assert "frontmatter" in result["message"].lower()

    def test_ingest_one_empty_body(self, vault):
        """File with empty body -> skip. (FLOW-03/2)"""
        ing = _import_ingest(vault)
        clippings_dir = vault / "raw" / "inbound" / "clippings"
        filepath = clippings_dir / "empty-body.md"
        content = """---
title: "Empty Article"
source: "https://example.com/empty"
created: 2026-05-15
tags:
  - "clippings"
---

"""
        filepath.write_text(content, encoding="utf-8")

        with patch.object(ing, "_merged_tag_map", return_value=dict(ing.TAG_TO_DOMAIN)):
            result = ing.ingest_one(filepath, vault)

        assert result["status"] == "skip"
        assert "empty body" in result["message"].lower()

    def test_ingest_one_already_ingested(self, vault):
        """Second run on same file -> skip 'already ingested'. (AC-06)"""
        ing = _import_ingest(vault)
        clippings_dir = vault / "raw" / "inbound" / "clippings"
        filepath = _make_clipping(
            clippings_dir, "duplicate-article",
            tags=["clippings", "static"],
            body="Some knowledge content.",
        )

        # First ingest
        with patch.object(ing, "_merged_tag_map", return_value=dict(ing.TAG_TO_DOMAIN)):
            result1 = ing.ingest_one(filepath, vault)
        assert result1["status"] == "ok"

        # Second ingest of the same file
        with patch.object(ing, "_merged_tag_map", return_value=dict(ing.TAG_TO_DOMAIN)):
            result2 = ing.ingest_one(filepath, vault)
        assert result2["status"] == "skip"
        assert "already ingested" in result2["message"].lower()

    def test_ingest_one_dry_run(self, vault):
        """dry_run=True -> status ok, but no file written on disk."""
        ing = _import_ingest(vault)
        clippings_dir = vault / "raw" / "inbound" / "clippings"
        filepath = _make_clipping(
            clippings_dir, "dry-run-article",
            tags=["clippings", "search"],
            body="Content about search engine ranking.",
        )

        with patch.object(ing, "_merged_tag_map", return_value=dict(ing.TAG_TO_DOMAIN)):
            result = ing.ingest_one(filepath, vault, dry_run=True)

        assert result["status"] == "ok"
        assert "dry_run" in result["message"]
        # The target file should NOT exist on disk
        target_path = Path(result["target_path"])
        assert not target_path.exists()


# ---------------------------------------------------------------------------
# ingest_batch
# ---------------------------------------------------------------------------


class TestIngestBatch:
    """Tests for ingest_batch function."""

    def test_ingest_batch_all_new(self, vault):
        """3 new files -> 3 processed. (AC-05)"""
        ing = _import_ingest(vault)
        clippings_dir = vault / "raw" / "inbound" / "clippings"

        for i in range(1, 4):
            _make_clipping(
                clippings_dir, f"article-{i}",
                tags=["clippings", "static"],
                body=f"Content for article {i} about hotel properties.",
            )

        with patch.object(ing, "_merged_tag_map", return_value=dict(ing.TAG_TO_DOMAIN)):
            result = ing.ingest_batch(dry_run=False, notify=False)

        assert result["status"] == "ok"
        assert result["processed"] == 3
        assert result["skipped"] == 0
        assert result["errors"] == 0
        assert len(result["details"]) == 3

    def test_ingest_batch_mixed(self, vault):
        """2 new + 1 already ingested -> 2 processed, 1 skipped. (AC-06)"""
        ing = _import_ingest(vault)
        clippings_dir = vault / "raw" / "inbound" / "clippings"

        # Create 3 clipping files
        for i in range(1, 4):
            _make_clipping(
                clippings_dir, f"batch-article-{i}",
                tags=["clippings", "static"],
                body=f"Content for batch article {i}.",
            )

        # Pre-ingest the first one so it's already processed
        source_rel = f"raw/inbound/clippings/batch-article-1.md"
        _make_wiki_knowledge_file(
            vault, "static-metadata", "K-STATIC-METADATA-0001", source_rel,
        )

        with patch.object(ing, "_merged_tag_map", return_value=dict(ing.TAG_TO_DOMAIN)):
            result = ing.ingest_batch(dry_run=False, notify=False)

        assert result["status"] == "ok"
        assert result["processed"] == 2
        assert result["skipped"] == 1
        assert result["errors"] == 0


# ---------------------------------------------------------------------------
# _build_wiki_content
# ---------------------------------------------------------------------------


class TestBuildWikiContent:
    """Tests for _build_wiki_content function."""

    def test_build_wiki_content_frontmatter(self, vault):
        """Verify output has required frontmatter fields. (AC-08)"""
        ing = _import_ingest(vault)
        metadata = {
            "title": "Test Article",
            "source": "https://example.com/test",
            "author": "John Doe",
            "created": "2026-05-15",
            "tags": ["clippings", "static"],
        }

        content = ing._build_wiki_content(
            file_id="K-STATIC-METADATA-0001",
            domain="static-metadata",
            source_file_rel="raw/inbound/clippings/test.md",
            metadata=metadata,
            body="Article body here.",
        )

        # Check all required frontmatter fields
        assert "id: K-STATIC-METADATA-0001" in content
        assert "type: knowledge" in content
        assert "domain: static-metadata" in content
        assert "source:" in content
        assert "source_file:" in content
        assert "ingested_at:" in content
        assert "status: inbox" in content
        assert "author:" in content
        assert "tags:" in content
        # Body heading should be present
        assert "# Test Article" in content
        assert "Article body here." in content

    def test_build_wiki_content_tags_merge(self, vault):
        """Tags merge: original + 'knowledge' + 'clipping', minus 'clippings'. (FLOW-01/7)"""
        ing = _import_ingest(vault)
        metadata = {
            "title": "Tag Test",
            "source": "https://example.com/tags",
            "created": "2026-05-15",
            "tags": ["clippings", "static", "reference"],
        }

        content = ing._build_wiki_content(
            file_id="K-STATIC-METADATA-0002",
            domain="static-metadata",
            source_file_rel="raw/inbound/clippings/tags.md",
            metadata=metadata,
            body="Body.",
        )

        # "knowledge" and "clipping" must be added
        assert "  - knowledge" in content
        assert "  - clipping" in content
        # Original tags "static" and "reference" must be preserved
        assert "  - static" in content
        assert "  - reference" in content
        # "clippings" (plural) must be removed
        assert "  - clippings" not in content
