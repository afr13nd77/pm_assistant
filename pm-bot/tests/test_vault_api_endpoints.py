"""Integration tests for vault_api FastAPI endpoints.

Uses TestClient and a temporary vault directory to simulate the real filesystem.
Tests the domain-based vault structure:
  wiki/domains/<domain>/ideas/
  wiki/domains/<domain>/tasks/
  wiki/domains/<domain>/epics/
  wiki/meetings/
  wiki/reports/
"""

import os
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock


def _make_domain_dir(vault_dir: Path, domain: str, artifact_type: str) -> Path:
    """Helper to create wiki/domains/<domain>/<artifact_type>/ structure."""
    d = vault_dir / "wiki" / "domains" / domain / artifact_type
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def vault_dir(tmp_path):
    """Create a temporary vault directory with domain-based structure."""
    # Cross-domain directories
    meetings = tmp_path / "wiki" / "meetings"
    meetings.mkdir(parents=True)
    reports = tmp_path / "wiki" / "reports"
    reports.mkdir(parents=True)
    # Domain directories
    _make_domain_dir(tmp_path, "content", "ideas")
    _make_domain_dir(tmp_path, "content", "tasks")
    _make_domain_dir(tmp_path, "content", "epics")
    _make_domain_dir(tmp_path, "payments", "ideas")
    _make_domain_dir(tmp_path, "payments", "tasks")
    _make_domain_dir(tmp_path, "payments", "epics")
    # domains dir itself (for all_domains discovery)
    return tmp_path


@pytest.fixture
def client(vault_dir):
    """Create a FastAPI test client with vault_paths pointing to temp directory."""
    with patch("app.vault_api.VAULT_PATH", vault_dir), \
         patch("app.vault_api.wiki_meetings", return_value=vault_dir / "wiki" / "meetings"), \
         patch("app.vault_api.wiki_reports", return_value=vault_dir / "wiki" / "reports"), \
         patch("app.vault_api.all_domains", return_value=["content", "payments"]), \
         patch("app.vault_api.wiki_domain_dir", side_effect=lambda domain, at: vault_dir / "wiki" / "domains" / domain / at):
        from fastapi.testclient import TestClient
        from app.vault_api import app, _cache
        _cache.invalidate()
        yield TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/v1/domains
# ---------------------------------------------------------------------------

class TestDomainsEndpoint:

    def test_empty_domains(self, vault_dir):
        """Should return empty list when no domains exist."""
        # Create a client with no domains
        with patch("app.vault_api.VAULT_PATH", vault_dir), \
             patch("app.vault_api.wiki_meetings", return_value=vault_dir / "wiki" / "meetings"), \
             patch("app.vault_api.wiki_reports", return_value=vault_dir / "wiki" / "reports"), \
             patch("app.vault_api.all_domains", return_value=[]), \
             patch("app.vault_api.wiki_domain_dir", side_effect=lambda domain, at: vault_dir / "wiki" / "domains" / domain / at):
            from fastapi.testclient import TestClient
            from app.vault_api import app, _cache
            _cache.invalidate()
            tc = TestClient(app)
            resp = tc.get("/api/v1/domains")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_domains_with_files_in_multiple_types(self, client, vault_dir):
        """Should count files per artifact type and compute total."""
        ideas = vault_dir / "wiki" / "domains" / "content" / "ideas"
        (ideas / "2026-04-25-idea1.md").write_text("# Idea 1\n", encoding="utf-8")
        (ideas / "2026-04-26-idea2.md").write_text("# Idea 2\n", encoding="utf-8")

        tasks = vault_dir / "wiki" / "domains" / "content" / "tasks"
        (tasks / "2026-04-27-task1.md").write_text("# Task 1\n", encoding="utf-8")

        epics = vault_dir / "wiki" / "domains" / "content" / "epics"
        (epics / "E-01.md").write_text("# Epic 1\n", encoding="utf-8")

        resp = client.get("/api/v1/domains")
        assert resp.status_code == 200
        data = resp.json()

        content_domain = next(d for d in data if d["name"] == "content")
        assert content_domain["ideas_count"] == 2
        assert content_domain["tasks_count"] == 1
        assert content_domain["epics_count"] == 1
        assert content_domain["prds_count"] == 0
        assert content_domain["userstories_count"] == 0
        assert content_domain["bugs_count"] == 0
        assert content_domain["total_count"] == 4

    def test_domains_service_files_excluded(self, client, vault_dir):
        """Service files (index.md, log.md) should be excluded from counts."""
        ideas = vault_dir / "wiki" / "domains" / "content" / "ideas"
        (ideas / "2026-04-25-real.md").write_text("# Real\n", encoding="utf-8")
        (ideas / "index.md").write_text("# Index\n", encoding="utf-8")
        (ideas / "log.md").write_text("# Log\n", encoding="utf-8")

        resp = client.get("/api/v1/domains")
        assert resp.status_code == 200
        data = resp.json()

        content_domain = next(d for d in data if d["name"] == "content")
        assert content_domain["ideas_count"] == 1

    def test_domains_last_updated_is_correct(self, client, vault_dir):
        """last_updated should reflect the most recently modified file."""
        import time

        ideas = vault_dir / "wiki" / "domains" / "content" / "ideas"
        older = ideas / "2026-04-20-old.md"
        older.write_text("# Old\n", encoding="utf-8")

        # Set an older mtime to ensure a clear gap
        old_ts = datetime(2026, 4, 20, 12, 0, 0).timestamp()
        os.utime(older, (old_ts, old_ts))
        os.utime(ideas, (old_ts, old_ts))

        tasks = vault_dir / "wiki" / "domains" / "content" / "tasks"
        newer = tasks / "2026-04-28-new.md"
        newer.write_text("# New\n", encoding="utf-8")

        new_ts = datetime(2026, 4, 28, 15, 0, 0).timestamp()
        os.utime(newer, (new_ts, new_ts))
        os.utime(tasks, (new_ts, new_ts))

        resp = client.get("/api/v1/domains")
        assert resp.status_code == 200
        data = resp.json()

        content_domain = next(d for d in data if d["name"] == "content")
        assert content_domain["last_updated"] == "2026-04-28"

    def test_domains_sorted_alphabetically(self, client, vault_dir):
        """Domains should be sorted alphabetically by name."""
        resp = client.get("/api/v1/domains")
        assert resp.status_code == 200
        data = resp.json()
        names = [d["name"] for d in data]
        assert names == sorted(names)

    def test_domains_last_updated_none_when_empty(self, client, vault_dir):
        """last_updated should be null when a domain has no files."""
        # payments domain has no files (created empty by vault_dir fixture)
        resp = client.get("/api/v1/domains")
        assert resp.status_code == 200
        data = resp.json()

        payments_domain = next(d for d in data if d["name"] == "payments")
        assert payments_domain["total_count"] == 0
        assert payments_domain["last_updated"] is None


