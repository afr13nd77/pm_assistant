"""Unit tests for obsidian_writer.py: _parse_domain, write_idea,
write_meeting, write_jira_draft, write_report,
_load_idea_template, _format_tag_yaml, _fill_frontmatter, _fill_title, _fill_block1.
"""

import pytest
import re
from datetime import date
from pathlib import Path
from unittest.mock import patch


# ---------------------------------------------------------------------------
# _parse_domain
# ---------------------------------------------------------------------------

class TestParseDomain:

    def test_extracts_domain_from_frontmatter(self):
        from app.obsidian_writer import _parse_domain

        content = "---\ntitle: Test\ndomain: hotels\ntags: [a]\n---\n# Body"
        assert _parse_domain(content) == "hotels"

    def test_returns_general_when_no_frontmatter(self):
        from app.obsidian_writer import _parse_domain

        assert _parse_domain("# Just a heading\nSome text.") == "general"

    def test_returns_general_when_domain_missing(self):
        from app.obsidian_writer import _parse_domain

        content = "---\ntitle: Test\ntags: [a]\n---\n# Body"
        assert _parse_domain(content) == "general"

    def test_returns_general_when_domain_is_general(self):
        from app.obsidian_writer import _parse_domain

        content = "---\ndomain: general\n---\n# Body"
        assert _parse_domain(content) == "general"

    def test_returns_general_when_domain_is_empty(self):
        from app.obsidian_writer import _parse_domain

        content = "---\ndomain: \n---\n# Body"
        assert _parse_domain(content) == "general"

    def test_strips_quotes_from_domain(self):
        from app.obsidian_writer import _parse_domain

        content = '---\ndomain: "flights"\n---\n# Body'
        assert _parse_domain(content) == "flights"

    def test_strips_single_quotes_from_domain(self):
        from app.obsidian_writer import _parse_domain

        content = "---\ndomain: 'payments'\n---\n# Body"
        assert _parse_domain(content) == "payments"


# ---------------------------------------------------------------------------
# write_idea
# ---------------------------------------------------------------------------

