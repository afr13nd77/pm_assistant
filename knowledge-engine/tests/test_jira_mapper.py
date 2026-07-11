"""Unit tests for app.jira_fetcher.mapper."""

import json

import app.jira_fetcher.mapper as mapper_module
from app.jira_fetcher.mapper import (
    artifact_type,
    detect_domain,
    normalize_status,
    to_markdown,
    update_frontmatter,
)

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_issue(
    key="GO-187",
    summary="Test task",
    status="To Do",
    assignee="Tester",
    priority="Medium",
    labels=None,
    project="GO",
    description="Description text",
    created="2026-04-20T10:00:00.000+0300",
    updated="2026-05-01T12:00:00.000+0300",
    issue_type="Task",
) -> dict:
    return {
        "key": key,
        "self": f"https://jira.server/rest/api/2/issue/{key}",
        "fields": {
            "summary": summary,
            "status": {"name": status},
            "assignee": {"displayName": assignee} if assignee else None,
            "priority": {"name": priority} if priority else None,
            "labels": labels or [],
            "project": {"key": project},
            "description": description,
            "created": created,
            "updated": updated,
            "issuetype": {"name": issue_type},
        },
    }


JIRA_URL = "https://jira.server"


# ---------------------------------------------------------------------------
# detect_domain
# ---------------------------------------------------------------------------

class TestDetectDomain:
    def test_detect_domain_dictionary(self):
        issue = _make_issue(labels=["r6", "dictionary"])
        assert detect_domain(issue) == "static-metadata"

    def test_detect_domain_suggester(self):
        issue = _make_issue(labels=["r6", "suggester"])
        assert detect_domain(issue) == "suggester"

    def test_detect_domain_search(self):
        issue = _make_issue(labels=["search", "r6"])
        assert detect_domain(issue) == "search-engine"

    def test_detect_domain_no_match(self):
        issue = _make_issue(labels=["r6", "backend"])
        assert detect_domain(issue) == "general"

    def test_detect_domain_empty_labels(self):
        issue = _make_issue(labels=[])
        assert detect_domain(issue) == "general"

    def test_detect_domain_case_insensitive(self):
        issue = _make_issue(labels=["Dictionary"])
        assert detect_domain(issue) == "static-metadata"


# ---------------------------------------------------------------------------
# normalize_status
# ---------------------------------------------------------------------------

class TestNormalizeStatus:
    def test_normalize_status_todo(self):
        assert normalize_status("To Do") == "todo"

    def test_normalize_status_in_progress(self):
        assert normalize_status("In Progress") == "in-progress"

    def test_normalize_status_done_russian(self):
        assert normalize_status("Готово") == "done"

    def test_normalize_status_unknown(self):
        assert normalize_status("Custom Status") == "custom-status"


# ---------------------------------------------------------------------------
# to_markdown
# ---------------------------------------------------------------------------

class TestToMarkdown:
    def _parse_frontmatter(self, md: str) -> dict:
        """Extract frontmatter key→value pairs from the markdown string."""
        lines = md.splitlines()
        assert lines[0] == "---", "First line must be ---"
        end_idx = lines.index("---", 1)
        fm_lines = lines[1:end_idx]
        result = {}
        for line in fm_lines:
            if ":" in line:
                k, _, v = line.partition(":")
                result[k.strip()] = v.strip()
        return result

    def test_to_markdown_basic(self):
        issue = _make_issue()
        md = to_markdown(issue, JIRA_URL)
        assert "---" in md
        fm = self._parse_frontmatter(md)
        assert fm["jira_key"] == "GO-187"
        assert fm["status"] == "todo"
        assert fm["project"] == "GO"

    def test_to_markdown_contains_key_in_heading(self):
        issue = _make_issue(key="GO-187", summary="My summary")
        md = to_markdown(issue, JIRA_URL)
        assert "# GO-187:" in md

    def test_to_markdown_null_assignee(self):
        issue = _make_issue(assignee=None)
        md = to_markdown(issue, JIRA_URL)
        fm = self._parse_frontmatter(md)
        # assignee field present with empty value
        assert "assignee" in fm
        # value should be empty (quoted empty string or just empty after stripping quotes)
        assert fm["assignee"].strip('"') == ""

    def test_to_markdown_null_description(self):
        issue = _make_issue(description=None)
        md = to_markdown(issue, JIRA_URL)
        assert "Нет описания" in md

    def test_to_markdown_special_chars_in_title(self):
        issue = _make_issue(summary="Fix: update [config] values")
        md = to_markdown(issue, JIRA_URL)
        fm = self._parse_frontmatter(md)
        # title value must be wrapped in double quotes
        assert fm["title"].startswith('"'), (
            f"Expected title to be quoted, got: {fm['title']!r}"
        )

    def test_to_markdown_tags_include_labels(self):
        issue = _make_issue(labels=["r6", "suggester"])
        md = to_markdown(issue, JIRA_URL)
        assert "jira" in md
        assert "r6" in md
        assert "suggester" in md
        # The tags line must contain all three
        tags_line = next(line for line in md.splitlines() if line.startswith("tags:"))
        assert "jira" in tags_line
        assert "r6" in tags_line
        assert "suggester" in tags_line

    def test_to_markdown_jira_url_constructed(self):
        issue = _make_issue(key="GO-42")
        md = to_markdown(issue, "https://jira.example.com")
        assert "https://jira.example.com/browse/GO-42" in md

    def test_to_markdown_priority_lowercased(self):
        issue = _make_issue(priority="High")
        md = to_markdown(issue, JIRA_URL)
        fm = self._parse_frontmatter(md)
        assert fm["priority"] == "high"

    def test_to_markdown_null_priority(self):
        issue = _make_issue(priority=None)
        md = to_markdown(issue, JIRA_URL)
        fm = self._parse_frontmatter(md)
        assert fm["priority"] == ""

    def test_to_markdown_synced_at_present(self):
        issue = _make_issue()
        md = to_markdown(issue, JIRA_URL)
        assert "synced_at:" in md


