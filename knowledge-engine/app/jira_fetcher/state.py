"""State tracker for Jira Fetcher.

Manages `.jira-sync-state.json` in the vault root to track which Jira issues
have been synced, detect changes, and identify closed issues.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

STATE_FILENAME = ".jira-sync-state.json"
STATE_VERSION = 1


def _empty_state() -> dict:
    """Return a fresh empty state dict."""
    return {
        "version": STATE_VERSION,
        "last_sync": "",
        "issues": {},
    }


def load(vault_path: "str | Path") -> dict:
    """Read `.jira-sync-state.json` from vault root and return parsed dict.

    If the file does not exist, returns a default empty state.
    If the file is corrupt (invalid JSON), logs a warning and returns an empty
    state without raising.

    Args:
        vault_path: Absolute path to the Obsidian vault root.

    Returns:
        Parsed state dict with keys ``version``, ``last_sync``, ``issues``.
    """
    path = Path(vault_path) / STATE_FILENAME
    logger.info("load: reading state from %s", path)

    if not path.exists():
        logger.info("load: state file not found, returning empty state")
        return _empty_state()

    try:
        raw = path.read_text(encoding="utf-8")
        state = json.loads(raw)
        issue_count = len(state.get("issues", {}))
        logger.info("load: loaded %d issues from state", issue_count)
        return state
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("load: state file is corrupt (%s), returning empty state", exc)
        return _empty_state()
    except Exception as exc:
        logger.warning("load: unexpected error reading state (%s), returning empty state", exc)
        return _empty_state()


def save(vault_path: "str | Path", state: dict) -> Path:
    """Write state to `.jira-sync-state.json` using an atomic write pattern.

    Updates ``last_sync`` to the current ISO timestamp before writing.

    Args:
        vault_path: Absolute path to the Obsidian vault root.
        state:      State dict to persist (mutated in place to set ``last_sync``).

    Returns:
        Path to the written state file.
    """
    path = Path(vault_path) / STATE_FILENAME
    logger.info("save: writing state to %s", path)

    state["last_sync"] = datetime.now().isoformat()
    issue_count = len(state.get("issues", {}))

    tmp_path = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(state, ensure_ascii=False, indent=2)
        tmp_path.write_text(content, encoding="utf-8")
        os.replace(str(tmp_path), str(path))
        logger.info("save: saved %d issues to state", issue_count)
    except Exception as exc:
        logger.error("save: failed to write state to %s: %s", path, exc)
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    return path


def diff(
    state: dict,
    current_issues: "list[dict]",
) -> "tuple[list[dict], list[dict], list[str]]":
    """Compare current Jira issues against persisted state.

    Args:
        state:          State dict as returned by :func:`load`.
        current_issues: List of Jira issue dicts.  Each dict must have
                        ``key`` (str) and ``fields`` (dict with ``updated`` str).

    Returns:
        A 3-tuple ``(new_issues, updated_issues, closed_keys)`` where:

        - ``new_issues``    — issues whose key is NOT yet in state.
        - ``updated_issues`` — issues whose key IS in state but whose
          ``fields.updated`` differs from the stored ``updated`` value.
        - ``closed_keys``  — keys that ARE in state but NOT in current_issues.
    """
    logger.info("diff: comparing %d current issues against state", len(current_issues))

    known: dict = state.get("issues", {})
    current_keys = {issue["key"] for issue in current_issues}

    new_issues: list[dict] = []
    updated_issues: list[dict] = []

    for issue in current_issues:
        key = issue["key"]
        fields_updated = issue.get("fields", {}).get("updated", "")

        if key not in known:
            new_issues.append(issue)
        elif known[key].get("updated", "") != fields_updated:
            updated_issues.append(issue)

    closed_keys: list[str] = [key for key in known if key not in current_keys]

    logger.info(
        "diff: %d new, %d updated, %d closed",
        len(new_issues),
        len(updated_issues),
        len(closed_keys),
    )
    return new_issues, updated_issues, closed_keys


def update_entry(
    state: dict,
    key: str,
    status: str,
    updated: str,
    domain: str,
) -> None:
    """Add or update a single issue entry in the state dict (in place).

    Sets ``synced_at`` to the current ISO timestamp.

    Args:
        state:   State dict to mutate.
        key:     Jira issue key, e.g. ``"GO-187"``.
        status:  Issue status string, e.g. ``"todo"``.
        updated: ISO timestamp of the issue's last update from Jira.
        domain:  Domain label for the issue, e.g. ``"suggester"``.
    """
    logger.info("update_entry: key=%s status=%s domain=%s", key, status, domain)
    state.setdefault("issues", {})[key] = {
        "status": status,
        "updated": updated,
        "domain": domain,
        "synced_at": datetime.now().isoformat(),
    }
    logger.info("update_entry: OK, total issues=%d", len(state["issues"]))


def mark_closed(state: dict, key: str) -> None:
    """Mark an issue as closed/done in the state dict (in place).

    Sets ``state["issues"][key]["status"]`` to ``"done"`` and updates
    ``synced_at`` to now.  If the key is not in state, logs a warning and
    returns without raising.

    Args:
        state: State dict to mutate.
        key:   Jira issue key to mark as closed.
    """
    logger.info("mark_closed: key=%s", key)
    issues: dict = state.get("issues", {})

    if key not in issues:
        logger.warning("mark_closed: key %s not found in state, skipping", key)
        return

    issues[key]["status"] = "done"
    issues[key]["synced_at"] = datetime.now().isoformat()
    logger.info("mark_closed: key=%s marked as done", key)
