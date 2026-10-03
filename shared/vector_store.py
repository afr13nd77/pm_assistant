"""ChromaDB wrapper: the single access point to the digests vector store.

Write API (upsert/delete/drop_and_recreate) is intended for knowledge-engine only;
read API (hybrid_search/get_by_id/list_artifacts/get_stats) for pm-bot and MCP.
"""
import json
import logging
import os
import threading
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def _resolve_dim() -> int:
    """Определяет размерность эмбеддингов: env -> prefs -> 1024."""
    env_val = os.getenv("EMBEDDING_DIM")
    if env_val:
        try:
            return int(env_val)
        except ValueError as e:
            logger.error("vector_store._resolve_dim: invalid EMBEDDING_DIM=%r: %s", env_val, e)
    try:
        from shared.embedding_client import _load_embedding_prefs
        prefs = _load_embedding_prefs()
        dim = int(prefs.get("embedding_dim", 1024))
        logger.info("vector_store._resolve_dim: dim=%d from prefs", dim)
        return dim
    except Exception as e:
        logger.error("vector_store._resolve_dim: failed to read prefs: %s, fallback 1024", e)
        return 1024


EMBEDDING_DIM = _resolve_dim()
logger.info("vector_store: EMBEDDING_DIM=%d", EMBEDDING_DIM)
TABLE_NAME = "digests"
DEFAULT_PATH = "/vector-store"
RRF_K = 60
SNIPPET_LEN = 200

# Поля, хранимые в metadata (tags сериализуются в tags_json)
METADATA_FIELDS = [
    "source_path", "type", "domain", "tier", "status",
    "title", "relevance", "one_liner", "core_digest",
    "extended_digest", "changelog", "body_hash",
    "created", "updated", "embedding_model", "embedding_provider",
    "tokens_one_liner", "tokens_core", "tokens_extended",
    "tags_json",
]
_STR_FIELDS = [
    "source_path", "type", "domain", "tier", "status", "title", "one_liner",
    "core_digest", "extended_digest", "changelog", "body_hash", "created",
    "updated", "embedding_model", "embedding_provider",
]
_INT_FIELDS = ["tokens_one_liner", "tokens_core", "tokens_extended"]

_lock = threading.RLock()
_client = None
_client_path: str | None = None
_collection = None


@dataclass
class SearchResult:
    id: str
    title: str
    domain: str
    type: str
    score: float
    one_liner: str
    snippet: str
    semantic_score: float | None
    source_path: str


def _get_client(path: str | None = None):
    """Singleton connection. A different explicit path reconnects."""
    global _client, _client_path, _collection
    import chromadb

    target = path or os.environ.get("VECTOR_STORE_PATH") or DEFAULT_PATH
    with _lock:
        if _client is None or (path is not None and target != _client_path):
            try:
                os.makedirs(target, exist_ok=True)
                _client = chromadb.PersistentClient(path=target)
            except Exception as e:
                logger.warning("vector_store: connect failed path=%s: %s", target, e)
                raise
            _client_path = target
            _collection = None
            logger.debug("vector_store: connected path=%s", target)
        return _client


def _reset() -> None:
    """Drop cached connection/collection (used by tests)."""
    global _client, _client_path, _collection
    with _lock:
        _client = _client_path = _collection = None


def _get_collection():
    global _collection
    with _lock:
        if _collection is not None:
            return _collection
        client = _get_client()
        try:
            # embedding_function=None: эмбеддинги всегда передаются явно (без скачивания моделей)
            _collection = client.get_or_create_collection(
                name=TABLE_NAME,
                metadata={"hnsw:space": "cosine"},
                embedding_function=None,
            )
            logger.debug("vector_store: collection %s ready", TABLE_NAME)
        except Exception as e:
            _collection = None
            logger.warning("vector_store: open/create collection failed: %s", e)
            raise
        return _collection


def _placeholder_vector() -> list[float]:
    """Заглушка для записей без вектора (Chroma требует embedding); отсекается флагом has_vector."""
    v = [0.0] * EMBEDDING_DIM
    v[0] = 1.0
    return v


def _normalize(record: dict) -> dict:
    out = {"id": record.get("id")}
    for name in _STR_FIELDS:
        v = record.get(name)
        out[name] = "" if v is None else str(v)
    for name in _INT_FIELDS:
        v = record.get(name)
        out[name] = 0 if v is None else int(v)
    rel = record.get("relevance")
    out["relevance"] = 0.0 if rel is None else float(rel)
    tags = record.get("tags")
    out["tags"] = [] if tags is None else list(tags)
    out["search_text"] = record.get("search_text") or ""
    if not out["id"]:
        raise ValueError("record must have non-empty 'id'")
    vec = record.get("vector")
    if vec is not None:
        vec = [float(x) for x in vec]
        if len(vec) != EMBEDDING_DIM:
            raise ValueError(f"vector dim {len(vec)} != {EMBEDDING_DIM}")
    out["vector"] = vec
    return out


