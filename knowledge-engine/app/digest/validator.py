"""Digest validation against token budgets and required fields."""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from .templates import get_required_fields

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate(
    digest_data: dict,
    source_path: Path,
    vault_path: str,
    token_counts: dict,
) -> ValidationResult:
    """Validate digest against token budgets, required fields, and format rules.

    Args:
        digest_data: dict with keys: frontmatter, one_liner, core_digest,
            extended_digest, changelog, artifact_type
        source_path: path to original wiki/ file
        vault_path: vault root path
        token_counts: dict with keys: one_liner, core_digest, extended_digest

    Returns:
        ValidationResult with valid=True if all checks pass.
    """
    errors = []
    warnings = []

    one_liner_tokens = token_counts.get("one_liner", 0)
    core_tokens = token_counts.get("core_digest", 0)
    ext_tokens = token_counts.get("extended_digest", 0)

    if one_liner_tokens > 30:
        errors.append(f"one_liner exceeds token budget: {one_liner_tokens} > 30")

    if core_tokens < 200:
        errors.append(f"core_digest below minimum: {core_tokens} < 200")
    if core_tokens > 500:
        errors.append(f"core_digest exceeds token budget: {core_tokens} > 500")

    if ext_tokens > 2000:
        errors.append(f"extended_digest exceeds token budget: {ext_tokens} > 2000")

    artifact_type = digest_data.get("artifact_type", "")
    required = get_required_fields(artifact_type)
    core_digest = digest_data.get("core_digest", "")

    for req_field in required:
        pattern = rf"^-\s*{re.escape(req_field)}\s*:"
        if not re.search(pattern, core_digest, re.MULTILINE):
            errors.append(f"missing required field: {req_field}")

    if not source_path.exists():
        errors.append(f"source file does not exist: {source_path}")

    changelog = digest_data.get("changelog", "").strip()
    if not changelog:
        errors.append("changelog section is empty")

    if core_digest.strip():
        lines = [ln for ln in core_digest.strip().split("\n") if ln.strip()]
        kv_lines = sum(1 for ln in lines if ln.strip().startswith("- "))
        if lines and kv_lines / len(lines) < 0.7:
            errors.append(
                f"core_digest not in key-value format: "
                f"{kv_lines}/{len(lines)} lines start with '- ' (need >= 70%)"
            )

    dep_pattern = re.compile(r"layer1p-[\w-]+")
    deps = dep_pattern.findall(core_digest)
    if deps:
        vault_root = Path(vault_path)
        llm_wiki_dir = vault_root / "llm_wiki"
        for dep_id in deps:
            found = False
            if llm_wiki_dir.exists():
                for md_file in llm_wiki_dir.rglob("*.md"):
                    if md_file.name == "_index.md":
                        continue
                    try:
                        content = md_file.read_text(encoding="utf-8")
                        if f"id: {dep_id}" in content or f'id: "{dep_id}"' in content:
                            found = True
                            break
                    except Exception:
                        continue
            if not found:
                warnings.append(f"dependency not found: {dep_id}")

    valid = len(errors) == 0

    if valid:
        logger.info("validator: digest passed validation for %s", source_path.name)
    else:
        logger.warning(
            "validator: digest failed validation for %s: %s",
            source_path.name,
            "; ".join(errors),
        )

    if warnings:
        logger.warning(
            "validator: warnings for %s: %s",
            source_path.name,
            "; ".join(warnings),
        )

    return ValidationResult(valid=valid, errors=errors, warnings=warnings)