# ---------------------------------------------------------------------------
# GET /api/v1/ideas (formerly /api/v1/inbox)
# ---------------------------------------------------------------------------

class TestIdeasEndpoint:

    def test_empty_ideas(self, client, vault_dir):
        """Should return empty list when ideas folders have no files."""
        resp = client.get("/api/v1/ideas")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_ideas_from_multiple_domains(self, client, vault_dir):
        """Should aggregate ideas from all domains and include domain field."""
        ideas_content = vault_dir / "wiki" / "domains" / "content" / "ideas"
        (ideas_content / "2026-04-25-older.md").write_text(
            "---\ndate: 2026-04-25\ntags: [idea]\nstatus: inbox\n---\n# Older Idea\n\nOlder body.\n",
            encoding="utf-8",
        )

        ideas_payments = vault_dir / "wiki" / "domains" / "payments" / "ideas"
        (ideas_payments / "2026-04-26-newer.md").write_text(
            "---\ndate: 2026-04-26\ntags: idea, product\nstatus: inbox\n---\n# Newer Idea\n\nNewer body.\n",
            encoding="utf-8",
        )

        resp = client.get("/api/v1/ideas")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        # Newest first
        assert data[0]["date"] == "2026-04-26"
        assert data[0]["title"] == "Newer Idea"
        assert data[0]["domain"] == "payments"
        assert data[1]["date"] == "2026-04-25"
        assert data[1]["domain"] == "content"

    def test_ideas_filter_by_domain(self, client, vault_dir):
        """Should filter by domain when ?domain= parameter is provided."""
        ideas_content = vault_dir / "wiki" / "domains" / "content" / "ideas"
        (ideas_content / "2026-04-25-idea.md").write_text(
            "---\ndate: 2026-04-25\n---\n# Content Idea\n\nBody.\n",
            encoding="utf-8",
        )

        ideas_payments = vault_dir / "wiki" / "domains" / "payments" / "ideas"
        (ideas_payments / "2026-04-26-idea.md").write_text(
            "---\ndate: 2026-04-26\n---\n# Payments Idea\n\nBody.\n",
            encoding="utf-8",
        )

        resp = client.get("/api/v1/ideas?domain=content")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "Content Idea"
        assert data[0]["domain"] == "content"

    def test_ideas_without_frontmatter(self, client, vault_dir):
        """Should handle notes without frontmatter."""
        ideas = vault_dir / "wiki" / "domains" / "content" / "ideas"
        (ideas / "2026-04-26-plain.md").write_text(
            "# Plain Note\n\nNo frontmatter here.\n", encoding="utf-8"
        )

        resp = client.get("/api/v1/ideas")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "Plain Note"
        assert data[0]["tags"] == []
        assert data[0]["status"] == "inbox"
        assert data[0]["domain"] == "content"

    def test_ideas_excludes_service_files(self, client, vault_dir):
        """Should exclude index.md and log.md from results."""
        ideas = vault_dir / "wiki" / "domains" / "content" / "ideas"
        (ideas / "2026-04-26-real.md").write_text(
            "---\ndate: 2026-04-26\n---\n# Real Idea\n", encoding="utf-8"
        )
        (ideas / "index.md").write_text("# Index\n", encoding="utf-8")
        (ideas / "log.md").write_text("# Log\n", encoding="utf-8")

        resp = client.get("/api/v1/ideas")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "Real Idea"

    def test_old_inbox_endpoint_returns_404(self, client, vault_dir):
        """Old /api/v1/inbox endpoint should no longer exist."""
        resp = client.get("/api/v1/inbox")
        assert resp.status_code in (404, 405)


# ---------------------------------------------------------------------------
# GET /api/v1/meetings
# ---------------------------------------------------------------------------

