"""Move artifacts between domains in the vault wiki structure.

Provides single-file move, batch reclassification with keyword/tag scoring,
and domain audit to find candidates for migration.
"""

import logging
import shutil
from collections import defaultdict
from pathlib import Path

from shared import domain_config, vault_paths
from shared.frontmatter_utils import read_frontmatter, update_frontmatter

from .domain_manager import _ARTIFACT_TYPES, append_domain_log, update_domain_index

logger = logging.getLogger(__name__)

_SERVICE_FILES = frozenset({"index.md", "log.md"})


def _parse_artifact_path(filepath: Path) -> tuple[str, str]:
    parts = filepath.parts
    try:
        idx = list(parts).index("domains")
    except ValueError:
        logger.error(f"_parse_artifact_path: 'domains' not found in path {filepath}")
        raise ValueError(f"Path does not contain 'domains' segment: {filepath}")

    if idx + 2 >= len(parts):
        logger.error(f"_parse_artifact_path: path too short after 'domains': {filepath}")
        raise ValueError(f"Path too short after 'domains' segment: {filepath}")

    source_domain = parts[idx + 1]
    artifact_type = parts[idx + 2]

    if artifact_type not in _ARTIFACT_TYPES:
        logger.error(
            f"_parse_artifact_path: invalid artifact_type={artifact_type} "
            f"in path {filepath}, valid={_ARTIFACT_TYPES}"
        )
        raise ValueError(
            f"Invalid artifact_type '{artifact_type}' in path. "
            f"Must be one of: {', '.join(_ARTIFACT_TYPES)}"
        )

    logger.debug(
        f"_parse_artifact_path: parsed domain={source_domain}, "
        f"artifact_type={artifact_type} from {filepath}"
    )
    return source_domain, artifact_type


