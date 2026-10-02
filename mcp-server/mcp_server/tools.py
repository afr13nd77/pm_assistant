"""Реализация 4 read-only tools. Запись в хранилище не вызывается."""
import logging
import os

from shared import embedding_client, vector_store

logger = logging.getLogger(__name__)

os.environ.setdefault("VECTOR_STORE_PATH", "/vector-store")

MAX_LIMIT = 50
TIER1_BUDGET = 3000
TIER2_BUDGET = 10000
TIER3_BUDGET = 6000
_HIDDEN = ("vector", "search_text")


def _tokens(text: str) -> int:
    """Грубая оценка токенов: chars / 4."""
    return (len(text) + 3) // 4


def _strip(row: dict) -> dict:
    return {k: v for k, v in row.items() if k not in _HIDDEN}


def _embed_query(query: str) -> list[float] | None:
    """Вектор запроса; при ошибке None (FTS-only)."""
    try:
        res = embedding_client.embed(query, "mcp_search")
        return res.vector if res else None
    except Exception as e:
        logger.warning("mcp.tools: embed не удался, FTS-only: %s", e)
        return None


def search(query: str, domain: str | None = None, type: str | None = None,
           limit: int = 10) -> dict:
    """Поиск по базе знаний. limit ограничен 50."""
    try:
        limit = max(1, min(int(limit), MAX_LIMIT))
        vector = _embed_query(query)
        found = vector_store.hybrid_search(query, vector, limit, domain, type)
        results = [
            {"id": r.id, "title": r.title, "domain": r.domain, "type": r.type,
             "score": r.score, "one_liner": r.one_liner, "snippet": r.snippet}
            for r in found
        ]
        logger.info("mcp.tools: search q=%r -> %d", query, len(results))
        return {"results": results, "total": len(results)}
    except Exception as e:
        logger.error("mcp.tools: search failed: %s", e)
        return {"error": f"Ошибка поиска: {e}", "results": [], "total": 0}


def get_context(topic: str, token_budget: int = 19000, domain: str | None = None) -> dict:
    """Waterfall-сборка контекста: one-liners -> core -> extended."""
    try:
        vector = _embed_query(topic)
        found = vector_store.hybrid_search(topic, vector, 30, domain, None)
        sources: dict[str, str] = {}
        parts: list[str] = []
        sections = {"one_liners": 0, "core_digests": 0, "extended_digests": 0}
        remaining = max(0, int(token_budget))

        def fill(header: str, items: list[tuple[str, str, str]], budget: int, key: str) -> None:
            nonlocal remaining
            budget = min(budget, remaining)
            lines, used = [], 0
            for aid, title, text in items:
                if not text:
                    continue
                line = f"- [{title}] {text}" if key == "one_liners" else f"### {title}\n{text}"
                t = _tokens(line)
                if used + t > budget:
                    break
                lines.append(line)
                used += t
                sources[aid] = title
            if lines:
                parts.append(f"## {header}\n" + "\n".join(lines))
                sections[key] = used
                remaining -= used

        fill("ONE-LINERS", [(r.id, r.title, r.one_liner) for r in found],
             TIER1_BUDGET, "one_liners")

        def digests(rows, field):
            out = []
            for r in rows:
                full = vector_store.get_by_id(r.id)
                if full:
                    out.append((r.id, r.title, full.get(field) or ""))
            return out

        fill("CORE-DIGESTS", digests(found[:10], "core_digest"), TIER2_BUDGET, "core_digests")
        fill("EXTENDED-DIGESTS", digests(found[:3], "extended_digest"),
             TIER3_BUDGET, "extended_digests")

        context = "\n\n".join(parts)
        total = sum(sections.values())
        logger.info("mcp.tools: get_context topic=%r tokens=%d", topic, total)
        return {"context": context, "total_tokens": total,
                "sources_used": [{"id": i, "title": t} for i, t in sources.items()],
                "sections": sections}
    except Exception as e:
        logger.error("mcp.tools: get_context failed: %s", e)
        return {"error": f"Ошибка сборки контекста: {e}", "context": "",
                "total_tokens": 0, "sources_used": [],
                "sections": {"one_liners": 0, "core_digests": 0, "extended_digests": 0}}


def list_artifacts(domain: str | None = None, type: str | None = None,
                   status: str | None = None, tier: str | None = None,
                   limit: int = 50, offset: int = 0) -> dict:
    """Список артефактов без vector и search_text."""
    try:
        limit = max(1, min(int(limit), MAX_LIMIT))
        offset = max(0, int(offset))
        rows = vector_store.list_artifacts(domain, type, status, tier, limit, offset)
        items = [_strip(r) for r in rows]
        logger.info("mcp.tools: list_artifacts -> %d", len(items))
        return {"artifacts": items, "total": len(items), "limit": limit, "offset": offset}
    except Exception as e:
        logger.error("mcp.tools: list_artifacts failed: %s", e)
        return {"error": f"Ошибка получения списка: {e}", "artifacts": [], "total": 0}


def get_artifact(id: str) -> dict:
    """Полный дайджест артефакта."""
    try:
        row = vector_store.get_by_id(id)
        if not row:
            logger.info("mcp.tools: get_artifact id=%s не найден", id)
            return {"error": "Артефакт не найден", "id": id}
        keys = ("id", "title", "domain", "type", "tier", "status", "tags", "one_liner",
                "core_digest", "extended_digest", "changelog", "source_path", "updated")
        logger.info("mcp.tools: get_artifact id=%s", id)
        return {k: row.get(k) for k in keys}
    except Exception as e:
        logger.error("mcp.tools: get_artifact failed id=%s: %s", id, e)
        return {"error": f"Ошибка получения артефакта: {e}", "id": id}
