"""Jira sync orchestrator.

Ties together the Jira client, state tracker, and mapper modules to perform
a full synchronization cycle: fetch issues from Jira, diff against persisted
state, write Markdown files to the vault, update domain indexes/logs, save
state, and optionally send Telegram notifications.
"""

import logging
import os
import re
from datetime import datetime
from pathlib import Path

from .client import JiraClientError, get_issue, search
from . import client as jira_client
from . import state as sync_state
from .mapper import detect_domain, normalize_status, to_markdown, update_frontmatter, artifact_type, reverse_map, _ISSUE_TYPE_TO_ARTIFACT
from .. import vault_paths
from .. import frontmatter_utils
from ..file_writer import atomic_write
from ..domain_manager import append_domain_log, update_domain_index
from ..notifier import send_telegram

logger = logging.getLogger(__name__)

# DEFAULT_JQL = (
#     '(labels in (r6) and labels not in (backlog)) '
#     'and status not in (Done, "Готово", "Готово/Closed", DEPLOY, Staging, Отменена) '
#     'and project not in ("Задачи беклога Суточно.ру")'
# )

DEFAULT_JQL = (
    '(labels in (r6) and labels not in (backlog)) '
     'and project not in ("Задачи беклога Суточно.ру")'
)

def _error_result(message: str) -> dict:
    """Build a standardised error-result dict.

    Args:
        message: Human-readable description of the error.

    Returns:
        Result dict with ``status="error"`` and zero counters.
    """
    logger.error("_error_result: %s", message)
    return {
        "status": "error",
        "new": 0,
        "updated": 0,
        "closed": 0,
        "errors": 1,
        "details": [],
        "message": message,
    }


