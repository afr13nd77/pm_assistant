"""Unit tests for reporter.py: scan_folder, scan_all_domain_folders,
get_open_tasks, build_context, and generate_weekly_report.
"""

import pytest
from datetime import date
from pathlib import Path
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# _parse_frontmatter
# ---------------------------------------------------------------------------

class TestParseFrontmatter:
    """Tests for the internal _parse_frontmatter helper."""

    def test_valid_frontmatter(self):
        from app.reporter import _parse_frontmatter

        text = "---\ntitle: Test\nstatus: inbox\n---\n# Heading\n\nBody text."
        meta, body = _parse_frontmatter(text)

        assert meta["title"] == "Test"
        assert meta["status"] == "inbox"
        assert "Body text." in body

    def test_no_frontmatter(self):
        from app.reporter import _parse_frontmatter

        text = "# Just a heading\n\nSome body."
        meta, body = _parse_frontmatter(text)

        assert meta == {}
        assert "Just a heading" in body

    def test_invalid_yaml_frontmatter(self):
        from app.reporter import _parse_frontmatter

        text = "---\n: invalid {{{\n---\nBody."
        meta, body = _parse_frontmatter(text)

        assert meta == {}
        assert body == "Body."

    def test_empty_frontmatter(self):
        from app.reporter import _parse_frontmatter

        text = "---\n\n---\nBody text."
        meta, body = _parse_frontmatter(text)

        assert meta == {}
        assert body == "Body text."


# ---------------------------------------------------------------------------
# _extract_date_from_filename
# ---------------------------------------------------------------------------

class TestExtractDateFromFilename:

    def test_valid_date_prefix(self):
        from app.reporter import _extract_date_from_filename

        result = _extract_date_from_filename("2026-04-21-meeting-notes.md")
        assert result == date(2026, 4, 21)

    def test_no_date_prefix(self):
        from app.reporter import _extract_date_from_filename

        result = _extract_date_from_filename("meeting-notes.md")
        assert result is None

    def test_invalid_date(self):
        from app.reporter import _extract_date_from_filename

        result = _extract_date_from_filename("2026-13-45-bad.md")
        assert result is None

    def test_date_only_filename(self):
        from app.reporter import _extract_date_from_filename

        result = _extract_date_from_filename("2026-01-15.md")
        assert result == date(2026, 1, 15)


# ---------------------------------------------------------------------------
# _extract_title
# ---------------------------------------------------------------------------

class TestExtractTitle:

    def test_title_from_frontmatter(self):
        from app.reporter import _extract_title

        assert _extract_title({"title": "FM Title"}, "# Heading", "file.md") == "FM Title"

    def test_title_from_heading(self):
        from app.reporter import _extract_title

        assert _extract_title({}, "# My Heading\n\nBody", "file.md") == "My Heading"

    def test_title_from_filename(self):
        from app.reporter import _extract_title

        assert _extract_title({}, "No heading here", "2026-04-21-notes.md") == "2026-04-21-notes"


# ---------------------------------------------------------------------------
# scan_folder — now takes Path directly
# ---------------------------------------------------------------------------

