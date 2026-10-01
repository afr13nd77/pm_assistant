"""Central reader/writer for <VAULT_PATH>/domain-config.yaml.

Used by mapper.py (jira sync) and CLI to read and write domain configuration.
Provides mtime-based caching, validation, and atomic writes.
"""

import logging
import os
import re
from pathlib import Path

import yaml

from shared import vault_paths
from shared.file_writer import atomic_write

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

_DEFAULT_COLOR = "#607D8B"
_MAX_DOMAINS = 100
_MAX_DISPLAY_NAME = 100
_MAX_DESCRIPTION = 500
_MAX_PROMPT_HINT = 500

_YAML_HEADER = (
    "# Domain Configuration\n"
    "# Managed via Web UI or CLI. Manual edits are also supported.\n"
    "\n"
)

# Module-level cache
_cache: dict | None = None
_cache_mtime: float = 0.0


def config_path() -> Path:
    """Return path to domain-config.yaml."""
    logger.debug("config_path: returning %s", vault_paths.domain_config_path())
    return vault_paths.domain_config_path()


def load() -> dict:
    """Load config with mtime-based caching.

    Returns {"domains": {}} on missing file or invalid YAML.
    """
    global _cache, _cache_mtime

    path = config_path()

    if not path.exists():
        logger.warning("load: config file not found at %s, returning empty config", path)
        return {"domains": {}}

    try:
        current_mtime = os.stat(path).st_mtime
    except OSError as exc:
        logger.warning("load: cannot stat %s: %s, returning empty config", path, exc)
        return {"domains": {}}

    if _cache is not None and current_mtime == _cache_mtime:
        logger.debug("load: cache hit for %s (mtime=%s)", path, current_mtime)
        return _cache

    logger.info("load: reading config from %s (mtime=%s)", path, current_mtime)
    try:
        raw = path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
    except Exception as exc:
        logger.warning("load: failed to parse YAML at %s: %s, returning empty config", path, exc)
        return {"domains": {}}

    if not isinstance(data, dict):
        logger.warning(
            "load: parsed YAML is not a dict (got %s) at %s, returning empty config",
            type(data).__name__,
            path,
        )
        return {"domains": {}}

    if "domains" not in data:
        data["domains"] = {}

    _cache = data
    _cache_mtime = current_mtime
    logger.info("load: config loaded successfully — %d domain(s)", len(data.get("domains", {})))
    return _cache


def save(config: dict) -> None:
    """Atomic write of config to disk. Validates first, raises ValueError on failure."""
    global _cache, _cache_mtime

    logger.info("save: validating config before write")
    errors = validate(config)
    if errors:
        msg = "save: config validation failed — " + "; ".join(errors)
        logger.warning(msg)
        raise ValueError(msg)

    path = config_path()
    content = _YAML_HEADER + yaml.dump(
        config,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=120,
    )

    logger.info("save: writing config to %s (%d domains)", path, len(config.get("domains", {})))
    try:
        atomic_write(path, content)
    except Exception as exc:
        logger.error("save: atomic_write failed for %s: %s", path, exc)
        raise

    try:
        _cache_mtime = os.stat(path).st_mtime
    except OSError as exc:
        logger.warning("save: cannot stat after write, cache mtime reset: %s", exc)
        _cache_mtime = 0.0

    _cache = config
    logger.info("save: config saved successfully to %s", path)


