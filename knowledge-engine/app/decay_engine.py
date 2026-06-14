from __future__ import annotations

import logging
import math
import os
import random
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import yaml

from shared.file_writer import file_lock
from shared.frontmatter_utils import read_frontmatter, update_frontmatter

logger = logging.getLogger(__name__)

_SKIP_FILENAMES = frozenset({"INDEX.md", "LOG.md", "index.md", "log.md", "glossary.md", "decisions.md"})

_PATH_TYPE_MAP = {
    "ideas": "idea",
    "tasks": "task",
    "epics": "epic",
    "bugs": "bug",
    "knowledge": "knowledge",
    "prds": "prd",
    "userstories": "userstory",
    "meetings": "meeting",
    "daily-logs": "daily-log",
    "reports": "report",
}


@dataclass
class DecayConfig:
    floor: float = 0.05
    tier_thresholds: dict[str, int] = field(default_factory=lambda: {"active": 7, "warm": 21, "cold": 60})
    default_rate: float = 0.020
    rates: dict[str, float] = field(default_factory=lambda: {
        "idea": 0.020, "task": 0.025, "epic": 0.015, "prd": 0.023,
        "meeting": 0.030, "daily-log": 0.040, "report": 0.015,
        "knowledge": 0.010, "bug": 0.030, "userstory": 0.020, "concept": 0.015,
    })


def load_config(config_path: str = "/app/decay.yaml") -> DecayConfig:
    logger.info(f"load_config: loading from {config_path}")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        if not isinstance(raw, dict):
            logger.warning(f"load_config: invalid YAML structure in {config_path}, using defaults")
            return DecayConfig()
        defaults = DecayConfig()
        cfg = DecayConfig(
            floor=raw.get("floor", defaults.floor),
            tier_thresholds=raw.get("tier_thresholds", defaults.tier_thresholds),
            default_rate=raw.get("default_rate", defaults.default_rate),
            rates=raw.get("rates", defaults.rates),
        )
        logger.info(f"load_config: loaded successfully from {config_path}")
        return cfg
    except FileNotFoundError:
        logger.info(f"load_config: file {config_path} not found, using built-in defaults")
        return DecayConfig()
    except Exception as exc:
        logger.warning(f"load_config: error reading {config_path}: {exc}, using built-in defaults")
        return DecayConfig()


def calc_relevance(days_since_access: int, access_count: int, rate: float, floor: float = 0.05) -> float:
    strength = 1 + math.log(max(1, access_count))
    effective_rate = rate / strength
    return max(floor, 1.0 - effective_rate * days_since_access)


def calc_tier(days_since_access: int, thresholds: dict[str, int]) -> str:
    if days_since_access <= thresholds["active"]:
        return "active"
    elif days_since_access <= thresholds["warm"]:
        return "warm"
    elif days_since_access <= thresholds["cold"]:
        return "cold"
    else:
        return "archive"


def _parse_date(value: str | date | datetime) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).date()
        except (ValueError, TypeError):
            return None
    try:
        return datetime.fromisoformat(str(value)).date()
    except (ValueError, TypeError):
        return None


def _parse_readiness(value) -> int:
    """Parse readiness value from frontmatter.

    Handles int, float, str (with optional '%'), None.
    Returns 0 on any parse error.
    """
    try:
        if value is None:
            logger.debug("_parse_readiness: value is None, returning 0")
            return 0
        if isinstance(value, (int, float)):
            result = int(value)
            logger.debug(f"_parse_readiness: numeric value={value}, returning {result}")
            return result
        if isinstance(value, str):
            cleaned = value.strip().rstrip("%").strip()
            result = int(cleaned)
            logger.debug(f"_parse_readiness: parsed string '{value}' -> {result}")
            return result
        result = int(value)
        logger.debug(f"_parse_readiness: fallback int() on {type(value).__name__}, returning {result}")
        return result
    except (ValueError, TypeError) as exc:
        logger.warning(f"_parse_readiness: failed to parse value={value!r}, error={exc}, returning 0")
        return 0