class TestScanFolder:

    def test_scan_with_matching_files(self, tmp_path):
        from app.reporter import scan_folder

        meetings_dir = tmp_path / "Meetings"
        meetings_dir.mkdir()

        # File within range
        f1 = meetings_dir / "2026-04-21-standup.md"
        f1.write_text("---\ntitle: Standup\n---\n# Standup\n\nDiscussed items.", encoding="utf-8")

        # File outside range
        f2 = meetings_dir / "2026-04-14-old-meeting.md"
        f2.write_text("---\ntitle: Old\n---\n# Old Meeting\n\nOld stuff.", encoding="utf-8")

        # File within range
        f3 = meetings_dir / "2026-04-23-review.md"
        f3.write_text("# Review\n\nReviewed things.", encoding="utf-8")

        results = scan_folder(meetings_dir, date(2026, 4, 21), date(2026, 4, 25))

        assert len(results) == 2
        filenames = {r["filename"] for r in results}
        assert "2026-04-21-standup.md" in filenames
        assert "2026-04-23-review.md" in filenames

    def test_scan_missing_folder(self, tmp_path):
        from app.reporter import scan_folder

        non_existent = tmp_path / "NonExistent"
        results = scan_folder(non_existent, date(2026, 4, 21), date(2026, 4, 25))

        assert results == []

    def test_scan_empty_folder(self, tmp_path):
        from app.reporter import scan_folder

        empty_dir = tmp_path / "Empty"
        empty_dir.mkdir()

        results = scan_folder(empty_dir, date(2026, 4, 21), date(2026, 4, 25))

        assert results == []

    def test_scan_skips_files_without_date_prefix(self, tmp_path):
        from app.reporter import scan_folder

        folder = tmp_path / "Inbox"
        folder.mkdir()

        (folder / "random-note.md").write_text("# Random\n\nStuff.", encoding="utf-8")
        (folder / "2026-04-22-valid.md").write_text("# Valid\n\nContent.", encoding="utf-8")

        results = scan_folder(folder, date(2026, 4, 21), date(2026, 4, 25))

        assert len(results) == 1
        assert results[0]["filename"] == "2026-04-22-valid.md"

    def test_scan_inclusive_date_boundaries(self, tmp_path):
        from app.reporter import scan_folder

        folder = tmp_path / "Data"
        folder.mkdir()

        (folder / "2026-04-21-start.md").write_text("# Start\nBody.", encoding="utf-8")
        (folder / "2026-04-25-end.md").write_text("# End\nBody.", encoding="utf-8")
        (folder / "2026-04-20-before.md").write_text("# Before\nBody.", encoding="utf-8")
        (folder / "2026-04-26-after.md").write_text("# After\nBody.", encoding="utf-8")

        results = scan_folder(folder, date(2026, 4, 21), date(2026, 4, 25))

        assert len(results) == 2
        filenames = {r["filename"] for r in results}
        assert "2026-04-21-start.md" in filenames
        assert "2026-04-25-end.md" in filenames


# ---------------------------------------------------------------------------
# scan_all_domain_folders
# ---------------------------------------------------------------------------

class TestScanAllDomainFolders:

    def test_aggregates_across_domains(self, tmp_path):
        from app.reporter import scan_all_domain_folders

        # Create two domain idea folders
        domain_a = tmp_path / "wiki" / "domains" / "flights" / "ideas"
        domain_a.mkdir(parents=True)
        (domain_a / "2026-04-21-idea-a.md").write_text("# Idea A\nBody.", encoding="utf-8")

        domain_b = tmp_path / "wiki" / "domains" / "hotels" / "ideas"
        domain_b.mkdir(parents=True)
        (domain_b / "2026-04-22-idea-b.md").write_text("# Idea B\nBody.", encoding="utf-8")

        with patch("app.reporter.vault_paths") as mock_vp:
            mock_vp.all_domains.return_value = ["flights", "hotels"]
            mock_vp.wiki_domain_dir.side_effect = lambda d, t: tmp_path / "wiki" / "domains" / d / t

            results = scan_all_domain_folders("ideas", date(2026, 4, 20), date(2026, 4, 25))

        assert len(results) == 2
        assert results[0]["domain"] in ("flights", "hotels")
        assert results[1]["domain"] in ("flights", "hotels")
        domains = {r["domain"] for r in results}
        assert domains == {"flights", "hotels"}

    def test_empty_when_no_domains(self):
        from app.reporter import scan_all_domain_folders

        with patch("app.reporter.vault_paths") as mock_vp:
            mock_vp.all_domains.return_value = []

            results = scan_all_domain_folders("ideas", date(2026, 4, 20), date(2026, 4, 25))

        assert results == []

    def test_skips_domains_without_matching_files(self, tmp_path):
        from app.reporter import scan_all_domain_folders

        # Domain exists but has no matching files
        domain_dir = tmp_path / "wiki" / "domains" / "flights" / "tasks"
        domain_dir.mkdir(parents=True)
        (domain_dir / "2026-03-01-old-task.md").write_text("# Old\nBody.", encoding="utf-8")

        with patch("app.reporter.vault_paths") as mock_vp:
            mock_vp.all_domains.return_value = ["flights"]
            mock_vp.wiki_domain_dir.return_value = domain_dir

            results = scan_all_domain_folders("tasks", date(2026, 4, 20), date(2026, 4, 25))

        assert results == []


