"""
prompts.py — REST API для управления промптами компонентов (BL-197, BL-152 T-09).

Эндпоинты для чтения/сохранения/сброса промптов pm-bot (локально),
knowledge-engine и idea-pipeline (через HTTP-клиенты).
"""

import logging
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import ke_client, pipeline_client
from ..prompt_registry import PROMPT_REGISTRY

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Prompts"])

_PROMPT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_VALID_COMPONENTS = frozenset({"pm-bot", "knowledge-engine", "idea-pipeline"})
MAX_PROMPT_SIZE = 50 * 1024
_pmbot_prompts_dir = Path(__file__).resolve().parent.parent / "prompts"


class PromptSaveRequest(BaseModel):
    content: str = Field(..., max_length=MAX_PROMPT_SIZE)


def _validate_prompt_name(name: str) -> None:
    """Проверяет корректность имени промпта."""
    if not _PROMPT_NAME_RE.match(name):
        logger.error("_validate_prompt_name — invalid name: %s", name)
        raise HTTPException(status_code=400, detail="Invalid prompt name")
    logger.info("_validate_prompt_name — success: %s", name)


def _validate_component(component: str) -> None:
    """Проверяет, что компонент входит в список допустимых."""
    if component not in _VALID_COMPONENTS:
        logger.error("_validate_component — invalid component: %s", component)
        raise HTTPException(status_code=400, detail="Invalid component name")
    logger.info("_validate_component — success: %s", component)


def _safe_prompt_path(name: str, prompts_dir: Path) -> Path:
    """Возвращает безопасный путь к файлу промпта, защищённый от path traversal."""
    _validate_prompt_name(name)
    path = (prompts_dir / f"{name}.txt").resolve()
    if not str(path).startswith(str(prompts_dir.resolve())):
        logger.error("_safe_prompt_path — path traversal attempt: %s", name)
        raise HTTPException(status_code=400, detail="Invalid prompt name")
    if not path.exists():
        logger.error("_safe_prompt_path — prompt not found: %s", name)
        raise HTTPException(status_code=404, detail=f"Prompt not found: {name}")
    logger.info("_safe_prompt_path — success: %s", path)
    return path


def _is_modified(prompt_path: Path) -> bool:
    """Проверяет, отличается ли текущее содержимое промпта от дефолтного."""
    default_path = prompt_path.with_suffix(".txt.default")
    if not default_path.exists():
        return False
    return prompt_path.read_text(encoding="utf-8") != default_path.read_text(encoding="utf-8")


def _get_pmbot_prompts() -> dict:
    """Get pm-bot prompts with metadata from PROMPT_REGISTRY."""
    logger.info("_get_pmbot_prompts — start")
    prompts = []
    for name, meta in PROMPT_REGISTRY.items():
        path = _pmbot_prompts_dir / f"{name}.txt"
        if not path.exists():
            logger.warning("_get_pmbot_prompts — file not found: %s", path)
            continue
        content = path.read_text(encoding="utf-8")
        prompts.append({
            "name": name,
            "description": meta["description"],
            "content": content,
            "lines": content.count("\n") + 1,
            "variables": meta["variables"],
            "is_modified": _is_modified(path),
        })
    logger.info("_get_pmbot_prompts — returning %d prompts", len(prompts))
    return {"status": "ok", "prompts": prompts}


@router.get("/api/v1/prompts/all")
def get_all_prompts():
    logger.info("GET /api/v1/prompts/all — start")
    result = {}

    # pm-bot (local)
    result["pm-bot"] = _get_pmbot_prompts()

    # knowledge-engine (via ke_client)
    try:
        ke_data = ke_client.get_prompts()
        result["knowledge-engine"] = {"status": "ok", "prompts": ke_data.get("prompts", [])}
    except Exception as exc:
        logger.error("GET /api/v1/prompts/all — KE error: %s", exc)
        result["knowledge-engine"] = {"status": "error", "error": str(exc), "prompts": []}

    # idea-pipeline (via pipeline_client)
    try:
        pl_data = pipeline_client.get_prompts()
        result["idea-pipeline"] = {"status": "ok", "prompts": pl_data.get("prompts", [])}
    except Exception as exc:
        logger.error("GET /api/v1/prompts/all — pipeline error: %s", exc)
        result["idea-pipeline"] = {"status": "error", "error": str(exc), "prompts": []}

    logger.info(
        "GET /api/v1/prompts/all — pm-bot=%d, ke=%s, pipeline=%s",
        len(result["pm-bot"].get("prompts", [])),
        result["knowledge-engine"]["status"],
        result["idea-pipeline"]["status"],
    )
    return result


@router.post("/api/v1/prompts/{component}/{name}")
def save_component_prompt(component: str, name: str, request: PromptSaveRequest):
    logger.info("POST /api/v1/prompts/%s/%s — start, content_len=%d", component, name, len(request.content))
    _validate_component(component)
    _validate_prompt_name(name)

    if component == "pm-bot":
        path = _safe_prompt_path(name, _pmbot_prompts_dir)
        path.write_text(request.content, encoding="utf-8")
        result = {
            "status": "ok",
            "name": name,
            "lines": request.content.count("\n") + 1,
            "is_modified": _is_modified(path),
        }
    elif component == "knowledge-engine":
        try:
            result = ke_client.save_prompt(name, request.content)
        except Exception as exc:
            logger.error("POST /api/v1/prompts/%s/%s — KE error: %s", component, name, exc)
            raise HTTPException(status_code=502, detail=f"knowledge-engine service unavailable: {exc}")
    elif component == "idea-pipeline":
        try:
            result = pipeline_client.save_prompt(name, request.content)
        except Exception as exc:
            logger.error("POST /api/v1/prompts/%s/%s — pipeline error: %s", component, name, exc)
            raise HTTPException(status_code=502, detail=f"idea-pipeline service unavailable: {exc}")

    logger.info("POST /api/v1/prompts/%s/%s — done", component, name)
    return result


@router.post("/api/v1/prompts/{component}/{name}/reset")
def reset_component_prompt(component: str, name: str):
    logger.info("POST /api/v1/prompts/%s/%s/reset — start", component, name)
    _validate_component(component)
    _validate_prompt_name(name)

    if component == "pm-bot":
        path = _safe_prompt_path(name, _pmbot_prompts_dir)
        default_path = path.with_suffix(".txt.default")
        if not default_path.exists():
            logger.error("POST /api/v1/prompts/%s/%s/reset — default not found", component, name)
            raise HTTPException(status_code=404, detail=f"Default not found for: {name}")
        content = default_path.read_text(encoding="utf-8")
        path.write_text(content, encoding="utf-8")
        result = {
            "status": "ok",
            "name": name,
            "content": content,
            "lines": content.count("\n") + 1,
            "is_modified": False,
        }
    elif component == "knowledge-engine":
        try:
            result = ke_client.reset_prompt(name)
        except Exception as exc:
            logger.error("POST /api/v1/prompts/%s/%s/reset — KE error: %s", component, name, exc)
            raise HTTPException(status_code=502, detail=f"knowledge-engine service unavailable: {exc}")
    elif component == "idea-pipeline":
        try:
            result = pipeline_client.reset_prompt(name)
        except Exception as exc:
            logger.error("POST /api/v1/prompts/%s/%s/reset — pipeline error: %s", component, name, exc)
            raise HTTPException(status_code=502, detail=f"idea-pipeline service unavailable: {exc}")

    logger.info("POST /api/v1/prompts/%s/%s/reset — done", component, name)
    return result