def _build_metadata(row: dict) -> dict:
    meta = {name: row[name] for name in METADATA_FIELDS if name != "tags_json"}
    meta["tags_json"] = json.dumps(row["tags"], ensure_ascii=False)
    meta["has_vector"] = row["vector"] is not None
    return meta


def upsert_batch(records: list[dict]) -> int:
    """Upsert by id (last wins within the batch)."""
    if not records:
        return 0
    try:
        rows = {}
        for r in records:
            n = _normalize(r)
            rows[n["id"]] = n
        items = list(rows.values())
        placeholder = _placeholder_vector()
        with _lock:
            col = _get_collection()
            col.upsert(
                ids=[r["id"] for r in items],
                embeddings=[r["vector"] if r["vector"] is not None else placeholder for r in items],
                documents=[r["search_text"] for r in items],
                metadatas=[_build_metadata(r) for r in items],
            )
        logger.info("vector_store: upserted %d record(s)", len(rows))
        return len(rows)
    except Exception as e:
        logger.warning("vector_store: upsert_batch failed: %s", e)
        raise


def upsert(record: dict) -> None:
    upsert_batch([record])


def delete(artifact_id: str) -> None:
    try:
        with _lock:
            _get_collection().delete(ids=[artifact_id])
        logger.info("vector_store: deleted id=%s", artifact_id)
    except Exception as e:
        logger.warning("vector_store: delete failed id=%s: %s", artifact_id, e)
        raise


def drop_and_recreate() -> None:
    global _collection
    try:
        with _lock:
            client = _get_client()
            try:
                client.delete_collection(TABLE_NAME)
            except Exception as e:
                logger.debug("vector_store: delete_collection skipped: %s", e)
            _collection = None
            _get_collection()
        logger.info("vector_store: collection %s dropped and recreated", TABLE_NAME)
    except Exception as e:
        logger.warning("vector_store: drop_and_recreate failed: %s", e)
        raise


def _build_where(domain=None, artifact_type=None, status=None, tier=None) -> dict | None:
    conds = []
    if domain:
        conds.append({"domain": domain})
    if artifact_type:
        conds.append({"type": artifact_type})
    if status:
        conds.append({"status": status})
    if tier:
        conds.append({"tier": tier})
    if not conds:
        return None
    return conds[0] if len(conds) == 1 else {"$and": conds}


def _row_from(id_: str, meta: dict | None, doc: str | None, vector=None) -> dict:
    """Собирает плоский dict записи из Chroma (tags десериализуются из JSON)."""
    meta = meta or {}
    row = {"id": id_}
    for name in _STR_FIELDS:
        row[name] = meta.get(name, "")
    for name in _INT_FIELDS:
        row[name] = int(meta.get(name, 0) or 0)
    row["relevance"] = float(meta.get("relevance", 0.0) or 0.0)
    try:
        row["tags"] = list(json.loads(meta.get("tags_json") or "[]"))
    except (ValueError, TypeError) as e:
        logger.warning("vector_store: bad tags_json id=%s: %s", id_, e)
        row["tags"] = []
    row["search_text"] = doc or ""
    if vector is not None and meta.get("has_vector"):
        row["vector"] = [float(x) for x in vector]
    else:
        row["vector"] = None
    return row


def _snippet(row: dict) -> str:
    return (row.get("core_digest") or "")[:SNIPPET_LEN]


def _fts_rows(col, query: str, where: dict | None, n: int) -> list[dict]:
    """Keyword-поиск: $contains по каждому слову, ранжирование по числу совпавших слов."""
    if not query or not query.strip():
        return []
    try:
        words = list(dict.fromkeys(w for w in query.split() if w))
        hits: dict[str, int] = {}
        rows: dict[str, dict] = {}
        for w in words:
            # $contains чувствителен к регистру — пробуем несколько вариантов
            variants = list(dict.fromkeys([w, w.lower(), w.capitalize()]))
            doc_filter = (
                {"$contains": variants[0]} if len(variants) == 1
                else {"$or": [{"$contains": v} for v in variants]}
            )
            res = col.get(where=where, where_document=doc_filter,
                          include=["metadatas", "documents"])
            for i, id_ in enumerate(res["ids"]):
                hits[id_] = hits.get(id_, 0) + 1
                rows.setdefault(id_, _row_from(id_, res["metadatas"][i], res["documents"][i]))
        ranked = sorted(hits, key=lambda k: hits[k], reverse=True)[:n]
        return [rows[i] for i in ranked]
    except Exception as e:
        logger.warning("vector_store: FTS search failed: %s", e)
        return []


def _with_vector_filter(where: dict | None) -> dict:
    """Добавляет фильтр has_vector, чтобы заглушки не попадали в векторный поиск."""
    cond = {"has_vector": True}
    if not where:
        return cond
    if "$and" in where:
        return {"$and": where["$and"] + [cond]}
    return {"$and": [where, cond]}