def validate(config: dict) -> list[str]:
    """Validate full config. Returns list of error strings (empty = valid)."""
    errors: list[str] = []

    if not isinstance(config, dict):
        errors.append("config must be a dict")
        logger.warning("validate: config is not a dict")
        return errors

    domains = config.get("domains")
    if not isinstance(domains, dict):
        errors.append("'domains' must be a dict")
        logger.warning("validate: 'domains' key is missing or not a dict")
        return errors

    if len(domains) > _MAX_DOMAINS:
        errors.append(f"too many domains: {len(domains)} exceeds limit of {_MAX_DOMAINS}")
        logger.warning("validate: domain count %d exceeds limit %d", len(domains), _MAX_DOMAINS)

    # Check label uniqueness across all domains (case-insensitive)
    label_to_domain: dict[str, str] = {}
    for slug, entry in domains.items():
        entry_errors = validate_domain_entry(slug, entry)
        if entry_errors:
            for e in entry_errors:
                errors.append(f"domain {slug!r}: {e}")

        if isinstance(entry, dict):
            for label in entry.get("jira_labels", []):
                if isinstance(label, str):
                    key = label.lower()
                    if key in label_to_domain and label_to_domain[key] != slug:
                        errors.append(
                            f"label {label!r} is used by both {label_to_domain[key]!r} and {slug!r}"
                        )
                        logger.warning(
                            "validate: label conflict — %r belongs to both %r and %r",
                            label,
                            label_to_domain[key],
                            slug,
                        )
                    else:
                        label_to_domain[key] = slug

    if errors:
        logger.warning("validate: found %d error(s): %s", len(errors), errors)
    else:
        logger.debug("validate: config is valid (%d domains)", len(domains))

    return errors


def validate_domain_entry(slug: str, entry: dict) -> list[str]:
    """Validate a single domain entry. Returns list of error strings (empty = valid)."""
    errors: list[str] = []

    if not isinstance(slug, str) or not _SLUG_RE.match(slug):
        errors.append(
            f"slug {slug!r} is invalid; must match ^[a-z0-9]+(?:-[a-z0-9]+)*$"
        )
        logger.warning("validate_domain_entry: invalid slug %r", slug)

    if not isinstance(entry, dict):
        errors.append("entry must be a dict")
        logger.warning("validate_domain_entry: entry for slug %r is not a dict", slug)
        return errors

    # display_name: required, non-empty string, max 100 chars
    display_name = entry.get("display_name")
    if not display_name:
        errors.append("'display_name' is required and must be non-empty")
        logger.warning("validate_domain_entry: missing display_name for slug %r", slug)
    elif not isinstance(display_name, str):
        errors.append("'display_name' must be a string")
        logger.warning("validate_domain_entry: display_name for slug %r is not a string", slug)
    elif len(display_name) > _MAX_DISPLAY_NAME:
        errors.append(
            f"'display_name' exceeds max length {_MAX_DISPLAY_NAME} (got {len(display_name)})"
        )
        logger.warning(
            "validate_domain_entry: display_name for slug %r is too long (%d > %d)",
            slug, len(display_name), _MAX_DISPLAY_NAME,
        )

    # description: optional string, max 500 chars
    description = entry.get("description", "")
    if description is not None:
        if not isinstance(description, str):
            errors.append("'description' must be a string")
            logger.warning("validate_domain_entry: description for slug %r is not a string", slug)
        elif len(description) > _MAX_DESCRIPTION:
            errors.append(
                f"'description' exceeds max length {_MAX_DESCRIPTION} (got {len(description)})"
            )
            logger.warning(
                "validate_domain_entry: description for slug %r is too long (%d > %d)",
                slug, len(description), _MAX_DESCRIPTION,
            )

    # color: optional, must match #RRGGBB
    color = entry.get("color", _DEFAULT_COLOR)
    if color is not None:
        if not isinstance(color, str):
            errors.append("'color' must be a string")
            logger.warning("validate_domain_entry: color for slug %r is not a string", slug)
        elif not _COLOR_RE.match(color):
            errors.append(f"'color' {color!r} must match ^#[0-9A-Fa-f]{{6}}$")
            logger.warning(
                "validate_domain_entry: invalid color %r for slug %r", color, slug
            )

    # jira_labels: optional list of non-empty strings
    jira_labels = entry.get("jira_labels", [])
    if jira_labels is not None:
        if not isinstance(jira_labels, list):
            errors.append("'jira_labels' must be a list")
            logger.warning("validate_domain_entry: jira_labels for slug %r is not a list", slug)
        else:
            for i, label in enumerate(jira_labels):
                if not isinstance(label, str) or not label:
                    errors.append(f"'jira_labels[{i}]' must be a non-empty string")
                    logger.warning(
                        "validate_domain_entry: jira_labels[%d] for slug %r is invalid: %r",
                        i, slug, label,
                    )

    # tags: optional list of non-empty strings (for clipping tag-to-domain matching)
    tags = entry.get("tags", [])
    if tags is not None:
        if not isinstance(tags, list):
            errors.append("'tags' must be a list")
            logger.warning("validate_domain_entry: tags for slug %r is not a list", slug)
        else:
            for i, tag in enumerate(tags):
                if not isinstance(tag, str) or not tag:
                    errors.append(f"'tags[{i}]' must be a non-empty string")
                    logger.warning(
                        "validate_domain_entry: tags[%d] for slug %r is invalid: %r",
                        i, slug, tag,
                    )

    # keywords: optional list of non-empty strings
    keywords = entry.get("keywords", [])
    if keywords is not None:
        if not isinstance(keywords, list):
            errors.append("'keywords' must be a list")
            logger.warning(
                "validate_domain_entry: keywords for slug %r is not a list", slug
            )
        else:
            for i, kw in enumerate(keywords):
                if not isinstance(kw, str) or not kw:
                    errors.append(f"'keywords[{i}]' must be a non-empty string")
                    logger.warning(
                        "validate_domain_entry: keywords[%d] for slug %r is invalid: %r",
                        i, slug, kw,
                    )

    # prompt_hint: optional string, max _MAX_PROMPT_HINT chars
    prompt_hint = entry.get("prompt_hint", "")
    if prompt_hint is not None:
        if not isinstance(prompt_hint, str):
            errors.append("'prompt_hint' must be a string")
            logger.warning(
                "validate_domain_entry: prompt_hint for slug %r is not a string", slug
            )
        elif len(prompt_hint) > _MAX_PROMPT_HINT:
            errors.append(
                f"'prompt_hint' exceeds max length {_MAX_PROMPT_HINT} "
                f"(got {len(prompt_hint)})"
            )
            logger.warning(
                "validate_domain_entry: prompt_hint for slug %r is too long (%d > %d)",
                slug, len(prompt_hint), _MAX_PROMPT_HINT,
            )

    if errors:
        logger.debug(
            "validate_domain_entry: %d error(s) for slug %r: %s", len(errors), slug, errors
        )
    else:
        logger.debug("validate_domain_entry: entry for slug %r is valid", slug)

    return errors