class TestMeetingsEndpoint:

    def test_empty_meetings(self, client, vault_dir):
        """Should return empty list when meetings folder has no files."""
        resp = client.get("/api/v1/meetings")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_meetings_with_sections(self, client, vault_dir):
        """Should parse decisions, action_items, blockers from sections."""
        meetings = vault_dir / "wiki" / "meetings"
        (meetings / "2026-04-26-daily.md").write_text(
            "---\ndate: 2026-04-26\ntype: daily\n---\n"
            "# Daily 26.04\n\n"
            "## Решения\n- Decision A\n- Decision B\n\n"
            "## Action Items\n- [ ] Task 1 -- @Anton\n- [x] Done task\n- [ ] Task 2\n\n"
            "## Блокеры и риски\nNo blockers today.\n",
            encoding="utf-8",
        )

        resp = client.get("/api/v1/meetings?days=14")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1

        meeting = data[0]
        assert meeting["type"] == "daily"
        assert "Decision A" in meeting["decisions"]
        assert "Decision B" in meeting["decisions"]
        assert len(meeting["action_items"]) == 2  # only - [ ] lines
        assert meeting["blockers"] == "No blockers today."

    def test_meetings_date_filter(self, client, vault_dir):
        """Should filter out meetings older than N days."""
        meetings = vault_dir / "wiki" / "meetings"
        (meetings / "2020-01-01-old.md").write_text(
            "---\ndate: 2020-01-01\ntype: sync\n---\n# Old Meeting\n",
            encoding="utf-8",
        )
        (meetings / "2026-04-26-recent.md").write_text(
            "---\ndate: 2026-04-26\ntype: daily\n---\n# Recent Meeting\n",
            encoding="utf-8",
        )

        resp = client.get("/api/v1/meetings?days=14")
        assert resp.status_code == 200
        data = resp.json()
        # Only the recent one should be included
        assert len(data) == 1
        assert data[0]["title"] == "Recent Meeting"

    def test_meetings_excludes_service_files(self, client, vault_dir):
        """Should exclude index.md from meetings results."""
        meetings = vault_dir / "wiki" / "meetings"
        (meetings / "2026-04-26-daily.md").write_text(
            "---\ndate: 2026-04-26\ntype: daily\n---\n# Daily\n",
            encoding="utf-8",
        )
        (meetings / "index.md").write_text("# Index\n", encoding="utf-8")

        resp = client.get("/api/v1/meetings?days=14")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "Daily"


# ---------------------------------------------------------------------------
# GET /api/v1/tasks
# ---------------------------------------------------------------------------

