"""user_prefs.py — эндпоинты пользовательских настроек (refresh mode, тема,
LLM-провайдеры, fallback-цепочки, CalDAV, AI Agent).

Настройки хранятся в .pm-user-prefs.json внутри vault и читаются/пишутся
через _read_user_prefs()/_write_user_prefs(). Эти функции, а также
_AI_AGENT_VALID_PROVIDERS и _load_business_context_file, экспортируются
для использования в других модулях (vault_api.py: jira_sync, ai_agent/
playground эндпоинты).
"""

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..vault_cache import _cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["User Preferences"])


# ---------------------------------------------------------------------------
# User preferences (refresh mode, etc.)
# ---------------------------------------------------------------------------

_VALID_REFRESH_MODES = frozenset({"auto", "manual"})
_VALID_THEMES = frozenset({"matrix", "light"})
_VALID_LLM_PROVIDERS = frozenset({"claude", "ollama", "hybrid"})
_VALID_TRANSCRIPTION_PROVIDERS = frozenset({"default", "openrouter"})
_VALID_CAPTURE_MODES = frozenset({"simple", "extended"})
_VALID_FALLBACK_PROVIDERS = frozenset({"claude", "ollama", "openrouter"})
_VALID_EMBEDDING_PROVIDERS = frozenset({"ollama", "openrouter"})
_CALDAV_PASSWORD_MASK = "••••••••"
# NOTE: также используется в vault_api.py эндпоинтами ai-agent/chat и
# ai-agent/playground (T-24: перенесено сюда, т.к. используется в
# get_user_prefs()/put_user_prefs()).
_AI_AGENT_VALID_PROVIDERS = frozenset({"claude", "ollama", "openrouter"})
_DEFAULT_USER_PREFS = {
    "refresh_mode": "auto",
    "theme": "matrix",
    "llm_provider": "claude",
    "ollama_url": "",
    "ollama_model": "qwen3.5:latest",
    "jira_sync_notify": True,
    "transcription_provider": "default",
    "openrouter_model": "qwen/qwen3-32b",
    "capture_mode": "simple",
    "capture_fallback": ["claude"],
    "transcription_fallback": ["claude"],
    "analysis_fallback": ["claude"],
    "pipeline_fallback": ["claude"],
    "digest_fallback": ["ollama", "claude"],
    "signal_triage_fallback": ["openrouter", "claude"],
    "signal_deep_fallback": ["openrouter", "claude"],
    "signal_analysis_fallback": ["openrouter", "claude"],
    "signal_escalation_fallback": ["openrouter", "claude"],
    "caldav_username": "",
    "caldav_password": "",
    "caldav_timezone": "Europe/Moscow",
    "caldav_url": "https://caldav.yandex.ru/",
    "ai_agent_provider": "claude",
    "ai_agent_model": "",
    "editor_col_split_2": 0.5,
    "editor_col_split_3": [0.4, 0.4, 400],
    "embedding_fallback": ["ollama", "openrouter"],
    "embedding_model_ollama": "nomic-embed-text",
    "embedding_model_openrouter": "text-embedding-3-small",
    "embedding_dim": 768,
}