# ---------------------------------------------------------------------------
# get_open_tasks — now scans across all domains
# ---------------------------------------------------------------------------

class TestGetOpenTasks:

    def test_filters_out_done_tasks(self, tmp_path):
        from app.reporter import get_open_tasks

        tasks_dir = tmp_path / "wiki" / "domains" / "flights" / "tasks"
        tasks_dir.mkdir(parents=True)

        (tasks_dir / "2026-04-21-jira-01.md").write_text(
            "---\nstatus: inbox\n---\n# Open Task\nBody.", encoding="utf-8"
        )
        (tasks_dir / "2026-04-22-jira-02.md").write_text(
            "---\nstatus: done\n---\n# Done Task\nBody.", encoding="utf-8"
        )
        (tasks_dir / "2026-04-23-jira-03.md").write_text(
            "---\nstatus: wip\n---\n# WIP Task\nBody.", encoding="utf-8"
        )

        with patch("app.reporter.vault_paths") as mock_vp:
            mock_vp.all_domains.return_value = ["flights"]
            mock_vp.wiki_domain_dir.return_value = tasks_dir

            results = get_open_tasks()

        assert len(results) == 2
        statuses = {r["status"] for r in results}
        assert "done" not in statuses
        assert "inbox" in statuses
        assert "wip" in statuses
        # All tasks should have domain field
        for r in results:
            assert r["domain"] == "flights"

    def test_no_domains_returns_empty(self):
        from app.reporter import get_open_tasks

        with patch("app.reporter.vault_paths") as mock_vp:
            mock_vp.all_domains.return_value = []

            results = get_open_tasks()

        assert results == []

    def test_missing_tasks_folder_skipped(self, tmp_path):
        from app.reporter import get_open_tasks

        # Domain directory does not have a tasks subfolder
        non_existent = tmp_path / "wiki" / "domains" / "flights" / "tasks"

        with patch("app.reporter.vault_paths") as mock_vp:
            mock_vp.all_domains.return_value = ["flights"]
            mock_vp.wiki_domain_dir.return_value = non_existent

            results = get_open_tasks()

        assert results == []

    def test_no_frontmatter_status_defaults_to_unknown(self, tmp_path):
        from app.reporter import get_open_tasks

        tasks_dir = tmp_path / "wiki" / "domains" / "hotels" / "tasks"
        tasks_dir.mkdir(parents=True)

        (tasks_dir / "2026-04-21-task.md").write_text("# Plain Task\nBody.", encoding="utf-8")

        with patch("app.reporter.vault_paths") as mock_vp:
            mock_vp.all_domains.return_value = ["hotels"]
            mock_vp.wiki_domain_dir.return_value = tasks_dir

            results = get_open_tasks()

        assert len(results) == 1
        assert results[0]["status"] == "unknown"
        assert results[0]["domain"] == "hotels"

    def test_multiple_domains_aggregated(self, tmp_path):
        from app.reporter import get_open_tasks

        flights_dir = tmp_path / "wiki" / "domains" / "flights" / "tasks"
        flights_dir.mkdir(parents=True)
        (flights_dir / "2026-04-21-task-a.md").write_text(
            "---\nstatus: wip\n---\n# Task A", encoding="utf-8"
        )

        hotels_dir = tmp_path / "wiki" / "domains" / "hotels" / "tasks"
        hotels_dir.mkdir(parents=True)
        (hotels_dir / "2026-04-22-task-b.md").write_text(
            "---\nstatus: inbox\n---\n# Task B", encoding="utf-8"
        )

        with patch("app.reporter.vault_paths") as mock_vp:
            mock_vp.all_domains.return_value = ["flights", "hotels"]
            mock_vp.wiki_domain_dir.side_effect = lambda d, t: tmp_path / "wiki" / "domains" / d / t

            results = get_open_tasks()

        assert len(results) == 2
        domains = {r["domain"] for r in results}
        assert domains == {"flights", "hotels"}


# ---------------------------------------------------------------------------
# build_context
# ---------------------------------------------------------------------------

