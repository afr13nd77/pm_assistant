"""Jira Server REST API v2 client."""

import logging
import os
import time

import requests
from requests.exceptions import ConnectionError, Timeout

logger = logging.getLogger(__name__)

_DEFAULT_FIELDS = "summary,status,assignee,priority,labels,project,description,created,updated,issuetype,customfield_10008"
_REQUEST_TIMEOUT = 30
_RETRY_DELAY = 10
_MAX_RETRIES = 1


class JiraClientError(Exception):
    """Raised on Jira API errors (auth failures, config problems, not-found, etc.)."""
    pass


def _get_config() -> tuple[str, str]:
    """
    Read JIRA_URL and JIRA_TOKEN from environment variables.

    Strips trailing slash from JIRA_URL.

    Returns:
        Tuple of (jira_url, jira_token).

    Raises:
        JiraClientError: If either variable is missing or empty.
    """
    logger.debug("_get_config: reading JIRA_URL and JIRA_TOKEN from environment")

    jira_url = os.environ.get("JIRA_URL", "").strip()
    jira_token = os.environ.get("JIRA_TOKEN", "").strip()

    missing = []
    if not jira_url:
        missing.append("JIRA_URL")
    if not jira_token:
        missing.append("JIRA_TOKEN")

    if missing:
        msg = f"Missing required environment variable(s): {', '.join(missing)}"
        logger.error("_get_config failed: %s", msg)
        raise JiraClientError(msg)

    jira_url = jira_url.rstrip("/")
    logger.debug("_get_config success: JIRA_URL=%s", jira_url)
    return jira_url, jira_token


def _make_request(
    url: str,
    headers: dict,
    params: dict | None = None,
    method: str = "GET",
    json_body: dict | None = None,
) -> dict | list:
    """
    Perform an HTTP request with one retry on connection error or 5xx response.

    Args:
        url: Full request URL.
        headers: HTTP headers dict (includes Authorization).
        params: Query parameters dict. Defaults to None.
        method: HTTP method string (e.g. "GET", "POST"). Defaults to "GET".
        json_body: Request body to send as JSON (POST/PUT). Defaults to None.

    Returns:
        Parsed JSON response as dict or list (e.g. GET /project returns a list).

    Raises:
        JiraClientError: On 400 validation errors, 401/403 auth errors, 404 not found,
            or after exhausting retries on 5xx / connection errors.
    """
    attempt = 0
    last_exc: Exception | None = None

    while attempt <= _MAX_RETRIES:
        try:
            logger.info(
                "_make_request: %s %s params=%s (attempt %d/%d)",
                method,
                url,
                params,
                attempt + 1,
                _MAX_RETRIES + 1,
            )
            response = requests.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_body,
                timeout=_REQUEST_TIMEOUT,
            )

            if response.status_code == 400:
                try:
                    err_body = response.json()
                    error_messages = err_body.get("errorMessages", [])
                    errors = err_body.get("errors", {})
                    detail = "; ".join(error_messages)
                    if errors:
                        field_errors = ", ".join(f"{k}: {v}" for k, v in errors.items())
                        detail = f"{detail}; {field_errors}" if detail else field_errors
                except Exception:
                    detail = response.text
                logger.error(
                    "_make_request: validation error status=400 url=%s detail=%s",
                    url,
                    detail,
                )
                raise JiraClientError(f"Jira validation error (400): {detail}")

            if response.status_code in (401, 403):
                logger.error(
                    "_make_request: auth error status=%d url=%s",
                    response.status_code,
                    url,
                )
                raise JiraClientError(
                    f"Jira authentication error: HTTP {response.status_code}"
                )

            if response.status_code == 404:
                logger.error("_make_request: not found status=404 url=%s", url)
                raise JiraClientError(f"Jira resource not found: {url}")

            if response.status_code >= 500:
                logger.warning(
                    "_make_request: server error status=%d url=%s, attempt %d",
                    response.status_code,
                    url,
                    attempt + 1,
                )
                last_exc = JiraClientError(
                    f"Jira server error: HTTP {response.status_code}"
                )
                attempt += 1
                if attempt <= _MAX_RETRIES:
                    logger.info("_make_request: retrying in %ds", _RETRY_DELAY)
                    time.sleep(_RETRY_DELAY)
                continue

            response.raise_for_status()
            data = response.json()
            logger.info("_make_request: success status=%d url=%s", response.status_code, url)
            return data

        except JiraClientError:
            raise

        except (ConnectionError, Timeout) as exc:
            logger.warning(
                "_make_request: connection/timeout error url=%s attempt %d: %s",
                url,
                attempt + 1,
                exc,
            )
            last_exc = exc
            attempt += 1
            if attempt <= _MAX_RETRIES:
                logger.info("_make_request: retrying in %ds", _RETRY_DELAY)
                time.sleep(_RETRY_DELAY)
            continue

    logger.error(
        "_make_request: all %d attempt(s) exhausted for url=%s, last error: %s",
        _MAX_RETRIES + 1,
        url,
        last_exc,
    )
    raise JiraClientError(
        f"Request to {url} failed after {_MAX_RETRIES + 1} attempt(s): {last_exc}"
    )