class TestWriteIdea:

    def _make_idea_data(self, **overrides):
        """Return a minimal idea_data dict with optional overrides."""
        data = {
            "title": "Test Idea",
            "domain": "hotels",
            "problem": "Hotels have no photos",
            "solution": "Add photo pipeline",
            "usp": "Only OTA with auto-photos",
            "metric": "Photo coverage +30%",
            "tags": ["idea", "hotels"],
        }
        data.update(overrides)
        return data

    def test_creates_files_in_raw_and_wiki(self, tmp_path):
        from app.obsidian_writer import write_idea

        idea_data = self._make_idea_data(domain="hotels")
        with _multi_patch_vault(tmp_path):
            filepath = write_idea(idea_data, "my test idea text")

        # Returned path should be the wiki path
        assert "wiki" in str(filepath)
        assert "hotels" in str(filepath)
        assert "ideas" in str(filepath)
        assert filepath.exists()

        content = filepath.read_text(encoding="utf-8")
        assert "IDEA-0001" in content
        assert "hotels" in content

        # Raw copy should also exist
        raw_path = tmp_path / "raw" / "inbound" / "ideas" / filepath.name
        assert raw_path.exists()

    def test_default_domain_is_general(self, tmp_path):
        from app.obsidian_writer import write_idea

        idea_data = self._make_idea_data(domain="general")
        del idea_data["domain"]  # Test default fallback
        with _multi_patch_vault(tmp_path):
            filepath = write_idea(idea_data, "some idea")

        assert "general" in str(filepath)
        assert filepath.exists()

    def test_slug_truncation(self, tmp_path):
        from app.obsidian_writer import write_idea

        long_text = "a " * 100  # 200 chars
        idea_data = self._make_idea_data()
        with _multi_patch_vault(tmp_path):
            filepath = write_idea(idea_data, long_text)

        # Filename stem should be reasonable length
        assert len(filepath.stem) <= 80

    def test_idea_filename_format(self, tmp_path):
        from app.obsidian_writer import write_idea

        idea_data = self._make_idea_data()
        with _multi_patch_vault(tmp_path):
            filepath = write_idea(idea_data, "my idea")

        pattern = r"^IDEA-0001-\d{4}-\d{2}-\d{2}_my-idea\.md$"
        assert re.match(pattern, filepath.name), f"Unexpected filename: {filepath.name}"

    def test_idea_auto_increment(self, tmp_path):
        from app.obsidian_writer import write_idea

        idea_data = self._make_idea_data()
        with _multi_patch_vault(tmp_path):
            fp1 = write_idea(idea_data, "alpha")
            fp2 = write_idea(idea_data, "beta")

        assert "IDEA-0001-" in fp1.name
        assert "IDEA-0002-" in fp2.name

    def test_idea_continues_from_existing_in_raw(self, tmp_path):
        """If IDEA-0005 already exists in raw/, next should be IDEA-0006."""
        from app.obsidian_writer import write_idea

        raw_dir = tmp_path / "raw" / "inbound" / "ideas"
        raw_dir.mkdir(parents=True)
        (raw_dir / "IDEA-0005-2026-01-01_old-idea.md").write_text("old")

        idea_data = self._make_idea_data()
        with _multi_patch_vault(tmp_path):
            filepath = write_idea(idea_data, "new idea")

        assert "IDEA-0006-" in filepath.name

    def test_idea_continues_from_existing_in_wiki(self, tmp_path):
        """If IDEA-0003 exists in wiki/domains/hotels/ideas/, next is IDEA-0004."""
        from app.obsidian_writer import write_idea

        wiki_ideas = tmp_path / "wiki" / "domains" / "hotels" / "ideas"
        wiki_ideas.mkdir(parents=True)
        (wiki_ideas / "IDEA-0003-2026-01-01_hotel-idea.md").write_text("old")

        idea_data = self._make_idea_data()
        with _multi_patch_vault(tmp_path):
            filepath = write_idea(idea_data, "new idea")

        assert "IDEA-0004-" in filepath.name

    def test_idea_scans_both_locations_for_max(self, tmp_path):
        """Max number across raw (IDEA-0002) and wiki (IDEA-0007) -> IDEA-0008."""
        from app.obsidian_writer import write_idea

        raw_dir = tmp_path / "raw" / "inbound" / "ideas"
        raw_dir.mkdir(parents=True)
        (raw_dir / "IDEA-0002-2026-01-01_raw-idea.md").write_text("old")

        wiki_ideas = tmp_path / "wiki" / "domains" / "flights" / "ideas"
        wiki_ideas.mkdir(parents=True)
        (wiki_ideas / "IDEA-0007-2026-01-01_flight-idea.md").write_text("old")

        idea_data = self._make_idea_data(domain="hotels")
        with _multi_patch_vault(tmp_path):
            filepath = write_idea(idea_data, "new idea")

        assert "IDEA-0008-" in filepath.name

    def test_frontmatter_filled_correctly(self, tmp_path):
        """Frontmatter should contain id, domain, status, source, dates, tags."""
        from app.obsidian_writer import write_idea

        idea_data = self._make_idea_data(
            domain="flights",
            tags=["idea", "pricing"],
        )
        with _multi_patch_vault(tmp_path):
            filepath = write_idea(idea_data, "pricing idea")

        content = filepath.read_text(encoding="utf-8")
        assert 'id: "IDEA-0001"' in content
        assert "domain: flights" in content
        assert 'status: "Новая"' in content
        assert "source: telegram-inbox" in content
        assert "  - idea" in content
        assert "  - pricing" in content

    def test_title_filled_in_body(self, tmp_path):
        """The H1 heading should be the idea title."""
        from app.obsidian_writer import write_idea

        idea_data = self._make_idea_data(title="My Great Idea")
        with _multi_patch_vault(tmp_path):
            filepath = write_idea(idea_data, "great idea text")

        content = filepath.read_text(encoding="utf-8")
        assert "# My Great Idea" in content

    def test_block1_sections_filled(self, tmp_path):
        """Block 1 sections should be filled with idea_data values."""
        from app.obsidian_writer import write_idea

        idea_data = self._make_idea_data(
            problem="Hotels lack photos",
            solution="Auto-photo pipeline",
            usp="Only OTA with this",
            metric="+30% coverage",
        )
        with _multi_patch_vault(tmp_path):
            filepath = write_idea(idea_data, "photo idea")

        content = filepath.read_text(encoding="utf-8")
        assert "Hotels lack photos" in content
        assert "Auto-photo pipeline" in content
        assert "Only OTA with this" in content
        assert "+30% coverage" in content

    def test_fallback_template_used_when_no_file(self, tmp_path):
        """When templates/idea.md is missing, fallback template is used."""
        from app.obsidian_writer import write_idea

        idea_data = self._make_idea_data()
        with _multi_patch_vault(tmp_path):
            # No templates/idea.md created — fallback should kick in
            filepath = write_idea(idea_data, "fallback test")

        content = filepath.read_text(encoding="utf-8")
        # Fallback template has these sections
        assert "## Блок 1" in content or "Паспорт идеи" in content
        assert "### 1." in content

    def test_slug_strips_invalid_chars(self, tmp_path):
        """Filename slug should not contain characters invalid on Windows."""
        from app.obsidian_writer import write_idea

        idea_data = self._make_idea_data()
        with _multi_patch_vault(tmp_path):
            filepath = write_idea(idea_data, 'idea with "quotes" and <angle> brackets')

        # Should not contain any of: < > : " | ? * \
        assert '"' not in filepath.name
        assert '<' not in filepath.name
        assert '>' not in filepath.name