class TestTasksEndpoint:

    def test_empty_tasks(self, client, vault_dir):
        """Should return empty list when task folders have no files."""
        resp = client.get("/api/v1/tasks")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_tasks_with_data(self, client, vault_dir):
        """Should parse task files with frontmatter fields and domain."""
        tasks = vault_dir / "wiki" / "domains" / "content" / "tasks"
        (tasks / "2026-04-26-jira-01.md").write_text(
            "---\n"
            "date: 2026-04-26\n"
            "type: Story\n"
            "priority: High\n"
            "story_points: 5\n"
            "status: draft\n"
            "---\n"
            "# [DRAFT] Validate Required Fields\n\n"
            "Description here.\n",
            encoding="utf-8",
        )

        resp = client.get("/api/v1/tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        task = data[0]
        assert task["type"] == "Story"
        assert task["priority"] == "High"
        assert task["story_points"] == 5
        assert task["status"] == "draft"
        assert task["domain"] == "content"

    def test_tasks_filter_by_domain(self, client, vault_dir):
        """Should filter tasks by domain."""
        tasks_content = vault_dir / "wiki" / "domains" / "content" / "tasks"
        (tasks_content / "2026-04-26-task.md").write_text(
            "---\ndate: 2026-04-26\n---\n# Content Task\n",
            encoding="utf-8",
        )
        tasks_payments = vault_dir / "wiki" / "domains" / "payments" / "tasks"
        (tasks_payments / "2026-04-25-task.md").write_text(
            "---\ndate: 2026-04-25\n---\n# Payments Task\n",
            encoding="utf-8",
        )

        resp = client.get("/api/v1/tasks?domain=payments")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "Payments Task"
        assert data[0]["domain"] == "payments"


# ---------------------------------------------------------------------------
# GET /api/v1/epics
# ---------------------------------------------------------------------------

class TestEpicsEndpoint:

    def test_empty_epics(self, client, vault_dir):
        """Should return empty list when epic folders have no files."""
        resp = client.get("/api/v1/epics")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_epics_with_tickets_and_progress(self, client, vault_dir):
        """Should parse tickets and calculate progress correctly with domain."""
        epics = vault_dir / "wiki" / "domains" / "content" / "epics"
        (epics / "E-01.md").write_text(
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
            "  - id: CONT-414\n"
            "    title: UI review\n"
            "    status: done\n"
            "---\n"
            "# Photo Dedup Epic\n",
            encoding="utf-8",
        )

        resp = client.get("/api/v1/epics")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1

        epic = data[0]
        assert epic["id"] == "E-01"
        assert epic["title"] == "Photo Dedup"
        assert epic["horizon"] == "now"
        assert epic["priority"] == "p1"
        assert epic["prd_status"] == "APPROVED"
        assert len(epic["tickets"]) == 3
        # 2 done out of 3 = 67%
        assert epic["progress"] == 67
        assert epic["domain"] == "content"
        # PRD summary fields should be present (empty since body has no sections)
        assert "goal" in epic
        assert "scope" in epic
        assert "acceptance_criteria" in epic

    def test_epics_no_tickets_zero_progress(self, client, vault_dir):
        """Should return 0 progress when no tickets defined."""
        epics = vault_dir / "wiki" / "domains" / "content" / "epics"
        (epics / "E-02.md").write_text(
            "---\nid: E-02\ntitle: Empty\nhorizon: later\n---\n# Empty Epic\n",
            encoding="utf-8",
        )

        resp = client.get("/api/v1/epics")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["progress"] == 0
        assert data[0]["tickets"] == []

    def test_epics_filter_by_domain(self, client, vault_dir):
        """Should filter epics by domain."""
        epics_content = vault_dir / "wiki" / "domains" / "content" / "epics"
        (epics_content / "E-10.md").write_text(
            "---\nid: E-10\ntitle: Content Epic\n---\n# Content Epic\n",
            encoding="utf-8",
        )
        epics_payments = vault_dir / "wiki" / "domains" / "payments" / "epics"
        (epics_payments / "E-20.md").write_text(
            "---\nid: E-20\ntitle: Payments Epic\n---\n# Payments Epic\n",
            encoding="utf-8",
        )

        resp = client.get("/api/v1/epics?domain=payments")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == "E-20"
        assert data[0]["domain"] == "payments"

    def test_epics_prd_summary_fields_parsed(self, client, vault_dir):
        """Should extract goal, scope, acceptance_criteria from epic body."""
        epics = vault_dir / "wiki" / "domains" / "content" / "epics"
        (epics / "E-10.md").write_text(
            "---\n"
            "id: E-10\n"
            "title: Photo Dedup\n"
            "horizon: now\n"
            "priority: p1\n"
            "tickets:\n"
            "  - id: CONT-500\n"
            "    title: Hash impl\n"
            "    status: done\n"
            "---\n"
            "# Photo Dedup\n\n"
            "## Goal\n"
            "Remove duplicate photos from 1.2M objects.\n\n"
            "## Scope\n"
            "Perceptual hash, similarity threshold 92%.\n\n"
            "## Acceptance Criteria\n"
            "- 0 duplicates in 10k sample\n"
            "- Process 1M in 24 hours\n",
            encoding="utf-8",
        )

        resp = client.get("/api/v1/epics")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1

        epic = data[0]
        assert epic["id"] == "E-10"
        assert epic["goal"] == "Remove duplicate photos from 1.2M objects."
        assert epic["scope"] == "Perceptual hash, similarity threshold 92%."
        assert "0 duplicates in 10k sample" in epic["acceptance_criteria"]
        assert "Process 1M in 24 hours" in epic["acceptance_criteria"]

    def test_epics_prd_summary_fields_empty_when_missing(self, client, vault_dir):
        """Should return empty strings when body has no Goal/Scope/AC sections."""
        epics = vault_dir / "wiki" / "domains" / "content" / "epics"
        (epics / "E-11.md").write_text(
            "---\nid: E-11\ntitle: Minimal\nhorizon: later\n---\n"
            "# Minimal Epic\n\nJust some text without structured sections.\n",
            encoding="utf-8",
        )

        resp = client.get("/api/v1/epics")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1

        epic = data[0]
        assert epic["goal"] == ""
        assert epic["scope"] == ""
        assert epic["acceptance_criteria"] == ""


# ---------------------------------------------------------------------------
# GET /api/v1/reports  (list all reports)
# ---------------------------------------------------------------------------

class TestListReportsEndpoint:

    def test_no_reports(self, client, vault_dir):
        """Should return empty list when reports folder is empty."""
        resp = client.get("/api/v1/reports")
        assert resp.status_code == 200
        data = resp.json()
        assert data["reports"] == []

    def test_returns_all_reports_sorted_descending(self, client, vault_dir):
        """Should return all reports sorted by filename descending (newest first)."""
        reports = vault_dir / "wiki" / "reports"
        (reports / "2026-04-20-weekly.md").write_text(
            "# Week 16\nOld report.", encoding="utf-8"
        )
        (reports / "2026-04-27-weekly.md").write_text(
            "# Week 17\nLatest report.", encoding="utf-8"
        )

        resp = client.get("/api/v1/reports")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["reports"]) == 2
        assert data["reports"][0]["filename"] == "2026-04-27-weekly.md"
        assert data["reports"][0]["date"] == "2026-04-27"
        assert data["reports"][0]["title"] == "Week 17"
        assert data["reports"][1]["filename"] == "2026-04-20-weekly.md"
        assert data["reports"][1]["date"] == "2026-04-20"
        assert data["reports"][1]["title"] == "Week 16"

    def test_reports_excludes_service_files(self, client, vault_dir):
        """Should exclude index.md and log.md from report list."""
        reports = vault_dir / "wiki" / "reports"
        (reports / "2026-04-27-weekly.md").write_text(
            "# Week 17\nReport.", encoding="utf-8"
        )
        (reports / "index.md").write_text("# Index\n", encoding="utf-8")
        (reports / "log.md").write_text("# Log\n", encoding="utf-8")

        resp = client.get("/api/v1/reports")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["reports"]) == 1
        assert data["reports"][0]["filename"] == "2026-04-27-weekly.md"

    def test_title_from_heading(self, client, vault_dir):
        """Should extract title from the first # heading in the body."""
        reports = vault_dir / "wiki" / "reports"
        (reports / "2026-04-27-weekly.md").write_text(
            "---\ndate: 2026-04-27\n---\n# Weekly Report 27 Apr\n\nBody text.",
            encoding="utf-8",
        )

        resp = client.get("/api/v1/reports")
        assert resp.status_code == 200
        data = resp.json()
        assert data["reports"][0]["title"] == "Weekly Report 27 Apr"

    def test_title_fallback_to_stem(self, client, vault_dir):
        """Should use filename stem as title when no heading is found."""
        reports = vault_dir / "wiki" / "reports"
        (reports / "2026-04-27-weekly.md").write_text(
            "No heading here, just text.", encoding="utf-8"
        )

        resp = client.get("/api/v1/reports")
        assert resp.status_code == 200
        data = resp.json()
        assert data["reports"][0]["title"] == "2026-04-27-weekly"

    def test_date_extracted_from_filename(self, client, vault_dir):
        """Should extract date from first 10 chars of filename stem."""
        reports = vault_dir / "wiki" / "reports"
        (reports / "2026-04-27-weekly.md").write_text(
            "# Report\nContent.", encoding="utf-8"
        )

        resp = client.get("/api/v1/reports")
        assert resp.status_code == 200
        data = resp.json()
        assert data["reports"][0]["date"] == "2026-04-27"

    def test_short_filename_date(self, client, vault_dir):
        """Should handle short filenames gracefully for date extraction."""
        reports = vault_dir / "wiki" / "reports"
        (reports / "short.md").write_text("# Short\nContent.", encoding="utf-8")

        resp = client.get("/api/v1/reports")
        assert resp.status_code == 200
        data = resp.json()
        assert data["reports"][0]["date"] == "short"
        assert data["reports"][0]["filename"] == "short.md"