class UserPrefs(BaseModel):
    refresh_mode: str = "auto"
    theme: str = "matrix"
    llm_provider: str = "claude"
    ollama_url: str = ""
    ollama_model: str = "qwen3.5:latest"
    jira_sync_notify: bool = True
    transcription_provider: str = "default"
    openrouter_model: str = "qwen/qwen3-32b"
    capture_mode: str = "simple"
    # NOTE: intentionally `list[Any]`, not `list[str]` -- elements can be either
    # legacy provider-name strings ("openrouter") or new-format step objects
    # ({"provider": "openrouter", "model": "..."}), see design.md §2.1/§3.4
    # (T-07). Full validation of element shape happens in put_user_prefs(),
    # not at the pydantic-field level, so both formats reach our code intact
    # instead of being rejected/mangled by automatic str coercion.
    capture_fallback: list[Any] = ["claude"]
    transcription_fallback: list[Any] = ["claude"]
    analysis_fallback: list[Any] = ["claude"]
    pipeline_fallback: list[Any] = ["claude"]
    digest_fallback: list[Any] = ["ollama", "claude"]
    signal_triage_fallback: list[Any] = ["openrouter", "claude"]
    signal_deep_fallback: list[Any] = ["openrouter", "claude"]
    signal_analysis_fallback: list[Any] = ["openrouter", "claude"]
    signal_escalation_fallback: list[Any] = ["openrouter", "claude"]
    caldav_username: str = ""
    caldav_password: str = ""
    caldav_timezone: str = "Europe/Moscow"
    caldav_url: str = "https://caldav.yandex.ru/"
    ai_agent_provider: str = "claude"
    ai_agent_model: str = ""
    editor_col_split_2: float = 0.5
    editor_col_split_3: list[Any] = [0.4, 0.4, 400]
    business_context: str = ""
    embedding_fallback: list[Any] = ["ollama", "openrouter"]
    embedding_model_ollama: str = "nomic-embed-text"
    embedding_model_openrouter: str = "text-embedding-3-small"
    embedding_dim: int = 768


def _read_user_prefs() -> dict:
    from shared.vault_paths import user_prefs_path
    path = user_prefs_path()
    if not path.exists():
        logger.info("_read_user_prefs: file not found at %s, returning defaults", path)
        return dict(_DEFAULT_USER_PREFS)
    try:
        import json as _json
        data = _json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            logger.warning("_read_user_prefs: file is not a JSON object, returning defaults")
            return dict(_DEFAULT_USER_PREFS)
        logger.info("_read_user_prefs: loaded prefs from %s", path)
        return data
    except Exception as exc:
        logger.warning("_read_user_prefs: failed to read %s: %s, returning defaults", path, exc)
        return dict(_DEFAULT_USER_PREFS)


def _write_user_prefs(prefs: dict) -> None:
    import json as _json

    from shared.file_writer import atomic_write
    from shared.vault_paths import user_prefs_path
    path = user_prefs_path()
    content = _json.dumps(prefs, indent=2, ensure_ascii=False) + "\n"
    logger.info("_write_user_prefs: writing to %s", path)
    atomic_write(path, content)
    logger.info("_write_user_prefs: success")


def _normalize_fallback_step_for_read(el, default_openrouter_model: str) -> dict:
    """Normalize one fallback-chain element into the canonical object form
    {provider, model} for GET /api/v1/user-prefs (design.md §2.1/§3.2).

    - legacy string "openrouter"      -> {"provider": "openrouter", "model": default_openrouter_model}
    - legacy string "claude"/"ollama" -> {"provider": <that>, "model": None}
    - object {"provider":..,"model":..} for openrouter -> model kept if it's a
      non-empty string, otherwise falls back to default_openrouter_model
    - object {"provider":..} for claude/ollama -> {"provider": <that>, "model": None}
      (any "model" field present on the stored object is ignored, same as PUT
      validation/dedup logic in put_user_prefs()).

    This is read-only / in-memory normalization -- it never rewrites
    .pm-user-prefs.json (design.md §3.2, lazy migration; the file is only
    rewritten when the user explicitly saves via PUT).

    NOTE: intentionally NOT importing the private `_normalize_step`/
    `_default_model_for` helpers from shared/llm_client.py -- same
    architectural decision as T-07's local validation logic in
    put_user_prefs() (see its note above `default_openrouter_model`):
    keeping this module's own small, explicit normalization avoids leaking a
    private cross-module abstraction and avoids coupling GET's "always show a
    default" read semantics to llm_client's execution-resolution semantics,
    which may evolve independently.
    """
    if isinstance(el, str):
        provider = el
        model = default_openrouter_model if provider == "openrouter" else None
        return {"provider": provider, "model": model}
    if isinstance(el, dict):
        provider_val: str | None = el.get("provider")
        if provider_val == "openrouter":
            raw_model = el.get("model")
            model = raw_model if isinstance(raw_model, str) and raw_model.strip() else default_openrouter_model
        else:
            model = None
        return {"provider": provider_val, "model": model}
    # Unknown/invalid shape -- caller filters these out before normalizing
    # (provider extraction below returns None, which is never a valid provider).
    return {"provider": None, "model": None}


