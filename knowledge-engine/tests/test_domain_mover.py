"""Tests for domain_mover module (T-02, BL-124).

Covers: _parse_artifact_path, _classify_file, move_artifact,
_safe_move, batch_reclassify, audit_domain.
"""

import contextlib
import importlib
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_DOMAINS = [
    "general",
    "search-engine",
    "partner-search-engine",
    "static-metadata",
    "suggester",
]

_TAG_MAP = {
    "search": "search-engine",
    "partner": "partner-search-engine",
}

_KEYWORD_MAP = {
    "фильтрация": "search-engine",
    "партнёр": "partner-search-engine",
}


def _write_md(path: Path, title: str, domain: str, tags: list[str], body: str):
    """Write a markdown file with frontmatter."""
    tags_str = ", ".join(tags)
    content = (
        f"---\n"
        f"title: {title}\n"
        f"domain: {domain}\n"
        f"tags: [{tags_str}]\n"
        f"---\n"
        f"\n"
        f"{body}\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _build_vault(tmp_path: Path):
    """Create a mock vault directory structure with sample files."""
    # general domain
    general_ideas = tmp_path / "wiki" / "domains" / "general" / "ideas"
    general_ideas.mkdir(parents=True, exist_ok=True)
    (tmp_path / "wiki" / "domains" / "general" / "index.md").touch()
    (tmp_path / "wiki" / "domains" / "general" / "log.md").touch()

    _write_md(
        general_ideas / "test-idea.md",
        title="Добавить фильтрацию по цене",
        domain="general",
        tags=["search", "filter"],
        body="Нужно добавить фильтр по цене в поисковый движок.",
    )
    _write_md(
        general_ideas / "another-idea.md",
        title="Улучшить UI",
        domain="general",
        tags=["ui"],
        body="Общее улучшение интерфейса.",
    )
    # Service files inside ideas dir
    (general_ideas / "index.md").write_text("index", encoding="utf-8")
    (general_ideas / "log.md").write_text("log", encoding="utf-8")

    # search-engine domain
    se_ideas = tmp_path / "wiki" / "domains" / "search-engine" / "ideas"
    se_ideas.mkdir(parents=True, exist_ok=True)
    (se_ideas / "index.md").write_text("index", encoding="utf-8")
    (se_ideas / "log.md").write_text("log", encoding="utf-8")

    # partner-search-engine domain
    pse_ideas = tmp_path / "wiki" / "domains" / "partner-search-engine" / "ideas"
    pse_ideas.mkdir(parents=True, exist_ok=True)
    (pse_ideas / "index.md").write_text("index", encoding="utf-8")
    (pse_ideas / "log.md").write_text("log", encoding="utf-8")

    return tmp_path


def _reload_domain_mover(tmp_path: Path):
    """Reload vault_paths and domain_mover so VAULT_PATH points to tmp_path."""
    with patch.dict(os.environ, {"VAULT_PATH": str(tmp_path)}):
        if "shared.vault_paths" in sys.modules:
            importlib.reload(sys.modules["shared.vault_paths"])
        else:
            import shared.vault_paths  # noqa: F401

    if "app.domain_mover" in sys.modules:
        importlib.reload(sys.modules["app.domain_mover"])
    else:
        import app.domain_mover  # noqa: F401

    from app import domain_mover
    return domain_mover


def _wiki_domain_dir_factory(tmp_path: Path):
    """Return a side_effect function for vault_paths.wiki_domain_dir mock."""
    def _side_effect(domain: str, artifact_type: str) -> Path:
        p = tmp_path / "wiki" / "domains" / domain / artifact_type
        p.mkdir(parents=True, exist_ok=True)
        return p
    return _side_effect


def _apply_standard_patches(tmp_path: Path):
    """Return an ExitStack context manager with all standard patches applied.

    Also returns a dict of mock objects keyed by short name.
    """
    mock_update_index = MagicMock()
    mock_append_log = MagicMock()

    stack = contextlib.ExitStack()
    stack.enter_context(
        patch("app.domain_mover.domain_config.get_valid_domains",
              return_value=_VALID_DOMAINS)
    )
    stack.enter_context(
        patch("app.domain_mover.domain_config.build_keyword_map",
              return_value=_KEYWORD_MAP.copy())
    )
    stack.enter_context(
        patch("app.domain_mover.domain_config.build_tag_map",
              return_value=_TAG_MAP.copy())
    )
    stack.enter_context(
        patch("app.domain_mover.vault_paths.VAULT_PATH", tmp_path)
    )
    stack.enter_context(
        patch("app.domain_mover.vault_paths.wiki_domain_dir",
              side_effect=_wiki_domain_dir_factory(tmp_path))
    )
    stack.enter_context(
        patch("app.domain_mover.update_domain_index", mock_update_index)
    )
    stack.enter_context(
        patch("app.domain_mover.append_domain_log", mock_append_log)
    )
    mocks = {
        "update_domain_index": mock_update_index,
        "append_domain_log": mock_append_log,
    }
    return stack, mocks


# ---------------------------------------------------------------------------
# _parse_artifact_path
# ---------------------------------------------------------------------------


class TestParseArtifactPath:
    def test_parse_artifact_path_valid(self, tmp_path):
        """Correct path returns (domain, artifact_type) tuple."""
        dm = _reload_domain_mover(tmp_path)
        filepath = tmp_path / "wiki" / "domains" / "general" / "ideas" / "test.md"
        result = dm._parse_artifact_path(filepath)
        assert result == ("general", "ideas")

    def test_parse_artifact_path_invalid(self, tmp_path):
        """Path without 'domains' segment raises ValueError."""
        dm = _reload_domain_mover(tmp_path)
        filepath = tmp_path / "wiki" / "general" / "ideas" / "test.md"
        with pytest.raises(ValueError, match="domains"):
            dm._parse_artifact_path(filepath)


# ---------------------------------------------------------------------------
# _classify_file
# ---------------------------------------------------------------------------


class TestClassifyFile:
    def test_classify_file_tag_match(self, tmp_path):
        """Tag from tag_map gives +3 and correct domain."""
        _build_vault(tmp_path)
        dm = _reload_domain_mover(tmp_path)

        filepath = tmp_path / "wiki" / "domains" / "general" / "ideas" / "test-idea.md"
        target, score, reasons = dm._classify_file(filepath, _KEYWORD_MAP, _TAG_MAP)
        assert target == "search-engine"
        assert score >= 3
        assert any("tag:search" in r for r in reasons)

    def test_classify_file_keyword_match(self, tmp_path):
        """Keywords in title (+2) and body (+1) are scored correctly."""
        _build_vault(tmp_path)
        dm = _reload_domain_mover(tmp_path)

        # test-idea.md has "фильтрация" in title and "фильтр" is NOT a keyword,
        # but "фильтрация" IS a keyword. Title contains "фильтрацию" (inflected).
        # The keyword map uses substring matching, so "фильтрация" matches
        # "фильтрацию" in title -> +2, and body contains no exact match.
        # Let's create a file with exact keyword match in both title and body.
        ideas_dir = tmp_path / "wiki" / "domains" / "general" / "ideas"
        _write_md(
            ideas_dir / "keyword-test.md",
            title="фильтрация в поиске",
            domain="general",
            tags=[],
            body="Нужна фильтрация для отелей.",
        )
        filepath = ideas_dir / "keyword-test.md"
        target, score, reasons = dm._classify_file(filepath, _KEYWORD_MAP, _TAG_MAP)
        assert target == "search-engine"
        # title_kw +2, body_kw +1 = 3
        assert score == 3
        assert any("title_kw" in r for r in reasons)
        assert any("body_kw" in r for r in reasons)

    def test_classify_file_ambiguous(self, tmp_path):
        """Two domains with equal scores return (None, score, ['ambiguous: ...'])."""
        _build_vault(tmp_path)
        dm = _reload_domain_mover(tmp_path)

        ideas_dir = tmp_path / "wiki" / "domains" / "general" / "ideas"
        _write_md(
            ideas_dir / "ambiguous.md",
            title="общий текст",
            domain="general",
            tags=["search", "partner"],
            body="общее тело.",
        )
        filepath = ideas_dir / "ambiguous.md"
        target, score, reasons = dm._classify_file(filepath, _KEYWORD_MAP, _TAG_MAP)
        assert target is None
        assert score == 3  # both tags give +3 each, equal top
        assert any("ambiguous" in r for r in reasons)

    def test_classify_file_unmatched(self, tmp_path):
        """No keyword or tag match returns (None, 0, ['unmatched'])."""
        _build_vault(tmp_path)
        dm = _reload_domain_mover(tmp_path)

        ideas_dir = tmp_path / "wiki" / "domains" / "general" / "ideas"
        _write_md(
            ideas_dir / "unmatched.md",
            title="Абсолютно несвязанная тема",
            domain="general",
            tags=["unrelated"],
            body="Ничего общего.",
        )
        filepath = ideas_dir / "unmatched.md"
        target, score, reasons = dm._classify_file(filepath, _KEYWORD_MAP, _TAG_MAP)
        assert target is None
        assert score == 0
        assert reasons == ["unmatched"]


# ---------------------------------------------------------------------------
# move_artifact
# ---------------------------------------------------------------------------


class TestMoveArtifact:
    def test_move_artifact_success(self, tmp_path):
        """File is moved, frontmatter updated, index and log called."""
        _build_vault(tmp_path)
        dm = _reload_domain_mover(tmp_path)

        src_file = tmp_path / "wiki" / "domains" / "general" / "ideas" / "test-idea.md"
        assert src_file.exists()

        stack, mocks = _apply_standard_patches(tmp_path)
        with stack:
            result = dm.move_artifact(str(src_file), "search-engine")

        assert result["status"] == "ok"
        assert result["file"] == "test-idea.md"
        assert result["from"] == "general"
        assert result["to"] == "search-engine"

        # Source file should no longer exist
        assert not src_file.exists()

        # Destination file should exist
        dst_file = tmp_path / "wiki" / "domains" / "search-engine" / "ideas" / "test-idea.md"
        assert dst_file.exists()

        # update_domain_index should have been called for both source and target
        assert mocks["update_domain_index"].call_count == 2

        # append_domain_log should have been called for both source and target
        assert mocks["append_domain_log"].call_count == 2

    def test_move_artifact_invalid_domain(self, tmp_path):
        """Non-existent target domain returns error."""
        _build_vault(tmp_path)
        dm = _reload_domain_mover(tmp_path)

        src_file = tmp_path / "wiki" / "domains" / "general" / "ideas" / "test-idea.md"

        stack, mocks = _apply_standard_patches(tmp_path)
        with stack:
            result = dm.move_artifact(str(src_file), "nonexistent-domain")

        assert result["status"] == "error"
        assert "Invalid target domain" in result["message"]

    def test_move_artifact_same_domain(self, tmp_path):
        """Moving to the same domain returns error."""
        _build_vault(tmp_path)
        dm = _reload_domain_mover(tmp_path)

        src_file = tmp_path / "wiki" / "domains" / "general" / "ideas" / "test-idea.md"

        stack, mocks = _apply_standard_patches(tmp_path)
        with stack:
            result = dm.move_artifact(str(src_file), "general")

        assert result["status"] == "error"
        assert "same as source" in result["message"]

    def test_move_artifact_conflict(self, tmp_path):
        """File already exists in target domain returns error."""
        _build_vault(tmp_path)
        dm = _reload_domain_mover(tmp_path)

        src_file = tmp_path / "wiki" / "domains" / "general" / "ideas" / "test-idea.md"
        # Create conflicting file in target
        dst_dir = tmp_path / "wiki" / "domains" / "search-engine" / "ideas"
        dst_dir.mkdir(parents=True, exist_ok=True)
        _write_md(
            dst_dir / "test-idea.md",
            title="Existing",
            domain="search-engine",
            tags=[],
            body="Already here.",
        )

        stack, mocks = _apply_standard_patches(tmp_path)
        with stack:
            result = dm.move_artifact(str(src_file), "search-engine")

        assert result["status"] == "error"
        assert "already exists" in result["message"]


# ---------------------------------------------------------------------------
# _safe_move
# ---------------------------------------------------------------------------


class TestSafeMove:
    def test_safe_move_verify_fail(self, tmp_path):
        """Content mismatch after copy raises IOError."""
        dm = _reload_domain_mover(tmp_path)

        src = tmp_path / "source.md"
        dst = tmp_path / "dest.md"
        src.write_text("original content", encoding="utf-8")

        # Patch shutil.copy2 to write different content to dst
        original_copy2 = __import__("shutil").copy2

        def bad_copy2(s, d):
            original_copy2(s, d)
            # Corrupt the destination
            Path(d).write_text("corrupted content", encoding="utf-8")

        with patch("app.domain_mover.shutil.copy2", side_effect=bad_copy2):
            with pytest.raises(IOError, match="Content verification failed"):
                dm._safe_move(src, dst)

        # dst should have been cleaned up
        assert not dst.exists()
        # src should still exist (not deleted on failure)
        assert src.exists()


# ---------------------------------------------------------------------------
# batch_reclassify
# ---------------------------------------------------------------------------


class TestBatchReclassify:
    def test_batch_reclassify_dry_run(self, tmp_path):
        """Dry-run returns to_move, unmatched, summary without moving files."""
        _build_vault(tmp_path)
        dm = _reload_domain_mover(tmp_path)

        src_file = tmp_path / "wiki" / "domains" / "general" / "ideas" / "test-idea.md"
        assert src_file.exists()

        stack, mocks = _apply_standard_patches(tmp_path)
        with stack:
            result = dm.batch_reclassify("general", artifact_type="ideas", dry_run=True)

        assert result["status"] == "ok"
        assert result["dry_run"] is True
        assert isinstance(result["to_move"], list)
        assert isinstance(result["unmatched"], list)
        assert "summary" in result
        assert result["summary"]["total_scanned"] == (
            result["summary"]["to_move"] + result["summary"]["unmatched"]
        )

        # Files should still be in original location
        assert src_file.exists()

        # At least test-idea.md should be in to_move (has search tag -> search-engine)
        moved_filenames = [item["filename"] for item in result["to_move"]]
        assert "test-idea.md" in moved_filenames

        # another-idea.md has no matching tags/keywords -> unmatched
        assert "another-idea.md" in result["unmatched"]

    def test_batch_reclassify_execute(self, tmp_path):
        """Full execution: files moved, by_domain counted."""
        _build_vault(tmp_path)
        dm = _reload_domain_mover(tmp_path)

        src_file = tmp_path / "wiki" / "domains" / "general" / "ideas" / "test-idea.md"
        assert src_file.exists()

        stack, mocks = _apply_standard_patches(tmp_path)
        with stack:
            result = dm.batch_reclassify("general", artifact_type="ideas", dry_run=False)

        assert result["status"] == "ok"
        assert result["dry_run"] is False
        assert result["moved"] >= 1
        assert isinstance(result["by_domain"], dict)

        # test-idea.md should have been moved to search-engine
        assert not src_file.exists()
        dst_file = (
            tmp_path / "wiki" / "domains" / "search-engine" / "ideas" / "test-idea.md"
        )
        assert dst_file.exists()

        # by_domain should contain search-engine
        assert "search-engine" in result["by_domain"]
        assert result["by_domain"]["search-engine"] >= 1


# ---------------------------------------------------------------------------
# audit_domain
# ---------------------------------------------------------------------------


class TestAuditDomain:
    def test_audit_domain(self, tmp_path):
        """Returns candidates, recommendation (keep/remove/review)."""
        _build_vault(tmp_path)
        dm = _reload_domain_mover(tmp_path)

        stack, mocks = _apply_standard_patches(tmp_path)
        with stack:
            result = dm.audit_domain("search-engine", source_domain="general")

        assert result["status"] == "ok"
        assert result["domain"] == "search-engine"
        assert isinstance(result["current_files"], int)
        assert isinstance(result["candidates"], list)
        assert result["recommendation"] in ("keep", "remove", "review")

        # test-idea.md has tag "search" -> should be a candidate for search-engine
        candidate_files = [c["file"] for c in result["candidates"]]
        assert "test-idea.md" in candidate_files
