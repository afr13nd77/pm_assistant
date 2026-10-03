import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

import requests as _requests

logger = logging.getLogger(__name__)

DEFAULTS: dict = {
    "embedding_fallback": ["ollama", "openrouter"],
    "embedding_model_ollama": "nomic-embed-text",
    "embedding_model_openrouter": "text-embedding-3-small",
    "embedding_dim": 1024,
}

_OLLAMA_TIMEOUT = 30
_OPENROUTER_BATCH_SIZE = 100
_KNOWN_PROVIDERS = ("ollama", "openrouter")


@dataclass
class EmbeddingResult:
    vector: list[float]
    model: str
    provider: str
    dim: int


def _load_embedding_prefs() -> dict:
    """Read .pm-user-prefs.json from vault; return embedding fields + ollama_url with defaults."""
    prefs = dict(DEFAULTS)
    prefs["ollama_url"] = ""

    data_dir = os.getenv("PM_BOT_DATA_PATH", os.getenv("VAULT_PATH", ""))
    prefs_path = Path(data_dir) / ".pm-user-prefs.json"
    try:
        if prefs_path.exists():
            data = json.loads(prefs_path.read_text(encoding="utf-8"))
            for key in (*DEFAULTS.keys(), "ollama_url"):
                if data.get(key) not in (None, "", []):
                    prefs[key] = data[key]
            logger.info("_load_embedding_prefs: loaded prefs from file, chain=%s", prefs["embedding_fallback"])
        else:
            logger.info("_load_embedding_prefs: prefs file not found, using defaults")
    except Exception as e:
        logger.warning("_load_embedding_prefs: failed to read prefs file: %s, using defaults", e)
    return prefs


def _call_ollama_embed(text: str, prefs: dict) -> list[float]:
    url = prefs.get("ollama_url", "").rstrip("/")
    model = prefs.get("embedding_model_ollama", DEFAULTS["embedding_model_ollama"])
    resp = _requests.post(f"{url}/api/embed", json={"model": model, "input": text}, timeout=_OLLAMA_TIMEOUT)
    resp.raise_for_status()
    vector = resp.json()["embeddings"][0]
    logger.info("_call_ollama_embed: success, model=%s, dim=%d", model, len(vector))
    return vector


def _call_openrouter_embed_many(texts: list[str], prefs: dict) -> list[list[float]]:
    from openai import OpenAI  # lazy: may be absent in pm-bot

    model = prefs.get("embedding_model_openrouter", DEFAULTS["embedding_model_openrouter"])
    dim = prefs.get("embedding_dim", DEFAULTS["embedding_dim"])
    client = OpenAI(
        api_key=os.getenv("OPENROUTER_API_KEY", ""),
        base_url="https://openrouter.ai/api/v1",
    )
    resp = client.embeddings.create(input=texts, model=model, dimensions=dim)
    vectors = [d.embedding for d in resp.data]
    logger.info("_call_openrouter_embed_many: success, model=%s, count=%d, dim=%d", model, len(vectors), dim)
    return vectors


def _call_openrouter_embed(text: str, prefs: dict) -> list[float]:
    return _call_openrouter_embed_many([text], prefs)[0]


def _resolve_chain(prefs: dict) -> list[str]:
    chain = prefs.get("embedding_fallback", DEFAULTS["embedding_fallback"])
    if not isinstance(chain, list) or not chain:
        logger.warning("_resolve_chain: invalid embedding_fallback, using default")
        chain = DEFAULTS["embedding_fallback"]
    return [p for p in chain if p in _KNOWN_PROVIDERS]


def _is_available(provider: str, prefs: dict) -> bool:
    if provider == "ollama":
        ok = bool(prefs.get("ollama_url", ""))
        if not ok:
            logger.info("_is_available: ollama skipped (ollama_url not configured)")
        return ok
    if provider == "openrouter":
        ok = bool(os.getenv("OPENROUTER_API_KEY"))
        if not ok:
            logger.info("_is_available: openrouter skipped (OPENROUTER_API_KEY not set)")
        return ok
    return False


def _model_for(provider: str, prefs: dict) -> str:
    key = "embedding_model_ollama" if provider == "ollama" else "embedding_model_openrouter"
    return prefs.get(key, DEFAULTS[key])