def _fallback_step_provider(el):
    """Extract the provider name from a fallback-chain element regardless of
    whether it's a legacy string or a new-format {"provider": ...} object.
    Used only for the GET-side validity filter (see get_user_prefs())."""
    if isinstance(el, str):
        return el
    if isinstance(el, dict):
        return el.get("provider")
    return None


def _load_business_context_file() -> str:
    """Load business-context-brief.md from vault, strip frontmatter."""
    import re as _re

    vault_path = os.getenv("VAULT_PATH", "")
    path = Path(vault_path) / "wiki" / "concepts" / "business-context-brief.md"

    if not path.exists():
        logger.warning("_load_business_context_file: not found at %s", path)
        return ""

    try:
        content = path.read_text(encoding="utf-8")
        content = _re.sub(r"^---\s*\n.*?\n---\s*\n", "", content, count=1, flags=_re.DOTALL)
        logger.info("_load_business_context_file: loaded %d chars", len(content.strip()))
        return content.strip()
    except Exception as exc:
        logger.warning("_load_business_context_file: read failed: %s", exc)
        return ""


@router.get("/api/v1/user-prefs")
def get_user_prefs():
    logger.info("GET /api/v1/user-prefs — start")
    prefs = _read_user_prefs()
    if prefs.get("refresh_mode") not in _VALID_REFRESH_MODES:
        prefs["refresh_mode"] = "auto"
    if prefs.get("theme") not in _VALID_THEMES:
        prefs["theme"] = "matrix"
    if prefs.get("llm_provider") not in _VALID_LLM_PROVIDERS:
        prefs["llm_provider"] = "claude"
    if "ollama_url" not in prefs:
        prefs["ollama_url"] = ""
    if "ollama_model" not in prefs:
        prefs["ollama_model"] = "qwen3.5:latest"
    if "jira_sync_notify" not in prefs:
        prefs["jira_sync_notify"] = True
    if "transcription_provider" not in prefs:
        prefs["transcription_provider"] = "default"
    if "openrouter_model" not in prefs:
        prefs["openrouter_model"] = "qwen/qwen3-32b"
    if prefs.get("capture_mode") not in _VALID_CAPTURE_MODES:
        prefs["capture_mode"] = "simple"
    # --- fallback chains ---
    if "capture_fallback" not in prefs:
        prefs["capture_fallback"] = ["claude"]
    if "transcription_fallback" not in prefs:
        prefs["transcription_fallback"] = ["claude"]
    if "analysis_fallback" not in prefs:
        prefs["analysis_fallback"] = ["claude"]
    if "pipeline_fallback" not in prefs:
        prefs["pipeline_fallback"] = ["claude"]
    if "signal_triage_fallback" not in prefs:
        prefs["signal_triage_fallback"] = _DEFAULT_USER_PREFS.get("signal_triage_fallback", ["openrouter", "claude"])
    if "signal_analysis_fallback" not in prefs:
        prefs["signal_analysis_fallback"] = _DEFAULT_USER_PREFS.get("signal_analysis_fallback", ["openrouter", "claude"])
    if "signal_escalation_fallback" not in prefs:
        prefs["signal_escalation_fallback"] = _DEFAULT_USER_PREFS.get("signal_escalation_fallback", ["openrouter", "claude"])
    # --- CalDAV ---
    if "caldav_username" not in prefs:
        prefs["caldav_username"] = ""
    if "caldav_password" not in prefs:
        prefs["caldav_password"] = ""
    if "caldav_timezone" not in prefs:
        prefs["caldav_timezone"] = "Europe/Moscow"
    if "caldav_url" not in prefs:
        prefs["caldav_url"] = "https://caldav.yandex.ru/"
    # --- AI Agent ---
    if prefs.get("ai_agent_provider") not in _AI_AGENT_VALID_PROVIDERS:
        prefs["ai_agent_provider"] = "claude"
    if "ai_agent_model" not in prefs:
        prefs["ai_agent_model"] = ""
    # --- Editor column split ---
    if "editor_col_split_2" not in prefs:
        prefs["editor_col_split_2"] = 0.5
    if "editor_col_split_3" not in prefs:
        prefs["editor_col_split_3"] = [0.4, 0.4, 400]
    # --- Embeddings (BL-237) ---
    ef = prefs.get("embedding_fallback")
    if (not isinstance(ef, list) or not ef
            or any(p not in _VALID_EMBEDDING_PROVIDERS for p in ef)):
        prefs["embedding_fallback"] = list(_DEFAULT_USER_PREFS["embedding_fallback"])
    if "embedding_model_ollama" not in prefs:
        prefs["embedding_model_ollama"] = _DEFAULT_USER_PREFS["embedding_model_ollama"]
    if "embedding_model_openrouter" not in prefs:
        prefs["embedding_model_openrouter"] = _DEFAULT_USER_PREFS["embedding_model_openrouter"]
    ed = prefs.get("embedding_dim")
    if not isinstance(ed, int) or isinstance(ed, bool) or ed <= 0:
        prefs["embedding_dim"] = _DEFAULT_USER_PREFS["embedding_dim"]
    if not prefs.get("business_context"):
        seeded = _load_business_context_file()
        if seeded:
            prefs["business_context"] = seeded
            logger.info("GET /api/v1/user-prefs — seeded business_context from file (%d chars)", len(seeded))
        else:
            prefs["business_context"] = ""
    from shared.openrouter_client import DEFAULT_MODEL as _OR_DEFAULT_MODEL
    default_openrouter_model = prefs.get("openrouter_model") or _OR_DEFAULT_MODEL
    for key in ("capture_fallback", "transcription_fallback", "analysis_fallback", "pipeline_fallback", "signal_triage_fallback", "signal_analysis_fallback", "signal_escalation_fallback"):
        val = prefs[key]
        if not isinstance(val, list) or len(val) == 0:
            logger.info("GET /api/v1/user-prefs — %s invalid (not list or empty), resetting to default", key)
            prefs[key] = [{"provider": "claude", "model": None}]
        else:
            # T-08: filter must recognize BOTH legacy string elements AND
            # new-format {"provider": ..., "model": ...} step objects (T-07
            # bug -- the old `p in _VALID_FALLBACK_PROVIDERS` check compared a
            # dict against a frozenset of strings, which is always False, so
            # every object-format step was silently dropped here).
            filtered = [el for el in val if _fallback_step_provider(el) in _VALID_FALLBACK_PROVIDERS]
            if not filtered:
                logger.info("GET /api/v1/user-prefs — %s has no valid providers, resetting to default", key)
                prefs[key] = [{"provider": "claude", "model": None}]
            else:
                # Normalize every valid element to the canonical object form
                # {provider, model} so the UI always receives the same shape,
                # regardless of how the step is actually stored on disk
                # (design.md §2.1/§3.2). Read-only -- does not rewrite the file.
                prefs[key] = [
                    _normalize_fallback_step_for_read(el, default_openrouter_model)
                    for el in filtered
                ]
    # Mask CalDAV password before returning
    if prefs.get("caldav_password"):
        prefs["caldav_password"] = _CALDAV_PASSWORD_MASK
    logger.info(
        "GET /api/v1/user-prefs — returning refresh_mode=%s theme=%s"
        " llm_provider=%s caldav_username=%s ai_agent_provider=%s",
        prefs["refresh_mode"], prefs["theme"],
        prefs["llm_provider"], prefs.get("caldav_username", ""),
        prefs.get("ai_agent_provider", "claude"),
    )
    return prefs


