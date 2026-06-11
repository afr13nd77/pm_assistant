"""Unit tests for vault_api utility functions: parse_note, parse_epic_note,
_extract_section, _parse_tags, _safe_int, _scan_domain_folders, _domain_from_path.
"""

import pytest
from pathlib import Path
from unittest.mock import patch


# ---------------------------------------------------------------------------
# parse_note
# ---------------------------------------------------------------------------

class TestParseNote:
    """Tests for parse_note() — the simple line-by-line frontmatter parser."""

    def test_basic_frontmatter(self, tmp_path):
        """Should parse standard frontmatter with date, tags, status."""
        from app.vault_api import parse_note

        md = tmp_path / "2026-04-26-test.md"
        md.write_text(
            "---\n"
            "date: 2026-04-26\n"
            "tags: idea, product\n"
            "status: inbox\n"
            "---\n"
            "# My Great Idea\n\n"
            "Some body text here.\n",
            encoding="utf-8",
        )
        result = parse_note(md)

        assert result["filename"] == "2026-04-26-test.md"
        assert result["date"] == "2026-04-26"
        assert result["title"] == "My Great Idea"
        assert "tags" in result
        assert result["status"] == "inbox"
        assert "Some body text here." in result["body"]

    def test_no_frontmatter(self, tmp_path):
        """Should handle files without frontmatter."""
        from app.vault_api import parse_note

        md = tmp_path / "2026-04-26-plain.md"
        md.write_text("# Just a Title\n\nPlain body.\n", encoding="utf-8")
        result = parse_note(md)

        assert result["title"] == "Just a Title"
        assert result["filename"] == "2026-04-26-plain.md"
        assert result["date"] == "2026-04-26"  # from filename stem

    def test_no_title_heading(self, tmp_path):
        """Should fall back to stem when no # heading exists."""
        from app.vault_api import parse_note

        md = tmp_path / "2026-04-26-noheading.md"
        md.write_text("Just some text without a heading.\n", encoding="utf-8")
        result = parse_note(md)

        assert result["title"] == "2026-04-26-noheading"

    def test_frontmatter_without_date_uses_filename(self, tmp_path):
        """Should derive date from filename stem when not in frontmatter."""
        from app.vault_api import parse_note

        md = tmp_path / "2026-01-15-some-note.md"
        md.write_text(
            "---\ntags: test\n---\n# Heading\nBody.\n", encoding="utf-8"
        )
        result = parse_note(md)

        assert result["date"] == "2026-01-15"

    def test_empty_file(self, tmp_path):
        """Should handle an empty file gracefully."""
        from app.vault_api import parse_note

        md = tmp_path / "empty.md"
        md.write_text("", encoding="utf-8")
        result = parse_note(md)

        assert result["filename"] == "empty.md"
        assert result["body"] == ""

    def test_frontmatter_only_dashes(self, tmp_path):
        """Should handle a file that starts with --- but has no closing ---."""
        from app.vault_api import parse_note

        md = tmp_path / "2026-04-26-broken.md"
        md.write_text("---\nkey: value\n", encoding="utf-8")
        result = parse_note(md)

        # split("---", 2) on "---\nkey: value\n" produces ['', '\nkey: value\n']
        # len < 3, so no frontmatter parsed
        assert result["filename"] == "2026-04-26-broken.md"


# ---------------------------------------------------------------------------
# parse_epic_note
# ---------------------------------------------------------------------------

