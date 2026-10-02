"""One-time migration: llm_wiki/ .md files → LanceDB vector store (BL-237)."""

import logging
import re
import time
from datetime import date
from pathlib import Path

from .digest.token_counter import count_tokens

logger = logging.getLogger(__name__)

# Служебные файлы, которые не являются дайджестами
SKIP_FILES = {"_index.md", "_cowork-session.md"}


def _parse_digest_sections(body: str) -> dict:
    """Разбирает тело файла llm_wiki/ на 4 секции дайджеста."""
    sections = {"one_liner": "", "core_digest": "", "extended_digest": "", "changelog": ""}
    try:
        parts = re.split(r"^## ", body, flags=re.MULTILINE)
        for part in parts:
            lower = part.lower()
            content = part.split("\n", 1)[1].strip() if "\n" in part else ""
            if lower.startswith("one-liner") or lower.startswith("one_liner"):
                sections["one_liner"] = content
            elif lower.startswith("core digest") or lower.startswith("core_digest"):
                sections["core_digest"] = content
            elif lower.startswith("extended digest") or lower.startswith("extended_digest"):
                sections["extended_digest"] = content
            elif lower.startswith("changelog"):
                sections["changelog"] = content
        logger.info("migrator: sections parsed, non-empty=%d", sum(1 for v in sections.values() if v))
    except Exception as e:
        logger.error("migrator: failed to parse sections: %s", e)
    return sections


def _collect_files(llm_wiki: Path) -> list[Path]:
    """Собирает все .md дайджесты, кроме служебных."""
    files = sorted(p for p in llm_wiki.rglob("*.md") if p.name not in SKIP_FILES)
    logger.info("migrator: collected %d files in %s", len(files), llm_wiki)
    return files


def _build_record(path: Path, embedding_client) -> dict:
    """Читает файл дайджеста и строит запись для DIGESTS_SCHEMA (с embedding)."""
    from shared.frontmatter_utils import read_frontmatter

    metadata, body = read_frontmatter(path)
    metadata = metadata or {}
    sections = _parse_digest_sections(body or "")

    source = str(metadata.get("source", "") or "")
    source_path = Path(source) if source else Path(path.stem)
    artifact_type = str(metadata.get("artifact_type", "idea") or "idea")
    digest_id = f"layer1p-{artifact_type}-{source_path.stem}"

    title = str(metadata.get("title") or source_path.stem)
    one_liner = sections["one_liner"]
    core = sections["core_digest"]
    extended = sections["extended_digest"]
    search_text = f"{title} {one_liner} {core}"

    try:
        emb = embedding_client.embed(search_text, operation="migration")
    except Exception as e:
        logger.warning("migrator: embedding failed for %s: %s", path.name, e)
        emb = None

    tags = metadata.get("tags") or []
    if not isinstance(tags, list):
        tags = [str(tags)]
    try:
        relevance = float(metadata.get("relevance", 0.0) or 0.0)
    except (TypeError, ValueError):
        relevance = 0.0

    today = date.today().isoformat()
    return {
        "id": digest_id,
        "source_path": Path(source).as_posix() if source else "",
        "type": artifact_type,
        "domain": str(metadata.get("domain", "general") or "general"),
        "tier": str(metadata.get("tier", "active") or "active"),
        "status": str(metadata.get("status", "") or ""),
        "tags": [str(t) for t in tags],
        "title": title,
        "relevance": relevance,
        "one_liner": one_liner,
        "core_digest": core,
        "extended_digest": extended,
        "changelog": sections["changelog"],
        "search_text": search_text,
        "vector": emb.vector if emb else None,
        "body_hash": str(metadata.get("body_hash", "") or ""),
        "created": str(metadata.get("created") or today),
        "updated": today,
        "embedding_model": emb.model if emb else "",
        "embedding_provider": emb.provider if emb else "",
        "tokens_one_liner": count_tokens(one_liner),
        "tokens_core": count_tokens(core),
        "tokens_extended": count_tokens(extended),
    }


def _run_migration(vault_path: str, dry_run: bool, notify: bool) -> dict:
    """Основная логика миграции (без обёртки LoggedProcess)."""
    start = time.monotonic()
    llm_wiki = Path(vault_path) / "llm_wiki"
    if not llm_wiki.exists():
        logger.warning("migrator: llm_wiki/ not found at %s", llm_wiki)
        return {"status": "skip", "message": "llm_wiki/ not found"}

    files = _collect_files(llm_wiki)
    total = len(files)

    if dry_run:
        logger.info("migrator: dry-run, %d files would be migrated", total)
        return {
            "status": "ok",
            "dry_run": True,
            "total_files": total,
            "files": [f.relative_to(llm_wiki).as_posix() for f in files],
        }

    from shared import embedding_client, vector_store

    migrated = errors = with_vectors = 0
    for i, f in enumerate(files, 1):
        try:
            record = _build_record(f, embedding_client)
            vector_store.upsert(record)
            migrated += 1
            if record["vector"] is not None:
                with_vectors += 1
        except Exception as e:
            errors += 1
            logger.error("migrator: failed to migrate %s: %s", f, e)
        logger.info("Migrated %d/%d (%d%%)", i, total, i * 100 // total)

    result = {
        "status": "ok",
        "total_files": total,
        "migrated": migrated,
        "errors": errors,
        "with_vectors": with_vectors,
        "duration_sec": round(time.monotonic() - start, 2),
    }

    # Валидация: сравнить количество записей в LanceDB с количеством файлов
    try:
        stats = vector_store.get_stats()
        db_total = stats.get("total") if isinstance(stats, dict) else None
        result["db_total"] = db_total
        if db_total is not None and db_total != total:
            logger.warning("migrator: validation mismatch, files=%d, db_total=%s", total, db_total)
        else:
            logger.info("migrator: validation ok, db_total=%s", db_total)
    except Exception as e:
        logger.error("migrator: get_stats failed: %s", e)

    if notify:
        try:
            from .notifier import send_telegram
            send_telegram(
                f"Миграция llm_wiki → LanceDB завершена: {migrated}/{total}, "
                f"ошибок {errors}, с векторами {with_vectors}"
            )
        except Exception as e:
            logger.error("migrator: notify failed: %s", e)

    logger.info("migrator: done %s", result)
    return result


def migrate_llm_wiki_to_lancedb(vault_path: str, dry_run: bool = False, notify: bool = False) -> dict:
    """Одноразовая миграция готовых дайджестов llm_wiki/ в LanceDB (без LLM)."""
    from shared.system_log import LoggedProcess

    try:
        with LoggedProcess("migrate-to-lancedb", source="ke-cli") as lp:
            result = _run_migration(vault_path, dry_run, notify)
            lp.summary = f"migrate-to-lancedb: {result.get('migrated', 0)}/{result.get('total_files', 0)}"
            lp.details = {k: v for k, v in result.items() if k != "files"}
        return result
    except Exception as e:
        logger.error("migrator: migration failed: %s", e)
        return {"status": "error", "message": str(e)}
