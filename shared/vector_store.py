"""LanceDB wrapper: the single access point to the digests vector store.

Write API (upsert/delete/drop_and_recreate) is intended for knowledge-engine only;
read API (hybrid_search/get_by_id/list_artifacts/get_stats) for pm-bot and MCP.
"""
import logging
import os
import threading
from dataclasses import dataclass

import pyarrow as pa

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 768
TABLE_NAME = "digests"
DEFAULT_PATH = "/vector-store"
RRF_K = 60
SNIPPET_LEN = 200

DIGESTS_SCHEMA = pa.schema([
    pa.field("id", pa.utf8()),
    pa.field("source_path", pa.utf8()),
    pa.field("type", pa.utf8()),
    pa.field("domain", pa.utf8()),
    pa.field("tier", pa.utf8()),
    pa.field("status", pa.utf8()),
    pa.field("tags", pa.list_(pa.utf8())),
    pa.field("title", pa.utf8()),
    pa.field("relevance", pa.float32()),
    pa.field("one_liner", pa.utf8()),
    pa.field("core_digest", pa.utf8()),
    pa.field("extended_digest", pa.utf8()),
    pa.field("changelog", pa.utf8()),
    pa.field("search_text", pa.utf8()),
    pa.field("vector", pa.list_(pa.float32(), EMBEDDING_DIM), nullable=True),
    pa.field("body_hash", pa.utf8()),
    pa.field("created", pa.utf8()),
    pa.field("updated", pa.utf8()),
    pa.field("embedding_model", pa.utf8()),
    pa.field("embedding_provider", pa.utf8()),
    pa.field("tokens_one_liner", pa.int32()),
    pa.field("tokens_core", pa.int32()),
    pa.field("tokens_extended", pa.int32()),
])

_SCHEMA_FIELDS = [f.name for f in DIGESTS_SCHEMA]

_lock = threading.RLock()
_db = None
_db_path: str | None = None
_table = None
_fts_ready = False


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


def _get_db(path: str | None = None):
    """Singleton connection. A different explicit path reconnects."""
    global _db, _db_path, _table, _fts_ready
    import lancedb

    target = path or os.environ.get("VECTOR_STORE_PATH") or DEFAULT_PATH
    with _lock:
        if _db is None or (path is not None and target != _db_path):
            try:
                os.makedirs(target, exist_ok=True)
                _db = lancedb.connect(target)
            except Exception as e:
                logger.warning("vector_store: connect failed path=%s: %s", target, e)
                raise
            _db_path = target
            _table = None
            _fts_ready = False
            logger.debug("vector_store: connected path=%s", target)
        return _db


def _reset() -> None:
    """Drop cached connection/table (used by tests)."""
    global _db, _db_path, _table, _fts_ready
    with _lock:
        _db = _db_path = _table = None
        _fts_ready = False


def _ensure_fts(table) -> None:
    global _fts_ready
    try:
        table.create_fts_index("search_text", replace=True)
        _fts_ready = True
        logger.debug("vector_store: FTS index ready")
    except Exception as e:
        # Index may already exist / table empty; retried lazily on search
        logger.debug("vector_store: FTS index creation skipped: %s", e)


def _get_table():
    global _table
    with _lock:
        if _table is not None:
            return _table
        db = _get_db()
        try:
            names = db.table_names()
            if TABLE_NAME in names:
                _table = db.open_table(TABLE_NAME)
            else:
                _table = db.create_table(TABLE_NAME, schema=DIGESTS_SCHEMA)
                logger.info("vector_store: created table %s", TABLE_NAME)
            _ensure_fts(_table)
        except Exception as e:
            _table = None
            logger.warning("vector_store: open/create table failed: %s", e)
            raise
        return _table


