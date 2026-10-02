"""Digest generation pipeline for Layer 1' (llm_wiki/)."""

import hashlib
import logging
import os
import time
from datetime import date, datetime
from pathlib import Path

import frontmatter

from shared import vault_paths
from shared.file_writer import atomic_write
from shared.frontmatter_utils import read_frontmatter, update_frontmatter
from shared.llm_client import call as llm_call

from . import paths as digest_paths
from .templates import ARTIFACT_TYPE_MAP, detect_type, get_template
from .token_counter import count_sections, count_tokens
from .validator import validate

logger = logging.getLogger(__name__)

DIGEST_MAX_RETRIES = int(os.getenv("DIGEST_MAX_RETRIES", "2"))

_SKIP_FILENAMES = frozenset({
    "INDEX.md", "LOG.md", "index.md", "log.md",
    "glossary.md", "decisions.md", "_index.md",
})

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _compute_body_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def _generate_id(artifact_type: str, source_path: Path) -> str:
    slug = source_path.stem
    return f"layer1p-{artifact_type}-{slug}"


def vector_store_enabled() -> bool:
    return os.getenv("VECTOR_STORE_ENABLED", "0") == "1"


def _get_existing_record(digest_id: str) -> dict | None:
    """Lookup existing LanceDB record by id; None on miss or error."""
    try:
        from shared import vector_store
        return vector_store.get_by_id(digest_id)
    except Exception as e:
        logger.warning("generator: vector_store lookup failed for %s: %s", digest_id, e)
        return None


def _write_to_vector_store(
    *,
    digest_id: str,
    source_path: Path,
    vault_root: Path,
    metadata: dict,
    artifact_type: str,
    domain: str,
    sections: dict,
    token_counts: dict,
    body_hash: str,
    existing: dict | None,
) -> None:
    """Build full record, embed and upsert into LanceDB. Raises on upsert failure."""
    from shared import embedding_client, vector_store

    title = str(metadata.get("title") or source_path.stem)
    one_liner = sections["one_liner"]
    core = sections["core_digest"]
    extended = sections["extended_digest"]
    search_text = f"{title} {one_liner} {core}"

    try:
        emb = embedding_client.embed(search_text)
    except Exception as e:
        logger.warning("generator: embedding failed for %s: %s", source_path.name, e)
        emb = None

    tags = metadata.get("tags") or []
    if not isinstance(tags, list):
        tags = [str(tags)]
    try:
        relevance = float(metadata.get("relevance", 0.0) or 0.0)
    except (TypeError, ValueError):
        relevance = 0.0

    today = date.today().isoformat()
    try:
        source_rel = source_path.relative_to(vault_root).as_posix()
    except ValueError:
        source_rel = source_path.as_posix()

    record = {
        "id": digest_id,
        "source_path": source_rel,
        "type": artifact_type,
        "domain": domain,
        "tier": metadata.get("tier", "active"),
        "status": metadata.get("status", ""),
        "tags": [str(t) for t in tags],
        "title": title,
        "relevance": relevance,
        "one_liner": one_liner,
        "core_digest": core,
        "extended_digest": extended,
        "changelog": sections["changelog"],
        "search_text": search_text,
        "vector": emb.vector if emb else None,
        "body_hash": body_hash,
        "created": (existing or {}).get("created") or today,
        "updated": today,
        "embedding_model": emb.model if emb else "",
        "embedding_provider": emb.provider if emb else "",
        "tokens_one_liner": token_counts.get("one_liner") or count_tokens(one_liner),
        "tokens_core": token_counts.get("core_digest") or count_tokens(core),
        "tokens_extended": token_counts.get("extended_digest") or count_tokens(extended),
    }
    vector_store.upsert(record)
    logger.info(
        "generator: digest upserted to vector store id=%s (vector=%s)",
        digest_id, "yes" if emb else "no",
    )


