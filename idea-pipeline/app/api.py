import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from slugify import slugify

from idea_pipeline.auth import ApiKeyMiddleware
from idea_pipeline.config import load_config
from idea_pipeline.claude_client import PipelineClaudeClient
from idea_pipeline.state import PipelineStore
from idea_pipeline.orchestrator import PipelineOrchestrator
from idea_pipeline import vault_writer, vault_paths
from idea_pipeline.models import (
    PipelineRunRequest,
    PipelineRunResponse,
    PipelineStatusResponse,
    PipelineResumeRequest,
    PipelineListItem,
    PipelineListResponse,
    HealthResponse,
    ErrorResponse,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="Idea Pipeline API", version="0.1.0")
app.add_middleware(ApiKeyMiddleware)

_store = PipelineStore()
_orchestrator: Optional[PipelineOrchestrator] = None
_vault_path: Optional[Path] = None


@app.on_event("startup")
async def startup():
    global _orchestrator, _vault_path

    vault_path_str = os.getenv("VAULT_PATH", "/vault")
    _vault_path = Path(vault_path_str)

    config_path = os.getenv("PIPELINE_CONFIG", "pipeline.yaml")
    config = load_config(config_path)

    api_key = os.getenv("CLAUDE_API_KEY", "")
    client = PipelineClaudeClient(api_key)

    _orchestrator = PipelineOrchestrator(
        config=config,
        claude_client=client,
        store=_store,
        vault_path=_vault_path,
    )
    logger.info("Idea Pipeline API started: vault_path=%s", _vault_path)


def _validate_file_path(file_path: str, vault_path: Path) -> Path:
    full_path = (vault_path / file_path).resolve()
    vault_resolved = vault_path.resolve()
    if not str(full_path).startswith(str(vault_resolved)):
        raise HTTPException(status_code=400, detail="Invalid file path")
    if not full_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")
    return full_path


@app.post("/pipeline/run", status_code=202, response_model=PipelineRunResponse)
async def run_pipeline(
    request: PipelineRunRequest,
    background_tasks: BackgroundTasks,
):
    logger.info(
        "POST /pipeline/run: start_from=%s, has_text=%s, has_file=%s, "
        "notify_chat_id=%s, domain=%s",
        request.start_from,
        request.text is not None,
        request.file_path is not None,
        request.notify_chat_id,
        request.domain,
    )

    if request.file_path is not None:
        full_path = _validate_file_path(request.file_path, _vault_path)
        input_text = full_path.read_text(encoding="utf-8")
        input_type = "file"
        source_file = request.file_path
        logger.info(
            "POST /pipeline/run: read file %s, chars=%d",
            request.file_path,
            len(input_text),
        )
    else:
        input_text = request.text
        input_type = "text"
        source_file = ""

    slug = slugify(input_text[:40], allow_unicode=True)
    domain = request.domain

    ctx = vault_writer.get_pipeline_context(slug, domain)

    run = _store.create(
        slug=slug,
        input_type=input_type,
        started_from=request.start_from,
        vault_dir=str(ctx["ideas_dir"]),
        domain=domain,
    )

    vault_writer.write_input(
        input_text,
        pipeline_id=run.pipeline_id,
        input_type=input_type,
        slug=slug,
        domain=domain,
        source_file=source_file,
    )

    if _orchestrator.is_running:
        logger.warning(
            "POST /pipeline/run: conflict, pipeline %s is already running",
            _orchestrator.running_pipeline_id,
        )
        raise HTTPException(
            status_code=409,
            detail=f"Pipeline {_orchestrator.running_pipeline_id} is already running",
        )

    background_tasks.add_task(
        _orchestrator.run_pipeline,
        run.pipeline_id,
        input_text,
        request.start_from,
        request.notify_chat_id,
    )

    logger.info(
        "POST /pipeline/run: 202, pipeline_id=%s, slug=%s, domain=%s",
        run.pipeline_id,
        slug,
        domain,
    )

    return PipelineRunResponse(
        pipeline_id=run.pipeline_id,
        status=run.stage.value,
        vault_dir=str(ctx["ideas_dir"]),
        message="Pipeline started",
    )