def get_domain(slug: str) -> dict | None:
    """Get a single domain entry by slug, or None if not found."""
    logger.debug("get_domain: looking up slug=%r", slug)
    config = load()
    entry = config.get("domains", {}).get(slug)
    if entry is None:
        logger.debug("get_domain: slug=%r not found", slug)
    else:
        logger.debug("get_domain: found entry for slug=%r", slug)
    return entry


def set_domain(slug: str, entry: dict, config: dict | None = None) -> dict:
    """Add or update a domain entry. Returns updated config.

    Raises ValueError on slug/entry validation failure or label conflict.
    """
    logger.info("set_domain: slug=%r", slug)

    if config is None:
        config = load()
        logger.debug("set_domain: loaded config from disk for slug=%r", slug)
    else:
        logger.debug("set_domain: using provided config for slug=%r", slug)

    # Validate the new entry itself
    entry_errors = validate_domain_entry(slug, entry)
    if entry_errors:
        msg = f"set_domain: invalid entry for slug {slug!r}: " + "; ".join(entry_errors)
        logger.warning(msg)
        raise ValueError(msg)

    # Check label uniqueness: no OTHER domain may own the same label
    new_labels = {lbl.lower() for lbl in entry.get("jira_labels", []) if isinstance(lbl, str)}
    domains = config.get("domains", {})
    for other_slug, other_entry in domains.items():
        if other_slug == slug:
            continue
        if not isinstance(other_entry, dict):
            continue
        for other_label in other_entry.get("jira_labels", []):
            if isinstance(other_label, str) and other_label.lower() in new_labels:
                msg = (
                    f"set_domain: label {other_label!r} is already owned by domain "
                    f"{other_slug!r}; cannot assign to {slug!r}"
                )
                logger.warning(msg)
                raise ValueError(msg)

    # Merge with existing entry to preserve fields not passed (e.g. Web UI)
    existing = config.get("domains", {}).get(slug)

    # Normalize entry — fill in defaults for missing optional fields
    normalized = {
        "display_name": entry["display_name"],
        "description": entry.get("description", ""),
        "color": entry.get("color", _DEFAULT_COLOR),
        "jira_labels": entry.get("jira_labels", []),
        "tags": entry.get("tags", existing.get("tags", []) if existing else []),
        "keywords": entry.get("keywords", existing.get("keywords", []) if existing else []),
        "prompt_hint": entry.get("prompt_hint", existing.get("prompt_hint", "") if existing else ""),
    }

    config.setdefault("domains", {})[slug] = normalized

    # Full validation before saving
    full_errors = validate(config)
    if full_errors:
        msg = "set_domain: post-merge validation failed: " + "; ".join(full_errors)
        logger.warning(msg)
        raise ValueError(msg)

    save(config)
    logger.info("set_domain: domain %r saved successfully", slug)
    return config