def _load_base_prompt() -> str:
    path = _PROMPTS_DIR / "digest.txt"
    if not path.exists():
        logger.error("generator: base prompt not found at %s", path)
        raise FileNotFoundError(f"Base prompt not found: {path}")
    return path.read_text(encoding="utf-8")


def _build_prompt(body: str, artifact_type: str, prev_digest: str | None) -> str:
    base = _load_base_prompt()
    template = get_template(artifact_type)
    prev_section = ""
    if prev_digest:
        prev_section = f"ПРЕДЫДУЩИЙ DIGEST (для changelog diff):\n\n{prev_digest}"
    prompt = base.replace("{TEMPLATE}", template)
    prompt = prompt.replace("{PREVIOUS_DIGEST}", prev_section)
    prompt = prompt.replace("{BODY}", body)
    return prompt


def _parse_sections(raw_response: str) -> dict:
    sections = {"one_liner": "", "core_digest": "", "extended_digest": "", "changelog": ""}
    current = None
    section_map = {
        "# one-liner": "one_liner",
        "# core-digest": "core_digest",
        "# extended-digest": "extended_digest",
        "# changelog": "changelog",
    }
    for line in raw_response.split("\n"):
        stripped = line.strip().lower()
        if stripped in section_map:
            current = section_map[stripped]
            continue
        if current is not None:
            sections[current] += line + "\n"
    for key in sections:
        sections[key] = sections[key].strip()
    return sections


def _format_digest(fm: dict, sections: dict) -> str:
    post = frontmatter.Post("")
    for k, v in fm.items():
        post[k] = v
    body_parts = []
    for section_name, section_key in [
        ("# one-liner", "one_liner"),
        ("# core-digest", "core_digest"),
        ("# extended-digest", "extended_digest"),
        ("# changelog", "changelog"),
    ]:
        body_parts.append(section_name)
        body_parts.append(sections.get(section_key, ""))
        body_parts.append("")
    post.content = "\n".join(body_parts).rstrip() + "\n"
    return frontmatter.dumps(post)


def _detect_domain(source_path: Path, vault_root: Path) -> str:
    try:
        rel = source_path.relative_to(vault_root / "wiki")
        parts = rel.parts
        if len(parts) >= 2 and parts[0] == "domains":
            return parts[1]
    except ValueError:
        pass
    return "cross-domain"