def _get_artifact_type(filepath: str, frontmatter: dict) -> str:
    fm_type = frontmatter.get("type")
    if fm_type and isinstance(fm_type, str) and fm_type.strip():
        return fm_type.strip()

    path_str = filepath.replace("\\", "/")
    for path_component, artifact_type in _PATH_TYPE_MAP.items():
        if f"/{path_component}/" in path_str:
            return artifact_type

    return "idea"


def _collect_md_files(vault_path: str) -> list[Path]:
    logger.info(f"_collect_md_files: scanning vault at {vault_path}")
    wiki = Path(vault_path) / "wiki"
    scan_dirs: list[Path] = []

    domains_root = wiki / "domains"
    if domains_root.is_dir():
        for domain_dir in sorted(domains_root.iterdir()):
            if domain_dir.is_dir():
                for sub in ("ideas", "tasks", "epics", "bugs", "knowledge", "prds", "userstories"):
                    candidate = domain_dir / sub
                    if candidate.is_dir():
                        scan_dirs.append(candidate)

    for top_level in ("meetings", "daily-logs", "reports"):
        candidate = wiki / top_level
        if candidate.is_dir():
            scan_dirs.append(candidate)

    collected: list[Path] = []
    for scan_dir in scan_dirs:
        for md_file in sorted(scan_dir.rglob("*.md")):
            if not md_file.is_file():
                continue
            if md_file.name in _SKIP_FILENAMES:
                continue
            file_str = str(md_file).replace("\\", "/")
            if "/_index/" in file_str or "\\_index\\" in str(md_file):
                continue
            collected.append(md_file)

    logger.info(f"_collect_md_files: found {len(collected)} files in {len(scan_dirs)} directories")
    return collected


def recalc_vault(vault_path: str, config: DecayConfig | None = None, dry_run: bool = False) -> dict:
    logger.info(f"recalc_vault: starting, vault_path={vault_path}, dry_run={dry_run}")

    if config is None:
        config = load_config()

    today = date.today()
    md_files = _collect_md_files(vault_path)

    processed = 0
    skipped = 0
    transitions: list[dict] = []
    errors: list[dict] = []

    for filepath in md_files:
        try:
            frontmatter, _ = read_frontmatter(filepath)

            if not frontmatter:
                skipped += 1
                continue

            if frontmatter.get("tier") == "core":
                skipped += 1
                continue

            last_accessed_raw = (
                frontmatter.get("last_accessed")
                or frontmatter.get("updated")
                or frontmatter.get("created")
            )

            if last_accessed_raw is not None:
                last_accessed_date = _parse_date(last_accessed_raw)
            else:
                mtime_ts = os.path.getmtime(filepath)
                last_accessed_date = datetime.fromtimestamp(mtime_ts).date()

            if last_accessed_date is None:
                logger.warning(f"recalc_vault: cannot parse date for {filepath}, skipping")
                skipped += 1
                continue

            days = (today - last_accessed_date).days
            access_count = int(frontmatter.get("access_count", 0))
            artifact_type = _get_artifact_type(str(filepath), frontmatter)
            rate = config.rates.get(artifact_type, config.default_rate)

            new_relevance = round(calc_relevance(days, access_count, rate, config.floor), 2)
            new_tier = calc_tier(days, config.tier_thresholds)

            old_relevance = frontmatter.get("relevance")
            old_tier = frontmatter.get("tier")

            if new_relevance != old_relevance or new_tier != old_tier:
                if not dry_run:
                    with file_lock(filepath):
                        update_frontmatter(filepath, {"relevance": new_relevance, "tier": new_tier})

                if old_tier is not None and old_tier != new_tier:
                    transitions.append({"file": str(filepath), "from": old_tier, "to": new_tier})

            processed += 1

        except Exception as exc:
            logger.warning(f"recalc_vault: error processing {filepath}: {exc}")
            errors.append({"file": str(filepath), "error": str(exc)})

    logger.info(
        f"recalc_vault: completed, processed={processed}, skipped={skipped}, "
        f"transitions={len(transitions)}, errors={len(errors)}"
    )
    return {"processed": processed, "skipped": skipped, "transitions": transitions, "errors": errors}


