"""Jira issue → Markdown mapper.

Converts raw Jira issue dicts (REST API v2 format) into Markdown files
with YAML frontmatter suitable for storage in an Obsidian vault.
"""

import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Artifact type mapping
# ---------------------------------------------------------------------------

_ISSUE_TYPE_TO_ARTIFACT: dict[str, str] = {
    "epic": "epics",
    "bug": "bugs",
    "story": "userstories",
    "user story": "userstories",
    "история": "userstories",
}


def artifact_type(issue_type: str) -> str:
    """Map Jira issue type to vault artifact folder name.

    Returns "tasks" for any type not explicitly mapped.

    Args:
        issue_type: Raw issue type string from Jira (e.g. ``"Epic"``).

    Returns:
        Vault artifact folder name (e.g. ``"epics"``).
    """
    result = _ISSUE_TYPE_TO_ARTIFACT.get(issue_type.strip().lower(), "tasks")
    logger.info("artifact_type: %r → %r", issue_type, result)
    return result

# ---------------------------------------------------------------------------
# Domain mapping
# ---------------------------------------------------------------------------

LABEL_TO_DOMAIN: dict[str, str] = {
    "dictionary": "static-metadata",
    "suggester": "suggester",
    "search": "search-engine",
    "partner_search": "partner-search-engine",
}

# Status normalisation map (source keys are lowercase)
STATUS_MAP: dict[str, str] = {
    "to do": "todo",
    "open": "todo",
    "backlog": "todo",
    "in progress": "in-progress",
    "in review": "in-review",
    "in testing": "in-testing",
    "done": "done",
    "готово": "done",
    "готово/closed": "done",
    "closed": "done",
    "resolved": "done",
    "deploy": "deploy",
    "staging": "staging",
    "отменена": "cancelled",
    "development": "in-progress",
    "ready for development": "todo",
    "в работе": "in-progress",
}

# Characters that require the YAML scalar to be wrapped in double quotes
_YAML_SPECIAL_CHARS = set(':#[]{}"\',')


def _merged_label_map() -> dict[str, str]:
    """Return LABEL_TO_DOMAIN merged with any overrides from the environment and
    domain-config.yaml.

    Merge priority (highest wins):
      Layer 1 — built-in ``LABEL_TO_DOMAIN`` hardcoded defaults
      Layer 2 — ``JIRA_LABEL_DOMAIN_MAP`` env var (JSON object)
      Layer 3 — domain-config.yaml (highest priority)

    Returns:
        Merged mapping dict.
    """
    result = dict(LABEL_TO_DOMAIN)
    env_val = os.environ.get("JIRA_LABEL_DOMAIN_MAP", "").strip()
    if env_val:
        try:
            extra = json.loads(env_val)
            if isinstance(extra, dict):
                result.update(extra)
                logger.debug(
                    "_merged_label_map: merged %d extra entry(ies) from env",
                    len(extra),
                )
            else:
                logger.warning(
                    "_merged_label_map: JIRA_LABEL_DOMAIN_MAP is not a JSON object, ignoring"
                )
        except json.JSONDecodeError as exc:
            logger.warning(
                "_merged_label_map: failed to parse JIRA_LABEL_DOMAIN_MAP: %s", exc
            )

    # Layer 3 (highest priority): domain-config.yaml
    from shared import domain_config
    config_map = domain_config.build_label_map()
    if config_map:
        for label, domain in config_map.items():
            if label in result and result[label] != domain:
                logger.warning(
                    "_merged_label_map: config override for label %r: %r -> %r",
                    label, result[label], domain,
                )
        result.update(config_map)
        logger.info(
            "_merged_label_map: merged %d config entries (total map size: %d)",
            len(config_map), len(result),
        )

    return result


def detect_domain(issue: dict) -> str:
    """Detect the domain for a Jira issue based on its labels.

    Iterates labels in order, returns the domain for the first label that
    matches a key in the (possibly env-extended) ``LABEL_TO_DOMAIN`` map.
    Comparison is case-insensitive.

    The log message for a successful match includes the source of the mapping:
    ``"config"`` when the label was defined in domain-config.yaml, or
    ``"hardcoded/env"`` when it came from the built-in defaults or env var.

    Args:
        issue: Raw Jira issue dict.

    Returns:
        Domain string (e.g. ``"suggester"``) or ``"general"`` if no match.
    """
    key = issue.get("key", "<unknown>")
    logger.debug("detect_domain: processing issue key=%s", key)

    labels: list = issue.get("fields", {}).get("labels", []) or []
    label_map = _merged_label_map()

    # Build the set of labels that originate from domain-config.yaml for
    # source attribution in the log message.  build_label_map() is cheap
    # because load() uses mtime-based caching.
    from shared import domain_config
    config_label_set: set[str] = set(domain_config.build_label_map().keys())

    for label in labels:
        lower_label = label.lower()
        if lower_label in label_map:
            domain = label_map[lower_label]
            source = "config" if lower_label in config_label_set else "hardcoded/env"
            logger.info(
                "detect_domain: issue key=%s -> domain=%s (matched label=%s, source=%s)",
                key,
                domain,
                label,
                source,
            )
            return domain

    logger.info(
        "detect_domain: issue key=%s -> domain=general (no label matched)", key
    )
    return "general"