# ---------------------------------------------------------------------------
# write_meeting
# ---------------------------------------------------------------------------

class TestWriteMeeting:

    def test_creates_files_in_raw_and_wiki(self, tmp_path):
        from app.obsidian_writer import write_meeting

        content = "# Meeting Notes\n\nAction items."
        with _multi_patch_vault(tmp_path):
            filepath = write_meeting(content, "standup.txt")

        # Wiki path
        assert "wiki" in str(filepath)
        assert "meetings" in str(filepath)
        assert "standup" in filepath.name
        assert filepath.exists()
        assert filepath.read_text(encoding="utf-8") == content

        # Raw copy
        raw_path = tmp_path / "raw" / "inbound" / "meeting-notes" / "standup.txt"
        assert raw_path.exists()

    def test_meeting_filename_format(self, tmp_path):
        from app.obsidian_writer import write_meeting

        with _multi_patch_vault(tmp_path):
            filepath = write_meeting("content", "daily-sync.txt")

        today = date.today().isoformat()
        assert filepath.name == f"{today}-daily-sync.md"


# ---------------------------------------------------------------------------
# write_jira_draft
# ---------------------------------------------------------------------------

class TestWriteJiraDraft:

    def test_creates_files_in_raw_and_wiki(self, tmp_path):
        from app.obsidian_writer import write_jira_draft

        content = "---\ndomain: hotels\n---\n# CONT-500\n\nDescription."
        with _multi_patch_vault(tmp_path):
            filepath = write_jira_draft(content)

        # Wiki path
        assert "wiki" in str(filepath)
        assert "hotels" in str(filepath)
        assert "tasks" in str(filepath)
        assert "jira-01" in filepath.name
        assert filepath.exists()

        # Raw copy
        raw_path = tmp_path / "raw" / "inbound" / "tasks" / filepath.name
        assert raw_path.exists()

    def test_default_domain_is_general(self, tmp_path):
        from app.obsidian_writer import write_jira_draft

        content = "# CONT-501\n\nNo frontmatter."
        with _multi_patch_vault(tmp_path):
            filepath = write_jira_draft(content)

        assert "general" in str(filepath)

    def test_increments_index(self, tmp_path):
        from app.obsidian_writer import write_jira_draft

        content = "---\ndomain: hotels\n---\nDraft."
        with _multi_patch_vault(tmp_path):
            fp1 = write_jira_draft(content)
            fp2 = write_jira_draft(content)

        assert "jira-01" in fp1.name
        assert "jira-02" in fp2.name


# ---------------------------------------------------------------------------
# write_report
# ---------------------------------------------------------------------------