class TestParseEpicNote:
    """Tests for parse_epic_note() — the YAML-based parser for epics."""

    def test_epic_with_tickets(self, tmp_path):
        """Should parse tickets list from YAML frontmatter."""
        from app.vault_api import parse_epic_note

        md = tmp_path / "E-01.md"
        md.write_text(
            "---\n"
            "id: E-01\n"
            "title: Photo Dedup\n"
            "horizon: now\n"
            "priority: p1\n"
            "prd_status: APPROVED\n"
            "confluence_link: https://example.com\n"
            "tickets:\n"
            "  - id: CONT-412\n"
            "    title: Perceptual hash\n"
            "    status: done\n"
            "  - id: CONT-413\n"
            "    title: Batch pipeline\n"
            "    status: wip\n"
            "---\n"
            "# Photo Dedup Epic\n\n"
            "Details here.\n",
            encoding="utf-8",
        )
        result = parse_epic_note(md)

        assert result["id"] == "E-01"
        assert result["title"] == "Photo Dedup"
        assert result["horizon"] == "now"
        assert len(result["tickets"]) == 2
        assert result["tickets"][0]["id"] == "CONT-412"
        assert result["tickets"][0]["status"] == "done"

    def test_epic_no_tickets(self, tmp_path):
        """Should return empty tickets list when none defined."""
        from app.vault_api import parse_epic_note

        md = tmp_path / "E-02.md"
        md.write_text(
            "---\nid: E-02\ntitle: Empty Epic\n---\n# Empty Epic\n",
            encoding="utf-8",
        )
        result = parse_epic_note(md)

        assert result["id"] == "E-02"
        assert result.get("tickets", []) == [] or result.get("tickets") is None

    def test_epic_invalid_yaml(self, tmp_path):
        """Should handle invalid YAML frontmatter gracefully."""
        from app.vault_api import parse_epic_note

        md = tmp_path / "E-03.md"
        md.write_text(
            "---\n: invalid yaml {{{\n---\n# Broken\n", encoding="utf-8"
        )
        result = parse_epic_note(md)

        # Should still return something usable
        assert result["filename"] == "E-03.md"
        assert result["title"] == "Broken"

    def test_epic_title_from_frontmatter_takes_priority(self, tmp_path):
        """Frontmatter title should be preferred over heading."""
        from app.vault_api import parse_epic_note

        md = tmp_path / "E-04.md"
        md.write_text(
            "---\ntitle: FM Title\n---\n# Heading Title\n", encoding="utf-8"
        )
        result = parse_epic_note(md)

        assert result["title"] == "FM Title"


# ---------------------------------------------------------------------------
# _extract_section
# ---------------------------------------------------------------------------

class TestExtractSection:
    """Tests for _extract_section() helper."""

    def test_extract_existing_section(self):
        from app.vault_api import _extract_section

        body = (
            "## Intro\nSome intro text.\n\n"
            "## Решения\n- Decision 1\n- Decision 2\n\n"
            "## Action Items\n- [ ] Task 1\n"
        )
        result = _extract_section(body, "Решения")
        assert "Decision 1" in result
        assert "Decision 2" in result
        assert "Task 1" not in result

    def test_extract_last_section(self):
        from app.vault_api import _extract_section

        body = "## Блокеры и риски\nSome blocker info.\n"
        result = _extract_section(body, "Блокеры и риски")
        assert result == "Some blocker info."

    def test_extract_missing_section(self):
        from app.vault_api import _extract_section

        body = "## Other Section\nContent.\n"
        result = _extract_section(body, "Решения")
        assert result == ""

    def test_extract_empty_section(self):
        from app.vault_api import _extract_section

        body = "## Решения\n\n## Next\nStuff.\n"
        result = _extract_section(body, "Решения")
        assert result == ""


# ---------------------------------------------------------------------------
# _parse_tags
# ---------------------------------------------------------------------------

class TestParseTags:
    """Tests for _parse_tags() helper."""

    def test_bracket_format(self):
        from app.vault_api import _parse_tags

        assert _parse_tags("[idea, product]") == ["idea", "product"]

    def test_comma_separated(self):
        from app.vault_api import _parse_tags

        assert _parse_tags("idea, product, ux") == ["idea", "product", "ux"]

    def test_empty_string(self):
        from app.vault_api import _parse_tags

        assert _parse_tags("") == []

    def test_single_tag(self):
        from app.vault_api import _parse_tags

        assert _parse_tags("idea") == ["idea"]

    def test_quoted_tags(self):
        from app.vault_api import _parse_tags

        assert _parse_tags('["idea", "product"]') == ["idea", "product"]


# ---------------------------------------------------------------------------
# _safe_int
# ---------------------------------------------------------------------------