def _vector_rows(col, query_vector: list[float], where: dict | None, n: int) -> list[dict]:
    try:
        res = col.query(query_embeddings=[list(query_vector)], n_results=n,
                        where=_with_vector_filter(where),
                        include=["metadatas", "documents", "distances"])
        out = []
        for i, id_ in enumerate(res["ids"][0]):
            row = _row_from(id_, res["metadatas"][0][i], res["documents"][0][i])
            row["_distance"] = res["distances"][0][i]
            out.append(row)
        return out
    except Exception as e:
        logger.warning("vector_store: vector search failed: %s", e)
        return []


def hybrid_search(
    query: str,
    query_vector: list[float] | None = None,
    limit: int = 20,
    domain: str | None = None,
    artifact_type: str | None = None,
    status: str | None = None,
    min_score: float = 0.0,
) -> list[SearchResult]:
    """RRF fusion of vector and FTS rankings; FTS only if query_vector is None."""
    try:
        col = _get_collection()
        where = _build_where(domain, artifact_type, status)
        n = limit * 2
        fts = _fts_rows(col, query, where, n)
        vec = _vector_rows(col, query_vector, where, n) if query_vector is not None else []

        scores: dict[str, float] = {}
        rows: dict[str, dict] = {}
        sem: dict[str, float] = {}
        absent_rank = n + 1
        fts_rank = {r["id"]: i + 1 for i, r in enumerate(fts)}
        vec_rank = {r["id"]: i + 1 for i, r in enumerate(vec)}
        for r in fts + vec:
            rows.setdefault(r["id"], r)
        for r in vec:
            dist = r.get("_distance")
            if dist is not None:
                sem[r["id"]] = 1.0 / (1.0 + float(dist))
        for rid in rows:
            s = 1.0 / (RRF_K + fts_rank.get(rid, absent_rank))
            if query_vector is not None:
                s += 1.0 / (RRF_K + vec_rank.get(rid, absent_rank))
            scores[rid] = s

        out = []
        for rid, s in sorted(scores.items(), key=lambda kv: kv[1], reverse=True):
            if s < min_score:
                continue
            r = rows[rid]
            out.append(SearchResult(
                id=rid,
                title=r.get("title") or "",
                domain=r.get("domain") or "",
                type=r.get("type") or "",
                score=s,
                one_liner=r.get("one_liner") or "",
                snippet=_snippet(r),
                semantic_score=sem.get(rid),
                source_path=r.get("source_path") or "",
            ))
            if len(out) >= limit:
                break
        logger.debug("vector_store: hybrid_search q=%r -> %d results", query, len(out))
        return out
    except Exception as e:
        logger.warning("vector_store: hybrid_search failed: %s", e)
        raise


def get_by_id(artifact_id: str) -> dict | None:
    try:
        res = _get_collection().get(ids=[artifact_id],
                                    include=["metadatas", "documents", "embeddings"])
        found = len(res["ids"]) > 0
        logger.debug("vector_store: get_by_id id=%s found=%s", artifact_id, found)
        if not found:
            return None
        embs = res.get("embeddings")
        vec = embs[0] if embs is not None and len(embs) else None
        return _row_from(res["ids"][0], res["metadatas"][0], res["documents"][0], vec)
    except Exception as e:
        logger.warning("vector_store: get_by_id failed id=%s: %s", artifact_id, e)
        raise


def list_artifacts(
    domain: str | None = None,
    artifact_type: str | None = None,
    status: str | None = None,
    tier: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    try:
        where = _build_where(domain, artifact_type, status, tier)
        res = _get_collection().get(where=where, include=["metadatas", "documents"],
                                    limit=limit, offset=offset)
        rows = [_row_from(id_, res["metadatas"][i], res["documents"][i])
                for i, id_ in enumerate(res["ids"])]
        logger.debug("vector_store: list_artifacts -> %d rows", len(rows))
        return rows
    except Exception as e:
        logger.warning("vector_store: list_artifacts failed: %s", e)
        raise


def get_stats() -> dict:
    try:
        col = _get_collection()
        total = col.count()
        with_vectors = 0
        last_update = ""
        model = ""
        if total:
            res = col.get(include=["metadatas"])
            metas = res["metadatas"] or []
            with_vectors = sum(1 for m in metas if m.get("has_vector"))
            last_update = max((m.get("updated") or "" for m in metas), default="")
            models = [m["embedding_model"] for m in metas if m.get("embedding_model")]
            model = models[-1] if models else ""
        stats = {
            "total": total,
            "with_vectors": with_vectors,
            "last_update": last_update,
            "model": model,
        }
        logger.debug("vector_store: stats %s", stats)
        return stats
    except Exception as e:
        logger.warning("vector_store: get_stats failed: %s", e)
        raise