def normalize_status(jira_status: str) -> str:
    """Normalize a Jira status string to a vault-friendly slug.

    Uses the built-in ``STATUS_MAP`` for known values. Unknown values are
    lower-cased with spaces replaced by hyphens.

    Args:
        jira_status: Raw status name from Jira (e.g. ``"In Progress"``).

    Returns:
        Normalized status slug (e.g. ``"in-progress"``).
    """
    logger.debug("normalize_status: input=%r", jira_status)
    lowered = jira_status.strip().lower()
    result = STATUS_MAP.get(lowered, lowered.replace(" ", "-"))
    logger.info("normalize_status: %r → %r", jira_status, result)
    return result


def _yaml_quote(value: str) -> str:
    """Wrap *value* in double quotes if it contains YAML special characters.

    Args:
        value: Raw string value.

    Returns:
        Original string or double-quoted version.
    """
    if any(ch in value for ch in _YAML_SPECIAL_CHARS):
        # Escape any embedded double quotes
        escaped = value.replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _format_labels_inline(labels: list) -> str:
    """Format a list of labels as an inline YAML sequence ``[a, b, c]``."""
    return "[" + ", ".join(str(lb) for lb in labels) + "]"


def to_markdown(issue: dict, jira_url: str) -> str:
    """Convert a raw Jira issue dict into a Markdown string with YAML frontmatter.

    The ``jira_url`` parameter is the base URL of the Jira server (e.g.
    ``"https://jira.example.com"``). The browse URL is constructed as
    ``{jira_url}/browse/{key}``.

    Args:
        issue: Raw Jira issue dict from the REST API v2.
        jira_url: Base URL of the Jira server (no trailing slash required).

    Returns:
        Full Markdown string with YAML frontmatter and body.
    """
    key = issue.get("key", "")
    fields = issue.get("fields", {}) or {}

    summary: str = fields.get("summary") or ""
    issue_type_raw = fields.get("issuetype")
    issue_type: str = (issue_type_raw.get("name", "") if issue_type_raw else "").lower()
    status_raw: str = (fields.get("status") or {}).get("name") or "unknown"
    assignee_raw = fields.get("assignee")
    assignee: str = assignee_raw.get("displayName", "") if assignee_raw else ""
    priority_raw = fields.get("priority")
    priority: str = (priority_raw.get("name", "") if priority_raw else "").lower()
    labels: list = fields.get("labels") or []
    project: str = (fields.get("project") or {}).get("key") or ""
    description: str | None = fields.get("description")
    epic_key: str = fields.get("customfield_10008") or ""
    created_at: str = fields.get("created") or ""
    updated_at: str = fields.get("updated") or ""

    status = normalize_status(status_raw)
    domain = detect_domain(issue)
    jira_browse_url = f"{jira_url.rstrip('/')}/browse/{key}"
    synced_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    tags: list[str] = ["jira"] + list(labels)

    title_yaml = _yaml_quote(summary)
    assignee_yaml = _yaml_quote(assignee) if assignee else '""'
    labels_yaml = _format_labels_inline(labels)
    tags_yaml = _format_labels_inline(tags)

    body_text = description if description is not None else "Нет описания"

    epic_extra = ""
    if issue_type == "epic":
        epic_extra = (
            'prd_status: ""\n'
        )

    frontmatter_block = (
        "---\n"
        f"jira_key: {key}\n"
        f"jira_url: {jira_browse_url}\n"
        f"title: {title_yaml}\n"
        f"type: {issue_type}\n"
        f"epic_key: {epic_key}\n"
        f"status: {status}\n"
        f"assignee: {assignee_yaml}\n"
        f"priority: {priority}\n"
        f"project: {project}\n"
        f"labels: {labels_yaml}\n"
        f"domain: {domain}\n"
        f'created_at: "{created_at}"\n'
        f'updated_at: "{updated_at}"\n'
        f'synced_at: "{synced_at}"\n'
        f"relevance: 1.0\n"
        f"tier: active\n"
        f'last_accessed: "{synced_at[:10]}"\n'
        f"access_count: 0\n"
        f"tags: {tags_yaml}\n"
        f"{epic_extra}"
        "---\n"
    )

    heading = f"# {key}: {summary}"
    content = f"{frontmatter_block}\n{heading}\n\n{body_text}\n"

    logger.info("to_markdown: mapped issue key=%s", key)
    return content


def update_frontmatter(existing_content: str, issue: dict, jira_url: str) -> str:
    """Regenerate the full Markdown content for an existing vault file.

    Currently performs a full rewrite via ``to_markdown()``. This function
    exists as a dedicated hook point to support partial frontmatter updates
    in the future without changing the call-site API.

    Args:
        existing_content: Current content of the vault file (unused in this
            implementation — full rewrite strategy).
        issue: Raw Jira issue dict.
        jira_url: Base URL of the Jira server.

    Returns:
        Regenerated Markdown string.
    """
    key = issue.get("key", "<unknown>")
    logger.info("update_frontmatter: regenerating content for issue key=%s", key)
    result = to_markdown(issue, jira_url)
    logger.info("update_frontmatter: done for issue key=%s", key)
    return result