class TestWriteReport:

    def test_creates_file_in_wiki_reports(self, tmp_path):
        from app.obsidian_writer import write_report

        with _multi_patch_vault(tmp_path):
            with patch("app.obsidian_writer.date") as mock_date:
                mock_date.today.return_value = date(2026, 4, 27)
                mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

                filepath = write_report("# Weekly Report\n\nContent.")

        assert filepath.exists()
        assert "wiki" in str(filepath)
        assert "reports" in str(filepath)
        assert "2026-04-27" in filepath.name
        assert "week-18" in filepath.name
        assert filepath.read_text(encoding="utf-8") == "# Weekly Report\n\nContent."

    def test_no_raw_copy_for_reports(self, tmp_path):
        from app.obsidian_writer import write_report

        with _multi_patch_vault(tmp_path):
            with patch("app.obsidian_writer.date") as mock_date:
                mock_date.today.return_value = date(2026, 4, 27)
                mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

                write_report("Report content.")

        # No raw directory for reports should have been created with report files
        raw_dir = tmp_path / "raw"
        if raw_dir.exists():
            report_files = list(raw_dir.rglob("*week*"))
            assert len(report_files) == 0

    def test_report_folder_created_if_missing(self, tmp_path):
        from app.obsidian_writer import write_report

        with _multi_patch_vault(tmp_path):
            with patch("app.obsidian_writer.date") as mock_date:
                mock_date.today.return_value = date(2026, 4, 27)
                mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

                filepath = write_report("Report content.")

        assert (tmp_path / "wiki" / "reports").is_dir()
        assert filepath.exists()


# ---------------------------------------------------------------------------
# write_daily
# ---------------------------------------------------------------------------

class TestWriteDaily:

    def test_creates_files_in_raw_and_wiki(self, tmp_path):
        from app.obsidian_writer import write_daily

        content = "---\ntags: [daily-log]\ndate: 2026-05-01\n---\n# Daily Log"
        with _multi_patch_vault(tmp_path):
            filepath = write_daily(content)

        # Wiki path
        assert "wiki" in str(filepath)
        assert "daily-logs" in str(filepath)
        assert filepath.exists()
        assert filepath.read_text(encoding="utf-8") == content

        # Raw copy
        raw_dir = tmp_path / "raw" / "inbound" / "daily-logs"
        raw_files = list(raw_dir.glob("*.md"))
        assert len(raw_files) == 1
        assert raw_files[0].read_text(encoding="utf-8") == content

    def test_filename_uses_today_date(self, tmp_path):
        from app.obsidian_writer import write_daily

        with _multi_patch_vault(tmp_path):
            with patch("app.vault_paths.date") as mock_date:
                mock_date.today.return_value = date(2026, 5, 1)
                mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

                filepath = write_daily("content")

        assert filepath.name == "2026.05.01-001-Daily-summary.md"

    def test_increments_sequence_when_file_exists(self, tmp_path):
        from app.obsidian_writer import write_daily

        with _multi_patch_vault(tmp_path):
            with patch("app.vault_paths.date") as mock_date:
                mock_date.today.return_value = date(2026, 5, 1)
                mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

                fp1 = write_daily("first log")
                fp2 = write_daily("second log")

        assert fp1.name == "2026.05.01-001-Daily-summary.md"
        assert fp2.name == "2026.05.01-002-Daily-summary.md"

    def test_increments_sequence_multiple(self, tmp_path):
        from app.obsidian_writer import write_daily

        with _multi_patch_vault(tmp_path):
            with patch("app.vault_paths.date") as mock_date:
                mock_date.today.return_value = date(2026, 5, 1)
                mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

                fp1 = write_daily("first")
                fp2 = write_daily("second")
                fp3 = write_daily("third")

        assert fp1.name == "2026.05.01-001-Daily-summary.md"
        assert fp2.name == "2026.05.01-002-Daily-summary.md"
        assert fp3.name == "2026.05.01-003-Daily-summary.md"

    def test_directories_created_if_missing(self, tmp_path):
        from app.obsidian_writer import write_daily

        with _multi_patch_vault(tmp_path):
            filepath = write_daily("content")

        assert (tmp_path / "raw" / "inbound" / "daily-logs").is_dir()
        assert (tmp_path / "wiki" / "daily-logs").is_dir()
        assert filepath.exists()

    def test_no_domain_routing(self, tmp_path):
        """Daily logs go to wiki/daily-logs/, NOT to wiki/domains/<domain>/."""
        from app.obsidian_writer import write_daily

        content = "---\ndomain: hotels\n---\n# Daily Log"
        with _multi_patch_vault(tmp_path):
            filepath = write_daily(content)

        assert "domains" not in str(filepath)
        assert "daily-logs" in str(filepath)