class TestSafeInt:
    """Tests for _safe_int() helper."""

    def test_valid_int(self):
        from app.vault_api import _safe_int

        assert _safe_int("5") == 5

    def test_valid_int_zero(self):
        from app.vault_api import _safe_int

        assert _safe_int("0") == 0

    def test_none(self):
        from app.vault_api import _safe_int

        assert _safe_int(None) == 0

    def test_invalid_string(self):
        from app.vault_api import _safe_int

        assert _safe_int("abc") == 0

    def test_custom_default(self):
        from app.vault_api import _safe_int

        assert _safe_int("abc", default=-1) == -1


# ---------------------------------------------------------------------------
# _domain_from_path
# ---------------------------------------------------------------------------

class TestDomainFromPath:
    """Tests for _domain_from_path() helper."""

    def test_standard_domain_path(self):
        from app.vault_api import _domain_from_path

        p = Path("/vault/wiki/domains/content/ideas/2026-04-26-idea.md")
        assert _domain_from_path(p) == "content"

    def test_different_domain(self):
        from app.vault_api import _domain_from_path

        p = Path("/vault/wiki/domains/payments/tasks/2026-04-26-task.md")
        assert _domain_from_path(p) == "payments"

    def test_no_domains_in_path(self):
        from app.vault_api import _domain_from_path

        p = Path("/vault/wiki/meetings/2026-04-26-daily.md")
        assert _domain_from_path(p) == "unknown"

    def test_domains_at_end_of_path(self):
        from app.vault_api import _domain_from_path

        # Edge case: "domains" is the last part — IndexError on idx+1
        p = Path("/vault/wiki/domains")
        assert _domain_from_path(p) == "unknown"


# ---------------------------------------------------------------------------
# _scan_domain_folders
# ---------------------------------------------------------------------------

class TestScanDomainFolders:
    """Tests for _scan_domain_folders() helper."""

    def test_scan_all_domains(self, tmp_path):
        from app.vault_api import _scan_domain_folders

        # Set up domain structure
        d1 = tmp_path / "wiki" / "domains" / "content" / "ideas"
        d1.mkdir(parents=True)
        (d1 / "2026-04-26-idea-a.md").write_text("# A", encoding="utf-8")

        d2 = tmp_path / "wiki" / "domains" / "payments" / "ideas"
        d2.mkdir(parents=True)
        (d2 / "2026-04-25-idea-b.md").write_text("# B", encoding="utf-8")

        with patch("app.vault_api.all_domains", return_value=["content", "payments"]), \
             patch("app.vault_api.wiki_domain_dir", side_effect=lambda domain, at: tmp_path / "wiki" / "domains" / domain / at):
            result = _scan_domain_folders("ideas")

        assert len(result) == 2
        filenames = [f.name for f in result]
        assert "2026-04-26-idea-a.md" in filenames
        assert "2026-04-25-idea-b.md" in filenames

    def test_scan_single_domain(self, tmp_path):
        from app.vault_api import _scan_domain_folders

        d1 = tmp_path / "wiki" / "domains" / "content" / "ideas"
        d1.mkdir(parents=True)
        (d1 / "2026-04-26-idea-a.md").write_text("# A", encoding="utf-8")

        d2 = tmp_path / "wiki" / "domains" / "payments" / "ideas"
        d2.mkdir(parents=True)
        (d2 / "2026-04-25-idea-b.md").write_text("# B", encoding="utf-8")

        with patch("app.vault_api.wiki_domain_dir", side_effect=lambda domain, at: tmp_path / "wiki" / "domains" / domain / at):
            result = _scan_domain_folders("ideas", domain_filter="content")

        assert len(result) == 1
        assert result[0].name == "2026-04-26-idea-a.md"

    def test_scan_empty_domain(self, tmp_path):
        from app.vault_api import _scan_domain_folders

        d1 = tmp_path / "wiki" / "domains" / "content" / "ideas"
        d1.mkdir(parents=True)
        # No files

        with patch("app.vault_api.all_domains", return_value=["content"]), \
             patch("app.vault_api.wiki_domain_dir", side_effect=lambda domain, at: tmp_path / "wiki" / "domains" / domain / at):
            result = _scan_domain_folders("ideas")

        assert result == []

    def test_scan_nonexistent_domain(self, tmp_path):
        from app.vault_api import _scan_domain_folders

        # Domain folder does not exist on disk
        with patch("app.vault_api.wiki_domain_dir", side_effect=lambda domain, at: tmp_path / "wiki" / "domains" / domain / at):
            result = _scan_domain_folders("ideas", domain_filter="nonexistent")

        assert result == []

    def test_scan_excludes_service_files(self, tmp_path):
        from app.vault_api import _scan_domain_folders

        d1 = tmp_path / "wiki" / "domains" / "content" / "ideas"
        d1.mkdir(parents=True)
        (d1 / "2026-04-26-idea.md").write_text("# Idea", encoding="utf-8")
        (d1 / "index.md").write_text("# Index", encoding="utf-8")
        (d1 / "log.md").write_text("# Log", encoding="utf-8")

        with patch("app.vault_api.all_domains", return_value=["content"]), \
             patch("app.vault_api.wiki_domain_dir", side_effect=lambda domain, at: tmp_path / "wiki" / "domains" / domain / at):
            result = _scan_domain_folders("ideas")

        assert len(result) == 1
        assert result[0].name == "2026-04-26-idea.md"

    def test_scan_sorted_reverse(self, tmp_path):
        from app.vault_api import _scan_domain_folders

        d1 = tmp_path / "wiki" / "domains" / "content" / "ideas"
        d1.mkdir(parents=True)
        (d1 / "2026-04-20-old.md").write_text("# Old", encoding="utf-8")
        (d1 / "2026-04-26-new.md").write_text("# New", encoding="utf-8")
        (d1 / "2026-04-23-mid.md").write_text("# Mid", encoding="utf-8")

        with patch("app.vault_api.all_domains", return_value=["content"]), \
             patch("app.vault_api.wiki_domain_dir", side_effect=lambda domain, at: tmp_path / "wiki" / "domains" / domain / at):
            result = _scan_domain_folders("ideas")

        names = [f.name for f in result]
        assert names == sorted(names, reverse=True)