def generate_digest(
    source_path: Path,
    vault_path: str = "",
    force: bool = False,
) -> dict:
    """Generate digest for a single wiki/ artifact.

    Returns dict with status, digest_path, token_counts, body_hash.
    """
    vault_root = Path(vault_path) if vault_path else vault_paths.VAULT_PATH
    source_path = Path(source_path)

    logger.info("generator: starting digest for %s (force=%s)", source_path.name, force)

    if not source_path.exists():
        logger.error("generator: source file not found: %s", source_path)
        return {"status": "error", "error": f"Source not found: {source_path}"}

    try:
        metadata, body = read_frontmatter(source_path)
    except Exception as e:
        logger.error("generator: failed to read source %s: %s", source_path.name, e)
        return {"status": "error", "error": str(e)}

    artifact_type = detect_type(source_path, metadata)
    digest_path = digest_paths.wiki_to_llm_wiki(source_path, vault_root)
    body_hash = _compute_body_hash(body)
    digest_id = _generate_id(artifact_type, source_path)
    domain = _detect_domain(source_path, vault_root)

    use_vector = vector_store_enabled()
    existing_record = _get_existing_record(digest_id) if use_vector else None

    if use_vector:
        if not force and existing_record and existing_record.get("body_hash") == body_hash:
            logger.debug("generator: vector record up to date (body_hash match), skipping: %s", source_path.name)
            return {"status": "skip", "id": digest_id}
    elif not force and digest_path.exists():
        try:
            existing_meta, _ = read_frontmatter(digest_path)
            existing_hash = existing_meta.get("body_hash", "")
            if existing_hash == body_hash:
                logger.debug("generator: digest up to date (body_hash match), skipping: %s", source_path.name)
                return {"status": "skip", "digest_path": str(digest_path)}
        except Exception:
            pass

    prev_digest = None
    if use_vector:
        if existing_record:
            prev_digest = "\n\n".join(
                f"# {name}\n{existing_record.get(key) or ''}"
                for name, key in (
                    ("one-liner", "one_liner"),
                    ("core-digest", "core_digest"),
                    ("extended-digest", "extended_digest"),
                    ("changelog", "changelog"),
                )
            )
    elif digest_path.exists():
        try:
            _, prev_body = read_frontmatter(digest_path)
            prev_digest = prev_body
        except Exception:
            logger.warning("generator: could not read previous digest %s", digest_path)

    prompt = _build_prompt(body, artifact_type, prev_digest)

    try:
        raw_response = llm_call(
            operation="digest",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=3000,
        )
    except Exception as e:
        logger.error("generator: LLM call failed for %s: %s", source_path.name, e)
        return {"status": "error", "error": f"LLM call failed: {e}"}

    sections = _parse_sections(raw_response)
    token_counts = count_sections(
        "\n".join(f"# {k.replace('_', '-')}\n{v}" for k, v in sections.items())
    )

    digest_data = {
        "frontmatter": metadata,
        "one_liner": sections["one_liner"],
        "core_digest": sections["core_digest"],
        "extended_digest": sections["extended_digest"],
        "changelog": sections["changelog"],
        "artifact_type": artifact_type,
    }

    validation_status = "passed"
    last_validation = None

    for attempt in range(1 + DIGEST_MAX_RETRIES):
        last_validation = validate(digest_data, source_path, str(vault_root), token_counts)
        if last_validation.valid:
            break

        if attempt < DIGEST_MAX_RETRIES:
            logger.warning(
                "generator: validation failed (attempt %d/%d) for %s: %s. Retrying...",
                attempt + 1, DIGEST_MAX_RETRIES + 1, source_path.name,
                "; ".join(last_validation.errors),
            )
            feedback = (
                "Предыдущая попытка не прошла валидацию. Ошибки:\n"
                + "\n".join(f"- {e}" for e in last_validation.errors)
                + "\n\nИсправь и сгенерируй заново."
            )
            retry_prompt = prompt + "\n\n---\nFEEDBACK:\n" + feedback
            try:
                raw_response = llm_call(
                    operation="digest",
                    messages=[{"role": "user", "content": retry_prompt}],
                    max_tokens=3000,
                )
                sections = _parse_sections(raw_response)
                token_counts = count_sections(
                    "\n".join(f"# {k.replace('_', '-')}\n{v}" for k, v in sections.items())
                )
                digest_data["one_liner"] = sections["one_liner"]
                digest_data["core_digest"] = sections["core_digest"]
                digest_data["extended_digest"] = sections["extended_digest"]
                digest_data["changelog"] = sections["changelog"]
            except Exception as e:
                logger.error("generator: retry LLM call failed for %s: %s", source_path.name, e)
                break

    if last_validation and not last_validation.valid:
        validation_status = "failed"
        logger.warning(
            "generator: digest validation failed after %d retries for %s: %s",
            DIGEST_MAX_RETRIES, source_path.name,
            "; ".join(last_validation.errors),
        )

    if use_vector:
        try:
            _write_to_vector_store(
                digest_id=digest_id, source_path=source_path, vault_root=vault_root,
                metadata=metadata, artifact_type=artifact_type, domain=domain,
                sections=sections, token_counts=token_counts, body_hash=body_hash,
                existing=existing_record,
            )
        except Exception as e:
            logger.error("generator: vector store upsert failed for %s: %s", source_path.name, e)
            return {"status": "error", "error": f"Vector store upsert failed: {e}"}
        return {
            "status": "ok" if validation_status == "passed" else "validation_failed",
            "id": digest_id,
            "token_counts": token_counts,
            "body_hash": body_hash,
            "validation": validation_status,
        }

    today = date.today().isoformat()
    now = datetime.now().isoformat(timespec="seconds")

    digest_fm = {
        "id": digest_id,
        "source": str(source_path.relative_to(vault_root)),
        "type": artifact_type,
        "domain": domain,
        "created": today,
        "updated": today,
        "source_updated": now,
        "body_hash": body_hash,
        "validation": validation_status,
        "token_count": {
            "one_liner": token_counts.get("one_liner", 0),
            "core_digest": token_counts.get("core_digest", 0),
            "extended_digest": token_counts.get("extended_digest", 0),
            "total": token_counts.get("total", 0),
        },
    }

    if digest_path.exists():
        try:
            existing_meta, _ = read_frontmatter(digest_path)
            digest_fm["created"] = existing_meta.get("created", today)
        except Exception:
            pass

    formatted = _format_digest(digest_fm, sections)

    digest_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(digest_path, formatted)
    logger.info(
        "generator: digest written to %s (validation=%s, tokens=%s)",
        digest_path.name, validation_status, token_counts,
    )

    try:
        rel_digest = str(digest_path.relative_to(vault_root))
        update_frontmatter(source_path, {"digest": rel_digest})
    except Exception as e:
        logger.warning("generator: failed to update source frontmatter for %s: %s", source_path.name, e)

    return {
        "status": "ok" if validation_status == "passed" else "validation_failed",
        "digest_path": str(digest_path),
        "token_counts": token_counts,
        "body_hash": body_hash,
        "validation": validation_status,
    }