def search(
    jql: str,
    fields: list[str] | None = None,
    max_results: int = 100,
) -> list[dict]:
    """
    Search for Jira issues using JQL.

    Fetches all matching issues using pagination (startAt loop).

    Args:
        jql: JQL query string.
        fields: List of field names to return. Defaults to a standard set.
        max_results: Number of issues to request per page.

    Returns:
        List of raw issue dicts from Jira (elements of the ``issues`` array).

    Raises:
        JiraClientError: On auth errors (401/403), config errors (missing env vars),
            or persistent network/server failures.
    """
    logger.info("search: jql=%r fields=%s max_results=%d", jql, fields, max_results)

    jira_url, jira_token = _get_config()
    headers = {"Authorization": f"Bearer {jira_token}"}

    fields_str = ",".join(fields) if fields else _DEFAULT_FIELDS
    url = f"{jira_url}/rest/api/2/search"

    all_issues: list[dict] = []
    start_at = 0

    while True:
        params = {
            "jql": jql,
            "fields": fields_str,
            "maxResults": max_results,
            "startAt": start_at,
        }

        logger.info(
            "search: fetching page startAt=%d maxResults=%d url=%s",
            start_at,
            max_results,
            url,
        )

        data = _make_request(url, headers, params)
        assert isinstance(data, dict)

        issues = data.get("issues", [])
        total = data.get("total", 0)
        count = len(issues)

        logger.info(
            "search: received %d issue(s) at startAt=%d, total=%d",
            count,
            start_at,
            total,
        )

        all_issues.extend(issues)

        if start_at + count >= total:
            break

        start_at += count

    logger.info("search: completed, %d issue(s) returned in total", len(all_issues))
    return all_issues


def get_issue(key: str) -> dict:
    """
    Fetch a single Jira issue by its key.

    Args:
        key: Jira issue key, e.g. "PROJECT-123".

    Returns:
        Raw issue dict from Jira.

    Raises:
        JiraClientError: If the issue is not found (404), on auth errors,
            or on persistent network/server failures.
    """
    logger.info("get_issue: fetching issue key=%s", key)

    jira_url, jira_token = _get_config()
    headers = {"Authorization": f"Bearer {jira_token}"}
    url = f"{jira_url}/rest/api/2/issue/{key}"

    data = _make_request(url, headers, {})
    assert isinstance(data, dict)

    logger.info("get_issue: successfully fetched issue key=%s", key)
    return data