# ---------------------------------------------------------------------------
# update_frontmatter
# ---------------------------------------------------------------------------

class TestUpdateFrontmatter:
    def test_update_frontmatter_regenerates(self):
        issue = _make_issue(key="GO-999", summary="Regenerated")
        existing = "---\nold: data\n---\nOld body text\n"
        result = update_frontmatter(existing, issue, JIRA_URL)
        # Should produce fresh markdown via to_markdown
        assert "GO-999" in result
        assert "Regenerated" in result
        # The result must be identical to a fresh to_markdown call
        expected = to_markdown(issue, JIRA_URL)
        # synced_at will differ by sub-second; compare everything except that line
        def strip_synced(md: str) -> str:
            return "\n".join(
                line for line in md.splitlines() if not line.startswith("synced_at:")
            )
        assert strip_synced(result) == strip_synced(expected)


# ---------------------------------------------------------------------------
# Env-based label→domain override
# ---------------------------------------------------------------------------

class TestLabelDomainMapFromEnv:
    def test_label_domain_map_from_env(self, monkeypatch):
        extra = {"custom-label": "custom-domain"}
        monkeypatch.setenv("JIRA_LABEL_DOMAIN_MAP", json.dumps(extra))
        # Reload the merged map by calling _merged_label_map directly
        merged = mapper_module._merged_label_map()
        assert merged["custom-label"] == "custom-domain"
        # Built-in mappings still present
        assert merged["suggester"] == "suggester"

    def test_label_domain_map_env_overrides_default(self, monkeypatch):
        override = {"suggester": "my-custom-domain"}
        monkeypatch.setenv("JIRA_LABEL_DOMAIN_MAP", json.dumps(override))
        merged = mapper_module._merged_label_map()
        assert merged["suggester"] == "my-custom-domain"

    def test_label_domain_map_used_in_detect_domain(self, monkeypatch):
        extra = {"custom-label": "custom-domain"}
        monkeypatch.setenv("JIRA_LABEL_DOMAIN_MAP", json.dumps(extra))
        issue = _make_issue(labels=["custom-label"])
        domain = detect_domain(issue)
        assert domain == "custom-domain"


# ---------------------------------------------------------------------------
# artifact_type
# ---------------------------------------------------------------------------

class TestArtifactType:
    def test_epic_returns_epics(self):
        assert artifact_type("epic") == "epics"

    def test_bug_returns_bugs(self):
        assert artifact_type("bug") == "bugs"

    def test_story_returns_userstories(self):
        assert artifact_type("story") == "userstories"

    def test_user_story_returns_userstories(self):
        assert artifact_type("user story") == "userstories"

    def test_task_returns_tasks(self):
        assert artifact_type("task") == "tasks"

    def test_subtask_returns_tasks(self):
        assert artifact_type("sub-task") == "tasks"

    def test_unknown_returns_tasks(self):
        assert artifact_type("something-new") == "tasks"

    def test_case_insensitive(self):
        assert artifact_type("Epic") == "epics"
        assert artifact_type("BUG") == "bugs"
        assert artifact_type("Story") == "userstories"


# ---------------------------------------------------------------------------
# Epic frontmatter fields in to_markdown
# ---------------------------------------------------------------------------

class TestEpicFrontmatter:
    def test_epic_has_prd_status(self):
        issue = _make_issue(issue_type="Epic")
        md = to_markdown(issue, JIRA_URL)
        assert "horizon:" not in md
        assert "prd_status:" in md

    def test_non_epic_has_no_epic_fields(self):
        issue = _make_issue(issue_type="Task")
        md = to_markdown(issue, JIRA_URL)
        assert "horizon:" not in md
        assert "prd_status:" not in md

    def test_bug_has_no_epic_fields(self):
        issue = _make_issue(issue_type="Bug")
        md = to_markdown(issue, JIRA_URL)
        assert "horizon:" not in md
        assert "prd_status:" not in md