def _safe_move(src: Path, dst: Path) -> None:
    logger.info(f"_safe_move: {src} -> {dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)

    try:
        shutil.copy2(src, dst)
    except Exception as exc:
        logger.error(f"_safe_move: copy2 failed {src} -> {dst}: {exc}")
        raise

    try:
        src_text = src.read_text(encoding="utf-8")
        dst_text = dst.read_text(encoding="utf-8")
    except Exception as exc:
        logger.error(f"_safe_move: verification read failed: {exc}")
        dst.unlink(missing_ok=True)
        raise IOError(f"Failed to read files for verification: {exc}")

    if dst_text != src_text:
        logger.error(f"_safe_move: content mismatch after copy for {dst}")
        dst.unlink()
        raise IOError(f"Content verification failed: {src} != {dst}")

    src.unlink()
    logger.info(f"_safe_move: completed successfully, source removed: {src.name}")


def _classify_file(
    filepath: Path,
    keyword_map: dict[str, str],
    tag_map: dict[str, str],
) -> tuple[str | None, int, list[str]]:
    try:
        metadata, body = read_frontmatter(filepath)
    except Exception as exc:
        logger.warning(f"_classify_file: failed to read {filepath.name}: {exc}")
        return None, 0, [f"read_error: {exc}"]

    tags = metadata.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    elif not isinstance(tags, list):
        tags = []

    title = str(metadata.get("title", filepath.stem))
    body_snippet = body[:500].lower()
    title_lower = title.lower()

    scores: dict[str, int] = defaultdict(int)
    reasons: dict[str, list[str]] = defaultdict(list)

    for tag in tags:
        tag_key = tag.lower().strip()
        if tag_key in tag_map:
            domain = tag_map[tag_key]
            scores[domain] += 3
            reasons[domain].append(f"tag:{tag_key}(+3)")
            logger.debug(f"_classify_file: {filepath.name} tag match {tag_key} -> {domain} (+3)")

    for kw, domain in keyword_map.items():
        if kw in title_lower:
            scores[domain] += 2
            reasons[domain].append(f"title_kw:{kw}(+2)")
            logger.debug(f"_classify_file: {filepath.name} title keyword {kw} -> {domain} (+2)")
        if kw in body_snippet:
            scores[domain] += 1
            reasons[domain].append(f"body_kw:{kw}(+1)")
            logger.debug(f"_classify_file: {filepath.name} body keyword {kw} -> {domain} (+1)")

    if not scores:
        logger.debug(f"_classify_file: {filepath.name} unmatched")
        return None, 0, ["unmatched"]

    max_score = max(scores.values())
    winners = [d for d, s in scores.items() if s == max_score]

    if len(winners) == 1:
        winner = winners[0]
        logger.debug(
            f"_classify_file: {filepath.name} -> {winner} "
            f"(score={max_score}, reasons={reasons[winner]})"
        )
        return winner, max_score, reasons[winner]

    ambiguous_desc = ", ".join(f"{d}={scores[d]}" for d in sorted(winners))
    logger.debug(f"_classify_file: {filepath.name} ambiguous: {ambiguous_desc}")
    return None, max_score, [f"ambiguous: {ambiguous_desc}"]


def move_artifact(filepath: str, target_domain: str) -> dict:
    """Move a single artifact file to a different domain."""
    logger.info(f"move_artifact: filepath={filepath}, target_domain={target_domain}")

    src = Path(filepath)
    if not src.is_absolute():
        src = (vault_paths.VAULT_PATH / src).resolve()
    else:
        src = src.resolve()

    if not src.exists():
        logger.error(f"move_artifact: file not found: {src}")
        return {"status": "error", "message": f"File not found: {src}"}

    if src.suffix != ".md":
        logger.error(f"move_artifact: not a .md file: {src}")
        return {"status": "error", "message": f"Not a markdown file: {src}"}

    try:
        rel = src.relative_to(vault_paths.VAULT_PATH)
    except ValueError:
        logger.error(f"move_artifact: file not inside vault: {src}")
        return {"status": "error", "message": f"File is not inside the vault: {src}"}

    rel_parts = rel.parts
    if len(rel_parts) < 3 or rel_parts[0] != "wiki" or rel_parts[1] != "domains":
        logger.error(f"move_artifact: file not in wiki/domains/: {src}")
        return {"status": "error", "message": f"File is not in wiki/domains/: {src}"}

    valid_domains = domain_config.get_valid_domains()
    if target_domain not in valid_domains:
        logger.error(f"move_artifact: invalid target_domain={target_domain}, valid={valid_domains}")
        return {"status": "error", "message": f"Invalid target domain: {target_domain}"}

    try:
        source_domain, artifact_type = _parse_artifact_path(src)
    except ValueError as exc:
        logger.error(f"move_artifact: parse path failed: {exc}")
        return {"status": "error", "message": str(exc)}

    if target_domain == source_domain:
        logger.warning(f"move_artifact: target == source ({target_domain}), skipping")
        return {"status": "error", "message": f"Target domain is the same as source: {target_domain}"}

    filename = src.name
    dst_dir = vault_paths.wiki_domain_dir(target_domain, artifact_type)
    dst = dst_dir / filename

    if dst.exists():
        logger.error(f"move_artifact: destination already exists: {dst}")
        return {"status": "error", "message": f"File already exists in target domain: {dst}"}

    try:
        _safe_move(src, dst)
    except Exception as exc:
        logger.error(f"move_artifact: _safe_move failed: {exc}")
        return {"status": "error", "message": f"Move failed: {exc}"}

    try:
        update_frontmatter(dst, {"domain": target_domain})
        logger.info(f"move_artifact: updated frontmatter domain={target_domain} in {dst.name}")
    except Exception as exc:
        logger.error(f"move_artifact: update_frontmatter failed for {dst.name}: {exc}")

    try:
        update_domain_index(source_domain, artifact_type)
        logger.info(f"move_artifact: updated index for source domain={source_domain}/{artifact_type}")
    except Exception as exc:
        logger.error(f"move_artifact: update_domain_index failed for source: {exc}")

    try:
        update_domain_index(target_domain, artifact_type)
        logger.info(f"move_artifact: updated index for target domain={target_domain}/{artifact_type}")
    except Exception as exc:
        logger.error(f"move_artifact: update_domain_index failed for target: {exc}")

    try:
        append_domain_log(
            source_domain, artifact_type, "MOVE",
            filename, f"moved to {target_domain}"
        )
        logger.info(f"move_artifact: logged MOVE in source domain={source_domain}")
    except Exception as exc:
        logger.error(f"move_artifact: append_domain_log failed for source: {exc}")

    try:
        append_domain_log(
            target_domain, artifact_type, "MOVE",
            filename, f"received from {source_domain}"
        )
        logger.info(f"move_artifact: logged MOVE in target domain={target_domain}")
    except Exception as exc:
        logger.error(f"move_artifact: append_domain_log failed for target: {exc}")

    logger.info(
        f"move_artifact: success — {filename} moved from {source_domain} to {target_domain}"
    )
    return {
        "status": "ok",
        "file": filename,
        "from": source_domain,
        "to": target_domain,
    }


def batch_reclassify(
    source_domain: str,
    artifact_type: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Batch reclassify artifacts from a source domain using keyword/tag scoring."""
    logger.info(
        f"batch_reclassify: source_domain={source_domain}, "
        f"artifact_type={artifact_type}, dry_run={dry_run}"
    )

    valid_domains = domain_config.get_valid_domains()
    if source_domain not in valid_domains:
        logger.error(f"batch_reclassify: invalid source_domain={source_domain}")
        return {"status": "error", "message": f"Invalid source domain: {source_domain}"}

    keyword_map = domain_config.build_keyword_map()
    tag_map = domain_config.build_tag_map()
    logger.info(
        f"batch_reclassify: loaded {len(keyword_map)} keywords, {len(tag_map)} tags"
    )

    types_to_scan = [artifact_type] if artifact_type else list(_ARTIFACT_TYPES)
    to_move: list[dict] = []
    unmatched: list[str] = []

    for atype in types_to_scan:
        atype_dir = vault_paths.wiki_domain_dir(source_domain, atype)
        if not atype_dir.exists():
            logger.warning(f"batch_reclassify: directory not found: {atype_dir}")
            continue

        md_files = sorted(f for f in atype_dir.glob("*.md") if f.name not in _SERVICE_FILES)
        logger.info(f"batch_reclassify: scanning {len(md_files)} files in {source_domain}/{atype}")

        for md_file in md_files:
            target, score, reasons = _classify_file(md_file, keyword_map, tag_map)

            if target is not None and target != source_domain:
                to_move.append({
                    "file": str(md_file),
                    "filename": md_file.name,
                    "artifact_type": atype,
                    "target_domain": target,
                    "score": score,
                    "reasons": reasons,
                })
                logger.info(
                    f"batch_reclassify: candidate {md_file.name} -> "
                    f"{target} (score={score})"
                )
            else:
                unmatched.append(md_file.name)
                logger.debug(f"batch_reclassify: unmatched {md_file.name}")

    if dry_run:
        by_domain: dict[str, int] = defaultdict(int)
        for item in to_move:
            by_domain[item["target_domain"]] += 1

        logger.info(
            f"batch_reclassify: dry_run complete — "
            f"{len(to_move)} to_move, {len(unmatched)} unmatched"
        )
        return {
            "status": "ok",
            "dry_run": True,
            "to_move": to_move,
            "unmatched": unmatched,
            "summary": {
                "total_scanned": len(to_move) + len(unmatched),
                "to_move": len(to_move),
                "unmatched": len(unmatched),
                "by_domain": dict(by_domain),
            },
        }

    moved = 0
    failed = 0
    errors: list[str] = []
    by_domain_actual: dict[str, int] = defaultdict(int)

    for item in to_move:
        result = move_artifact(item["file"], item["target_domain"])
        if result["status"] == "ok":
            moved += 1
            by_domain_actual[item["target_domain"]] += 1
            logger.info(
                f"batch_reclassify: moved {item['filename']} -> "
                f"{item['target_domain']}"
            )
        else:
            failed += 1
            error_msg = f"{item['filename']}: {result['message']}"
            errors.append(error_msg)
            logger.error(f"batch_reclassify: failed to move {item['filename']}: {result['message']}")

    logger.info(
        f"batch_reclassify: complete — moved={moved}, failed={failed}, "
        f"unmatched={len(unmatched)}"
    )
    return {
        "status": "ok",
        "dry_run": False,
        "moved": moved,
        "failed": failed,
        "errors": errors,
        "unmatched": len(unmatched),
        "by_domain": dict(by_domain_actual),
    }


def audit_domain(domain: str, source_domain: str = "general") -> dict:
    """Audit a domain: count current files and find migration candidates in source."""
    logger.info(f"audit_domain: domain={domain}, source_domain={source_domain}")

    valid_domains = domain_config.get_valid_domains()
    if domain not in valid_domains:
        logger.error(f"audit_domain: invalid domain={domain}")
        return {"status": "error", "message": f"Invalid domain: {domain}"}
    if source_domain not in valid_domains:
        logger.error(f"audit_domain: invalid source_domain={source_domain}")
        return {"status": "error", "message": f"Invalid source domain: {source_domain}"}

    full_keyword_map = domain_config.build_keyword_map()
    full_tag_map = domain_config.build_tag_map()

    filtered_keyword_map = {kw: d for kw, d in full_keyword_map.items() if d == domain}
    filtered_tag_map = {tag: d for tag, d in full_tag_map.items() if d == domain}
    logger.info(
        f"audit_domain: filtered maps for {domain} — "
        f"{len(filtered_keyword_map)} keywords, {len(filtered_tag_map)} tags"
    )

    current_files = 0
    for atype in _ARTIFACT_TYPES:
        atype_dir = vault_paths.wiki_domain_dir(domain, atype)
        if atype_dir.exists():
            count = sum(
                1 for f in atype_dir.glob("*.md") if f.name not in _SERVICE_FILES
            )
            current_files += count
    logger.info(f"audit_domain: {domain} has {current_files} current files")

    candidates: list[dict] = []
    for atype in _ARTIFACT_TYPES:
        atype_dir = vault_paths.wiki_domain_dir(source_domain, atype)
        if not atype_dir.exists():
            continue

        md_files = sorted(f for f in atype_dir.glob("*.md") if f.name not in _SERVICE_FILES)
        for md_file in md_files:
            target, score, reasons = _classify_file(md_file, filtered_keyword_map, filtered_tag_map)
            if target == domain:
                candidates.append({
                    "file": md_file.name,
                    "artifact_type": atype,
                    "score": score,
                    "reasons": reasons,
                })
                logger.debug(
                    f"audit_domain: candidate {md_file.name} -> {domain} (score={score})"
                )

    candidate_count = len(candidates)
    if candidate_count > 5:
        recommendation = "keep"
    elif candidate_count == 0:
        recommendation = "remove"
    else:
        recommendation = "review"

    logger.info(
        f"audit_domain: {domain} — {current_files} current, "
        f"{candidate_count} candidates in {source_domain}, "
        f"recommendation={recommendation}"
    )
    return {
        "status": "ok",
        "domain": domain,
        "current_files": current_files,
        "candidates_in_general": candidate_count,
        "candidates": candidates,
        "recommendation": recommendation,
    }