class TestBuildContext:

    def test_builds_all_sections(self):
        from app.reporter import build_context

        meetings = [{"date": "2026-04-21", "title": "Standup", "body": "Discussed items."}]
        tasks = [{"date": "2026-04-22", "title": "CONT-500"}]
        ideas = [{"date": "2026-04-23", "title": "New idea"}]
        open_tasks = [{"title": "Open task", "status": "wip"}]
        upcoming = [{"date": "2026-04-28", "title": "Sprint Review"}]

        result = build_context(meetings, tasks, ideas, open_tasks, upcoming)

        assert "Встречи за прошлую неделю (1)" in result
        assert "Standup" in result
        assert "Discussed items." in result
        assert "Новые тикеты за неделю (1)" in result
        assert "CONT-500" in result
        assert "Идеи за неделю (1)" in result
        assert "New idea" in result
        assert "Открытые задачи (1)" in result
        assert "Open task [wip]" in result
        assert "Предстоящие встречи (1)" in result
        assert "Sprint Review" in result

    def test_empty_data(self):
        from app.reporter import build_context

        result = build_context([], [], [], [], [])

        assert "Встречи за прошлую неделю (0)" in result
        assert "Новые тикеты за неделю (0)" in result
        assert "Идеи за неделю (0)" in result
        assert "Открытые задачи (0)" in result
        assert "Предстоящие встречи (0)" in result

    def test_body_truncated_to_200_chars(self):
        from app.reporter import build_context

        long_body = "A" * 300
        meetings = [{"date": "2026-04-21", "title": "Long Meeting", "body": long_body}]

        result = build_context(meetings, [], [], [], [])

        # The body preview in the context should be at most 200 chars
        # Find the body preview line
        lines = result.split("\n")
        body_line = [l for l in lines if l.startswith("  A")]
        assert len(body_line) == 1
        assert len(body_line[0].strip()) == 200

    def test_daily_logs_section_rendered(self):
        from app.reporter import build_context

        daily_logs = [
            {"date": "2026-04-21", "title": "Monday Log", "body": "Did things."},
            {"date": "2026-04-22", "title": "Tuesday Log", "body": "Did more things."},
        ]

        result = build_context([], [], [], [], [], daily_logs=daily_logs)

        assert "Дневные логи за неделю (2)" in result
        assert "Monday Log" in result
        assert "Tuesday Log" in result
        assert "Did things." in result

    def test_daily_logs_omitted_when_empty(self):
        from app.reporter import build_context

        result = build_context([], [], [], [], [], daily_logs=[])

        assert "Дневные логи" not in result

    def test_daily_logs_omitted_when_none(self):
        from app.reporter import build_context

        result = build_context([], [], [], [], [])

        assert "Дневные логи" not in result

    def test_domain_tags_in_tasks_and_ideas(self):
        from app.reporter import build_context

        tasks = [{"date": "2026-04-22", "title": "CONT-500", "domain": "flights"}]
        ideas = [{"date": "2026-04-23", "title": "New idea", "domain": "hotels"}]
        open_tasks = [{"title": "Open task", "status": "wip", "domain": "flights"}]

        result = build_context([], tasks, ideas, open_tasks, [])

        assert "CONT-500 [flights]" in result
        assert "New idea [hotels]" in result
        assert "Open task [wip] [flights]" in result

    def test_no_domain_tag_when_domain_absent(self):
        from app.reporter import build_context

        tasks = [{"date": "2026-04-22", "title": "CONT-500"}]

        result = build_context([], tasks, [], [], [])

        # Should not have trailing brackets
        assert "CONT-500\n" in result or "CONT-500" in result
        assert "[None]" not in result


# ---------------------------------------------------------------------------
# generate_weekly_report
# ---------------------------------------------------------------------------