def generate_bulk(
    vault_path: str = "",
    domain: str | None = None,
    artifact_type: str | None = None,
    force: bool = False,
) -> dict:
    """Generate digests for all (or filtered) wiki/ artifacts."""
    vault_root = Path(vault_path) if vault_path else vault_paths.VAULT_PATH

    logger.info(
        "generator: bulk generation started (domain=%s, type=%s, force=%s)",
        domain, artifact_type, force,
    )

    digest_paths.ensure_llm_wiki_structure(vault_root)

    files_to_process = []

    if domain:
        domains = [domain]
    else:
        domains = vault_paths.all_domains()

    for d in domains:
        types = [artifact_type] if artifact_type else list(ARTIFACT_TYPE_MAP.keys())
        for t in types:
            type_dir = vault_root / "wiki" / "domains" / d / t
            if type_dir.exists():
                for md_file in sorted(type_dir.glob("*.md")):
                    if md_file.name not in _SKIP_FILENAMES:
                        files_to_process.append(md_file)

    if not artifact_type:
        cross_dirs = {
            "meetings": vault_root / "wiki" / "meetings",
            "daily-logs": vault_root / "wiki" / "daily-logs",
            "reports": vault_root / "wiki" / "reports",
        }
        for cd_name, cd_path in cross_dirs.items():
            if cd_path.exists():
                for md_file in sorted(cd_path.glob("*.md")):
                    if md_file.name not in _SKIP_FILENAMES:
                        files_to_process.append(md_file)

    total = len(files_to_process)
    generated = 0
    skipped = 0
    failed = 0
    details = []

    for i, file_path in enumerate(files_to_process, 1):
        logger.info("generator: Processing %d/%d: %s", i, total, file_path)
        result = generate_digest(file_path, vault_path=str(vault_root), force=force)
        status = result.get("status", "error")
        details.append({"path": str(file_path), "status": status})

        if status == "ok":
            generated += 1
        elif status == "skip":
            skipped += 1
        else:
            failed += 1

        if i < total:
            time.sleep(0.5)

    idx_result = regenerate_index(str(vault_root))
    logger.info(
        "generator: bulk generation complete — generated=%d, skipped=%d, failed=%d",
        generated, skipped, failed,
    )

    return {
        "status": "ok",
        "generated": generated,
        "skipped": skipped,
        "failed": failed,
        "total": total,
        "index": idx_result,
        "details": details,
    }


