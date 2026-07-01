"""Tests for app.cowork_context module — _cowork-session.md generator.

15 unit tests covering:
- generate_cowork_session (empty vault, inaccessible vault, frontmatter schema, output size)
- _collect_daily_logs (sorting, limit, broken frontmatter, jira keys)
- _collect_open_tasks (status filter, domain grouping)
- _collect_active_epics (status filter, progress calculation)
- _collect_recent_decisions (limit, empty section)
- _collect_activity_log (missing LOG.md)
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import frontmatter as fm_lib
import pytest

from app.cowork_context import (
    _collect_activity_log,
    _collect_active_epics,
    _collect_daily_logs,
    _collect_open_tasks,
    _collect_recent_decisions,
    generate_cowork_session,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _create_md_file(path: Path, metadata: dict, body: str = "Content here"):
    """Create a markdown file with frontmatter at *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    post = fm_lib.Post(body, **metadata)
    path.write_text(fm_lib.dumps(post), encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. test_empty_vault
# ---------------------------------------------------------------------------


def test_empty_vault(tmp_path):
    """Empty wiki/ directory -> all sections '*нет данных*', counts = 0, file created."""
    (tmp_path / "wiki").mkdir()

    result = generate_cowork_session(str(tmp_path))

    assert result["status"] == "ok"
    stats = result["session_sections"]
    assert stats["daily_logs"] == 0
    assert stats["open_tasks"] == 0
    assert stats["active_epics"] == 0
    assert stats["recent_decisions"] == 0
    assert stats["activity_entries"] == 0

    output = tmp_path / "llm_wiki" / "_cowork-session.md"
    assert output.exists()
    content = output.read_text(encoding="utf-8")
    assert content.count("*нет данных*") >= 5


# ---------------------------------------------------------------------------
# 2. test_daily_logs_sorting
# ---------------------------------------------------------------------------


def test_daily_logs_sorting(tmp_path):
    """7 daily-log files -> returns 5 most recent, sorted newest-first."""
    daily_dir = tmp_path / "wiki" / "daily-logs"
    dates = [
        "2026-06-24",
        "2026-06-25",
        "2026-06-26",
        "2026-06-27",
        "2026-06-28",
        "2026-06-29",
        "2026-06-30",
    ]
    for d in dates:
        _create_md_file(
            daily_dir / f"{d}-standup.md",
            {"date": d},
            body=f"- Worked on feature {d}\n",
        )

    md_text, count = _collect_daily_logs(tmp_path)

    assert count == 5
    # The 5 most recent dates, newest first
    expected_order = ["2026-06-30", "2026-06-29", "2026-06-28", "2026-06-27", "2026-06-26"]
    for date_str in expected_order:
        assert date_str in md_text
    # Oldest two should NOT appear
    assert "2026-06-24" not in md_text
    assert "2026-06-25" not in md_text

    # Verify ordering: position of each date in text should be ascending
    positions = [md_text.index(d) for d in expected_order]
    assert positions == sorted(positions)


# ---------------------------------------------------------------------------
# 3. test_daily_logs_less_than_limit
# ---------------------------------------------------------------------------


def test_daily_logs_less_than_limit(tmp_path):
    """3 daily-log files -> returns all 3."""
    daily_dir = tmp_path / "wiki" / "daily-logs"
    for d in ["2026-06-28", "2026-06-29", "2026-06-30"]:
        _create_md_file(
            daily_dir / f"{d}-standup.md",
            {"date": d},
            body=f"- Task for {d}\n",
        )

    md_text, count = _collect_daily_logs(tmp_path)

    assert count == 3
    assert "2026-06-28" in md_text
    assert "2026-06-29" in md_text
    assert "2026-06-30" in md_text


# ---------------------------------------------------------------------------
# 4. test_tasks_filter_status
# ---------------------------------------------------------------------------


def test_tasks_filter_status(tmp_path):
    """Tasks with closed statuses are excluded, open statuses are kept."""
    tasks_dir = tmp_path / "wiki" / "domains" / "test-domain" / "tasks"
    statuses = {
        "task-done.md": "done",
        "task-cancelled.md": "cancelled",
        "task-closed.md": "closed",
        "task-resolved.md": "resolved",
        "task-inprogress.md": "in-progress",
        "task-todo.md": "todo",
    }
    for fname, status in statuses.items():
        _create_md_file(
            tasks_dir / fname,
            {"status": status, "title": f"Task {status}"},
        )

    md_text, count = _collect_open_tasks(tmp_path)

    assert count == 2
    assert "in-progress" in md_text
    assert "todo" in md_text
    # Closed statuses should not appear as task rows
    for closed in ("done", "cancelled", "closed", "resolved"):
        # The status itself might appear in the section header "Открытые задачи"
        # but not as a table row value. Check that the task title is absent.
        assert f"Task {closed}" not in md_text


# ---------------------------------------------------------------------------
# 5. test_tasks_grouped_by_domain
# ---------------------------------------------------------------------------


def test_tasks_grouped_by_domain(tmp_path):
    """Tasks in two domains -> markdown has headers for both domains."""
    for domain in ("mobile", "backend"):
        tasks_dir = tmp_path / "wiki" / "domains" / domain / "tasks"
        _create_md_file(
            tasks_dir / f"{domain}-task-1.md",
            {"status": "todo", "title": f"{domain} task 1"},
        )
        _create_md_file(
            tasks_dir / f"{domain}-task-2.md",
            {"status": "in-progress", "title": f"{domain} task 2"},
        )

    md_text, count = _collect_open_tasks(tmp_path)

    assert count == 4
    assert "### backend" in md_text
    assert "### mobile" in md_text


# ---------------------------------------------------------------------------
# 6. test_epics_filter_status
# ---------------------------------------------------------------------------


def test_epics_filter_status(tmp_path):
    """Epics with done/cancelled are excluded; in-progress/todo/planned are kept."""
    epics_dir = tmp_path / "wiki" / "domains" / "search" / "epics"
    statuses = {
        "epic-done.md": "done",
        "epic-cancelled.md": "cancelled",
        "epic-inprogress.md": "in-progress",
        "epic-todo.md": "todo",
        "epic-planned.md": "planned",
    }
    for fname, status in statuses.items():
        _create_md_file(
            epics_dir / fname,
            {"status": status, "title": f"Epic {status}"},
        )

    md_text, count = _collect_active_epics(tmp_path)

    assert count == 3
    assert "Epic in-progress" in md_text
    assert "Epic todo" in md_text
    assert "Epic planned" in md_text
    assert "Epic done" not in md_text
    assert "Epic cancelled" not in md_text


# ---------------------------------------------------------------------------
# 7. test_epics_progress_calculation
# ---------------------------------------------------------------------------


def test_epics_progress_calculation(tmp_path):
    """Epic with 2/3 done tickets -> '66% (2/3)' in output (int truncation)."""
    epics_dir = tmp_path / "wiki" / "domains" / "dev" / "epics"
    _create_md_file(
        epics_dir / "epic-progress.md",
        {
            "status": "in-progress",
            "title": "Test Epic",
            "tickets": [
                {"status": "done"},
                {"status": "done"},
                {"status": "todo"},
            ],
        },
    )

    md_text, count = _collect_active_epics(tmp_path)

    assert count == 1
    assert "66% (2/3)" in md_text


# ---------------------------------------------------------------------------
# 8. test_decisions_limit
# ---------------------------------------------------------------------------


def test_decisions_limit(tmp_path):
    """5 meetings with 3 decisions each (15 total) -> count capped at 10."""
    meetings_dir = tmp_path / "wiki" / "meetings"
    for i in range(5):
        date_str = f"2026-06-{20 + i:02d}"
        decisions_body = (
            f"## Решения\n\n"
            f"- Решение {i}-A\n"
            f"- Решение {i}-B\n"
            f"- Решение {i}-C\n"
        )
        _create_md_file(
            meetings_dir / f"{date_str}-meeting.md",
            {"date": date_str, "title": f"Meeting {i}"},
            body=decisions_body,
        )

    md_text, count = _collect_recent_decisions(tmp_path)

    assert count == 10


# ---------------------------------------------------------------------------
# 9. test_decisions_empty_section
# ---------------------------------------------------------------------------


def test_decisions_empty_section(tmp_path):
    """Meeting without '## Решения' section -> count = 0, '*нет данных*'."""
    meetings_dir = tmp_path / "wiki" / "meetings"
    _create_md_file(
        meetings_dir / "2026-06-30-meeting.md",
        {"date": "2026-06-30", "title": "Quick sync"},
        body="Just a regular discussion, no decisions.\n",
    )

    md_text, count = _collect_recent_decisions(tmp_path)

    assert count == 0
    assert "*нет данных*" in md_text


# ---------------------------------------------------------------------------
# 10. test_activity_log_missing
# ---------------------------------------------------------------------------


def test_activity_log_missing(tmp_path):
    """No wiki/LOG.md -> '*нет данных*', count = 0."""
    (tmp_path / "wiki").mkdir(parents=True, exist_ok=True)

    md_text, count = _collect_activity_log(tmp_path)

    assert count == 0
    assert "*нет данных*" in md_text


# ---------------------------------------------------------------------------
# 11. test_vault_not_accessible
# ---------------------------------------------------------------------------


def test_vault_not_accessible(tmp_path):
    """Non-existent vault path -> status='error', message contains 'vault not accessible'."""
    nonexistent = str(tmp_path / "nonexistent")

    result = generate_cowork_session(nonexistent)

    assert result["status"] == "error"
    assert "vault not accessible" in result["message"]


# ---------------------------------------------------------------------------
# 12. test_broken_frontmatter
# ---------------------------------------------------------------------------


def test_broken_frontmatter(tmp_path):
    """Broken YAML frontmatter in 1 of 3 files -> count = 2 (broken file skipped)."""
    daily_dir = tmp_path / "wiki" / "daily-logs"
    daily_dir.mkdir(parents=True, exist_ok=True)

    # Two valid files
    _create_md_file(
        daily_dir / "2026-06-29-ok1.md",
        {"date": "2026-06-29"},
        body="- Valid entry 1\n",
    )
    _create_md_file(
        daily_dir / "2026-06-30-ok2.md",
        {"date": "2026-06-30"},
        body="- Valid entry 2\n",
    )

    # One broken file — write raw text with invalid YAML
    broken = daily_dir / "2026-06-28-broken.md"
    broken.write_text("---\n[invalid yaml\n---\n\nbody\n", encoding="utf-8")

    md_text, count = _collect_daily_logs(tmp_path)

    assert count == 2


# ---------------------------------------------------------------------------
# 13. test_frontmatter_schema
# ---------------------------------------------------------------------------


def test_frontmatter_schema(tmp_path):
    """Generated _cowork-session.md contains 'generated:' and 'vault_stats:' in frontmatter."""
    (tmp_path / "wiki").mkdir()

    generate_cowork_session(str(tmp_path))

    output = tmp_path / "llm_wiki" / "_cowork-session.md"
    assert output.exists()
    content = output.read_text(encoding="utf-8")

    # Check frontmatter markers are present in the first lines
    lines = content.splitlines()
    frontmatter_block = "\n".join(lines[:15])
    assert "generated:" in frontmatter_block
    assert "vault_stats:" in frontmatter_block


# ---------------------------------------------------------------------------
# 14. test_output_under_1000_lines
# ---------------------------------------------------------------------------


def test_output_under_1000_lines(tmp_path):
    """50 open tasks -> output file has < 1000 lines."""
    tasks_dir = tmp_path / "wiki" / "domains" / "test" / "tasks"
    for i in range(50):
        _create_md_file(
            tasks_dir / f"task-{i:03d}.md",
            {"status": "todo", "title": f"Task number {i}", "priority": "medium"},
        )

    generate_cowork_session(str(tmp_path))

    output = tmp_path / "llm_wiki" / "_cowork-session.md"
    assert output.exists()
    content = output.read_text(encoding="utf-8")
    line_count = len(content.splitlines())
    assert line_count < 1000, f"Output has {line_count} lines, expected < 1000"


# ---------------------------------------------------------------------------
# 15. test_jira_keys_extracted
# ---------------------------------------------------------------------------


def test_jira_keys_extracted(tmp_path):
    """Daily-log body with Jira keys -> keys appear in markdown output."""
    daily_dir = tmp_path / "wiki" / "daily-logs"
    _create_md_file(
        daily_dir / "2026-06-30-standup.md",
        {"date": "2026-06-30"},
        body="- Обсудили GO-153 и SUP-42, запланировали работу\n",
    )

    md_text, count = _collect_daily_logs(tmp_path)

    assert count == 1
    assert "GO-153" in md_text
    assert "SUP-42" in md_text
