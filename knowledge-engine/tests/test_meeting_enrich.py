"""Tests for BL-133 + BL-134: meeting protocol enrichment.

Covers:
- _inject_source_file: frontmatter injection + footer wikilink replacement
- jira_key_sync module aliases: sync_daily_jira_keys, patch_daily_links
- jira_key_sync public API surface
"""


from app.jira_key_sync import (
    patch_daily_links,
    patch_jira_links,
    sync_daily_jira_keys,
    sync_jira_keys,
)
from app.meeting_fetcher.fetcher import _inject_source_file

# ---------------------------------------------------------------------------
# TestInjectSourceFile
# ---------------------------------------------------------------------------


class TestInjectSourceFile:
    """Tests for _inject_source_file(protocol_md, raw_rel_path)."""

    _FOOTER = "*Источник: транскрипт Яндекс Телемост*"
    _PATH = "raw/inbound/meeting-notes/2026-06-17-1430-transcript.txt"

    # --- happy path ---

    def test_happy_path_source_file_in_frontmatter(self):
        """source_file field is injected into the frontmatter block."""
        md = (
            "---\n"
            "tags: [meeting]\n"
            "date: 2026-06-17\n"
            "---\n\n"
            "## Content\n\n"
            f"{self._FOOTER}"
        )
        result = _inject_source_file(md, self._PATH)
        assert f"source_file: {self._PATH}" in result

    def test_happy_path_wikilink_in_footer(self):
        """Footer is updated with an Obsidian wikilink to the source file."""
        md = (
            "---\n"
            "tags: [meeting]\n"
            "date: 2026-06-17\n"
            "---\n\n"
            "## Content\n\n"
            f"{self._FOOTER}"
        )
        result = _inject_source_file(md, self._PATH)
        assert f"[[{self._PATH}|исходный файл]]" in result

    def test_happy_path_frontmatter_opening_delimiter_preserved(self):
        """The opening --- of the frontmatter is preserved."""
        md = (
            "---\n"
            "tags: [meeting]\n"
            "date: 2026-06-17\n"
            "---\n\n"
            f"{self._FOOTER}"
        )
        result = _inject_source_file(md, self._PATH)
        assert result.startswith("---\n")

    def test_happy_path_existing_frontmatter_fields_preserved(self):
        """tags and date fields survive the injection."""
        md = (
            "---\n"
            "tags: [meeting]\n"
            "date: 2026-06-17\n"
            "---\n\n"
            f"{self._FOOTER}"
        )
        result = _inject_source_file(md, self._PATH)
        assert "tags: [meeting]" in result
        assert "date: 2026-06-17" in result

    def test_happy_path_returns_str(self):
        """Return value is always a string."""
        md = (
            "---\ntags: [meeting]\n---\n\n"
            f"{self._FOOTER}"
        )
        result = _inject_source_file(md, self._PATH)
        assert isinstance(result, str)

    # --- no frontmatter ---

    def test_no_frontmatter_source_file_not_injected(self):
        """When there is no frontmatter, source_file is NOT added to the text."""
        md = f"No frontmatter here\n\n{self._FOOTER}"
        result = _inject_source_file(md, self._PATH)
        assert "source_file:" not in result

    def test_no_frontmatter_footer_still_updated(self):
        """Even without frontmatter, the footer line receives the wikilink."""
        md = f"No frontmatter here\n\n{self._FOOTER}"
        result = _inject_source_file(md, self._PATH)
        assert f"[[{self._PATH}|исходный файл]]" in result

    def test_no_frontmatter_original_footer_replaced(self):
        """The bare footer marker is replaced, not duplicated."""
        md = f"No frontmatter here\n\n{self._FOOTER}"
        result = _inject_source_file(md, self._PATH)
        # The raw footer string is gone; only the enriched version remains
        assert self._FOOTER not in result

    # --- no footer ---

    def test_no_footer_source_file_injected(self):
        """When footer is absent, frontmatter injection still happens."""
        md = "---\ntags: [meeting]\n---\n\nContent without footer"
        result = _inject_source_file(md, self._PATH)
        assert f"source_file: {self._PATH}" in result

    def test_no_footer_appends_wikilink(self):
        """Without a footer line, wikilink is appended at the end."""
        md = "---\ntags: [meeting]\n---\n\nContent without footer"
        result = _inject_source_file(md, self._PATH)
        assert "исходный файл" in result
        assert result.rstrip().endswith("*")

    # --- path handling ---

    def test_forward_slash_path_preserved_in_output(self):
        """Forward slashes in the vault-relative path are kept as-is."""
        path = "raw/inbound/meeting-notes/some-meeting.txt"
        md = (
            "---\ntitle: test\n---\n\n"
            f"{self._FOOTER}"
        )
        result = _inject_source_file(md, path)
        assert "raw/inbound/meeting-notes/some-meeting.txt" in result

    def test_path_with_special_chars_in_filename(self):
        """Filename with hyphens and digits is handled correctly."""
        path = "raw/inbound/meeting-notes/2026-06-17-1430-standup-transcript.txt"
        md = (
            "---\ntitle: standup\n---\n\n"
            f"{self._FOOTER}"
        )
        result = _inject_source_file(md, path)
        assert f"source_file: {path}" in result
        assert f"[[{path}|исходный файл]]" in result

    def test_empty_string_input_does_not_raise(self):
        """Empty string input returns a string without raising."""
        result = _inject_source_file("", self._PATH)
        assert isinstance(result, str)

    def test_source_file_placed_before_closing_delimiter(self):
        """The injected source_file line appears before the closing --- delimiter."""
        md = (
            "---\n"
            "tags: [meeting]\n"
            "---\n\n"
            f"{self._FOOTER}"
        )
        result = _inject_source_file(md, self._PATH)
        source_file_pos = result.find(f"source_file: {self._PATH}")
        closing_delim_pos = result.find("---\n", 4)  # skip opening ---
        assert source_file_pos != -1
        assert source_file_pos < closing_delim_pos

    def test_footer_replaced_only_once(self):
        """When footer appears multiple times, only the first occurrence is replaced."""
        md = (
            "---\ntags: [meeting]\n---\n\n"
            f"{self._FOOTER}\n\n"
            f"{self._FOOTER}"
        )
        result = _inject_source_file(md, self._PATH)
        # After replacement the enriched wikilink footer appears once,
        # and the bare footer may survive in the second occurrence
        enriched = (
            f"*Источник: транскрипт Яндекс Телемост — [[{self._PATH}|исходный файл]]*"
        )
        assert result.count(enriched) == 1