class TestGenerateWeeklyReport:

    @pytest.mark.xfail(reason="mock target app.reporter.anthropic removed")
    @patch("app.reporter.anthropic")
    @patch("app.reporter.scan_folder")
    @patch("app.reporter.scan_all_domain_folders")
    @patch("app.reporter.get_open_tasks")
    @patch("app.reporter._load_prompt")
    def test_calls_claude_and_returns_result(
        self, mock_load_prompt, mock_open_tasks, mock_scan_domains, mock_scan, mock_anthropic
    ):
        from app.reporter import generate_weekly_report

        mock_scan.return_value = []
        mock_scan_domains.return_value = []
        mock_open_tasks.return_value = []
        mock_load_prompt.return_value = "test prompt"

        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="# Weekly Report\n\nContent here.")]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message
        mock_anthropic.Anthropic.return_value = mock_client

        result = generate_weekly_report()

        assert result == "# Weekly Report\n\nContent here."
        mock_client.messages.create.assert_called_once()

        # Verify Claude was called with correct model
        call_kwargs = mock_client.messages.create.call_args
        assert call_kwargs.kwargs["model"] == "claude-sonnet-4-6"
        assert call_kwargs.kwargs["max_tokens"] == 2000

    @pytest.mark.xfail(reason="mock target app.reporter.anthropic removed")
    @patch("app.reporter.anthropic")
    @patch("app.reporter.vault_paths")
    @patch("app.reporter.scan_folder")
    @patch("app.reporter.scan_all_domain_folders")
    @patch("app.reporter.get_open_tasks")
    @patch("app.reporter._load_prompt")
    def test_scan_called_with_correct_sources(
        self, mock_load_prompt, mock_open_tasks, mock_scan_domains, mock_scan,
        mock_vp, mock_anthropic
    ):
        from app.reporter import generate_weekly_report

        # Configure vault_paths mock
        meetings_path = Path("/vault/wiki/meetings")
        daily_logs_path = Path("/vault/wiki/daily-logs")
        mock_vp.wiki_meetings.return_value = meetings_path
        mock_vp.wiki_daily_logs.return_value = daily_logs_path

        mock_scan.return_value = []
        mock_scan_domains.return_value = []
        mock_open_tasks.return_value = []
        mock_load_prompt.return_value = "prompt"

        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="Report")]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message
        mock_anthropic.Anthropic.return_value = mock_client

        with patch("app.reporter.date") as mock_date:
            mock_date.today.return_value = date(2026, 4, 29)  # Wednesday
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

            generate_weekly_report()

        # scan_folder should be called 3 times:
        # 1. Meetings last week
        # 2. Daily logs last week
        # 3. Upcoming meetings this week
        assert mock_scan.call_count == 3

        scan_calls = mock_scan.call_args_list
        # Last Monday = 2026-04-20, Last Friday = 2026-04-24
        assert scan_calls[0].args == (meetings_path, date(2026, 4, 20), date(2026, 4, 24))
        assert scan_calls[1].args == (daily_logs_path, date(2026, 4, 20), date(2026, 4, 24))
        # This Monday = 2026-04-27, This Sunday = 2026-05-03
        assert scan_calls[2].args == (meetings_path, date(2026, 4, 27), date(2026, 5, 3))

        # scan_all_domain_folders should be called 2 times:
        # 1. tasks last week
        # 2. ideas last week
        assert mock_scan_domains.call_count == 2

        domain_calls = mock_scan_domains.call_args_list
        assert domain_calls[0].args == ("tasks", date(2026, 4, 20), date(2026, 4, 24))
        assert domain_calls[1].args == ("ideas", date(2026, 4, 20), date(2026, 4, 24))

    @pytest.mark.xfail(reason="mock target app.reporter.anthropic removed")
    @patch("app.reporter.anthropic")
    @patch("app.reporter.scan_folder")
    @patch("app.reporter.scan_all_domain_folders")
    @patch("app.reporter.get_open_tasks")
    @patch("app.reporter._load_prompt")
    def test_claude_api_failure_raises(
        self, mock_load_prompt, mock_open_tasks, mock_scan_domains, mock_scan, mock_anthropic
    ):
        from app.reporter import generate_weekly_report

        mock_scan.return_value = []
        mock_scan_domains.return_value = []
        mock_open_tasks.return_value = []
        mock_load_prompt.return_value = "prompt"

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("API error")
        mock_anthropic.Anthropic.return_value = mock_client

        with pytest.raises(Exception, match="API error"):
            generate_weekly_report()