def build_label_map() -> dict[str, str]:
    """Build {label_lower: domain_slug} map from config."""
    logger.info("build_label_map: building label map from config")
    config = load()
    label_map: dict[str, str] = {}
    domains = config.get("domains", {})
    for slug, entry in domains.items():
        if not isinstance(entry, dict):
            logger.warning(
                "build_label_map: entry for slug %r is not a dict, skipping", slug
            )
            continue
        for label in entry.get("jira_labels", []):
            if isinstance(label, str) and label:
                key = label.lower()
                if key in label_map:
                    logger.warning(
                        "build_label_map: duplicate label %r (domains %r and %r) — keeping first",
                        label, label_map[key], slug,
                    )
                else:
                    label_map[key] = slug

    logger.info("build_label_map: built map with %d label(s) from %d domain(s)",
                len(label_map), len(domains))
    return label_map


def build_tag_map() -> dict[str, str]:
    """Build {tag_lower: domain_slug} map from config.

    Uses the 'tags' field from each domain entry. If not present,
    falls back to 'jira_labels' for backward compatibility.
    """
    config = load()
    tag_map: dict[str, str] = {}
    domains = config.get("domains", {})
    for slug, entry in domains.items():
        if not isinstance(entry, dict):
            continue
        for tag in entry.get("tags", []):
            if isinstance(tag, str) and tag:
                key = tag.lower()
                if key not in tag_map:
                    tag_map[key] = slug
        for label in entry.get("jira_labels", []):
            if isinstance(label, str) and label:
                key = label.lower()
                if key not in tag_map:
                    tag_map[key] = slug
    logger.info("build_tag_map: built map with %d entries", len(tag_map))
    return tag_map


def build_keyword_map() -> dict[str, str]:
    """Build {keyword_lower: domain_slug} map from config."""
    logger.info("build_keyword_map: building keyword map from config")
    config = load()
    keyword_map: dict[str, str] = {}
    domains = config.get("domains", {})

    for slug, entry in domains.items():
        if not isinstance(entry, dict):
            logger.warning(
                "build_keyword_map: entry for slug %r is not a dict, skipping", slug
            )
            continue
        for kw in entry.get("keywords", []):
            if isinstance(kw, str) and kw:
                key = kw.lower()
                if key in keyword_map:
                    logger.warning(
                        "build_keyword_map: duplicate keyword %r (domains %r and %r) "
                        "— keeping first",
                        kw, keyword_map[key], slug,
                    )
                else:
                    keyword_map[key] = slug

    logger.info(
        "build_keyword_map: built map with %d keyword(s) from %d domain(s)",
        len(keyword_map), len(domains),
    )
    return keyword_map