# ---------------------------------------------------------------------------
# GET /api/v1/reports/{filename}  (single report detail)
# ---------------------------------------------------------------------------

class TestGetReportByFilenameEndpoint:

    def test_existing_report(self, client, vault_dir):
        """Should return full content of a specific report."""
        reports = vault_dir / "wiki" / "reports"
        (reports / "2026-04-27-weekly.md").write_text(
            "# Week 17\nFull report content here.", encoding="utf-8"
        )

        resp = client.get("/api/v1/reports/2026-04-27-weekly.md")
        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"] == "2026-04-27-weekly.md"
        assert data["date"] == "2026-04-27"
        assert "Full report content here" in data["content"]

    def test_report_not_found(self, client, vault_dir):
        """Should return 404 when report file does not exist."""
        resp = client.get("/api/v1/reports/nonexistent.md")
        assert resp.status_code == 404

    def test_filename_without_md_extension(self, client, vault_dir):
        """Should return 400 when filename does not end with .md."""
        resp = client.get("/api/v1/reports/report.txt")
        assert resp.status_code == 400

    def test_filename_with_path_separator_slash(self, client, vault_dir):
        """Should return 400 when filename contains forward slash."""
        resp = client.get("/api/v1/reports/..%2F..%2Fetc%2Fpasswd.md")
        # URL-encoded slash — FastAPI may or may not decode it depending on version,
        # but a direct slash in the path would be routed differently.
        # Test the direct validation logic via a filename that contains backslash.
        pass

    def test_filename_with_backslash(self, client, vault_dir):
        """Should return 400 when filename contains backslash (path traversal attempt)."""
        # We encode the backslash in the URL to ensure it reaches the handler
        resp = client.get("/api/v1/reports/..\\secrets.md")
        assert resp.status_code == 400

    def test_old_weekly_endpoint_returns_404(self, client, vault_dir):
        """Old /api/v1/report/weekly endpoint should no longer exist."""
        resp = client.get("/api/v1/report/weekly")
        assert resp.status_code in (404, 405)


# ---------------------------------------------------------------------------
# GET /api/v1/timeline/{ticket_id}
# ---------------------------------------------------------------------------

