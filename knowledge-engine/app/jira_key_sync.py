"""Extract Jira issue keys from protocol text, find which ones are
missing from the vault, and batch-import them via the jira-import CLI.

Used by the protocol pipeline to ensure every Jira key mentioned in
a protocol has a corresponding artifact in the vault.
"""

import json
import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_JIRA_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")
_ARTIFACT_TYPES = ("tasks", "epics", "bugs", "userstories")
_MAX_IMPORT_KEYS = 20


def extract_jira_keys(content: str) -> set[str]:
    """Return a deduplicated set of Jira issue keys found in *content*."""
    logger.info("extract_jira_keys: scanning content, len=%d", len(content))
    try:
        keys = set(_JIRA_KEY_RE.findall(content))
        logger.info("extract_jira_keys: found %d unique keys", len(keys))
        return keys
    except Exception as exc:
        logger.error("extract_jira_keys: failed: %s", exc)
        raise


def find_missing_in_vault(
    keys: set[str], vault_path: str,
) -> tuple[list[str], dict[str, str]]:
    """Check which *keys* have a corresponding .md file in the vault.

    Returns ``(missing, found_map)`` where *found_map* maps each found key
    to its relative vault path (e.g. ``wiki/domains/general/tasks/GO-153``).
    """
    logger.info(
        "find_missing_in_vault: checking %d keys against vault_path=%s",
        len(keys), vault_path,
    )
    domains_dir = Path(vault_path) / "wiki" / "domains"
    missing: list[str] = []
    found_map: dict[str, str] = {}

    try:
        if domains_dir.exists():
            domain_dirs = [d for d in domains_dir.iterdir() if d.is_dir()]
        else:
            logger.warning(
                "find_missing_in_vault: domains directory does not exist: %s",
                domains_dir,
            )
            domain_dirs = []
    except Exception as exc:
        logger.error(
            "find_missing_in_vault: failed to list domains directory: %s", exc,
        )
        raise

    for key in sorted(keys):
        found = False
        found_domain = ""
        found_type = ""
        for domain_dir in domain_dirs:
            for art_type in _ARTIFACT_TYPES:
                candidate = domain_dir / art_type / f"{key}.md"
                if candidate.exists():
                    found = True
                    found_domain = domain_dir.name
                    found_type = art_type
                    break
            if found:
                break

        if found:
            logger.info(
                "find_missing_in_vault: key=%s FOUND in domain=%s type=%s",
                key, found_domain, found_type,
            )
            found_map[key] = f"wiki/domains/{found_domain}/{found_type}/{key}"
        else:
            logger.info("find_missing_in_vault: key=%s MISSING", key)
            missing.append(key)

    logger.info(
        "find_missing_in_vault: completed, checked=%d, found=%d, missing=%d",
        len(keys), len(found_map), len(missing),
    )
    return sorted(missing), found_map