def touch(filepath: str, vault_path: str, config: DecayConfig | None = None) -> dict:
    logger.info(f"touch: filepath={filepath}")

    if config is None:
        config = load_config()

    full_path = Path(vault_path) / filepath if not Path(filepath).is_absolute() else Path(filepath)

    try:
        frontmatter, _ = read_frontmatter(full_path)
    except Exception as exc:
        logger.warning(f"touch: error reading {full_path}: {exc}")
        return {"status": "skip", "reason": "no frontmatter"}

    if not frontmatter:
        logger.warning(f"touch: no frontmatter in {full_path}")
        return {"status": "skip", "reason": "no frontmatter"}

    old_tier = frontmatter.get("tier", "active")

    if "relevance" not in frontmatter:
        frontmatter["relevance"] = 1.0
        frontmatter["tier"] = "active"
        frontmatter["last_accessed"] = str(date.today())
        frontmatter["access_count"] = 0

    access_count = int(frontmatter.get("access_count", 0)) + 1
    last_accessed = str(date.today())

    artifact_type = _get_artifact_type(str(full_path), frontmatter)
    rate = config.rates.get(artifact_type, config.default_rate)

    new_relevance = round(calc_relevance(0, access_count, rate, config.floor), 2)
    new_tier = calc_tier(0, config.tier_thresholds)

    with file_lock(full_path):
        update_frontmatter(full_path, {
            "relevance": new_relevance,
            "tier": new_tier,
            "last_accessed": last_accessed,
            "access_count": access_count,
        })

    logger.info(f"touch: completed, access_count={access_count}, tier: {old_tier}->{new_tier}")
    return {"status": "ok", "access_count": access_count, "old_tier": old_tier, "new_tier": new_tier}


def set_tier(filepath: str, tier: str, vault_path: str, config: DecayConfig | None = None) -> dict:
    logger.info(f"set_tier: filepath={filepath}, tier={tier}")

    valid_tiers = {"core", "active", "warm", "cold", "archive"}
    if tier not in valid_tiers:
        logger.warning(f"set_tier: invalid tier: {tier}")
        return {"status": "error", "reason": f"invalid tier: {tier}"}

    if config is None:
        config = load_config()

    full_path = Path(vault_path) / filepath if not Path(filepath).is_absolute() else Path(filepath)

    try:
        frontmatter, _ = read_frontmatter(full_path)
    except Exception as exc:
        logger.warning(f"set_tier: error reading {full_path}: {exc}")
        return {"status": "skip", "reason": "no frontmatter"}

    if not frontmatter:
        logger.warning(f"set_tier: no frontmatter in {full_path}")
        return {"status": "skip", "reason": "no frontmatter"}

    old_tier = frontmatter.get("tier", "active")

    updates: dict = {"tier": tier}

    if tier == "active":
        updates["last_accessed"] = str(date.today())
        access_count = int(frontmatter.get("access_count", 0))
        artifact_type = _get_artifact_type(str(full_path), frontmatter)
        rate = config.rates.get(artifact_type, config.default_rate)
        updates["relevance"] = round(calc_relevance(0, access_count, rate, config.floor), 2)
    elif tier == "core":
        updates["relevance"] = 1.0

    with file_lock(full_path):
        update_frontmatter(full_path, updates)

    logger.info(f"set_tier: completed, old_tier={old_tier}, new_tier={tier}")
    return {"status": "ok", "old_tier": old_tier, "new_tier": tier}