# ---------------------------------------------------------------------------
# _daily_filename
# ---------------------------------------------------------------------------

class TestDailyFilename:

    def test_returns_001_when_no_file_exists(self, tmp_path):
        from app.obsidian_writer import _daily_filename

        with patch("app.vault_paths.date") as mock_date:
            mock_date.today.return_value = date(2026, 5, 1)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            result = _daily_filename(tmp_path)
        assert result == "2026.05.01-001-Daily-summary.md"

    def test_returns_002_when_001_exists(self, tmp_path):
        from app.obsidian_writer import _daily_filename

        (tmp_path / "2026.05.01-001-Daily-summary.md").write_text("existing")
        with patch("app.vault_paths.date") as mock_date:
            mock_date.today.return_value = date(2026, 5, 1)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            result = _daily_filename(tmp_path)
        assert result == "2026.05.01-002-Daily-summary.md"

    def test_returns_003_when_001_and_002_exist(self, tmp_path):
        from app.obsidian_writer import _daily_filename

        (tmp_path / "2026.05.01-001-Daily-summary.md").write_text("existing")
        (tmp_path / "2026.05.01-002-Daily-summary.md").write_text("existing")
        with patch("app.vault_paths.date") as mock_date:
            mock_date.today.return_value = date(2026, 5, 1)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            result = _daily_filename(tmp_path)
        assert result == "2026.05.01-003-Daily-summary.md"


# ---------------------------------------------------------------------------
# _update_artifact_index / _append_artifact_log (via write_idea / write_jira_draft)
# ---------------------------------------------------------------------------

