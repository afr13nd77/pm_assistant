"""Guard tests for the vault_api.py refactoring (BL-152).

These tests protect against regressions while vault_api.py (5672 lines,
72 endpoints) is split into helper modules and routers. Run this file
after every refactoring step.
"""

import importlib
import logging
from pathlib import Path

import pytest

logger = logging.getLogger(__name__)

EXPECTED_ENDPOINTS = {
    ("GET", "/api/v1/domains"),
    ("GET", "/api/v1/ideas"),
    ("GET", "/api/v1/meetings"),
    ("GET", "/api/v1/decisions"),
    ("GET", "/api/v1/meetings/{filename}"),
    ("GET", "/api/v1/tasks"),
    ("GET", "/api/v1/tasks/by-key/{jira_key}"),
    ("GET", "/api/v1/epics"),
    ("GET", "/api/v1/reports"),
    ("GET", "/api/v1/reports/{filename}"),
    ("POST", "/api/v1/reports/{filename}/pdf"),
    ("POST", "/api/v1/capture"),
    ("POST", "/api/v1/jira/import"),
    ("POST", "/api/v1/jira/create"),
    ("GET", "/api/v1/jira/projects"),
    ("GET", "/api/v1/jira/projects/{project_key}/epics"),
    ("GET", "/api/v1/jira/projects/{projectKey}/issue-types"),
    ("GET", "/api/v1/jira/search"),
    ("POST", "/api/v1/jira/sync"),
    ("POST", "/api/v1/fetch-meetings"),
    ("GET", "/api/v1/timeline/{ticket_id}"),
    ("POST", "/api/v1/synthesize"),
    ("GET", "/api/v1/pipeline"),
    ("GET", "/api/v1/domain-config"),
    ("PUT", "/api/v1/domain-config/{domain_slug}"),
    ("POST", "/api/v1/domain-config/seed"),
    ("GET", "/api/v1/prompts/all"),
    ("POST", "/api/v1/prompts/{component}/{name}"),
    ("POST", "/api/v1/prompts/{component}/{name}/reset"),
    ("GET", "/api/v1/settings"),
    ("POST", "/api/v1/settings"),
    ("GET", "/api/v1/user-prefs"),
    ("PUT", "/api/v1/user-prefs"),
    ("POST", "/api/v1/test-ollama"),
    ("GET", "/api/v1/openrouter-key-status"),
    ("POST", "/api/v1/test-openrouter"),
    ("GET", "/api/v1/openrouter-models"),
    ("POST", "/api/v1/test-caldav"),
    ("POST", "/api/v1/report/regenerate"),
    ("PATCH", "/api/v1/ideas/{filename}/status"),
    ("PATCH", "/api/v1/artifact/{filename}/field"),
    ("PATCH", "/api/v1/artifact/{filename}/body"),
    ("GET", "/api/v1/vault/health"),
    ("POST", "/api/v1/decay/touch"),
    ("POST", "/api/v1/decay/set-tier"),
    ("GET", "/api/v1/decay/snapshot"),
    ("GET", "/api/v1/system/status"),
    ("GET", "/api/v1/search"),
    ("GET", "/api/v1/artifact"),
    ("GET", "/api/v1/jira/sync-status"),
    ("GET", "/api/v1/overview/queue"),
    ("GET", "/api/v1/ideas/creative"),
    ("GET", "/api/v1/playground/providers"),
    ("POST", "/api/v1/playground/chat"),
    ("POST", "/api/v1/ai-agent/chat"),
    ("GET", "/api/v1/system-log"),
    ("GET", "/api/v1/system-log/stats"),
    ("GET", "/api/v1/today/digest"),
    ("GET", "/api/v1/todos"),
    ("POST", "/api/v1/todos"),
    ("PATCH", "/api/v1/todos/{todo_id}"),
    ("GET", "/api/v1/today/news"),
    ("GET", "/api/v1/today/meetings"),
    ("GET", "/api/v1/research-queue/status"),
    ("POST", "/api/v1/research-queue/run"),
    ("POST", "/api/v1/research-queue/retry"),
    ("GET", "/api/v1/signals/runs"),
    ("GET", "/api/v1/signals/runs/{run_id}"),
    ("GET", "/api/v1/signals/list"),
    ("GET", "/api/v1/signals/{signal_id}"),
    ("POST", "/api/v1/signals/{signal_id}/approve"),
    ("POST", "/api/v1/signals/{signal_id}/dismiss"),
}


def test_all_endpoint_urls_exist():
    """Проверяет, что все 72 ожидаемых endpoint зарегистрированы в FastAPI app."""
    from app.vault_api import app as test_app

    all_routes = list(test_app.routes)
    api_routes = [r for r in all_routes if hasattr(r, "path") and getattr(r, "path", "").startswith("/api/v1")]
    assert len(api_routes) > 0, (
        f"app.routes has {len(all_routes)} total routes but 0 start with /api/v1. "
        f"Route paths: {[getattr(r, 'path', '?') for r in all_routes[:20]]}"
    )

    actual_endpoints = set()
    for route in all_routes:
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)
        if not methods or not path:
            continue
        if not path.startswith("/api/v1"):
            continue
        for method in methods:
            if method == "HEAD":
                continue
            actual_endpoints.add((method, path))

    missing = EXPECTED_ENDPOINTS - actual_endpoints
    extra = actual_endpoints - EXPECTED_ENDPOINTS

    assert not missing, f"Missing endpoints: {sorted(missing)}"
    assert not extra, f"Unexpected extra endpoints: {sorted(extra)}"
    logger.info(
        "test_all_endpoint_urls_exist: success, %d endpoints verified", len(EXPECTED_ENDPOINTS)
    )


def test_no_circular_imports():
    """Проверяет отсутствие циклических импортов между vault_* модулями."""
    modules = ["app.vault_cache", "app.vault_parsers", "app.vault_scanner", "app.vault_search"]
    imported = []
    for mod in modules:
        try:
            importlib.import_module(mod)
            imported.append(mod)
        except ModuleNotFoundError:
            pytest.skip(f"{mod} not yet created")
        except Exception as exc:
            logger.error("test_no_circular_imports: import %s failed: %s", mod, exc)
            raise
    logger.info("test_no_circular_imports: success, imported %s", imported)


def test_vault_api_line_count():
    """Проверяет, что vault_api.py после рефакторинга не превышает 200 строк."""
    lines = Path("pm-bot/app/vault_api.py").read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 200, f"vault_api.py has {len(lines)} lines, expected <= 200"
    logger.info("test_vault_api_line_count: success, %d lines", len(lines))


def test_minimum_routers():
    """Проверяет, что после рефакторинга создано не менее 15 роутеров."""
    routers_dir = Path("pm-bot/app/routers")
    if not routers_dir.exists():
        pytest.skip("routers/ not yet created")
    router_files = [f for f in routers_dir.glob("*.py") if f.name != "__init__.py"]
    assert len(router_files) >= 15, f"Found {len(router_files)} routers, expected >= 15"
    logger.info("test_minimum_routers: success, %d routers found", len(router_files))
