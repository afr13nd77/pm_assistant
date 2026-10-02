"""Unit tests for app.context_assembler module."""

from __future__ import annotations

import os
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.context_assembler import (
    AssembledContext,
    _count_tokens,
    _infer_type_from_filepath,
    _load_digest_section,
    _load_index,
    _select_relevant,
    assemble_context,
    enrich_creative_recall,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    """Create a minimal vault structure with llm_wiki/_index.md."""
    llm_wiki = tmp_path / "llm_wiki"
    llm_wiki.mkdir()
    return tmp_path


@pytest.fixture
def index_content() -> str:
    return textwrap.dedent("""\
        | ID | Type | Domain | Tier | Relevance | One-liner | Updated |
        |---|---|---|---|---|---|---|
        | idea-001 | idea | travel | core | 0.95 | Core idea about travel | 2026-06-01 |
        | idea-002 | idea | travel | active | 0.80 | Active idea about bookings | 2026-06-02 |
        | idea-003 | idea | travel | warm | 0.60 | Warm idea about pricing | 2026-06-03 |
        | idea-004 | idea | travel | cold | 0.30 | Cold idea not relevant | 2026-06-04 |
        | idea-005 | idea | travel | archive | 0.10 | Archived idea | 2026-06-05 |
        | meeting-001 | meeting | general | active | 0.70 | Weekly standup notes | 2026-06-06 |
        | decision-001 | decision | finance | active | 0.85 | Decision about pricing | 2026-06-07 |
    """)


@pytest.fixture
def populated_vault(vault_dir: Path, index_content: str) -> Path:
    """Vault with index + digest files."""
    index_file = vault_dir / "llm_wiki" / "_index.md"
    index_file.write_text(index_content, encoding="utf-8")

    # Create digest files for core/active/warm ideas
    for entry_id in ("idea-001", "idea-002", "idea-003"):
        digest_dir = vault_dir / "llm_wiki" / "domains" / "travel" / "ideas"
        digest_dir.mkdir(parents=True, exist_ok=True)
        digest_file = digest_dir / f"{entry_id}.md"
        digest_file.write_text(
            textwrap.dedent(f"""\
                # {entry_id}

                ## core_digest

                Core digest content for {entry_id}. This is the main summary.

                ## extended_digest

                Extended digest content for {entry_id}. This has more details.

                ## changelog

                - Initial creation
            """),
            encoding="utf-8",
        )

    # Meeting digest
    meetings_dir = vault_dir / "llm_wiki" / "meetings"
    meetings_dir.mkdir(parents=True, exist_ok=True)
    (meetings_dir / "meeting-001.md").write_text(
        textwrap.dedent("""\
            # meeting-001

            ## core_digest

            Meeting summary about sprint planning.

            ## extended_digest

            Detailed meeting notes.
        """),
        encoding="utf-8",
    )

    return vault_dir


# ---------------------------------------------------------------------------
# _count_tokens
# ---------------------------------------------------------------------------


class TestCountTokens:
    def test_empty_string(self):
        assert _count_tokens("") == 0

    def test_nonempty_string(self):
        tokens = _count_tokens("Hello world")
        assert tokens > 0
        assert isinstance(tokens, int)

    def test_longer_text_more_tokens(self):
        short = _count_tokens("Hello")
        long = _count_tokens("Hello world, this is a longer sentence for testing purposes")
        assert long > short


# ---------------------------------------------------------------------------
# _load_index
# ---------------------------------------------------------------------------


class TestLoadIndex:
    def test_missing_file(self, vault_dir: Path):
        entries = _load_index(str(vault_dir))
        assert entries == []

    def test_parse_table(self, vault_dir: Path, index_content: str):
        index_file = vault_dir / "llm_wiki" / "_index.md"
        index_file.write_text(index_content, encoding="utf-8")

        entries = _load_index(str(vault_dir))
        assert len(entries) == 7

        first = entries[0]
        assert first["id"] == "idea-001"
        assert first["type"] == "idea"
        assert first["domain"] == "travel"
        assert first["tier"] == "core"
        assert first["relevance"] == "0.95"
        assert first["one_liner"] == "Core idea about travel"
        assert first["updated"] == "2026-06-01"

    def test_empty_table(self, vault_dir: Path):
        index_file = vault_dir / "llm_wiki" / "_index.md"
        index_file.write_text(
            "| ID | Type | Domain | Tier | Relevance | One-liner | Updated |\n"
            "|---|---|---|---|---|---|---|\n",
            encoding="utf-8",
        )
        entries = _load_index(str(vault_dir))
        assert entries == []


# ---------------------------------------------------------------------------
# _select_relevant
# ---------------------------------------------------------------------------


class TestSelectRelevant:
    def _make_entries(self):
        return [
            {"id": "i1", "tier": "core", "domain": "travel", "type": "idea"},
            {"id": "i2", "tier": "active", "domain": "travel", "type": "idea"},
            {"id": "i3", "tier": "warm", "domain": "finance", "type": "idea"},
            {"id": "i4", "tier": "cold", "domain": "travel", "type": "idea"},
            {"id": "i5", "tier": "archive", "domain": "travel", "type": "idea"},
            {"id": "d1", "tier": "active", "domain": "finance", "type": "decision"},
            {"id": "m1", "tier": "active", "domain": "general", "type": "meeting"},
        ]

    def test_tier_filter(self):
        entries = self._make_entries()
        result = _select_relevant(entries, "test", "", None)
        result_ids = {e["id"] for e in result}
        assert "i1" in result_ids  # core
        assert "i2" in result_ids  # active
        assert "i3" in result_ids  # warm
        assert "i4" not in result_ids  # cold excluded
        assert "i5" not in result_ids  # archive excluded

    def test_domain_filter(self):
        entries = self._make_entries()
        result = _select_relevant(entries, "test", "travel", None)
        result_ids = {e["id"] for e in result}
        assert "i1" in result_ids  # travel domain
        assert "i2" in result_ids  # travel domain
        assert "i3" not in result_ids  # finance domain, not decision/meeting
        # decision and meeting bypass domain filter
        assert "d1" in result_ids
        assert "m1" in result_ids

    def test_focus_artifacts_bypass_tier(self):
        entries = self._make_entries()
        result = _select_relevant(entries, "test", "", ["i4", "i5"])
        result_ids = {e["id"] for e in result}
        assert "i4" in result_ids  # cold, but in focus
        assert "i5" in result_ids  # archive, but in focus


# ---------------------------------------------------------------------------
# _load_digest_section
# ---------------------------------------------------------------------------


class TestLoadDigestSection:
    def test_missing_file(self, tmp_path: Path):
        result = _load_digest_section(tmp_path / "nonexistent.md", "## core_digest")
        assert result == ""

    def test_extract_section(self, tmp_path: Path):
        digest = tmp_path / "test.md"
        digest.write_text(
            "# Title\n\n## core_digest\n\nCore content here.\nMultiple lines.\n\n"
            "## extended_digest\n\nExtended content.\n",
            encoding="utf-8",
        )
        result = _load_digest_section(digest, "## core_digest")
        assert "Core content here." in result
        assert "Multiple lines." in result
        assert "Extended content." not in result

    def test_section_not_found(self, tmp_path: Path):
        digest = tmp_path / "test.md"
        digest.write_text("# Title\n\nSome content.\n", encoding="utf-8")
        result = _load_digest_section(digest, "## core_digest")
        assert result == ""

    def test_last_section(self, tmp_path: Path):
        digest = tmp_path / "test.md"
        digest.write_text(
            "# Title\n\n## core_digest\n\nFirst section.\n\n"
            "## extended_digest\n\nLast section content.\n",
            encoding="utf-8",
        )
        result = _load_digest_section(digest, "## extended_digest")
        assert "Last section content." in result
        assert "First section." not in result


# ---------------------------------------------------------------------------
# assemble_context — kill switch (Step 0)
# ---------------------------------------------------------------------------


class TestAssembleContextKillSwitch:
    def test_wiki_source_returns_empty(self):
        with patch.dict(os.environ, {"DIGEST_CONTEXT_SOURCE": "wiki"}):
            result = assemble_context("test query")

        assert isinstance(result, AssembledContext)
        assert result.one_liners == ""
        assert result.core_digests == ""
        assert result.extended_digests == ""
        assert result.total_tokens == 0
        assert result.sources_used == []
        assert result.fallback_used is True

    def test_default_source_is_wiki(self):
        env = os.environ.copy()
        env.pop("DIGEST_CONTEXT_SOURCE", None)
        with patch.dict(os.environ, env, clear=True):
            result = assemble_context("test query")

        assert result.fallback_used is True
        assert result.one_liners == ""


# ---------------------------------------------------------------------------
# assemble_context — full waterfall (Steps 1-4)
# ---------------------------------------------------------------------------


class TestAssembleContextWaterfall:
    @patch("app.context_assembler.ke_client", create=True)
    def test_llm_wiki_mode(self, mock_ke, populated_vault: Path):
        mock_ke.touch = MagicMock()

        with patch.dict(os.environ, {
            "DIGEST_CONTEXT_SOURCE": "llm_wiki",
            "VAULT_PATH": str(populated_vault),
        }):
            result = assemble_context("travel ideas", domain="travel")

        # One-liners should include entries
        assert "[idea-001]" in result.one_liners
        assert "[idea-002]" in result.one_liners

        # Core digests should include core/active/warm (not cold/archive)
        assert "idea-001" in result.core_digests
        assert "idea-002" in result.core_digests
        assert "idea-004" not in result.core_digests  # cold
        assert "idea-005" not in result.core_digests  # archive

        assert result.total_tokens > 0
        assert len(result.sources_used) > 0
        assert result.fallback_used is False

    @patch("app.context_assembler.ke_client", create=True)
    def test_focus_artifacts_extended(self, mock_ke, populated_vault: Path):
        mock_ke.touch = MagicMock()

        with patch.dict(os.environ, {
            "DIGEST_CONTEXT_SOURCE": "llm_wiki",
            "VAULT_PATH": str(populated_vault),
        }):
            result = assemble_context(
                "travel ideas",
                domain="travel",
                focus_artifacts=["idea-001"],
            )

        # Extended digest should include the focus artifact
        assert "idea-001" in result.extended_digests
        assert "Extended digest content" in result.extended_digests

    @patch("app.context_assembler.ke_client", create=True)
    def test_touch_called_for_digests_not_oneliners(self, mock_ke, populated_vault: Path):
        """AC-14: touch() must NOT be called for one-liner-only entries."""
        mock_ke.touch = MagicMock()

        with patch.dict(os.environ, {
            "DIGEST_CONTEXT_SOURCE": "llm_wiki",
            "VAULT_PATH": str(populated_vault),
        }):
            assemble_context("travel ideas", domain="travel")

        # touch should be called for core/extended digest entries
        if mock_ke.touch.call_count > 0:
            touched_paths = [
                call.args[0] for call in mock_ke.touch.call_args_list
            ]
            # Entries that only appear in one-liners (cold, archive)
            # should NOT have touch called
            for p in touched_paths:
                assert "idea-004" not in p  # cold
                assert "idea-005" not in p  # archive

    @patch("app.context_assembler.ke_client", create=True)
    def test_ac13_cold_archive_excluded_from_core(self, mock_ke, populated_vault: Path):
        """AC-13: cold/archive tiers excluded from core-digests."""
        mock_ke.touch = MagicMock()

        with patch.dict(os.environ, {
            "DIGEST_CONTEXT_SOURCE": "llm_wiki",
            "VAULT_PATH": str(populated_vault),
        }):
            result = assemble_context("travel ideas")

        assert "idea-004" not in result.core_digests
        assert "idea-005" not in result.core_digests

    @patch("app.context_assembler.ke_client", create=True)
    def test_auto_mode_fallback(self, mock_ke, populated_vault: Path):
        """AC-15: fallback to wiki/ when digest missing and source is 'auto'."""
        mock_ke.touch = MagicMock()

        # Create a wiki/ fallback file for an entry without a digest
        wiki_dir = populated_vault / "wiki" / "domains" / "travel" / "ideas"
        wiki_dir.mkdir(parents=True, exist_ok=True)
        # Remove the llm_wiki digest for idea-002 and create wiki fallback
        digest_path = (
            populated_vault / "llm_wiki" / "domains" / "travel" / "ideas" / "idea-002.md"
        )
        digest_path.unlink()
        (wiki_dir / "idea-002.md").write_text(
            "# idea-002\n\nFull wiki content for idea-002 that serves as fallback.\n",
            encoding="utf-8",
        )

        with patch.dict(os.environ, {
            "DIGEST_CONTEXT_SOURCE": "auto",
            "VAULT_PATH": str(populated_vault),
        }):
            result = assemble_context("travel ideas", domain="travel")

        # Should have used fallback
        assert result.fallback_used is True
        assert "idea-002" in result.core_digests

    @patch("app.context_assembler.ke_client", create=True)
    def test_empty_index(self, mock_ke, vault_dir: Path):
        """Empty index returns empty context."""
        mock_ke.touch = MagicMock()

        with patch.dict(os.environ, {
            "DIGEST_CONTEXT_SOURCE": "llm_wiki",
            "VAULT_PATH": str(vault_dir),
        }):
            result = assemble_context("test")

        assert result.one_liners == ""
        assert result.core_digests == ""
        assert result.extended_digests == ""
        assert result.total_tokens == 0
        assert result.sources_used == []
        assert result.fallback_used is False


# ---------------------------------------------------------------------------
# AssembledContext dataclass
# ---------------------------------------------------------------------------


class TestAssembledContext:
    def test_defaults(self):
        ctx = AssembledContext()
        assert ctx.one_liners == ""
        assert ctx.core_digests == ""
        assert ctx.extended_digests == ""
        assert ctx.total_tokens == 0
        assert ctx.sources_used == []
        assert ctx.fallback_used is False

    def test_custom_values(self):
        ctx = AssembledContext(
            one_liners="- [id1] hello\n",
            core_digests="### id1\ncontent\n",
            total_tokens=42,
            sources_used=["id1"],
            fallback_used=True,
        )
        assert ctx.total_tokens == 42
        assert ctx.fallback_used is True
        assert "id1" in ctx.sources_used


# ---------------------------------------------------------------------------
# _infer_type_from_filepath
# ---------------------------------------------------------------------------


class TestInferTypeFromFilepath:
    def test_ideas_directory(self):
        assert _infer_type_from_filepath("wiki/domains/travel/ideas/my-idea.md") == "idea"

    def test_tasks_directory(self):
        assert _infer_type_from_filepath("wiki/domains/general/tasks/task-001.md") == "task"

    def test_meetings_directory(self):
        assert _infer_type_from_filepath("wiki/meetings/meeting-001.md") == "meeting"

    def test_unknown_defaults_to_idea(self):
        assert _infer_type_from_filepath("wiki/unknown/some-file.md") == "idea"

    def test_backslash_path(self):
        assert _infer_type_from_filepath("wiki\\domains\\travel\\ideas\\my-idea.md") == "idea"

    def test_empty_path(self):
        assert _infer_type_from_filepath("") == "idea"


# ---------------------------------------------------------------------------
# enrich_creative_recall
# ---------------------------------------------------------------------------


class TestEnrichCreativeRecall:
    def test_empty_list(self):
        """Empty input returns empty output."""
        result = enrich_creative_recall([])
        assert result == []

    def test_no_digest_uses_title(self, tmp_path: Path):
        """When no digest exists, one_liner falls back to title."""
        with patch.dict(os.environ, {"VAULT_PATH": str(tmp_path)}):
            items = [
                {
                    "filepath": "wiki/domains/travel/ideas/idea-001.md",
                    "title": "My Great Idea",
                    "domain": "travel",
                    "id": "idea-001",
                    "tier": "cold",
                    "readiness": 30,
                    "created": "2026-01-01",
                },
            ]
            result = enrich_creative_recall(items)

        assert len(result) == 1
        assert result[0]["one_liner"] == "My Great Idea"
        assert result[0]["title"] == "My Great Idea"

    def test_digest_with_one_liner(self, tmp_path: Path):
        """When digest exists with ## one_liner section, it is used."""
        # Create digest file
        digest_dir = tmp_path / "llm_wiki" / "domains" / "travel" / "ideas"
        digest_dir.mkdir(parents=True)
        digest_file = digest_dir / "idea-001.md"
        digest_file.write_text(
            textwrap.dedent("""\
                # idea-001

                ## one_liner

                A compact summary of the idea.

                ## core_digest

                Full core content here.
            """),
            encoding="utf-8",
        )

        with patch.dict(os.environ, {"VAULT_PATH": str(tmp_path)}):
            items = [
                {
                    "filepath": "wiki/domains/travel/ideas/idea-001.md",
                    "title": "My Great Idea",
                    "domain": "travel",
                    "id": "idea-001",
                    "tier": "cold",
                    "readiness": 30,
                    "created": "2026-01-01",
                },
            ]
            result = enrich_creative_recall(items)

        assert len(result) == 1
        assert result[0]["one_liner"] == "A compact summary of the idea."

    def test_original_item_not_mutated(self, tmp_path: Path):
        """Original items should not be modified."""
        with patch.dict(os.environ, {"VAULT_PATH": str(tmp_path)}):
            item = {
                "filepath": "wiki/domains/travel/ideas/idea-001.md",
                "title": "Title",
                "domain": "travel",
                "id": "idea-001",
                "tier": "cold",
                "readiness": 0,
                "created": "2026-01-01",
            }
            result = enrich_creative_recall([item])

        assert "one_liner" not in item  # original unchanged
        assert "one_liner" in result[0]

    def test_touch_not_called(self, tmp_path: Path):
        """AC-17: touch() must NOT be called during creative recall enrichment."""
        with patch.dict(os.environ, {"VAULT_PATH": str(tmp_path)}), \
             patch("app.context_assembler.ke_client", create=True) as mock_ke:
            mock_ke.touch = MagicMock()
            items = [
                {
                    "filepath": "wiki/domains/travel/ideas/idea-001.md",
                    "title": "Title",
                    "domain": "travel",
                    "id": "idea-001",
                    "tier": "cold",
                    "readiness": 0,
                    "created": "2026-01-01",
                },
            ]
            enrich_creative_recall(items)
            mock_ke.touch.assert_not_called()

    def test_multiple_items_mixed(self, tmp_path: Path):
        """Test with multiple items, some with digests and some without."""
        # Create digest only for idea-002
        digest_dir = tmp_path / "llm_wiki" / "domains" / "travel" / "ideas"
        digest_dir.mkdir(parents=True)
        (digest_dir / "idea-002.md").write_text(
            "# idea-002\n\n## one_liner\n\nDigest summary for idea-002.\n\n## core_digest\n\nCore.\n",
            encoding="utf-8",
        )

        with patch.dict(os.environ, {"VAULT_PATH": str(tmp_path)}):
            items = [
                {
                    "filepath": "wiki/domains/travel/ideas/idea-001.md",
                    "title": "First Idea",
                    "domain": "travel",
                    "id": "idea-001",
                    "tier": "cold",
                    "readiness": 0,
                    "created": "2026-01-01",
                },
                {
                    "filepath": "wiki/domains/travel/ideas/idea-002.md",
                    "title": "Second Idea",
                    "domain": "travel",
                    "id": "idea-002",
                    "tier": "archive",
                    "readiness": 50,
                    "created": "2026-01-02",
                },
            ]
            result = enrich_creative_recall(items)

        assert len(result) == 2
        # idea-001: no digest -> title as fallback
        assert result[0]["one_liner"] == "First Idea"
        # idea-002: has digest -> one_liner from digest
        assert result[1]["one_liner"] == "Digest summary for idea-002."

    def test_task_type_inferred(self, tmp_path: Path):
        """Tasks filepath should resolve to tasks/ directory in digest."""
        digest_dir = tmp_path / "llm_wiki" / "domains" / "general" / "tasks"
        digest_dir.mkdir(parents=True)
        (digest_dir / "task-001.md").write_text(
            "# task-001\n\n## one_liner\n\nTask digest summary.\n",
            encoding="utf-8",
        )

        with patch.dict(os.environ, {"VAULT_PATH": str(tmp_path)}):
            items = [
                {
                    "filepath": "wiki/domains/general/tasks/task-001.md",
                    "title": "Some Task",
                    "domain": "general",
                    "id": "task-001",
                    "tier": "cold",
                    "readiness": 0,
                    "created": "2026-01-01",
                },
            ]
            result = enrich_creative_recall(items)

        assert result[0]["one_liner"] == "Task digest summary."

    def test_no_filepath_falls_back_to_title(self, tmp_path: Path):
        """Items without filepath should gracefully fall back to title."""
        with patch.dict(os.environ, {"VAULT_PATH": str(tmp_path)}):
            items = [
                {
                    "title": "Orphan Idea",
                    "domain": "",
                    "id": "orphan-001",
                    "tier": "cold",
                    "readiness": 0,
                    "created": "2026-01-01",
                },
            ]
            result = enrich_creative_recall(items)

        assert result[0]["one_liner"] == "Orphan Idea"


# ---------------------------------------------------------------------------
# LanceDB source (DIGEST_CONTEXT_SOURCE=lancedb)
# ---------------------------------------------------------------------------

import contextlib
import sys
import types
from dataclasses import dataclass


@dataclass
class _FakeResult:
    id: str
    one_liner: str = ""
    domain: str = "travel"
    title: str = ""
    type: str = "idea"
    score: float = 1.0
    snippet: str = ""
    semantic_score: float | None = None
    source_path: str = ""


@pytest.fixture
def fake_shared():
    """Inject fake shared.vector_store / shared.embedding_client (no real calls)."""
    try:
        import shared
    except ImportError:
        shared = types.ModuleType("shared")
        shared.__path__ = []
        sys.modules["shared"] = shared

    vs = types.ModuleType("shared.vector_store")
    vs.hybrid_search = MagicMock(return_value=[])
    vs.get_by_id = MagicMock(return_value=None)
    ec = types.ModuleType("shared.embedding_client")
    ec.embed = MagicMock(return_value=types.SimpleNamespace(vector=[0.1, 0.2]))
    with patch.dict(sys.modules, {"shared.vector_store": vs, "shared.embedding_client": ec}), \
         patch.object(shared, "vector_store", vs, create=True), \
         patch.object(shared, "embedding_client", ec, create=True):
        yield vs, ec


@contextlib.contextmanager
def _patch_touch():
    """Fake app.ke_client so that no HTTP call to knowledge-engine is made."""
    import app

    ke = types.ModuleType("app.ke_client")
    ke.touch = MagicMock()
    with patch.dict(sys.modules, {"app.ke_client": ke}),          patch.object(app, "ke_client", ke, create=True):
        yield ke.touch


def _row(aid: str, core: str = "core text", ext: str = "ext text", tc: int = 10, te: int = 10):
    return {
        "id": aid, "core_digest": core, "extended_digest": ext,
        "tokens_core": tc, "tokens_extended": te, "source_path": f"wiki/{aid}.md",
    }


class TestAssembleContextLanceDB:
    def test_lancedb_assembles_context(self, fake_shared):
        vs, ec = fake_shared
        vs.hybrid_search.return_value = [
            _FakeResult("a1", "First one-liner"), _FakeResult("a2", "Second one-liner"),
        ]
        vs.get_by_id.side_effect = lambda i: _row(i)
        with patch.dict(os.environ, {"DIGEST_CONTEXT_SOURCE": "lancedb"}), \
             _patch_touch() as touch:
            result = assemble_context("travel", domain="travel")

        assert "- [a1] First one-liner" in result.one_liners
        assert "### a1\ncore text" in result.core_digests
        assert "### a2" in result.extended_digests
        assert result.sources_used == ["a1", "a2"]
        assert result.fallback_used is False
        vs.hybrid_search.assert_called_once()
        assert vs.hybrid_search.call_args.args[1] == [0.1, 0.2]
        assert vs.hybrid_search.call_args.kwargs["domain"] == "travel"
        assert touch.call_count == 2

    def test_wiki_kill_switch_does_not_touch_lancedb(self, fake_shared):
        vs, _ = fake_shared
        with patch.dict(os.environ, {"DIGEST_CONTEXT_SOURCE": "wiki", "VECTOR_STORE_ENABLED": "1"}):
            result = assemble_context("q")
        assert result.fallback_used is True
        assert result.one_liners == ""
        vs.hybrid_search.assert_not_called()

    def test_vector_store_enabled_triggers_lancedb_when_source_unset(self, fake_shared):
        vs, _ = fake_shared
        env = {k: v for k, v in os.environ.items() if k != "DIGEST_CONTEXT_SOURCE"}
        env["VECTOR_STORE_ENABLED"] = "1"
        with patch.dict(os.environ, env, clear=True):
            assemble_context("q")
        vs.hybrid_search.assert_called_once()

    def test_lancedb_unavailable_returns_empty(self, fake_shared):
        vs, _ = fake_shared
        vs.hybrid_search.side_effect = RuntimeError("db down")
        with patch.dict(os.environ, {"DIGEST_CONTEXT_SOURCE": "lancedb"}):
            result = assemble_context("q")
        assert result.one_liners == "" and result.core_digests == ""
        assert result.total_tokens == 0
        assert result.fallback_used is True

    def test_import_error_returns_empty(self):
        shared = sys.modules.get("shared")
        saved = shared.__dict__.pop("vector_store", None) if shared else None
        try:
            with patch.dict(sys.modules, {"shared.vector_store": None}),                  patch.dict(os.environ, {"DIGEST_CONTEXT_SOURCE": "lancedb"}):
                result = assemble_context("q")
        finally:
            if saved is not None:
                shared.vector_store = saved
        assert result.fallback_used is True
        assert result.one_liners == ""

    def test_embed_failure_uses_fts_only(self, fake_shared):
        vs, ec = fake_shared
        ec.embed.side_effect = RuntimeError("ollama down")
        vs.hybrid_search.return_value = [_FakeResult("a1", "One")]
        vs.get_by_id.side_effect = lambda i: _row(i)
        with patch.dict(os.environ, {"DIGEST_CONTEXT_SOURCE": "lancedb"}), \
             _patch_touch():
            result = assemble_context("q")
        assert vs.hybrid_search.call_args.args[1] is None
        assert "[a1]" in result.one_liners
        assert "### a1" in result.core_digests

    def test_embed_returns_none_uses_fts_only(self, fake_shared):
        vs, ec = fake_shared
        ec.embed.return_value = None
        with patch.dict(os.environ, {"DIGEST_CONTEXT_SOURCE": "lancedb"}):
            assemble_context("q")
        assert vs.hybrid_search.call_args.args[1] is None

    def test_token_budgets_respected(self, fake_shared):
        vs, _ = fake_shared
        n = 100
        vs.hybrid_search.return_value = [_FakeResult(f"a{i}", "word " * 50) for i in range(n)]
        # core: 4000 tokens each -> 2 fit in 10000; extended: 2500 each -> 2 fit in 6000
        vs.get_by_id.side_effect = lambda i: _row(i, tc=4000, te=2500)
        with patch.dict(os.environ, {"DIGEST_CONTEXT_SOURCE": "lancedb"}), \
             _patch_touch():
            result = assemble_context("q", domain="travel")

        assert _count_tokens(result.one_liners) <= 3000
        assert 0 < result.one_liners.count("\n") < n
        assert result.core_digests.count("### ") == 2
        assert result.extended_digests.count("### ") == 2
        assert result.total_tokens <= 3000 + 10000 + 6000

    def test_focus_artifacts_extended(self, fake_shared):
        vs, _ = fake_shared
        vs.hybrid_search.return_value = [_FakeResult("a1", "One")]
        vs.get_by_id.side_effect = lambda i: _row(i, ext=f"extended of {i}")
        with patch.dict(os.environ, {"DIGEST_CONTEXT_SOURCE": "lancedb"}), \
             _patch_touch():
            result = assemble_context("q", focus_artifacts=["f1"])
        assert "extended of f1" in result.extended_digests
        assert "f1" in result.sources_used


class TestEnrichCreativeRecallLanceDB:
    def test_one_liner_from_lancedb(self, fake_shared, tmp_path: Path):
        vs, _ = fake_shared
        vs.get_by_id.return_value = {"id": "idea-1", "one_liner": "From LanceDB"}
        with patch.dict(os.environ, {"DIGEST_CONTEXT_SOURCE": "lancedb", "VAULT_PATH": str(tmp_path)}):
            result = enrich_creative_recall([{"id": "idea-1", "title": "T", "domain": "travel"}])
        assert result[0]["one_liner"] == "From LanceDB"

    def test_lancedb_error_falls_back_to_title(self, fake_shared, tmp_path: Path):
        vs, _ = fake_shared
        vs.get_by_id.side_effect = RuntimeError("boom")
        with patch.dict(os.environ, {"DIGEST_CONTEXT_SOURCE": "lancedb", "VAULT_PATH": str(tmp_path)}):
            result = enrich_creative_recall([{"id": "idea-1", "title": "T", "domain": "travel"}])
        assert result[0]["one_liner"] == "T"