def import_missing_keys(keys: list[str]) -> dict:
    """Import each key via the ``jira-import`` CLI sub-command.

    Returns a dict with ``imported`` (successful) and ``failed`` lists.
    At most ``_MAX_IMPORT_KEYS`` keys are processed; the rest are skipped
    with a warning.
    """
    logger.info("import_missing_keys: starting, keys_count=%d", len(keys))
    imported: list[dict] = []
    failed: list[dict] = []

    if len(keys) > _MAX_IMPORT_KEYS:
        logger.warning(
            "import_missing_keys: %d keys exceed limit of %d, truncating",
            len(keys), _MAX_IMPORT_KEYS,
        )
        keys = keys[:_MAX_IMPORT_KEYS]

    for key in keys:
        logger.info("import_missing_keys: importing key=%s", key)
        try:
            proc = subprocess.run(
                ["python", "-m", "knowledge_engine", "jira-import", key],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            logger.error("import_missing_keys: key=%s timed out after 60s", key)
            failed.append({"key": key, "error": "timeout 60s"})
            continue
        except Exception as exc:
            logger.error("import_missing_keys: key=%s subprocess error: %s", key, exc)
            failed.append({"key": key, "error": str(exc)})
            continue

        if proc.returncode == 0:
            try:
                result = json.loads(proc.stdout)
                entry = {
                    "key": key,
                    "domain": result.get("domain", ""),
                    "artifact_type": result.get("artifact_type", "") or "tasks",
                    "action": result.get("action", ""),
                }
                imported.append(entry)
                logger.info(
                    "import_missing_keys: key=%s SUCCESS domain=%s artifact_type=%s action=%s",
                    key, entry["domain"], entry["artifact_type"], entry["action"],
                )
            except json.JSONDecodeError as exc:
                logger.error(
                    "import_missing_keys: key=%s returned rc=0 but invalid JSON: %s",
                    key, exc,
                )
                failed.append({"key": key, "error": f"invalid JSON: {exc}"})
        else:
            error_msg = proc.stderr.strip() or proc.stdout.strip()
            try:
                error_data = json.loads(proc.stdout)
                error_msg = error_data.get("message", error_msg)
            except (json.JSONDecodeError, ValueError):
                pass
            logger.error(
                "import_missing_keys: key=%s FAILED rc=%d error=%s",
                key, proc.returncode, error_msg,
            )
            failed.append({"key": key, "error": error_msg})

    logger.info(
        "import_missing_keys: completed, imported=%d, failed=%d",
        len(imported), len(failed),
    )
    return {"imported": imported, "failed": failed}


def sync_jira_keys(content: str, vault_path: str) -> dict:
    """Orchestrate extraction, vault lookup, and import of Jira keys.

    Returns a summary dict with ``keys``, ``missing``, ``imported``,
    and ``failed`` lists.
    """
    logger.info(
        "sync_jira_keys: starting, content_len=%d", len(content),
    )

    try:
        keys = extract_jira_keys(content)
    except Exception as exc:
        logger.error("sync_jira_keys: extract_jira_keys failed: %s", exc)
        raise

    if not keys:
        logger.info("sync_jira_keys: no keys found, returning early")
        return {
            "keys": [], "missing": [], "imported": [], "failed": [],
            "keys_map": {},
        }

    try:
        missing, found_map = find_missing_in_vault(keys, vault_path)
    except Exception as exc:
        logger.error("sync_jira_keys: find_missing_in_vault failed: %s", exc)
        raise

    imported: list[dict] = []
    failed: list[dict] = []

    if missing:
        try:
            result = import_missing_keys(missing)
            imported = result["imported"]
            failed = result["failed"]
        except Exception as exc:
            logger.error("sync_jira_keys: import_missing_keys failed: %s", exc)
            raise
        for item in imported:
            domain = item.get("domain", "general")
            art_type = item.get("artifact_type", "tasks")
            found_map[item["key"]] = f"wiki/domains/{domain}/{art_type}/{item['key']}"
    else:
        logger.info("sync_jira_keys: no missing keys, skipping import")

    summary = {
        "keys": sorted(keys),
        "missing": missing,
        "imported": imported,
        "failed": failed,
        "keys_map": found_map,
    }
    logger.info(
        "sync_jira_keys: completed: keys=%d, missing=%d, imported=%d, failed=%d",
        len(keys),
        len(missing),
        len(imported),
        len(failed),
    )
    return summary


sync_daily_jira_keys = sync_jira_keys


def patch_jira_links(filepath: str, keys_map: dict[str, str]) -> None:
    """Replace plain Jira keys with Obsidian wiki-links in the saved file.

    Only patches lines in the ``## Упомянутые задачи`` section to avoid
    touching keys in other sections (Action Items, Блокеры, etc.).
    Modifies the wiki copy only — raw/ stays immutable.
    """
    if not keys_map:
        logger.info("patch_jira_links: empty keys_map, skipping")
        return

    path = Path(filepath)
    if not path.exists():
        logger.warning("patch_jira_links: file not found: %s", filepath)
        return

    logger.info("patch_jira_links: patching %d keys in %s", len(keys_map), path.name)

    content = path.read_text(encoding="utf-8")
    lines = content.split("\n")
    in_section = False
    patched = 0

    for i, line in enumerate(lines):
        if line.strip() == "## Упомянутые задачи":
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section:
            for key, rel_path in keys_map.items():
                plain = f"- {key}"
                if line.strip() == plain:
                    lines[i] = f"- [[{rel_path}|{key}]]"
                    patched += 1
                    break

    if patched:
        path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("patch_jira_links: patched %d links in %s", patched, path.name)
    else:
        logger.info("patch_jira_links: no lines matched, file unchanged")


patch_daily_links = patch_jira_links
