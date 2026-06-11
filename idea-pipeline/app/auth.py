import logging
import os

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class ApiKeyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, api_key: str | None = None):
        super().__init__(app)
        self.api_key = api_key or os.getenv("PIPELINE_API_KEY", "")
        if not self.api_key:
            logger.warning(
                "PIPELINE_API_KEY is not set — running in dev mode, all requests are allowed"
            )

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)

        if not self.api_key:
            return await call_next(request)

        provided_key = request.headers.get("X-Pipeline-Key", "")
        if provided_key != self.api_key:
            logger.warning(
                "Unauthorized request: path=%s, remote=%s",
                request.url.path,
                request.client.host if request.client else "unknown",
            )
            return JSONResponse(
                status_code=401,
                content={"error": "unauthorized", "detail": "Invalid or missing API key"},
            )

        return await call_next(request)