def create_issue(payload: dict) -> dict:
    """
    Create a Jira issue.

    Args:
        payload: Jira issue creation payload (``fields`` dict as per Jira REST API v2).

    Returns:
        Dict with ``id``, ``key``, and ``self`` fields returned by Jira on success.

    Raises:
        JiraClientError: On validation errors (400), auth errors (401/403),
            or persistent network/server failures.
    """
    logger.info("create_issue: creating issue with payload keys=%s", list(payload.keys()))

    jira_url, jira_token = _get_config()
    headers = {
        "Authorization": f"Bearer {jira_token}",
        "Content-Type": "application/json",
    }
    url = f"{jira_url}/rest/api/2/issue"

    try:
        data = _make_request(url, headers, method="POST", json_body=payload)
    except JiraClientError:
        logger.error("create_issue: failed to create issue")
        raise

    assert isinstance(data, dict)
    logger.info("[jira-client] created issue %s", data["key"])
    return data


def get_projects() -> list[dict]:
    """
    Fetch all accessible Jira projects.

    Returns:
        List of project dicts, each containing at minimum ``id``, ``key``, and ``name``.

    Raises:
        JiraClientError: On auth errors (401/403) or persistent network/server failures.
    """
    logger.info("get_projects: fetching all accessible projects")

    jira_url, jira_token = _get_config()
    headers = {"Authorization": f"Bearer {jira_token}"}
    url = f"{jira_url}/rest/api/2/project"

    result = _make_request(url, headers)

    # The /project endpoint returns a JSON array directly (not wrapped in an object).
    if not isinstance(result, list):
        logger.error(
            "get_projects: unexpected response type %s, expected list", type(result).__name__
        )
        raise JiraClientError(
            f"Unexpected response from GET /project: expected list, got {type(result).__name__}"
        )

    projects: list[dict] = result
    logger.info("[jira-client] fetched %d projects", len(projects))
    return projects


def get_project_issue_types(project_key: str) -> list[dict]:
    """Fetch issue types available for a Jira project.

    Uses GET /rest/api/2/project/{project_key} and extracts issueTypes.
    Filters out subtask types.

    Args:
        project_key: Jira project key, e.g. "GO".

    Returns:
        List of dicts: [{"id": "10001", "name": "Task", "subtask": False}, ...]

    Raises:
        JiraClientError: On auth errors (401/403), not found (404),
            or persistent network/server failures.
    """
    logger.info("get_project_issue_types: fetching for project_key=%s", project_key)

    jira_url, jira_token = _get_config()
    headers = {"Authorization": f"Bearer {jira_token}"}
    url = f"{jira_url}/rest/api/2/project/{project_key}"

    result = _make_request(url, headers)
    assert isinstance(result, dict)

    raw_types = result.get("issueTypes", [])
    issue_types = [
        {"id": str(t.get("id", "")), "name": t.get("name", ""), "subtask": bool(t.get("subtask", False))}
        for t in raw_types
        if not t.get("subtask", False)
    ]

    logger.info("get_project_issue_types: found %d types (excl. subtasks) for project %s", len(issue_types), project_key)
    return issue_types


def get_project_epics(project_key: str) -> list[dict]:
    """
    Fetch open epics for a project via JQL search.

    Args:
        project_key: Jira project key, e.g. "GO".

    Returns:
        List of simplified epic dicts: ``[{"key": "GO-100", "summary": "Epic title"}, ...]``.

    Raises:
        JiraClientError: On auth errors, config errors, or persistent network/server failures.
    """
    logger.info("get_project_epics: fetching epics for project_key=%s", project_key)

    jql = (
        f'project = "{project_key}" AND issuetype = Epic'
        ' AND status not in ("Готово/Closed")'
    )

    issues = search(jql, fields=["summary", "status"], max_results=200)

    epics = [
        {"key": issue["key"], "summary": issue["fields"]["summary"]}
        for issue in issues
    ]

    logger.info("[jira-client] fetched %d epics for project %s", len(epics), project_key)
    return epics