# ---------------------------------------------------------------------------
# TestJiraKeyAliases
# ---------------------------------------------------------------------------


class TestJiraKeyAliases:
    """Verify that the daily-* names are exact aliases for the base functions."""

    def test_sync_daily_jira_keys_is_sync_jira_keys(self):
        """sync_daily_jira_keys must be the same object as sync_jira_keys."""
        assert sync_daily_jira_keys is sync_jira_keys

    def test_patch_daily_links_is_patch_jira_links(self):
        """patch_daily_links must be the same object as patch_jira_links."""
        assert patch_daily_links is patch_jira_links


# ---------------------------------------------------------------------------
# TestJiraKeyModuleAPI
# ---------------------------------------------------------------------------


class TestJiraKeyModuleAPI:
    """Verify that the public API surface of jira_key_sync is complete."""

    def test_sync_jira_keys_is_callable(self):
        assert callable(sync_jira_keys)

    def test_patch_jira_links_is_callable(self):
        assert callable(patch_jira_links)

    def test_sync_daily_jira_keys_is_callable(self):
        assert callable(sync_daily_jira_keys)

    def test_patch_daily_links_is_callable(self):
        assert callable(patch_daily_links)

    def test_module_has_sync_jira_keys(self):
        import app.jira_key_sync as jks
        assert hasattr(jks, "sync_jira_keys")

    def test_module_has_patch_jira_links(self):
        import app.jira_key_sync as jks
        assert hasattr(jks, "patch_jira_links")

    def test_module_has_sync_daily_jira_keys(self):
        import app.jira_key_sync as jks
        assert hasattr(jks, "sync_daily_jira_keys")

    def test_module_has_patch_daily_links(self):
        import app.jira_key_sync as jks
        assert hasattr(jks, "patch_daily_links")