def _should_notify() -> bool:
    prefs_path = vault_paths.user_prefs_path()
    try:
        if not prefs_path.exists():
            logger.info("_should_notify: prefs file not found at %s, defaulting to True", prefs_path)
            return True
        import json as _json
        data = _json.loads(prefs_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            logger.warning("_should_notify: prefs file is not a JSON object, defaulting to True")
            return True
        value = data.get("jira_sync_notify", True)
        result = bool(value)
        logger.info("_should_notify: jira_sync_notify=%s", result)
        return result
    except Exception as exc:
        logger.warning("_should_notify: failed to read prefs: %s, defaulting to True", exc)
        return True


def sync(
    vault_path: str,
    notify: bool = False,
    dry_run: bool = False,
) -> dict:
    """Run one full Jira-to-vault synchronisation cycle.

    Args:
        vault_path: Absolute path to the Obsidian vault root directory.
        notify:     If ``True``, send a Telegram summary after sync.
        dry_run:    If ``True``, compute diffs but do not write any files
                    or mutate state.

    Returns:
        A dict with keys ``status``, ``new``, ``updated``, ``closed``,
        ``errors``, ``details`` (list of per-issue action strings), and
        ``message`` (human-readable summary).
    """
    logger.info(
        "sync: starting vault_path=%s notify=%s dry_run=%s",
        vault_path,
        notify,
        dry_run,
    )

    # ------------------------------------------------------------------
    # 0. Read JIRA_URL from environment
    # ------------------------------------------------------------------
    jira_url = os.environ.get("JIRA_URL", "").strip().rstrip("/")
    if not jira_url:
        msg = "JIRA_URL environment variable is not set or empty"
        logger.error("sync: %s", msg)
        if notify and _should_notify():
            send_telegram(f"Jira sync error: {msg}", parse_mode=None)
        elif notify:
            logger.info("sync: Telegram notification suppressed by user preference")
        return _error_result(msg)

    logger.info("sync: JIRA_URL=%s", jira_url)

    # ------------------------------------------------------------------
    # 1. Load state
    # ------------------------------------------------------------------
    st = sync_state.load(vault_path)
    issue_count = len(st.get("issues", {}))
    logger.info("sync: state loaded, %d issues in state", issue_count)

    # ------------------------------------------------------------------
    # 2. Fetch issues from Jira
    # ------------------------------------------------------------------
    try:
        issues = search(DEFAULT_JQL)
        logger.info("sync: Jira search returned %d issues", len(issues))
    except JiraClientError as exc:
        msg = f"Jira API error: {exc}"
        logger.error("sync: %s", msg)
        if notify and _should_notify():
            send_telegram(f"Jira sync error: {msg}", parse_mode=None)
        elif notify:
            logger.info("sync: Telegram notification suppressed by user preference")
        return _error_result(msg)

    # ------------------------------------------------------------------
    # 3. Diff
    # ------------------------------------------------------------------
    new_issues, updated_issues, closed_keys = sync_state.diff(st, issues)
    logger.info(
        "sync: diff result — %d new, %d updated, %d closed",
        len(new_issues),
        len(updated_issues),
        len(closed_keys),
    )

    # ------------------------------------------------------------------
    # 4. Dry-run: return counts only
    # ------------------------------------------------------------------
    if dry_run:
        summary = (
            f"Jira sync (dry-run): {len(new_issues)} new, "
            f"{len(updated_issues)} updated, {len(closed_keys)} closed"
        )
        logger.info("sync: %s", summary)
        return {
            "status": "skip",
            "new": len(new_issues),
            "updated": len(updated_issues),
            "closed": len(closed_keys),
            "errors": 0,
            "details": [],
            "message": summary,
        }

    errors = 0
    logged = 0
    details: list[str] = []

    # ------------------------------------------------------------------
    # 5. Process NEW issues
    # ------------------------------------------------------------------
    for issue in new_issues:
        try:
            key = issue["key"]
            domain = detect_domain(issue)
            status_str = normalize_status(issue["fields"]["status"]["name"])
            updated_at = issue["fields"].get("updated", "")
            issue_type_raw = issue.get("fields", {}).get("issuetype")
            issue_type_str = (issue_type_raw.get("name", "") if issue_type_raw else "").lower()
            art_type = artifact_type(issue_type_str)
            md_content = to_markdown(issue, jira_url)

            # 5a. Write to raw/inbound/tasks/<key>.md (immutable first snapshot)
            raw_path = vault_paths.raw_tasks() / f"{key}.md"
            atomic_write(raw_path, md_content)
            logger.info("sync: wrote raw file %s", raw_path)

            # 5b. Write to wiki/domains/<domain>/<art_type>/<key>.md
            wiki_dir = vault_paths.wiki_domain_dir(domain, art_type)
            wiki_path = wiki_dir / f"{key}.md"
            atomic_write(wiki_path, md_content)
            logger.info("sync: wrote wiki file %s", wiki_path)

            # 5c. Update domain log and index (non-fatal, independent)
            try:
                append_domain_log(
                    domain,
                    art_type,
                    "CREATE",
                    f"{key}.md",
                    f"synced from Jira (status={status_str})",
                )
                logged += 1
                logger.info(
                    "sync: log appended for CREATE key=%s domain=%s art_type=%s",
                    key,
                    domain,
                    art_type,
                )
            except Exception as exc:
                logger.warning(
                    "sync: failed to append domain log for key=%s: %s",
                    key,
                    exc,
                )

            try:
                update_domain_index(domain, art_type)
                logger.info(
                    "sync: domain index updated for key=%s domain=%s art_type=%s",
                    key,
                    domain,
                    art_type,
                )
            except Exception as exc:
                logger.warning(
                    "sync: failed to update domain index for key=%s: %s",
                    key,
                    exc,
                )

            # 5d. Update state entry
            sync_state.update_entry(st, key, status_str, updated_at, domain)
            st["issues"].setdefault(key, {})["artifact_type"] = art_type

            detail = f"NEW {key} domain={domain} status={status_str} art_type={art_type}"
            details.append(detail)
            logger.info("sync: processed new issue %s", detail)

        except Exception as exc:
            errors += 1
            key = issue.get("key", "<unknown>")
            logger.error(
                "sync: error processing new issue key=%s: %s", key, exc
            )
            details.append(f"ERROR NEW {key}: {exc}")

    # ------------------------------------------------------------------
    # 6. Process UPDATED issues
    # ------------------------------------------------------------------
    for issue in updated_issues:
        try:
            key = issue["key"]
            domain = detect_domain(issue)
            status_str = normalize_status(issue["fields"]["status"]["name"])
            updated_at = issue["fields"].get("updated", "")
            issue_type_raw = issue.get("fields", {}).get("issuetype")
            issue_type_str = (issue_type_raw.get("name", "") if issue_type_raw else "").lower()
            art_type = artifact_type(issue_type_str)

            # 6a. Read existing wiki file if present, then update
            wiki_dir = vault_paths.wiki_domain_dir(domain, art_type)
            wiki_path = wiki_dir / f"{key}.md"

            existing_content = ""
            if wiki_path.exists():
                existing_content = wiki_path.read_text(encoding="utf-8")

            new_content = update_frontmatter(existing_content, issue, jira_url)
            atomic_write(wiki_path, new_content)
            logger.info("sync: updated wiki file %s", wiki_path)

            # Do NOT touch raw/ (raw is immutable first snapshot)

            # 6b. Update domain log and index (non-fatal, independent)
            try:
                append_domain_log(
                    domain,
                    art_type,
                    "UPDATE",
                    f"{key}.md",
                    f"updated from Jira (status={status_str})",
                )
                logged += 1
                logger.info(
                    "sync: log appended for UPDATE key=%s domain=%s art_type=%s",
                    key,
                    domain,
                    art_type,
                )
            except Exception as exc:
                logger.warning(
                    "sync: failed to append domain log for key=%s: %s",
                    key,
                    exc,
                )

            try:
                update_domain_index(domain, art_type)
                logger.info(
                    "sync: domain index updated for key=%s domain=%s art_type=%s",
                    key,
                    domain,
                    art_type,
                )
            except Exception as exc:
                logger.warning(
                    "sync: failed to update domain index for key=%s: %s",
                    key,
                    exc,
                )

            # 6c. Update state entry
            sync_state.update_entry(st, key, status_str, updated_at, domain)
            st["issues"].setdefault(key, {})["artifact_type"] = art_type

            detail = f"UPDATED {key} domain={domain} status={status_str} art_type={art_type}"
            details.append(detail)
            logger.info("sync: processed updated issue %s", detail)

        except Exception as exc:
            errors += 1
            key = issue.get("key", "<unknown>")
            logger.error(
                "sync: error processing updated issue key=%s: %s", key, exc
            )
            details.append(f"ERROR UPDATED {key}: {exc}")

    # ------------------------------------------------------------------
    # 7. Process CLOSED keys (verify actual status before marking done)
    # ------------------------------------------------------------------
    _CLOSED_STATUSES = frozenset({
        "done", "готово", "готово/closed", "closed", "resolved",
        "deploy", "staging", "отменена",
    })

    for key in closed_keys:
        try:
            old_entry = st.get("issues", {}).get(key, {})
            domain = old_entry.get("domain", "general")
            art_type = old_entry.get("artifact_type", "")

            # Re-fetch from Jira to verify actual status
            actual_status_str = "done"
            try:
                issue = get_issue(key)
                actual_status_raw = (issue.get("fields", {}).get("status") or {}).get("name", "")
                actual_status_str = normalize_status(actual_status_raw)
                logger.info(
                    "sync: re-fetched closed key=%s, actual Jira status=%r → %s",
                    key, actual_status_raw, actual_status_str,
                )
                if not art_type:
                    issue_type_raw = issue.get("fields", {}).get("issuetype")
                    issue_type_str = (issue_type_raw.get("name", "") if issue_type_raw else "").lower()
                    art_type = artifact_type(issue_type_str)
                    st["issues"].setdefault(key, {})["artifact_type"] = art_type
                    logger.info("sync: resolved missing artifact_type for key=%s → %s", key, art_type)
            except JiraClientError as exc:
                logger.warning(
                    "sync: failed to re-fetch key=%s, assuming done: %s", key, exc
                )

            if not art_type:
                art_type = "tasks"

            is_really_closed = actual_status_str.lower() in _CLOSED_STATUSES

            if is_really_closed:
                sync_state.mark_closed(st, key)
            else:
                sync_state.update_entry(st, key, actual_status_str, "", domain)
                logger.info(
                    "sync: key=%s not actually closed (status=%s), updated state",
                    key, actual_status_str,
                )

            updated_any_wiki = False
            for try_art in {art_type, "tasks", "epics"}:
                wiki_dir = vault_paths.wiki_domain_dir(domain, try_art)
                wiki_path = wiki_dir / f"{key}.md"
                if wiki_path.exists():
                    existing = wiki_path.read_text(encoding="utf-8")
                    updated_content = re.sub(
                        r"^status: .+$",
                        f"status: {actual_status_str}",
                        existing,
                        count=1,
                        flags=re.MULTILINE,
                    )
                    atomic_write(wiki_path, updated_content)
                    logger.info("sync: updated wiki file status to '%s' %s", actual_status_str, wiki_path)
                    updated_any_wiki = True

            if updated_any_wiki:
                action_label = "CLOSED" if is_really_closed else "STATUS_UPDATE"

                try:
                    append_domain_log(
                        domain,
                        art_type,
                        action_label,
                        f"{key}.md",
                        f"verified from Jira → status={actual_status_str}",
                    )
                    logged += 1
                    logger.info(
                        "sync: log appended for %s key=%s domain=%s art_type=%s",
                        action_label, key, domain, art_type,
                    )
                except Exception as exc:
                    logger.warning(
                        "sync: failed to append domain log for closed key=%s: %s",
                        key, exc,
                    )

                try:
                    update_domain_index(domain, art_type)
                    logger.info(
                        "sync: domain index updated for %s key=%s domain=%s art_type=%s",
                        action_label, key, domain, art_type,
                    )
                except Exception as exc:
                    logger.warning(
                        "sync: failed to update domain index for closed key=%s: %s",
                        key, exc,
                    )

            action_label = "CLOSED" if is_really_closed else "STATUS_VERIFIED"
            detail = f"{action_label} {key} domain={domain} art_type={art_type} status={actual_status_str}"
            details.append(detail)
            logger.info("sync: processed %s issue %s", action_label.lower(), detail)

        except Exception as exc:
            errors += 1
            logger.error(
                "sync: error processing closed issue key=%s: %s", key, exc
            )
            details.append(f"ERROR CLOSED {key}: {exc}")

    # ------------------------------------------------------------------
    # 8. Save state
    # ------------------------------------------------------------------
    try:
        sync_state.save(vault_path, st)
        logger.info("sync: state saved to vault_path=%s", vault_path)
    except Exception as exc:
        errors += 1
        logger.error("sync: failed to save state: %s", exc)
        details.append(f"ERROR saving state: {exc}")

    # ------------------------------------------------------------------
    # 9. Build summary and notify
    # ------------------------------------------------------------------
    expected_logs = len(new_issues) + len(updated_issues) + len(closed_keys)
    summary = (
        f"Jira sync: {len(new_issues)} new, "
        f"{len(updated_issues)} updated, {len(closed_keys)} closed"
    )
    if errors > 0:
        summary += f", {errors} errors"
    if logged < expected_logs:
        summary += f", {expected_logs - logged} log misses"

    status = "ok" if errors == 0 else "error"

    if notify and _should_notify():
        send_telegram(summary, parse_mode=None)
        logger.info("sync: Telegram notification sent")
    elif notify:
        logger.info("sync: Telegram notification suppressed by user preference (jira_sync_notify=false)")

    # ------------------------------------------------------------------
    # 10. Return result dict
    # ------------------------------------------------------------------
    result = {
        "status": status,
        "new": len(new_issues),
        "updated": len(updated_issues),
        "closed": len(closed_keys),
        "errors": errors,
        "logged": logged,
        "details": details,
        "message": summary,
    }
    logger.info("sync: completed — %s", summary)
    return result


def import_single_issue(key: str, vault_path: str) -> dict:
    """Import a single Jira issue by key into the vault.

    Fetches the issue from Jira API, writes to raw/ and wiki/,
    updates domain index/log and sync state.

    If the issue already exists in the vault, it is updated.
    """
    logger.info("import_single_issue: key=%s vault_path=%s", key, vault_path)

    jira_url = os.environ.get("JIRA_URL", "").strip().rstrip("/")
    if not jira_url:
        logger.error("import_single_issue: JIRA_URL not set")
        return {"status": "error", "message": "JIRA_URL environment variable is not set"}

    try:
        issue = get_issue(key)
    except JiraClientError as exc:
        logger.error("import_single_issue: Jira API error for key=%s: %s", key, exc)
        return {"status": "error", "message": str(exc)}

    domain = detect_domain(issue)
    fields = issue.get("fields", {})
    status_raw = (fields.get("status") or {}).get("name", "unknown")
    status_str = normalize_status(status_raw)
    updated_at = fields.get("updated", "")
    summary = fields.get("summary", "")
    issue_type_raw = fields.get("issuetype")
    issue_type_str = (issue_type_raw.get("name", "") if issue_type_raw else "").lower()
    art_type = artifact_type(issue_type_str)

    md_content = to_markdown(issue, jira_url)

    # Check if file already exists (update vs create)
    wiki_dir = vault_paths.wiki_domain_dir(domain, art_type)
    wiki_path = wiki_dir / f"{key}.md"
    is_update = wiki_path.exists()
    action = "UPDATE" if is_update else "CREATE"

    if is_update:
        existing_content = wiki_path.read_text(encoding="utf-8")
        md_content = update_frontmatter(existing_content, issue, jira_url)

    # Write to raw/ (only for new issues)
    if not is_update:
        raw_path = vault_paths.raw_tasks() / f"{key}.md"
        atomic_write(raw_path, md_content)
        logger.info("import_single_issue: wrote raw file %s", raw_path)

    # Write to wiki/
    atomic_write(wiki_path, md_content)
    logger.info("import_single_issue: wrote wiki file %s", wiki_path)

    # Update domain index and log
    try:
        update_domain_index(domain, art_type)
        append_domain_log(
            domain, art_type, action, f"{key}.md",
            f"imported from Jira (status={status_str})",
        )
        logger.info(
            "import_single_issue: domain index/log updated for %s key=%s domain=%s art_type=%s",
            action, key, domain, art_type,
        )
    except Exception as exc:
        logger.warning("import_single_issue: failed to update domain index/log for key=%s: %s", key, exc)

    # Update sync state
    try:
        st = sync_state.load(vault_path)
        sync_state.update_entry(st, key, status_str, updated_at, domain)
        st["issues"].setdefault(key, {})["artifact_type"] = art_type
        sync_state.save(vault_path, st)
        logger.info("import_single_issue: sync state updated for key=%s art_type=%s", key, art_type)
    except Exception as exc:
        logger.warning("import_single_issue: failed to update sync state for key=%s: %s", key, exc)

    logger.info(
        "import_single_issue: completed key=%s domain=%s status=%s action=%s art_type=%s",
        key, domain, status_str, action, art_type,
    )
    return {
        "status": "ok",
        "key": key,
        "domain": domain,
        "task_status": status_str,
        "title": summary,
        "action": action.lower(),
        "filename": f"{key}.md",
        "message": f"Imported {key} → domain={domain}, status={status_str} ({action.lower()})",
    }


def _find_vault_file(vault_path: str, filename: str) -> Path | None:
    """Search for a vault file by name across all domain task and epic directories.

    Searches in:
    - wiki/domains/*/tasks/{filename}
    - wiki/domains/*/epics/{filename}

    Returns the first match or None.

    Args:
        vault_path: Absolute path to the Obsidian vault root directory.
        filename:   Filename to search for (e.g. ``"my-task.md"``).

    Returns:
        :class:`~pathlib.Path` to the first match found, or ``None``.
    """
    logger.info("_find_vault_file: searching for filename=%s in vault_path=%s", filename, vault_path)
    root = Path(vault_path)

    # Search tasks directories first, then epics
    for pattern in (
        f"wiki/domains/*/tasks/{filename}",
        f"wiki/domains/*/epics/{filename}",
    ):
        matches = list(root.glob(pattern))
        if matches:
            found = matches[0]
            logger.info("_find_vault_file: found %s", found)
            return found

    logger.info("_find_vault_file: file not found filename=%s vault_path=%s", filename, vault_path)
    return None


def create_and_sync(
    vault_path: str,
    filename: str,
    project_key: str,
    issue_type: str,
    summary: str,
    epic_key: str = "",
) -> dict:
    """Create a Jira issue from a vault file and update the vault with the result.

    Reads an existing vault Markdown file, builds a Jira creation payload via
    the reverse mapper, calls the Jira API to create the issue, and writes the
    new ``jira_key`` / ``jira_url`` / ``synced_at`` back into the file's YAML
    frontmatter.  Also updates the sync state.

    If the file already has a ``jira_key`` in its frontmatter the function
    returns immediately with ``status="already_exists"`` (idempotent).

    Args:
        vault_path:   Absolute path to the Obsidian vault root.
        filename:     Filename to locate inside the vault
                      (e.g. ``"my-task.md"``).
        project_key:  Target Jira project key (e.g. ``"GO"``).
        issue_type:   Jira issue type (e.g. ``"Task"``, ``"Bug"``, ``"Epic"``).
        summary:      Issue summary/title.  Falls back to the frontmatter
                      ``title`` field or *filename* when empty.
        epic_key:     Optional epic key to link the new issue to.

    Returns:
        A result dict with a ``status`` key.  Possible values:

        - ``"ok"``            — issue created and vault updated successfully.
        - ``"already_exists"`` — ``jira_key`` already present in frontmatter.
        - ``"partial"``       — issue created in Jira but vault/state update
                                failed.
        - ``"error"``         — file not found or Jira API error.
    """
    logger.info(
        "create_and_sync: start filename=%s project_key=%s issue_type=%s summary=%r epic_key=%s",
        filename, project_key, issue_type, summary, epic_key,
    )

    # ------------------------------------------------------------------
    # 1. Locate the vault file
    # ------------------------------------------------------------------
    filepath = _find_vault_file(vault_path, filename)
    if filepath is None:
        logger.error("create_and_sync: file not found filename=%s vault_path=%s", filename, vault_path)
        return {"status": "error", "message": f"File not found: {filename}"}

    logger.info("create_and_sync: file located at %s", filepath)

    # ------------------------------------------------------------------
    # 2. Read frontmatter and body
    # ------------------------------------------------------------------
    fm, body = frontmatter_utils.read_frontmatter(filepath)
    logger.info("create_and_sync: frontmatter read, keys=%s", list(fm.keys()))

    # ------------------------------------------------------------------
    # 3. Idempotency check
    # ------------------------------------------------------------------
    existing_key = fm.get("jira_key")
    if existing_key:
        msg = f"Issue already exists: jira_key={existing_key}"
        logger.info("create_and_sync: idempotency check — %s", msg)
        return {
            "status": "already_exists",
            "jira_key": existing_key,
            "jira_url": fm.get("jira_url", ""),
            "message": msg,
        }

    # ------------------------------------------------------------------
    # 4. Summary fallback
    # ------------------------------------------------------------------
    if not summary:
        summary = fm.get("title", filename)
        logger.info("create_and_sync: summary empty, fell back to %r", summary)

    # ------------------------------------------------------------------
    # 5. Read full file content for reverse_map
    # ------------------------------------------------------------------
    full_content = filepath.read_text(encoding="utf-8")
    logger.info("create_and_sync: full file content read, length=%d chars", len(full_content))

    # ------------------------------------------------------------------
    # 6. Build Jira payload
    # ------------------------------------------------------------------
    payload = reverse_map(fm, full_content, project_key, issue_type, summary, epic_key)
    logger.info("create_and_sync: payload built for project_key=%s issue_type=%s", project_key, issue_type)

    # ------------------------------------------------------------------
    # 7. Create issue in Jira
    # ------------------------------------------------------------------
    try:
        result = jira_client.create_issue(payload)
        logger.info("create_and_sync: issue created jira_key=%s", result["key"])
    except JiraClientError as err:
        logger.error("create_and_sync: Jira API error: %s", err)
        return {"status": "error", "message": f"Jira API error: {err}"}

    # ------------------------------------------------------------------
    # 8. Build jira_url
    # ------------------------------------------------------------------
    jira_base_url, _ = jira_client._get_config()
    jira_url = f"{jira_base_url}/browse/{result['key']}"
    logger.info("create_and_sync: constructed jira_url=%s", jira_url)

    # ------------------------------------------------------------------
    # 9–10. Update vault file and sync state
    # ------------------------------------------------------------------
    try:
        updates = {
            "jira_key": result["key"],
            "jira_url": jira_url,
            "synced_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        }
        if epic_key:
            updates["epic_key"] = epic_key

        frontmatter_utils.update_frontmatter(filepath, updates)
        logger.info(
            "create_and_sync: vault frontmatter updated for file=%s jira_key=%s",
            filepath,
            result["key"],
        )

        st = sync_state.load(vault_path)
        domain = fm.get("domain", "general")
        status = fm.get("status", "todo")
        sync_state.update_entry(st, result["key"], status, "", domain)
        logger.info(
            "create_and_sync: state entry created jira_key=%s status=%s domain=%s",
            result["key"], status, domain,
        )

        # Determine artifact_type
        if "epics" in str(filepath):
            st["issues"][result["key"]]["artifact_type"] = "epics"
        else:
            art_type_raw = fm.get("type", "task").lower()
            art_type_value = _ISSUE_TYPE_TO_ARTIFACT.get(art_type_raw, "tasks")
            st["issues"][result["key"]]["artifact_type"] = art_type_value

        logger.info(
            "create_and_sync: artifact_type=%s set for jira_key=%s",
            st["issues"][result["key"]]["artifact_type"],
            result["key"],
        )

        sync_state.save(vault_path, st)
        logger.info("create_and_sync: sync state saved to vault_path=%s", vault_path)

    except Exception as err:
        logger.error(
            "create_and_sync: vault/state update failed for jira_key=%s: %s",
            result["key"],
            err,
        )
        return {
            "status": "partial",
            "jira_key": result["key"],
            "jira_url": jira_url,
            "filename": filename,
            "vault_updated": False,
            "message": f"Created {result['key']} but failed to update vault: {err}",
        }

    # ------------------------------------------------------------------
    # 11. Return success
    # ------------------------------------------------------------------
    logger.info(
        "create_and_sync: completed successfully jira_key=%s project_key=%s",
        result["key"],
        project_key,
    )
    return {
        "status": "ok",
        "jira_key": result["key"],
        "jira_url": jira_url,
        "filename": filename,
        "message": f"Created {result['key']} in project {project_key}",
    }