@app.get("/pipeline/{pipeline_id}", response_model=PipelineStatusResponse)
async def get_pipeline_status(pipeline_id: str):
    logger.info("GET /pipeline/%s", pipeline_id)

    run = _store.get(pipeline_id)
    if run is None:
        logger.warning("GET /pipeline/%s: not found", pipeline_id)
        raise HTTPException(status_code=404, detail=f"Pipeline not found: {pipeline_id}")

    logger.info(
        "GET /pipeline/%s: 200, status=%s, artifacts=%d",
        pipeline_id,
        run.stage.value,
        len(run.artifacts),
    )

    return PipelineStatusResponse(
        pipeline_id=run.pipeline_id,
        status=run.stage.value,
        slug=run.slug,
        vault_dir=run.vault_dir,
        created_at=run.created_at.isoformat(),
        updated_at=run.updated_at.isoformat(),
        artifacts=list(run.artifacts),
        error=run.error,
        failed_stage=run.failed_stage,
    )


@app.post(
    "/pipeline/{pipeline_id}/resume",
    status_code=202,
    response_model=PipelineRunResponse,
)
async def resume_pipeline(
    pipeline_id: str,
    request: PipelineResumeRequest,
    background_tasks: BackgroundTasks,
):
    logger.info(
        "POST /pipeline/%s/resume: start_from=%s", pipeline_id, request.start_from
    )

    run = _store.get(pipeline_id)
    if run is None:
        logger.warning("POST /pipeline/%s/resume: not found", pipeline_id)
        raise HTTPException(status_code=404, detail=f"Pipeline not found: {pipeline_id}")

    domain = run.domain
    slug = run.slug
    today = __import__("datetime").date.today().isoformat()

    # Locate prerequisite artifacts in the new domain-based directories
    prerequisite_map = {
        "pm": ("ideas", f"{today}-{slug}-analysis.md"),
        "decomposer": ("prds", f"{today}-{slug}-prd.md"),
    }
    if request.start_from in prerequisite_map:
        artifact_type, artifact_name = prerequisite_map[request.start_from]
        artifact_dir = vault_paths.wiki_domain_dir(domain, artifact_type)
        artifact_path = artifact_dir / artifact_name
        if not artifact_path.exists():
            logger.warning(
                "POST /pipeline/%s/resume: prerequisite %s not found at %s",
                pipeline_id,
                artifact_name,
                artifact_path,
            )
            raise HTTPException(
                status_code=400,
                detail=f"Prerequisite artifact not found: {artifact_name}",
            )
        input_text = artifact_path.read_text(encoding="utf-8")
        logger.info(
            "POST /pipeline/%s/resume: loaded %s, chars=%d",
            pipeline_id,
            artifact_name,
            len(input_text),
        )
    else:
        raw_dir = vault_paths.raw_ideas()
        input_path = raw_dir / f"{today}-{slug}-input.md"
        input_text = input_path.read_text(encoding="utf-8") if input_path.exists() else ""

    if _orchestrator.is_running:
        logger.warning(
            "POST /pipeline/%s/resume: conflict, pipeline %s is already running",
            pipeline_id,
            _orchestrator.running_pipeline_id,
        )
        raise HTTPException(
            status_code=409,
            detail=f"Pipeline {_orchestrator.running_pipeline_id} is already running",
        )

    background_tasks.add_task(
        _orchestrator.run_pipeline,
        pipeline_id,
        input_text,
        request.start_from,
        None,
    )

    logger.info(
        "POST /pipeline/%s/resume: 202, start_from=%s", pipeline_id, request.start_from
    )

    return PipelineRunResponse(
        pipeline_id=run.pipeline_id,
        status=run.stage.value,
        vault_dir=run.vault_dir,
        message=f"Pipeline resumed from {request.start_from}",
    )


@app.get("/pipeline/", response_model=PipelineListResponse)
async def list_pipelines(
    limit: int = Query(default=20, ge=1, le=100),
    status: Optional[str] = Query(default=None),
):
    logger.info("GET /pipeline/: limit=%d, status=%s", limit, status)

    runs = _store.list_runs(limit=limit, status_filter=status)
    items = [
        PipelineListItem(
            pipeline_id=r.pipeline_id,
            slug=r.slug,
            status=r.stage.value,
            created_at=r.created_at.isoformat(),
            artifacts_count=len(r.artifacts),
        )
        for r in runs
    ]

    logger.info("GET /pipeline/: 200, returned %d runs", len(items))

    return PipelineListResponse(runs=items, total=len(items))


@app.get("/health", response_model=HealthResponse)
async def health():
    logger.info("GET /health")

    vault_accessible = _vault_path is not None and _vault_path.exists()
    claude_api_configured = bool(os.getenv("CLAUDE_API_KEY", ""))

    logger.info(
        "GET /health: vault_accessible=%s, claude_api_configured=%s",
        vault_accessible,
        claude_api_configured,
    )

    return HealthResponse(
        status="ok",
        version="0.1.0",
        vault_accessible=vault_accessible,
        claude_api_configured=claude_api_configured,
    )