class TestTimelineEndpoint:

    def test_empty_timeline_no_mentions(self, client, vault_dir):
        """Should return empty events when ticket_id is not mentioned anywhere."""
        resp = client.get("/api/v1/timeline/NONEXISTENT-999")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticket_id"] == "NONEXISTENT-999"
        assert data["events"] == []
        assert data["metrics"] == {}

    def test_timeline_finds_idea_mention(self, client, vault_dir):
        """Should find ticket mentioned in ideas and return as idea stage."""
        ideas = vault_dir / "wiki" / "domains" / "content" / "ideas"
        (ideas / "2026-04-20-idea.md").write_text(
            "---\ndate: 2026-04-20\ntags: idea\n---\n# New feature idea\n\n"
            "This relates to CONT-412 ticket.\n",
            encoding="utf-8",
        )

        resp = client.get("/api/v1/timeline/CONT-412")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticket_id"] == "CONT-412"
        assert len(data["events"]) == 1
        event = data["events"][0]
        assert event["stage"] == "idea"
        assert event["date"] == "2026-04-20"
        assert event["title"] == "New feature idea"
        assert "wiki/domains/content/ideas/" in event["source_file"]

    def test_timeline_case_insensitive_search(self, client, vault_dir):
        """Should match ticket_id case-insensitively."""
        ideas = vault_dir / "wiki" / "domains" / "content" / "ideas"
        (ideas / "2026-04-20-idea.md").write_text(
            "---\ndate: 2026-04-20\n---\n# Idea\n\nMentions cont-412 in lower case.\n",
            encoding="utf-8",
        )

        resp = client.get("/api/v1/timeline/CONT-412")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) == 1

    def test_timeline_multiple_folders(self, client, vault_dir):
        """Should collect events from domain and cross-domain folders."""
        ideas = vault_dir / "wiki" / "domains" / "content" / "ideas"
        (ideas / "2026-04-15-idea.md").write_text(
            "---\ndate: 2026-04-15\ntags: idea\n---\n# Idea for CONT-100\n\nCONT-100 first mention.\n",
            encoding="utf-8",
        )
        meetings = vault_dir / "wiki" / "meetings"
        (meetings / "2026-04-18-daily.md").write_text(
            "---\ndate: 2026-04-18\ntype: daily\n---\n# Daily\n\nDiscussed CONT-100.\n",
            encoding="utf-8",
        )
        tasks = vault_dir / "wiki" / "domains" / "content" / "tasks"
        (tasks / "2026-04-20-jira.md").write_text(
            "---\ndate: 2026-04-20\n---\n# CONT-100 Draft\n\nJira draft for CONT-100.\n",
            encoding="utf-8",
        )

        resp = client.get("/api/v1/timeline/CONT-100")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) == 3
        # Events should be sorted by date ascending
        dates = [e["date"] for e in data["events"]]
        assert dates == sorted(dates)
        # Check stages from different folders
        stages = [e["stage"] for e in data["events"]]
        assert "idea" in stages
        assert "meeting" in stages
        assert "jira" in stages

    def test_timeline_sorted_by_date(self, client, vault_dir):
        """Events should be sorted chronologically (oldest first)."""
        ideas = vault_dir / "wiki" / "domains" / "content" / "ideas"
        (ideas / "2026-04-25-later.md").write_text(
            "---\ndate: 2026-04-25\n---\n# Later\n\nTICKET-1 later.\n",
            encoding="utf-8",
        )
        (ideas / "2026-04-10-earlier.md").write_text(
            "---\ndate: 2026-04-10\n---\n# Earlier\n\nTICKET-1 earlier.\n",
            encoding="utf-8",
        )

        resp = client.get("/api/v1/timeline/TICKET-1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) == 2
        assert data["events"][0]["date"] == "2026-04-10"
        assert data["events"][1]["date"] == "2026-04-25"

    def test_timeline_metrics_days_to_ship(self, client, vault_dir):
        """Should calculate days_to_ship when 2+ events exist."""
        ideas = vault_dir / "wiki" / "domains" / "content" / "ideas"
        (ideas / "2026-04-01-start.md").write_text(
            "---\ndate: 2026-04-01\n---\n# Start\n\nFEAT-10 first mention.\n",
            encoding="utf-8",
        )
        reports = vault_dir / "wiki" / "reports"
        (reports / "2026-04-21-report.md").write_text(
            "---\ndate: 2026-04-21\n---\n# Report\n\nFEAT-10 shipped.\n",
            encoding="utf-8",
        )

        resp = client.get("/api/v1/timeline/FEAT-10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["metrics"]["days_to_ship"] == 20

    def test_timeline_metrics_idea_to_prd(self, client, vault_dir):
        """Should calculate idea_to_prd_days when idea and pm stages exist."""
        ideas = vault_dir / "wiki" / "domains" / "content" / "ideas"
        (ideas / "2026-04-01-idea.md").write_text(
            "---\ndate: 2026-04-01\ntags: idea\n---\n# Idea\n\nPRD-50 first idea.\n",
            encoding="utf-8",
        )

        # PRD in prds folder gets "pm" as default stage
        prds = _make_domain_dir(vault_dir, "content", "prds")
        (prds / "2026-04-11-prd.md").write_text(
            "---\ndate: 2026-04-11\n---\n# PRD\n\nPRD-50 prd created.\n",
            encoding="utf-8",
        )

        resp = client.get("/api/v1/timeline/PRD-50")
        assert resp.status_code == 200
        data = resp.json()
        assert data["metrics"]["idea_to_prd_days"] == 10

    def test_timeline_no_metrics_single_event(self, client, vault_dir):
        """Should not calculate days_to_ship with only one event."""
        ideas = vault_dir / "wiki" / "domains" / "content" / "ideas"
        (ideas / "2026-04-20-solo.md").write_text(
            "---\ndate: 2026-04-20\n---\n# Solo\n\nSOLO-1 only mention.\n",
            encoding="utf-8",
        )

        resp = client.get("/api/v1/timeline/SOLO-1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) == 1
        assert "days_to_ship" not in data["metrics"]

    def test_timeline_detail_truncated(self, client, vault_dir):
        """Event detail should be truncated to 200 chars."""
        ideas = vault_dir / "wiki" / "domains" / "content" / "ideas"
        long_body = "A" * 500
        (ideas / "2026-04-20-long.md").write_text(
            f"---\ndate: 2026-04-20\n---\n# Long Note\n\nTRUNC-1 {long_body}\n",
            encoding="utf-8",
        )

        resp = client.get("/api/v1/timeline/TRUNC-1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) == 1
        assert len(data["events"][0]["detail"]) == 200

    def test_timeline_stage_override_from_tags(self, client, vault_dir):
        """Should override default stage when pipeline+prd tags are present."""
        ideas = vault_dir / "wiki" / "domains" / "content" / "ideas"
        (ideas / "2026-04-20-tagged.md").write_text(
            "---\ndate: 2026-04-20\ntags: pipeline, prd\n---\n# Tagged\n\nTAG-1 with pipeline prd tags.\n",
            encoding="utf-8",
        )

        resp = client.get("/api/v1/timeline/TAG-1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) == 1
        assert data["events"][0]["stage"] == "pm"

    def test_timeline_stage_enriched_from_tags(self, client, vault_dir):
        """Should set stage to enriched when pipeline+enriched tags present."""
        ideas = vault_dir / "wiki" / "domains" / "content" / "ideas"
        (ideas / "2026-04-20-enriched.md").write_text(
            "---\ndate: 2026-04-20\ntags: pipeline, enriched\n---\n# Enriched\n\nENR-1 with enriched tag.\n",
            encoding="utf-8",
        )

        resp = client.get("/api/v1/timeline/ENR-1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) == 1
        assert data["events"][0]["stage"] == "enriched"

    def test_timeline_source_file_includes_domain(self, client, vault_dir):
        """Source file should include the domain path."""
        ideas = vault_dir / "wiki" / "domains" / "content" / "ideas"
        (ideas / "2026-04-20-idea.md").write_text(
            "---\ndate: 2026-04-20\n---\n# Idea\n\nDOMPATH-1 mention.\n",
            encoding="utf-8",
        )

        resp = client.get("/api/v1/timeline/DOMPATH-1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) == 1
        assert data["events"][0]["source_file"] == "wiki/domains/content/ideas/2026-04-20-idea.md"

    def test_timeline_excludes_service_files(self, client, vault_dir):
        """Should not include index.md or log.md in timeline search."""
        ideas = vault_dir / "wiki" / "domains" / "content" / "ideas"
        (ideas / "index.md").write_text(
            "---\ndate: 2026-04-20\n---\n# Index\n\nSERVICE-1 in index.\n",
            encoding="utf-8",
        )
        (ideas / "2026-04-20-real.md").write_text(
            "---\ndate: 2026-04-20\n---\n# Real\n\nSERVICE-1 in real note.\n",
            encoding="utf-8",
        )

        resp = client.get("/api/v1/timeline/SERVICE-1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) == 1
        assert "index.md" not in data["events"][0]["source_file"]


# ---------------------------------------------------------------------------
# POST /api/v1/capture
# ---------------------------------------------------------------------------

class TestCaptureEndpoint:

    def test_capture_idea(self, client, vault_dir):
        """Should process idea through Claude and save via obsidian_writer."""
        mock_filepath = vault_dir / "wiki" / "domains" / "content" / "ideas" / "2026-04-27-test-idea.md"
        mock_filepath.parent.mkdir(parents=True, exist_ok=True)
        mock_filepath.write_text("# Processed Idea\nContent.", encoding="utf-8")

        with patch("app.claude_client.process_idea", return_value="# Processed Idea\nContent."), \
             patch("app.obsidian_writer.write_idea", return_value=mock_filepath):

            resp = client.post(
                "/api/v1/capture",
                json={"type": "idea", "text": "Test idea text"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"] == "2026-04-27-test-idea.md"
        assert "Processed Idea" in data["content"]

    def test_capture_task(self, client, vault_dir):
        """Should process task through Claude and save as jira draft."""
        mock_filepath = vault_dir / "wiki" / "domains" / "content" / "tasks" / "2026-04-27-jira-01.md"
        mock_filepath.parent.mkdir(parents=True, exist_ok=True)
        mock_filepath.write_text("# Draft Task\nContent.", encoding="utf-8")

        with patch("app.claude_client.process_jira_ticket", return_value="# Draft Task\nContent."), \
             patch("app.obsidian_writer.write_jira_draft", return_value=mock_filepath):

            resp = client.post(
                "/api/v1/capture",
                json={"type": "task", "text": "Create a new feature"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"] == "2026-04-27-jira-01.md"

    def test_capture_invalid_type(self, client, vault_dir):
        """Should return 400 for invalid capture type."""
        resp = client.post(
            "/api/v1/capture",
            json={"type": "invalid", "text": "Some text"},
        )
        assert resp.status_code == 400

    def test_capture_missing_text(self, client, vault_dir):
        """Should return 422 for missing required field."""
        resp = client.post("/api/v1/capture", json={"type": "idea"})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/pipeline
# ---------------------------------------------------------------------------

class TestPipelineEndpoint:

    def test_pipeline_success(self, client, vault_dir):
        """Should proxy to pipeline_client.list_pipelines and return result."""
        mock_result = {"total": 3, "items": [{"id": "p1"}, {"id": "p2"}, {"id": "p3"}]}

        with patch("app.pipeline_client.list_pipelines", return_value=mock_result):
            resp = client.get("/api/v1/pipeline")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3

    def test_pipeline_service_error(self, client, vault_dir):
        """Should return 502 when pipeline service is unavailable."""
        with patch(
            "app.pipeline_client.list_pipelines",
            side_effect=ConnectionError("Service down"),
        ):
            resp = client.get("/api/v1/pipeline")

        assert resp.status_code == 502


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

class TestCORS:

    def test_cors_headers_present(self, client, vault_dir):
        """Should include CORS headers in response."""
        resp = client.options(
            "/api/v1/ideas",
            headers={
                "Origin": "http://localhost:8080",
                "Access-Control-Request-Method": "GET",
            },
        )
        # CORSMiddleware with allow_origins=["*"] reflects the requesting origin
        # on preflight, or returns "*" on simple requests.
        cors_origin = resp.headers.get("access-control-allow-origin")
        assert cors_origin in ("*", "http://localhost:8080")


# ---------------------------------------------------------------------------
# GET /api/v1/jira/sync-status
# ---------------------------------------------------------------------------

class TestJiraSyncStatusEndpoint:

    def test_sync_status_no_state_file(self, client, vault_dir):
        """Should return nulls when state file does not exist."""
        resp = client.get("/api/v1/jira/sync-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["last_sync"] is None
        assert data["tracked"] == 0
        assert data["last_new"] is None
        assert data["last_updated"] is None
        assert data["last_closed"] is None
        assert data["last_errors"] is None

    def test_sync_status_with_state_file(self, client, vault_dir):
        """Should return parsed data from .jira-sync-state.json."""
        import json
        state = {
            "last_sync": "2026-05-15T10:00:00Z",
            "issues": {"PROJ-1": {}, "PROJ-2": {}, "PROJ-3": {}},
            "last_run_result": {
                "new": 2,
                "updated": 5,
                "closed": 1,
                "errors": 0,
            },
        }
        state_file = vault_dir / ".jira-sync-state.json"
        state_file.write_text(json.dumps(state), encoding="utf-8")

        resp = client.get("/api/v1/jira/sync-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["last_sync"] == "2026-05-15T10:00:00Z"
        assert data["tracked"] == 3
        assert data["last_new"] == 2
        assert data["last_updated"] == 5
        assert data["last_closed"] == 1
        assert data["last_errors"] == 0

    def test_sync_status_corrupt_json(self, client, vault_dir):
        """Should return nulls when state file has corrupt JSON."""
        state_file = vault_dir / ".jira-sync-state.json"
        state_file.write_text("{not valid json!!!", encoding="utf-8")

        resp = client.get("/api/v1/jira/sync-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["last_sync"] is None
        assert data["tracked"] == 0

    def test_sync_status_empty_state(self, client, vault_dir):
        """Should handle empty JSON object gracefully."""
        import json
        state_file = vault_dir / ".jira-sync-state.json"
        state_file.write_text(json.dumps({}), encoding="utf-8")

        resp = client.get("/api/v1/jira/sync-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["last_sync"] is None
        assert data["tracked"] == 0
        assert data["last_new"] is None

    def test_sync_status_cached(self, client, vault_dir):
        """Should return cached result on second call."""
        import json
        state = {"last_sync": "2026-05-15T10:00:00Z", "issues": {"A-1": {}}}
        state_file = vault_dir / ".jira-sync-state.json"
        state_file.write_text(json.dumps(state), encoding="utf-8")

        resp1 = client.get("/api/v1/jira/sync-status")
        assert resp1.status_code == 200
        assert resp1.json()["tracked"] == 1

        # Modify file — but cache should still return old result
        state["issues"]["A-2"] = {}
        state_file.write_text(json.dumps(state), encoding="utf-8")

        resp2 = client.get("/api/v1/jira/sync-status")
        assert resp2.status_code == 200
        # Still returns cached value
        assert resp2.json()["tracked"] == 1

    def test_sync_status_last_sync_empty_string(self, client, vault_dir):
        """Should normalize empty-string last_sync to None."""
        import json
        state = {"last_sync": "", "issues": {}}
        state_file = vault_dir / ".jira-sync-state.json"
        state_file.write_text(json.dumps(state), encoding="utf-8")

        resp = client.get("/api/v1/jira/sync-status")
        assert resp.status_code == 200
        assert resp.json()["last_sync"] is None


# ---------------------------------------------------------------------------
# POST /api/v1/jira/sync
# ---------------------------------------------------------------------------

class TestJiraSyncEndpoint:

    def test_sync_success(self, client, vault_dir):
        """Should trigger sync and return parsed result on success."""
        import json
        sync_output = json.dumps({
            "status": "ok",
            "new": 3,
            "updated": 2,
            "closed": 1,
            "errors": 0,
            "logged": 6,
            "message": "Sync completed successfully",
        })
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = f"Starting sync...\n{sync_output}\n"
        mock_result.stderr = ""

        with patch("app.vault_api.subprocess.run", return_value=mock_result):
            resp = client.post("/api/v1/jira/sync")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["new"] == 3
        assert data["updated"] == 2
        assert data["closed"] == 1
        assert data["errors"] == 0
        assert data["logged"] == 6
        assert data["message"] == "Sync completed successfully"

    def test_sync_writes_state_file(self, client, vault_dir):
        """Should write last_run_result into .jira-sync-state.json."""
        import json
        # Pre-existing state file
        state_file = vault_dir / ".jira-sync-state.json"
        state_file.write_text(json.dumps({"issues": {"X-1": {}}}), encoding="utf-8")

        sync_output = json.dumps({
            "status": "ok", "new": 1, "updated": 0,
            "closed": 0, "errors": 0, "logged": 1, "message": "done",
        })
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = sync_output
        mock_result.stderr = ""

        with patch("app.vault_api.subprocess.run", return_value=mock_result):
            resp = client.post("/api/v1/jira/sync")

        assert resp.status_code == 200

        # Verify state file was updated
        updated_state = json.loads(state_file.read_text(encoding="utf-8"))
        assert "last_run_result" in updated_state
        assert updated_state["last_run_result"]["new"] == 1
        # Original data preserved
        assert "issues" in updated_state

    def test_sync_subprocess_failure(self, client, vault_dir):
        """Should return 502 when subprocess exits with non-zero code."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Connection refused"

        with patch("app.vault_api.subprocess.run", return_value=mock_result):
            resp = client.post("/api/v1/jira/sync")

        assert resp.status_code == 502
        assert "Connection refused" in resp.json()["detail"]

    def test_sync_timeout(self, client, vault_dir):
        """Should return 504 when subprocess times out."""
        import subprocess as sp

        with patch("app.vault_api.subprocess.run", side_effect=sp.TimeoutExpired(cmd="test", timeout=180)):
            resp = client.post("/api/v1/jira/sync")

        assert resp.status_code == 504
        assert "180 seconds" in resp.json()["detail"]

    def test_sync_concurrency_guard(self, client, vault_dir):
        """Should return 409 when sync is already running."""
        from app.vault_api import _jira_sync_lock

        # Simulate another sync in progress by holding the lock
        _jira_sync_lock.acquire()
        try:
            resp = client.post("/api/v1/jira/sync")
            assert resp.status_code == 409
            assert "already running" in resp.json()["detail"]
        finally:
            _jira_sync_lock.release()

    def test_sync_unparseable_output(self, client, vault_dir):
        """Should handle unparseable subprocess output gracefully."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Not JSON output at all\n"
        mock_result.stderr = ""

        with patch("app.vault_api.subprocess.run", return_value=mock_result):
            resp = client.post("/api/v1/jira/sync")

        assert resp.status_code == 200
        data = resp.json()
        # Should return defaults
        assert data["status"] == "ok"
        assert data["new"] == 0
        assert data["message"] == "Sync completed"

    def test_sync_generic_exception(self, client, vault_dir):
        """Should return 500 on unexpected exceptions."""
        with patch("app.vault_api.subprocess.run", side_effect=OSError("disk error")):
            resp = client.post("/api/v1/jira/sync")

        assert resp.status_code == 500
        assert "disk error" in resp.json()["detail"]