def _q(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _normalize(record: dict) -> dict:
    out = {}
    for field in DIGESTS_SCHEMA:
        name = field.name
        v = record.get(name)
        if v is None:
            if name == "vector":
                out[name] = None
            elif name == "tags":
                out[name] = []
            elif name == "relevance":
                out[name] = 0.0
            elif name.startswith("tokens_"):
                out[name] = 0
            else:
                out[name] = ""
        else:
            out[name] = v
    if not out["id"]:
        raise ValueError("record must have non-empty 'id'")
    vec = out["vector"]
    if vec is not None and len(vec) != EMBEDDING_DIM:
        raise ValueError(f"vector dim {len(vec)} != {EMBEDDING_DIM}")
    return out


def _to_arrow(rows: list[dict]) -> pa.Table:
    return pa.Table.from_pylist(rows, schema=DIGESTS_SCHEMA)


def _mark_dirty() -> None:
    global _fts_ready
    _fts_ready = False


def upsert_batch(records: list[dict]) -> int:
    """Upsert by id: delete existing rows, then add."""
    if not records:
        return 0
    try:
        rows = {}
        for r in records:
            n = _normalize(r)
            rows[n["id"]] = n  # last wins within the batch
        with _lock:
            table = _get_table()
            ids = ", ".join(_q(i) for i in rows)
            table.delete(f"id IN ({ids})")
            table.add(_to_arrow(list(rows.values())))
            _mark_dirty()
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
            _get_table().delete(f"id = {_q(artifact_id)}")
            _mark_dirty()
        logger.info("vector_store: deleted id=%s", artifact_id)
    except Exception as e:
        logger.warning("vector_store: delete failed id=%s: %s", artifact_id, e)
        raise


def drop_and_recreate() -> None:
    global _table
    try:
        with _lock:
            db = _get_db()
            if TABLE_NAME in db.table_names():
                db.drop_table(TABLE_NAME)
            _table = None
            _get_table()
        logger.info("vector_store: table %s dropped and recreated", TABLE_NAME)
    except Exception as e:
        logger.warning("vector_store: drop_and_recreate failed: %s", e)
        raise


def _build_where(domain=None, artifact_type=None, status=None, tier=None) -> str | None:
    parts = []
    if domain:
        parts.append(f"domain = {_q(domain)}")
    if artifact_type:
        parts.append(f"type = {_q(artifact_type)}")
    if status:
        parts.append(f"status = {_q(status)}")
    if tier:
        parts.append(f"tier = {_q(tier)}")
    return " AND ".join(parts) if parts else None


def _clean(row: dict) -> dict:
    row = {k: v for k, v in row.items() if k in _SCHEMA_FIELDS}
    if "vector" in row and row["vector"] is not None:
        row["vector"] = list(row["vector"])
    if "tags" in row and row["tags"] is not None:
        row["tags"] = list(row["tags"])
    return row


def _snippet(row: dict) -> str:
    return (row.get("core_digest") or "")[:SNIPPET_LEN]


def _fts_rows(table, query: str, where: str | None, n: int) -> list[dict]:
    global _fts_ready
    if not query or not query.strip():
        return []
    if not _fts_ready:
        _ensure_fts(table)
    try:
        q = table.search(query, query_type="fts")
        if where:
            q = q.where(where, prefilter=True)
        return q.limit(n).to_list()
    except Exception as e:
        logger.warning("vector_store: FTS search failed: %s", e)
        return []


def _vector_rows(table, query_vector: list[float], where: str | None, n: int) -> list[dict]:
    try:
        q = table.search(query_vector, vector_column_name="vector")
        if where:
            q = q.where(where, prefilter=True)
        return q.limit(n).to_list()
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
        table = _get_table()
        where = _build_where(domain, artifact_type, status)
        n = limit * 2
        fts = _fts_rows(table, query, where, n)
        vec = _vector_rows(table, query_vector, where, n) if query_vector is not None else []

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
        rows = (
            _get_table().search().where(f"id = {_q(artifact_id)}").limit(1).to_list()
        )
        logger.debug("vector_store: get_by_id id=%s found=%s", artifact_id, bool(rows))
        return _clean(rows[0]) if rows else None
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
        q = _get_table().search()
        where = _build_where(domain, artifact_type, status, tier)
        if where:
            q = q.where(where)
        rows = q.limit(limit + offset).to_list()
        rows = rows[offset:offset + limit]
        logger.debug("vector_store: list_artifacts -> %d rows", len(rows))
        return [_clean(r) for r in rows]
    except Exception as e:
        logger.warning("vector_store: list_artifacts failed: %s", e)
        raise


def get_stats() -> dict:
    try:
        table = _get_table()
        total = table.count_rows()
        with_vectors = table.count_rows("vector IS NOT NULL") if total else 0
        last_update = ""
        model = ""
        if total:
            rows = table.search().select(["updated", "embedding_model"]).limit(total).to_list()
            last_update = max((r["updated"] or "" for r in rows), default="")
            models = [r["embedding_model"] for r in rows if r["embedding_model"]]
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