@router.put("/api/v1/user-prefs")
def put_user_prefs(body: UserPrefs):
    logger.info(
        "PUT /api/v1/user-prefs — start, refresh_mode=%s theme=%s"
        " capture_mode=%s caldav_username=%s",
        body.refresh_mode, body.theme,
        body.capture_mode, body.caldav_username,
    )
    if body.refresh_mode not in _VALID_REFRESH_MODES:
        logger.warning("PUT /api/v1/user-prefs — invalid refresh_mode: %s", body.refresh_mode)
        raise HTTPException(
            status_code=422,
            detail=f"refresh_mode must be one of: {', '.join(sorted(_VALID_REFRESH_MODES))}"
        )
    if body.theme not in _VALID_THEMES:
        logger.warning("PUT /api/v1/user-prefs — invalid theme: %s", body.theme)
        raise HTTPException(
            status_code=422,
            detail=f"theme must be one of: {', '.join(sorted(_VALID_THEMES))}"
        )
    if body.llm_provider not in _VALID_LLM_PROVIDERS:
        logger.warning("PUT /api/v1/user-prefs — invalid llm_provider: %s", body.llm_provider)
        raise HTTPException(
            status_code=422,
            detail=f"llm_provider must be one of: {', '.join(sorted(_VALID_LLM_PROVIDERS))}"
        )
    if body.transcription_provider not in _VALID_TRANSCRIPTION_PROVIDERS:
        logger.warning("PUT /api/v1/user-prefs — invalid transcription_provider: %s", body.transcription_provider)
        raise HTTPException(
            status_code=422,
            detail=f"transcription_provider must be one of: {', '.join(sorted(_VALID_TRANSCRIPTION_PROVIDERS))}"
        )
    if body.capture_mode not in _VALID_CAPTURE_MODES:
        logger.warning("PUT /api/v1/user-prefs — invalid capture_mode: %s", body.capture_mode)
        raise HTTPException(
            status_code=422,
            detail=f"capture_mode must be one of: {', '.join(sorted(_VALID_CAPTURE_MODES))}"
        )
    # --- AI Agent fields ---
    if body.ai_agent_provider not in _AI_AGENT_VALID_PROVIDERS:
        logger.warning("PUT /api/v1/user-prefs — invalid ai_agent_provider: %s", body.ai_agent_provider)
        body.ai_agent_provider = "claude"
    if not isinstance(body.ai_agent_model, str):
        logger.warning("PUT /api/v1/user-prefs — ai_agent_model is not a string, resetting to empty")
        body.ai_agent_model = ""
    logger.info(
        "PUT /api/v1/user-prefs — ai_agent_provider=%s ai_agent_model=%s",
        body.ai_agent_provider, body.ai_agent_model,
    )
    # --- Editor column split fields ---
    if not isinstance(body.editor_col_split_2, (int, float)):
        logger.warning("PUT /api/v1/user-prefs — editor_col_split_2 is not numeric, resetting to 0.5")
        body.editor_col_split_2 = 0.5
    else:
        body.editor_col_split_2 = max(0.2, min(0.8, float(body.editor_col_split_2)))

    if not isinstance(body.editor_col_split_3, list) or len(body.editor_col_split_3) != 3:
        logger.warning("PUT /api/v1/user-prefs — editor_col_split_3 invalid format, resetting to defaults")
        body.editor_col_split_3 = [0.4, 0.4, 400]
    else:
        try:
            f0 = max(0.15, min(0.7, float(body.editor_col_split_3[0])))
            f1 = max(0.15, min(0.7, float(body.editor_col_split_3[1])))
            px = max(200, min(600, float(body.editor_col_split_3[2])))
            body.editor_col_split_3 = [f0, f1, px]
        except (TypeError, ValueError):
            logger.warning("PUT /api/v1/user-prefs — editor_col_split_3 contains non-numeric values, resetting")
            body.editor_col_split_3 = [0.4, 0.4, 400]

    logger.info(
        "PUT /api/v1/user-prefs — editor_col_split_2=%.2f editor_col_split_3=%s",
        body.editor_col_split_2, body.editor_col_split_3,
    )
    # Fallback-chain element can be a legacy provider-name string ("openrouter")
    # or a new-format step object ({"provider": "openrouter", "model": "..."}).
    # The old "no duplicate providers" check is intentionally REMOVED here --
    # it directly blocked BL-155's goal of multiple openrouter steps with
    # different models in one chain (design.md §3.4). Uniqueness is now
    # considered per (provider, model) pair, and only ADJACENT identical
    # pairs are collapsed (see dedup below) rather than rejected outright.
    from shared.openrouter_client import DEFAULT_MODEL as _OR_DEFAULT_MODEL
    default_openrouter_model = body.openrouter_model or _OR_DEFAULT_MODEL

    for key in ("capture_fallback", "transcription_fallback", "analysis_fallback", "pipeline_fallback", "signal_triage_fallback", "signal_analysis_fallback", "signal_escalation_fallback"):
        chain = getattr(body, key)
        if not isinstance(chain, list) or len(chain) == 0:
            logger.warning("PUT /api/v1/user-prefs — %s is empty or not a list, rejecting", key)
            raise HTTPException(
                status_code=422,
                detail=f"{key} must be a non-empty list of providers: {', '.join(sorted(_VALID_FALLBACK_PROVIDERS))}"
            )

        providers: list = []
        pairs: list = []  # (provider, effective_model) per element, used only to detect adjacent dups
        for el in chain:
            provider: str | None
            model: str | None
            is_object: bool
            if isinstance(el, str):
                provider, model, is_object = el, None, False
            elif isinstance(el, dict):
                provider, model, is_object = el.get("provider"), el.get("model"), True
            else:
                provider, model, is_object = None, None, True
            providers.append(provider)

            if provider == "openrouter" and is_object and (not isinstance(model, str) or not model.strip()):
                logger.warning(
                    "PUT /api/v1/user-prefs — %s has an openrouter step without a valid model: %r",
                    key, el,
                )
                raise HTTPException(
                    status_code=422,
                    detail="OpenRouter step requires a non-empty model",
                )

            if provider == "openrouter":
                effective_model = model if is_object else default_openrouter_model
            else:
                # claude/ollama are single-model providers -- any "model" field
                # on the step object is ignored for validation/dedup purposes
                # (design.md §2.1).
                effective_model = None
            pairs.append((provider, effective_model))

        invalid = [p for p in providers if p not in _VALID_FALLBACK_PROVIDERS]
        if invalid:
            logger.warning("PUT /api/v1/user-prefs — %s contains invalid providers: %s", key, invalid)
            raise HTTPException(
                status_code=422,
                detail=f"{key} contains invalid providers: {', '.join(str(p) for p in invalid)}. Valid: {', '.join(sorted(_VALID_FALLBACK_PROVIDERS))}"
            )

        # Collapse ADJACENT identical steps (design.md §3.4) -- e.g. two
        # consecutive openrouter steps with the exact same model, or two
        # consecutive legacy "openrouter" strings (which resolve to the same
        # default model), add no value and would just repeat the same failed
        # network call twice. Non-adjacent identical steps are left as-is.
        deduped_chain: list = []
        prev_pair = None
        for el, pair in zip(chain, pairs):
            if pair == prev_pair:
                logger.info("PUT /api/v1/user-prefs — %s: collapsing adjacent duplicate step %r", key, el)
                continue
            deduped_chain.append(el)
            prev_pair = pair

        setattr(body, key, deduped_chain)
        logger.info("PUT /api/v1/user-prefs — %s validated: %s", key, deduped_chain)
    # --- Embedding fields (BL-237) ---
    if (not isinstance(body.embedding_fallback, list) or not body.embedding_fallback
            or any(p not in _VALID_EMBEDDING_PROVIDERS for p in body.embedding_fallback)):
        logger.warning("PUT /api/v1/user-prefs — invalid embedding_fallback: %r", body.embedding_fallback)
        raise HTTPException(
            status_code=422,
            detail=f"embedding_fallback must be a non-empty list of: {', '.join(sorted(_VALID_EMBEDDING_PROVIDERS))}"
        )
    if body.embedding_dim <= 0:
        logger.warning("PUT /api/v1/user-prefs — invalid embedding_dim: %s", body.embedding_dim)
        raise HTTPException(status_code=422, detail="embedding_dim must be an integer > 0")
    logger.info(
        "PUT /api/v1/user-prefs — embedding_fallback=%s embedding_dim=%s",
        body.embedding_fallback, body.embedding_dim,
    )
    # CalDAV password sentinel: masked value means "keep current", empty means "clear"
    if body.caldav_password == _CALDAV_PASSWORD_MASK:
        current = _read_user_prefs()
        body.caldav_password = current.get("caldav_password", "")
        logger.info("PUT /api/v1/user-prefs — caldav_password sentinel detected, preserving current value")
    # Merge validated fields into existing prefs to preserve extra keys
    # (e.g. "moderator") that are not part of the UserPrefs Pydantic model
    # but are stored in .pm-user-prefs.json and used by other components
    # (knowledge-engine signal_orchestrator reads moderator.relevance_threshold).
    existing = _read_user_prefs()
    validated = body.model_dump()
    existing.update(validated)
    prefs = existing
    logger.info("PUT /api/v1/user-prefs — merged %d validated fields into existing prefs (preserving extra keys)", len(validated))
    try:
        _write_user_prefs(prefs)
    except Exception as exc:
        logger.error("PUT /api/v1/user-prefs — write failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
    _cache.invalidate()
    try:
        from app.calendar_client import _calendar_cache
        _calendar_cache.invalidate()
        logger.info("PUT /api/v1/user-prefs — CalDAV cache invalidated")
    except ImportError:
        pass
    try:
        from shared.llm_client import invalidate_cache as _invalidate_llm_cache
        _invalidate_llm_cache()
    except ImportError:
        pass
    logger.info("PUT /api/v1/user-prefs — saved successfully")
    return {"status": "ok", "refresh_mode": body.refresh_mode, "theme": body.theme,
            "llm_provider": body.llm_provider, "ollama_url": body.ollama_url,
            "ollama_model": body.ollama_model, "jira_sync_notify": body.jira_sync_notify,
            "transcription_provider": body.transcription_provider,
            "openrouter_model": body.openrouter_model,
            "capture_mode": body.capture_mode,
            "capture_fallback": body.capture_fallback,
            "transcription_fallback": body.transcription_fallback,
            "analysis_fallback": body.analysis_fallback,
            "pipeline_fallback": body.pipeline_fallback,
            "signal_triage_fallback": body.signal_triage_fallback,
            "signal_analysis_fallback": body.signal_analysis_fallback,
            "signal_escalation_fallback": body.signal_escalation_fallback,
            "caldav_username": body.caldav_username,
            "caldav_timezone": body.caldav_timezone,
            "caldav_url": body.caldav_url,
            "ai_agent_provider": body.ai_agent_provider,
            "ai_agent_model": body.ai_agent_model,
            "embedding_fallback": body.embedding_fallback,
            "embedding_model_ollama": body.embedding_model_ollama,
            "embedding_model_openrouter": body.embedding_model_openrouter,
            "embedding_dim": body.embedding_dim}