class TestArtifactIndexAndLog:

    def test_write_idea_updates_index(self, tmp_path):
        """After write_idea, index.md in the domain/ideas dir lists the new file."""
        from app.obsidian_writer import write_idea

        idea_data = {
            "title": "Great Idea",
            "domain": "hotels",
            "problem": "Problem text",
            "solution": "Solution text",
            "usp": "USP text",
            "metric": "Metric text",
            "tags": ["idea"],
        }
        with _multi_patch_vault(tmp_path):
            filepath = write_idea(idea_data, "great idea text")

        index_path = tmp_path / "wiki" / "domains" / "hotels" / "ideas" / "index.md"
        assert index_path.exists(), "index.md was not created"
        index_text = index_path.read_text(encoding="utf-8")
        assert filepath.name in index_text, f"{filepath.name} not found in index.md"
        assert "| File | Title | Status | Created |" in index_text

    def test_write_idea_updates_log(self, tmp_path):
        """After write_idea, log.md in the domain/ideas dir has a CREATE entry."""
        from app.obsidian_writer import write_idea

        idea_data = {
            "title": "Some Idea",
            "domain": "hotels",
            "problem": "",
            "solution": "",
            "usp": "",
            "metric": "",
            "tags": ["idea"],
        }
        with _multi_patch_vault(tmp_path):
            filepath = write_idea(idea_data, "some idea")

        log_path = tmp_path / "wiki" / "domains" / "hotels" / "ideas" / "log.md"
        assert log_path.exists(), "log.md was not created"
        log_text = log_path.read_text(encoding="utf-8")
        assert "CREATE" in log_text
        assert filepath.name in log_text
        assert "→ ok" in log_text

    def test_write_jira_draft_updates_index(self, tmp_path):
        """After write_jira_draft, index.md in the domain/tasks dir lists the new file."""
        from app.obsidian_writer import write_jira_draft

        content = "---\ndomain: flights\ntitle: Fix booking\nstatus: todo\ncreated: 2026-05-01\n---\n# CONT-999"
        with _multi_patch_vault(tmp_path):
            filepath = write_jira_draft(content)

        index_path = tmp_path / "wiki" / "domains" / "flights" / "tasks" / "index.md"
        assert index_path.exists(), "index.md was not created"
        index_text = index_path.read_text(encoding="utf-8")
        assert filepath.name in index_text, f"{filepath.name} not found in index.md"
        assert "| File | Title | Status | Created |" in index_text

    def test_write_jira_draft_updates_log(self, tmp_path):
        """After write_jira_draft, log.md in the domain/tasks dir has a CREATE entry."""
        from app.obsidian_writer import write_jira_draft

        content = "---\ndomain: flights\n---\n# CONT-999"
        with _multi_patch_vault(tmp_path):
            filepath = write_jira_draft(content)

        log_path = tmp_path / "wiki" / "domains" / "flights" / "tasks" / "log.md"
        assert log_path.exists(), "log.md was not created"
        log_text = log_path.read_text(encoding="utf-8")
        assert "CREATE" in log_text
        assert filepath.name in log_text
        assert "→ ok" in log_text

    def test_index_update_excludes_service_files(self, tmp_path):
        """index.md and log.md must NOT appear as rows in the index table."""
        from app.obsidian_writer import write_idea

        idea_data = {
            "title": "Idea One",
            "domain": "hotels",
            "problem": "",
            "solution": "",
            "usp": "",
            "metric": "",
            "tags": ["idea"],
        }
        with _multi_patch_vault(tmp_path):
            write_idea(idea_data, "idea one")

        index_path = tmp_path / "wiki" / "domains" / "hotels" / "ideas" / "index.md"
        assert index_path.exists()
        index_text = index_path.read_text(encoding="utf-8")

        # Service files must not appear as table rows (inside [[ ]])
        assert "[[index.md]]" not in index_text
        assert "[[log.md]]" not in index_text

    def test_index_update_failure_does_not_break_write(self, tmp_path):
        """If _update_artifact_index raises, write_idea must still succeed."""
        from app.obsidian_writer import write_idea

        idea_data = {
            "title": "Resilient Idea",
            "domain": "hotels",
            "problem": "",
            "solution": "",
            "usp": "",
            "metric": "",
            "tags": ["idea"],
        }
        with _multi_patch_vault(tmp_path):
            with patch(
                "app.obsidian_writer._update_artifact_index",
                side_effect=RuntimeError("disk full"),
            ):
                filepath = write_idea(idea_data, "resilient idea")

        # The main wiki file must still have been written
        assert filepath.exists()
        content = filepath.read_text(encoding="utf-8")
        assert "IDEA-0001" in content


# ---------------------------------------------------------------------------
# _load_idea_template
# ---------------------------------------------------------------------------

class TestLoadIdeaTemplate:

    def test_loads_from_vault_templates(self, tmp_path):
        from app.obsidian_writer import _load_idea_template

        tpl_dir = tmp_path / "templates"
        tpl_dir.mkdir(parents=True)
        (tpl_dir / "idea.md").write_text("---\nid: \"\"\n---\n# {title}\n", encoding="utf-8")

        with _multi_patch_vault(tmp_path):
            result = _load_idea_template()

        assert "# {title}" in result

    def test_falls_back_when_file_missing(self, tmp_path):
        from app.obsidian_writer import _load_idea_template, _FALLBACK_TEMPLATE

        with _multi_patch_vault(tmp_path):
            result = _load_idea_template()

        assert result == _FALLBACK_TEMPLATE
        assert "Блок 1" in result or "Паспорт идеи" in result


# ---------------------------------------------------------------------------
# _format_tag_yaml
# ---------------------------------------------------------------------------