def regenerate_index(vault_path: str = "") -> dict:
    """Regenerate llm_wiki/_index.md from all existing digests."""
    vault_root = Path(vault_path) if vault_path else vault_paths.VAULT_PATH
    index_path = digest_paths.llm_wiki_index(vault_root)

    logger.info("generator: regenerating _index.md at %s", index_path)

    llm_wiki_root = vault_root / "llm_wiki"
    if not llm_wiki_root.exists():
        logger.warning("generator: llm_wiki/ does not exist, creating empty index")
        index_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(index_path, "---\ngenerated: \"\"\nentry_count: 0\ntotal_one_liner_tokens: 0\n---\n")
        return {"status": "ok", "entries": 0, "total_tokens": 0}

    entries = []
    total_one_liner_tokens = 0

    for md_file in sorted(llm_wiki_root.rglob("*.md")):
        if md_file.name == "_index.md":
            continue
        try:
            meta, body = read_frontmatter(md_file)
        except Exception as e:
            logger.warning("generator: failed to read digest %s: %s", md_file.name, e)
            continue

        digest_id = meta.get("id", "")
        dtype = meta.get("type", "")
        ddomain = meta.get("domain", "")
        dupdated = meta.get("updated", "")
        tc = meta.get("token_count", {})
        ol_tokens = tc.get("one_liner", 0) if isinstance(tc, dict) else 0
        total_one_liner_tokens += ol_tokens

        one_liner = ""
        for line in body.split("\n"):
            if line.strip().lower() == "# one-liner":
                continue
            if line.strip().startswith("#"):
                break
            if line.strip():
                one_liner = line.strip()
                break

        source = meta.get("source", "")
        tier = "active"
        relevance = 1.0
        wiki_path = vault_root / source if source else None
        if wiki_path and wiki_path.exists():
            try:
                wiki_meta, _ = read_frontmatter(wiki_path)
                tier = wiki_meta.get("tier", "active")
                relevance = wiki_meta.get("relevance", 1.0)
            except Exception:
                pass

        entries.append({
            "id": digest_id,
            "type": dtype,
            "domain": ddomain,
            "tier": tier,
            "relevance": relevance,
            "updated": dupdated,
            "one_liner": one_liner,
        })

    tier_order = {"core": 0, "active": 1, "warm": 2, "cold": 3, "archive": 4}
    entries.sort(key=lambda ent: (tier_order.get(ent["tier"], 5), -(ent.get("relevance", 0))))

    now = datetime.now().isoformat(timespec="seconds")
    header = (
        f"---\ngenerated: \"{now}\"\n"
        f"entry_count: {len(entries)}\n"
        f"total_one_liner_tokens: {total_one_liner_tokens}\n---\n\n"
        f"# LLM Wiki Index\n\n"
        f"| id | type | domain | tier | relevance | updated | one_liner |\n"
        f"|---|---|---|---|---|---|---|\n"
    )
    rows = []
    for entry in entries:
        rel = entry.get("relevance", 1.0)
        rel_str = f"{rel:.2f}" if isinstance(rel, float) else str(rel)
        rows.append(
            f"| {entry['id']} | {entry['type']} | {entry['domain']} | {entry['tier']} "
            f"| {rel_str} | {entry['updated']} | {entry['one_liner']} |"
        )

    content = header + "\n".join(rows) + "\n"

    index_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(index_path, content)

    logger.info(
        "generator: _index.md regenerated — %d entries, %d one-liner tokens",
        len(entries), total_one_liner_tokens,
    )

    return {"status": "ok", "entries": len(entries), "total_tokens": total_one_liner_tokens}