def build_prompt_section() -> str:
    """Generate the domain list section for LLM prompt.

    For each domain, uses prompt_hint if present, otherwise falls back
    to description.
    """
    logger.info("build_prompt_section: generating prompt section from config")
    config = load()
    domains = config.get("domains", {})

    if not domains:
        logger.warning("build_prompt_section: no domains in config, returning empty")
        return ""

    lines: list[str] = []
    for slug, entry in domains.items():
        if not isinstance(entry, dict):
            continue
        hint = entry.get("prompt_hint", "").strip()
        if not hint:
            hint = entry.get("description", "").strip()
        if not hint:
            hint = slug
        lines.append(f"- {slug} — {hint}")

    section = "\n".join(lines)
    logger.info(
        "build_prompt_section: generated section with %d domain(s) (%d chars)",
        len(lines), len(section),
    )
    return section


def get_valid_domains() -> tuple[str, ...]:
    """Return tuple of all domain slugs from config."""
    logger.info("get_valid_domains: reading domain slugs from config")
    config = load()
    domains = config.get("domains", {})
    slugs = tuple(domains.keys())
    logger.info("get_valid_domains: found %d domain(s): %s", len(slugs), slugs)
    return slugs


def seed_from_defaults(hardcoded_map: dict[str, str], existing_domains: list[str]) -> dict:
    """Create initial config from hardcoded map and filesystem domains.

    Idempotent: if config file already exists, loads and returns it unchanged.

    Args:
        hardcoded_map: {label: domain_slug} mapping from the legacy/hardcoded source.
        existing_domains: list of domain slugs found on the filesystem.

    Returns:
        The resulting config dict (loaded or newly created).
    """
    path = config_path()

    if path.exists():
        logger.info(
            "seed_from_defaults: config already exists at %s, loading and returning", path
        )
        return load()

    logger.info(
        "seed_from_defaults: no config found — seeding from %d label(s) and %d filesystem domain(s)",
        len(hardcoded_map),
        len(existing_domains),
    )

    # Invert hardcoded_map: {domain_slug: [labels]}
    domain_labels: dict[str, list[str]] = {}
    for label, domain_slug in hardcoded_map.items():
        domain_labels.setdefault(domain_slug, []).append(label)

    domains: dict[str, dict] = {}

    # Add entries from hardcoded_map
    for slug, labels in domain_labels.items():
        if not _SLUG_RE.match(slug):
            logger.warning(
                "seed_from_defaults: skipping invalid slug %r from hardcoded_map", slug
            )
            continue
        domains[slug] = {
            "display_name": slug,
            "description": "",
            "color": _DEFAULT_COLOR,
            "jira_labels": labels,
            "tags": [],
            "keywords": [],
            "prompt_hint": "",
        }
        logger.debug(
            "seed_from_defaults: added domain %r with labels %r",
            slug, labels,
        )

    # Add filesystem domains not already present
    for slug in existing_domains:
        if slug in domains:
            logger.debug(
                "seed_from_defaults: filesystem domain %r already covered by hardcoded_map", slug
            )
            continue
        if not _SLUG_RE.match(slug):
            logger.warning(
                "seed_from_defaults: skipping invalid filesystem domain slug %r", slug
            )
            continue
        domains[slug] = {
            "display_name": slug,
            "description": "",
            "color": _DEFAULT_COLOR,
            "jira_labels": [],
            "tags": [],
            "keywords": [],
            "prompt_hint": "",
        }
        logger.debug("seed_from_defaults: added filesystem-only domain %r", slug)

    # Ensure a "general" domain always exists for cross-domain tasks
    if "general" not in domains:
        domains["general"] = {
            "display_name": "General",
            "description": "Cross-domain tasks",
            "color": _DEFAULT_COLOR,
            "jira_labels": [],
            "tags": ["general"],
            "keywords": [],
            "prompt_hint": "tasks not belonging to a specific domain",
        }
        logger.debug("seed_from_defaults: added default 'general' domain")

    config = {"domains": domains}

    logger.info("seed_from_defaults: saving seeded config with %d domain(s)", len(domains))
    save(config)
    logger.info("seed_from_defaults: done")
    return config