class TestFormatTagYaml:

    def test_simple_tag_no_quotes(self):
        from app.obsidian_writer import _format_tag_yaml

        assert _format_tag_yaml("idea") == "  - idea"
        assert _format_tag_yaml("hotels") == "  - hotels"

    def test_tag_with_special_chars_quoted(self):
        from app.obsidian_writer import _format_tag_yaml

        assert _format_tag_yaml("my tag") == '  - "my tag"'
        assert _format_tag_yaml("tag/sub") == '  - "tag/sub"'

    def test_cyrillic_tag_no_quotes(self):
        from app.obsidian_writer import _format_tag_yaml

        assert _format_tag_yaml("идея") == "  - идея"

    def test_hyphen_underscore_no_quotes(self):
        from app.obsidian_writer import _format_tag_yaml

        assert _format_tag_yaml("my-tag") == "  - my-tag"
        assert _format_tag_yaml("my_tag") == "  - my_tag"


# ---------------------------------------------------------------------------
# _fill_frontmatter
# ---------------------------------------------------------------------------

class TestFillFrontmatter:

    def test_fills_all_fields(self):
        from app.obsidian_writer import _fill_frontmatter

        template = (
            "---\n"
            'id: ""\n'
            "type: idea\n"
            "domain:\n"
            'status: "Новая"\n'
            "readiness: 0%\n"
            'created: ""\n'
            'updated: ""\n'
            "source:\n"
            "tags:\n"
            "  -\n"
            "---\n"
            "# {title}\n"
        )
        idea_data = {"domain": "flights", "tags": ["idea", "pricing"]}
        result = _fill_frontmatter(template, "IDEA-0042", idea_data, "2026-05-08", 44)

        assert 'id: "IDEA-0042"' in result
        assert "domain: flights" in result
        assert 'created: "2026-05-08"' in result
        assert 'updated: "2026-05-08"' in result
        assert "source: telegram-inbox" in result
        assert "  - idea" in result
        assert "  - pricing" in result
        assert "readiness: 44%" in result

    def test_returns_template_when_no_frontmatter(self):
        from app.obsidian_writer import _fill_frontmatter

        template = "# No frontmatter here"
        result = _fill_frontmatter(template, "IDEA-0001", {}, "2026-05-08", 0)
        assert result == template


# ---------------------------------------------------------------------------
# _fill_title
# ---------------------------------------------------------------------------

class TestFillTitle:

    def test_replaces_h1_heading(self):
        from app.obsidian_writer import _fill_title

        content = "---\nid: x\n---\n\n# {title}\n\n## Section"
        result = _fill_title(content, "My Great Idea")
        assert "# My Great Idea" in result
        assert "# {title}" not in result

    def test_preserves_rest_of_content(self):
        from app.obsidian_writer import _fill_title

        content = "---\nid: x\n---\n\n# {title}\n\n## Section\n\nBody text."
        result = _fill_title(content, "Title")
        assert "## Section" in result
        assert "Body text." in result


# ---------------------------------------------------------------------------
# _fill_block1
# ---------------------------------------------------------------------------

class TestFillBlock1:

    def test_fills_sections_with_content(self):
        from app.obsidian_writer import _fill_block1

        content = (
            "### 1. Проблема / Боль\n"
            "\n"
            "### 2. Решение\n"
            "\n"
            "### 3. Ценность (USP)\n"
            "\n"
            "### 4. Метрика\n"
        )
        idea_data = {
            "problem": "Hotels lack photos",
            "solution": "Auto-photo pipeline",
            "usp": "Only OTA with this",
            "metric": "+30% coverage",
        }
        result = _fill_block1(content, idea_data)

        assert "Hotels lack photos" in result
        assert "Auto-photo pipeline" in result
        assert "Only OTA with this" in result
        assert "+30% coverage" in result

    def test_skips_empty_fields(self):
        from app.obsidian_writer import _fill_block1

        content = (
            "### 1. Проблема / Боль\n"
            "\n"
            "### 2. Решение\n"
        )
        idea_data = {"problem": "", "solution": "Some fix"}
        result = _fill_block1(content, idea_data)

        # problem was empty, should not have been inserted
        assert "Some fix" in result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

from contextlib import contextmanager

@contextmanager
def _multi_patch_vault(tmp_path):
    """Patch VAULT_PATH in both obsidian_writer and vault_paths modules."""
    with patch("app.obsidian_writer.VAULT_PATH", tmp_path), \
         patch("app.vault_paths.VAULT_PATH", tmp_path):
        yield