def _make_result(vector: list[float], provider: str, prefs: dict) -> EmbeddingResult:
    return EmbeddingResult(
        vector=vector, model=_model_for(provider, prefs), provider=provider, dim=len(vector),
    )


def _log_event(status: str, summary: str, details: dict, t0: int) -> None:
    try:
        from shared.system_log import log_event
        log_event(
            process_type="llm-call",
            status=status,
            summary=summary,
            details=details,
            duration_ms=(time.monotonic_ns() - t0) // 1_000_000,
            source="embedding-client",
        )
    except Exception:
        pass


def embed(text: str, operation: str = "embedding") -> EmbeddingResult | None:
    """Embed text via the fallback chain (ollama -> openrouter). None if all providers fail."""
    prefs = _load_embedding_prefs()
    chain = _resolve_chain(prefs)
    t0 = time.monotonic_ns()
    errors: list[dict] = []

    for provider in chain:
        if not _is_available(provider, prefs):
            continue
        try:
            if provider == "ollama":
                vector = _call_ollama_embed(text, prefs)
            else:
                vector = _call_openrouter_embed(text, prefs)
            result = _make_result(vector, provider, prefs)
            logger.info("embed: success, operation=%s, provider=%s, model=%s, dim=%d",
                        operation, provider, result.model, result.dim)
            _log_event("success", f"{operation} via {provider}", {
                "operation": operation, "provider": provider, "model": result.model,
                "dim": result.dim, "fallback_errors": errors,
            }, t0)
            return result
        except Exception as exc:
            logger.warning("embed: %s failed for operation=%s: %s", provider, operation, exc)
            errors.append({"provider": provider, "error": str(exc)})

    logger.error("embed: all providers failed, operation=%s, chain=%s", operation, chain)
    _log_event("error", f"{operation}: all embedding providers failed",
               {"operation": operation, "chain": chain, "errors": errors}, t0)
    return None


def embed_batch(texts: list[str], operation: str = "embedding") -> list[EmbeddingResult | None]:
    """Embed many texts. Texts that failed on one provider are retried on the next."""
    results: list[EmbeddingResult | None] = [None] * len(texts)
    if not texts:
        return results

    prefs = _load_embedding_prefs()
    chain = _resolve_chain(prefs)
    t0 = time.monotonic_ns()
    errors: list[dict] = []

    for provider in chain:
        pending = [i for i, r in enumerate(results) if r is None]
        if not pending:
            break
        if not _is_available(provider, prefs):
            continue

        if provider == "ollama":
            for i in pending:
                try:
                    results[i] = _make_result(_call_ollama_embed(texts[i], prefs), provider, prefs)
                except Exception as exc:
                    logger.warning("embed_batch: ollama failed for item %d: %s", i, exc)
                    errors.append({"provider": provider, "index": i, "error": str(exc)})
        else:
            for start in range(0, len(pending), _OPENROUTER_BATCH_SIZE):
                idxs = pending[start:start + _OPENROUTER_BATCH_SIZE]
                try:
                    vectors = _call_openrouter_embed_many([texts[i] for i in idxs], prefs)
                    if len(vectors) != len(idxs):
                        raise RuntimeError(f"openrouter returned {len(vectors)} vectors for {len(idxs)} inputs")
                    for i, vec in zip(idxs, vectors):
                        results[i] = _make_result(vec, provider, prefs)
                except Exception as exc:
                    logger.warning("embed_batch: openrouter failed for batch of %d: %s", len(idxs), exc)
                    errors.append({"provider": provider, "count": len(idxs), "error": str(exc)})

    failed = sum(1 for r in results if r is None)
    if failed == 0:
        logger.info("embed_batch: success, operation=%s, count=%d", operation, len(texts))
        status = "success"
    else:
        logger.error("embed_batch: %d/%d failed, operation=%s", failed, len(texts), operation)
        status = "error"
    _log_event(status, f"{operation}: batch {len(texts) - failed}/{len(texts)} embedded", {
        "operation": operation, "chain": chain, "total": len(texts), "failed": failed, "errors": errors,
    }, t0)
    return results