# ---------------------------------------------------------------------------
# _is_service_file
# ---------------------------------------------------------------------------

class TestIsServiceFile:
    """Tests for _is_service_file() helper."""

    def test_index_md(self):
        from app.vault_api import _is_service_file

        assert _is_service_file(Path("some/path/index.md")) is True

    def test_log_md(self):
        from app.vault_api import _is_service_file

        assert _is_service_file(Path("some/path/log.md")) is True

    def test_index_case_insensitive(self):
        from app.vault_api import _is_service_file

        assert _is_service_file(Path("some/path/INDEX.md")) is True
        assert _is_service_file(Path("some/path/Index.md")) is True

    def test_regular_file(self):
        from app.vault_api import _is_service_file

        assert _is_service_file(Path("some/path/2026-04-26-idea.md")) is False


# ---------------------------------------------------------------------------
# _calculate_readiness
# ---------------------------------------------------------------------------

class TestCalculateReadiness:
    """Tests for _calculate_readiness() — dynamic section-based readiness."""

    def test_all_sections_filled(self):
        from app.vault_api import _calculate_readiness

        body = (
            "# My Idea\n\n"
            "### 1. Проблема / Боль\n<!-- hint -->\nReal problem text\n\n"
            "### 2. Решение\n<!-- hint -->\nSolution text\n\n"
            "### 3. Ценность (USP)\n<!-- hint -->\nValue text\n\n"
            "### 4. Метрика\n<!-- hint -->\nMetric text\n\n"
            "### 5. Сегмент (Кто)\n<!-- hint -->\nSegment text\n\n"
            "### 6. Job Story\n<!-- hint -->\nJob story text\n\n"
            "### 7. In scope\n<!-- hint -->\nIn scope text\n\n"
            "### 8. Out of scope\n<!-- hint -->\nOut scope text\n\n"
            "### 9. Ограничения\n<!-- hint -->\nConstraints text\n"
        )
        assert _calculate_readiness(body) == 100

    def test_no_sections_filled(self):
        from app.vault_api import _calculate_readiness

        body = (
            "# My Idea\n\n"
            "### 1. Проблема / Боль\n<!-- hint -->\n\n"
            "### 2. Решение\n<!-- hint -->\n\n"
            "### 3. Ценность (USP)\n<!-- hint -->\n\n"
            "### 4. Метрика\n<!-- hint -->\n\n"
            "### 5. Сегмент (Кто)\n<!-- hint -->\n\n"
            "### 6. Job Story\n<!-- hint -->\n\n"
            "### 7. In scope\n<!-- hint -->\n\n"
            "### 8. Out of scope\n<!-- hint -->\n\n"
            "### 9. Ограничения\n<!-- hint -->\n"
        )
        assert _calculate_readiness(body) == 0

    def test_partial_sections_filled(self):
        from app.vault_api import _calculate_readiness

        body = (
            "# My Idea\n\n"
            "### 1. Проблема / Боль\n<!-- hint -->\nReal problem\n\n"
            "### 2. Решение\n<!-- hint -->\nSolution\n\n"
            "### 3. Ценность (USP)\n<!-- hint -->\nValue\n\n"
            "### 4. Метрика\n<!-- hint -->\n\n"
            "### 5. Сегмент (Кто)\n<!-- hint -->\n\n"
            "### 6. Job Story\n<!-- hint -->\n\n"
            "### 7. In scope\n<!-- hint -->\n\n"
            "### 8. Out of scope\n<!-- hint -->\n\n"
            "### 9. Ограничения\n<!-- hint -->\n"
        )
        # 3/9 = 33.33... → int → 33
        assert _calculate_readiness(body) == 33

    def test_empty_body(self):
        from app.vault_api import _calculate_readiness

        assert _calculate_readiness("") == 0

    def test_no_template_sections(self):
        from app.vault_api import _calculate_readiness

        body = "# Some random note\n\nJust plain text, no numbered sections.\n"
        assert _calculate_readiness(body) == 0

    def test_multiline_html_comment(self):
        from app.vault_api import _calculate_readiness

        body = (
            "### 1. Проблема / Боль\n"
            "<!-- this is\n"
            "a multi-line\n"
            "comment -->\n"
            "Actual content after multi-line comment\n\n"
            "### 2. Решение\n<!-- hint -->\n\n"
        )
        # Section 1 has content, section 2 does not; only 2 sections present
        # 1/9 = 11.11 → 11
        assert _calculate_readiness(body) == 11

    def test_whitespace_only_not_counted(self):
        from app.vault_api import _calculate_readiness

        body = (
            "### 1. Проблема / Боль\n<!-- hint -->\n   \n  \n\n"
            "### 2. Решение\n<!-- hint -->\n\t\n  \n"
        )
        assert _calculate_readiness(body) == 0

    def test_section_before_end_of_file(self):
        """Last section (9) at end of file with no trailing boundary."""
        from app.vault_api import _calculate_readiness

        body = (
            "### 9. Ограничения\n<!-- hint -->\nSome constraints here\n"
        )
        # 1/9 = 11.11 → 11
        assert _calculate_readiness(body) == 11

    def test_section_with_only_comment_is_empty(self):
        """A section that has only an HTML comment and nothing else is not filled."""
        from app.vault_api import _calculate_readiness

        body = (
            "### 1. Проблема / Боль\n"
            "<!-- Опишите проблему, которую решает ваш продукт -->\n\n"
            "### 2. Решение\n"
            "<!-- Как именно решаем -->\n"
        )
        assert _calculate_readiness(body) == 0

    def test_boundary_with_double_hash(self):
        """## header should also act as a section boundary."""
        from app.vault_api import _calculate_readiness

        body = (
            "### 1. Проблема / Боль\n<!-- hint -->\nProblem text\n\n"
            "## Some other section\nOther content\n"
        )
        # 1/9 = 11
        assert _calculate_readiness(body) == 11

    def test_boundary_with_horizontal_rule(self):
        """--- should act as a section boundary."""
        from app.vault_api import _calculate_readiness

        body = (
            "### 1. Проблема / Боль\n<!-- hint -->\nProblem text\n\n"
            "---\nFooter content\n"
        )
        assert _calculate_readiness(body) == 11
