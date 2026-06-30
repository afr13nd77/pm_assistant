"""Regression tests for BUG-019.

When a vault `.md` file has a frontmatter key `tags:` that is present but
empty/null, PyYAML parses it as None. The old code used
`metadata.get("tags", [])` whose default is NOT applied for an existing key,
so `tags` became None and propagated into the matcher / vault index, where it
was iterated -> "'NoneType' object is not iterable".

These tests pin the fix:
- matcher.find_links tolerates tags=None and returns a list (0+ links).
- matcher.find_links still works with a real list of tags.
- vault_index.build_index does not drop / crash on a file with empty `tags:`,
  and a subsequent search() does not raise.
- enricher.enrich runs to completion on a protocol with empty `tags:`
  (claude_client.enrich + decay are mocked) instead of raising.
"""

import importlib
import os
from unittest.mock import patch


def _setup_vault_paths(tmp_path):
    with patch.dict(os.environ, {"VAULT_PATH": str(tmp_path)}):
        from shared import vault_paths
        importlib.reload(vault_paths)
    return tmp_path


# ---------------------------------------------------------------------------
# matcher.find_links
# ---------------------------------------------------------------------------


class TestFindLinksNoneTags:
    def test_none_tags_does_not_raise(self):
        """find_links(text, None, index) must not raise on empty index."""
        from app.matcher import find_links
        from app.vault_index import VaultIndex

        index = VaultIndex(entries=[])
        result = find_links("Some meeting body about booking", None, index)
        assert isinstance(result, list)
        assert result == []

    def test_none_tags_with_matching_entry(self):
        """find_links with None tags still matches by keywords (0+ links)."""
        from app.matcher import find_links
        from app.vault_index import VaultEntry, VaultIndex

        entry = VaultEntry(
            path="wiki/domains/booking/ideas/x.md",
            title="Booking improvement",
            tags=["booking"],
            keywords=["booking", "improvement"],
            category="idea",
        )
        index = VaultIndex(entries=[entry])
        result = find_links("Discussion about booking improvement", None, index)
        assert isinstance(result, list)
        # keyword match should surface the entry; at minimum no exception
        assert all(len(r) == 3 for r in result)

    def test_list_tags_still_work(self):
        """Normal path: a real list of tags is honoured and boosts score."""
        from app.matcher import find_links
        from app.vault_index import VaultEntry, VaultIndex

        entry = VaultEntry(
            path="wiki/domains/booking/ideas/x.md",
            title="Booking improvement",
            tags=["booking"],
            keywords=["booking"],
            category="idea",
        )
        index = VaultIndex(entries=[entry])
        result = find_links("unrelated text here", ["booking"], index)
        assert isinstance(result, list)
        assert len(result) >= 1
        assert result[0][0].title == "Booking improvement"


# ---------------------------------------------------------------------------
# vault_index with empty tags:
# ---------------------------------------------------------------------------


class TestVaultIndexEmptyTags:
    def test_empty_tags_frontmatter_indexed_not_dropped(self, tmp_path):
        _setup_vault_paths(tmp_path)
        meetings = tmp_path / "wiki" / "meetings"
        meetings.mkdir(parents=True, exist_ok=True)
        # `tags:` present but empty -> PyYAML None
        (meetings / "2026-06-30-standup.md").write_text(
            "---\ntags:\nstatus: inbox\n---\n\n# Standup\n\nBody about booking.\n",
            encoding="utf-8",
        )

        from app.vault_index import build_index

        index = build_index(str(tmp_path))
        assert len(index.entries) == 1
        # tags must be a list (coerced from None), never None
        assert index.entries[0].tags == []

    def test_search_after_empty_tags_index_does_not_raise(self, tmp_path):
        _setup_vault_paths(tmp_path)
        meetings = tmp_path / "wiki" / "meetings"
        meetings.mkdir(parents=True, exist_ok=True)
        (meetings / "2026-06-30-standup.md").write_text(
            "---\ntags:\nstatus: inbox\n---\n\n# Standup\n\nBody about booking.\n",
            encoding="utf-8",
        )

        from app.vault_index import build_index

        index = build_index(str(tmp_path))
        # Must not raise 'NoneType' object is not iterable
        results = index.search(["booking"], [])
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# enricher.enrich end-to-end on a protocol with empty tags:
# ---------------------------------------------------------------------------


class TestEnrichNoneTags:
    def test_enrich_empty_tags_does_not_raise(self, tmp_path):
        _setup_vault_paths(tmp_path)

        proto = tmp_path / "2026-06-30-meeting.md"
        proto.write_text(
            "---\ntags:\nstatus: inbox\n---\n\n# Meeting protocol\n\n"
            "Discussed booking flow and search ranking.\n",
            encoding="utf-8",
        )

        from app import enricher

        # decay touch import (`knowledge_engine.decay_engine`) is wrapped in a
        # non-fatal try/except inside enrich(), so it is fine if it is a no-op
        # in the test environment; only claude_client.enrich is mocked.
        with patch.object(
            enricher.claude_client, "enrich", return_value="\n## Связи\n\n- none\n"
        ):
            result = enricher.enrich(str(proto), vault_path=str(tmp_path))

        # Previously raised "'NoneType' object is not iterable"; now completes.
        assert result["status"] == "ok"
        assert result["links_found"] == 0

    def test_enrich_dry_run_empty_tags_does_not_raise(self, tmp_path):
        _setup_vault_paths(tmp_path)

        proto = tmp_path / "2026-06-30-meeting2.md"
        proto.write_text(
            "---\ntags:\nstatus: inbox\n---\n\n# Meeting protocol\n\nBody text.\n",
            encoding="utf-8",
        )

        from app import enricher

        result = enricher.enrich(str(proto), vault_path=str(tmp_path), dry_run=True)
        assert result["status"] == "dry_run"
        assert result["links_found"] == 0
