"""
vault_api.py — FastAPI application entry point.

Creates the FastAPI app, registers CORS middleware, includes all
routers from app.routers.*, and defines the startup _warm_cache handler.

No endpoints are defined here — all 72 endpoints live in app/routers/.
"""

import logging
import shutil
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import (
    ai_agent,
    artifacts,
    config,
    decay,
    decisions,
    domains,
    epics,
    ideas,
    jira,
    meetings,
    playground,
    prompts,
    providers,
    reports,
    research,
    settings,
    signals,
    system,
    tasks,
    today,
    todos,
    user_prefs,
    vault_ops,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="PM Vault API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(ai_agent.router)
app.include_router(artifacts.router)
app.include_router(config.router)
app.include_router(decay.router)
app.include_router(decisions.router)
app.include_router(domains.router)
app.include_router(epics.router)
app.include_router(ideas.router)
app.include_router(jira.router)
app.include_router(meetings.router)
app.include_router(playground.router)
app.include_router(prompts.router)
app.include_router(providers.router)
app.include_router(reports.router)
app.include_router(research.router)
app.include_router(settings.router)
app.include_router(signals.router)
app.include_router(system.router)
app.include_router(tasks.router)
app.include_router(today.router)
app.include_router(todos.router)
app.include_router(user_prefs.router)
app.include_router(vault_ops.router)


@app.on_event("startup")
async def _warm_cache():
    """Pre-populate cache on server start so first request is fast."""
    # Create *.txt.default backups for prompt files
    prompts_dir = Path(__file__).parent / "prompts"
    for txt_file in prompts_dir.glob("*.txt"):
        default_file = txt_file.with_suffix(".txt.default")
        if not default_file.exists():
            shutil.copy2(txt_file, default_file)
            logger.info("Created default backup: %s", default_file.name)

    logger.info("_warm_cache: pre-populating vault cache")
    try:
        domains.get_domains()
        ideas.get_ideas()
        tasks.get_tasks()
        epics.get_epics()
        meetings.get_meetings()
        await system.system_status()
        await vault_ops.overview_queue()
        logger.info("_warm_cache: cache populated successfully")
    except Exception as exc:
        logger.warning("_warm_cache: partial failure — %s", exc)
    try:
        vault_ops.vault_health()
    except Exception as exc:
        logger.warning("_warm_cache: vault_health failed: %s", exc)

