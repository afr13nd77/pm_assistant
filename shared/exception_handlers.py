"""Глобальные exception handlers для FastAPI (BL-180).

Скрывают внутренние детали ошибок (5xx) от клиента, добавляют request_id
в тело ответа и заголовок X-Request-ID.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Middleware для генерации и прокидывания X-Request-ID."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


def _get_request_id(request: Request) -> str:
    """Возвращает request_id из state или из входящего заголовка."""
    rid = getattr(request.state, "request_id", None)
    return str(rid or request.headers.get(REQUEST_ID_HEADER) or "unknown")


def _json(request_id: str, status_code: int, content: dict[str, Any]) -> JSONResponse:
    content["request_id"] = request_id
    return JSONResponse(
        status_code=status_code,
        content=content,
        headers={REQUEST_ID_HEADER: request_id},
    )


def setup_exception_handlers(app: FastAPI) -> None:
    """Подключает глобальные exception handlers и RequestIdMiddleware."""
    app.add_middleware(RequestIdMiddleware)

    # Unhandled exception обрабатывается ServerErrorMiddleware (снаружи всех
    # middleware), поэтому X-Request-ID выставляем прямо в handler.
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = _get_request_id(request)
        logger.exception("Unhandled exception [request_id=%s]: %s", request_id, type(exc).__name__)
        return _json(request_id, 500, {"detail": "Internal server error"})

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        request_id = _get_request_id(request)
        if exc.status_code >= 500:
            logger.error("HTTP %s [request_id=%s]: %s", exc.status_code, request_id, exc.detail)
            return _json(request_id, exc.status_code, {"detail": "Internal server error"})
        logger.info("HTTP %s [request_id=%s]: %s", exc.status_code, request_id, exc.detail)
        resp = _json(request_id, exc.status_code, {"detail": exc.detail})
        if exc.headers:
            resp.headers.update(exc.headers)
        return resp

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        request_id = _get_request_id(request)
        logger.info("Validation error [request_id=%s]", request_id)
        return _json(
            request_id,
            422,
            {"detail": jsonable_encoder(exc.errors())},
        )

    logger.info("Exception handlers installed")