def get_creative(vault_path: str, count: int = 5) -> list[dict]:
    logger.info(f"get_creative: starting, count={count}")
    vault = Path(vault_path)
    scan_patterns = [
        vault / "wiki" / "domains" / "*" / "ideas" / "*.md",
        vault / "wiki" / "domains" / "*" / "tasks" / "*.md",
    ]
    candidates = []
    for pattern in scan_patterns:
        for md_file in sorted(vault.glob(str(pattern.relative_to(vault)))):
            if not md_file.is_file():
                continue
            if md_file.name in _SKIP_FILENAMES:
                continue
            try:
                frontmatter, _ = read_frontmatter(md_file)
            except Exception as exc:
                logger.warning(f"get_creative: error reading {md_file}: {exc}")
                continue
            if not frontmatter:
                continue
            tier = frontmatter.get("tier", "")
            if tier not in ("cold", "archive"):
                continue
            status = str(frontmatter.get("status", "")).strip().lower()
            if status == "отсев":
                continue
            rel_path = md_file.relative_to(vault)
            parts = rel_path.parts
            domain = ""
            if "domains" in parts:
                idx = parts.index("domains")
                if idx + 1 < len(parts):
                    domain = parts[idx + 1]
            candidates.append({
                "filepath": str(rel_path).replace("\\", "/"),
                "title": frontmatter.get("title", md_file.stem),
                "domain": domain,
                "created": str(frontmatter.get("created", "")),
                "tier": tier,
                "readiness": _parse_readiness(frontmatter.get("readiness", 0)),
                "id": frontmatter.get("id", md_file.stem),
            })
    selected = random.sample(candidates, min(count, len(candidates))) if candidates else []
    logger.info(f"get_creative: completed, found={len(candidates)}, selected={len(selected)}")
    return selected


def init_vault(vault_path: str, config: DecayConfig | None = None, dry_run: bool = False) -> dict:
    logger.info(f"init_vault: starting, vault_path={vault_path}, dry_run={dry_run}")

    if config is None:
        config = load_config()

    today = date.today()
    md_files = _collect_md_files(vault_path)

    migrated = 0
    skipped = 0
    details: list[dict] = []

    for filepath in md_files:
        try:
            frontmatter, _ = read_frontmatter(filepath)

            if not frontmatter:
                skipped += 1
                continue

            if "relevance" in frontmatter:
                skipped += 1
                continue

            last_date_raw = None
            for key in ("updated", "updated_at", "synced_at", "created", "created_at"):
                val = frontmatter.get(key)
                if val is not None:
                    last_date_raw = val
                    break

            if last_date_raw is not None:
                last_date = _parse_date(last_date_raw)
            else:
                mtime_ts = os.path.getmtime(filepath)
                last_date = datetime.fromtimestamp(mtime_ts).date()

            if last_date is None:
                logger.warning(f"init_vault: cannot parse date for {filepath}, skipping")
                skipped += 1
                continue

            days = (today - last_date).days

            file_str = str(filepath).replace("\\", "/")
            is_adr = "/adr/" in file_str or frontmatter.get("type") == "adr"

            if is_adr:
                tier = "core"
                relevance = 1.0
            elif days <= 7:
                tier = "active"
                relevance = 1.0
            elif days <= 21:
                tier = "warm"
                relevance = 0.7
            elif days <= 60:
                tier = "cold"
                relevance = 0.4
            else:
                tier = "archive"
                relevance = 0.1

            updates = {"tier": tier, "relevance": relevance, "last_accessed": str(last_date), "access_count": 1}

            if not dry_run:
                with file_lock(filepath):
                    update_frontmatter(filepath, updates)

            details.append({"file": str(filepath), "tier": tier, "relevance": relevance})
            migrated += 1

        except Exception as exc:
            logger.warning(f"init_vault: error processing {filepath}: {exc}")
            skipped += 1

    logger.info(f"init_vault: completed, migrated={migrated}, skipped={skipped}")
    return {"migrated": migrated, "skipped": skipped, "details": details}