# ---------------------------------------------------------------------------
# Reverse mapping: vault → Jira API payload
# ---------------------------------------------------------------------------

_PRIORITY_TO_JIRA: dict[str, str] = {
    "critical": "Highest",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
    "lowest": "Lowest",
    "p1": "Highest",
    "p2": "High",
    "p3": "Medium",
}

_TYPE_TO_JIRA: dict[str, str] = {
    "task": "Task",
    "bug": "Bug",
    "story": "Story",
    "epic": "Epic",
    "userstory": "Story",
    "задача": "Task",
    "ошибка": "Bug",
}

_INTERNAL_TAGS = {"jira", "pipeline"}


def reverse_map(
    frontmatter: dict,
    body: str,
    project_key: str,
    issue_type: str,
    summary: str,
    epic_key: str = "",
) -> dict:
    """Build a Jira API issue creation payload from vault frontmatter and body.

    Args:
        frontmatter: Parsed YAML frontmatter dict from vault file.
        body: Full markdown content of the vault file (including frontmatter).
        project_key: Target Jira project key (e.g. "GO").
        issue_type: Jira issue type name (Task, Bug, Story, Epic).
        summary: Issue summary/title (may be edited by user in UI).
        epic_key: Optional epic key to link to (e.g. "GO-100"). Ignored for Epics.

    Returns:
        Dict suitable as body for POST /rest/api/2/issue.
    """
    # ------------------------------------------------------------------
    # 1. Extract description text: strip YAML frontmatter block and
    #    the leading H1 heading that typically repeats the title.
    # ------------------------------------------------------------------
    description_text = body
    parts = body.split("---", 2)
    # parts[0] is empty (before first ---), parts[1] is frontmatter,
    # parts[2] is the rest of the file when the frontmatter is present.
    if len(parts) >= 3:
        description_text = parts[2].lstrip("\n")

    # Strip a leading H1 heading line (e.g. "# KEY: Summary\n")
    lines = description_text.splitlines(keepends=True)
    if lines and lines[0].lstrip().startswith("# "):
        lines = lines[1:]
    description_text = "".join(lines).strip()

    logger.debug("reverse_map: extracted description length=%d chars", len(description_text))

    # ------------------------------------------------------------------
    # 2. Priority
    # ------------------------------------------------------------------
    raw_priority = frontmatter.get("priority", "")
    if not isinstance(raw_priority, str):
        raw_priority = ""
    jira_priority = _PRIORITY_TO_JIRA.get(raw_priority.strip().lower(), "Medium")
    logger.debug("reverse_map: priority %r → %r", raw_priority, jira_priority)

    # ------------------------------------------------------------------
    # 3. Labels
    # ------------------------------------------------------------------
    raw_labels = frontmatter.get("labels", [])
    if not isinstance(raw_labels, list):
        raw_labels = frontmatter.get("tags", [])
    if not isinstance(raw_labels, list):
        raw_labels = []

    labels_list: list[str] = [
        lb for lb in raw_labels
        if isinstance(lb, str) and lb not in _INTERNAL_TAGS
    ]
    if "r6" not in labels_list:
        labels_list.append("r6")

    logger.debug("reverse_map: labels=%r", labels_list)

    # ------------------------------------------------------------------
    # 4. Build core payload
    # ------------------------------------------------------------------
    payload: dict = {
        "fields": {
            "project": {"key": project_key},
            "summary": summary,
            "description": description_text,
            "issuetype": {"name": issue_type},
            "priority": {"name": jira_priority},
            "labels": labels_list,
        }
    }

    # ------------------------------------------------------------------
    # 5. Epic link (for non-Epic issues)
    # ------------------------------------------------------------------
    if epic_key and issue_type != "Epic":
        epic_link_field = os.environ.get("JIRA_EPIC_LINK_FIELD", "customfield_10008")
        payload["fields"][epic_link_field] = epic_key
        logger.debug("reverse_map: set epic link field %r = %r", epic_link_field, epic_key)

    # ------------------------------------------------------------------
    # 6. Epic name field (for Epic issues)
    # ------------------------------------------------------------------
    if issue_type == "Epic":
        epic_name_field = os.environ.get("JIRA_EPIC_NAME_FIELD", "customfield_10005")
        if epic_name_field:
            payload["fields"][epic_name_field] = summary
            logger.debug("reverse_map: set epic name field %r = %r", epic_name_field, summary)

    # ------------------------------------------------------------------
    # 7. Log payload summary
    # ------------------------------------------------------------------
    logger.info(
        "reverse_map: built payload project=%r type=%r summary=%r labels_count=%d",
        project_key,
        issue_type,
        summary[:50],
        len(labels_list),
    )

    return payload
