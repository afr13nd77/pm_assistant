"""Настройка MCP-сервера и регистрация tools."""
import logging

from mcp.server.fastmcp import FastMCP

from . import tools

logger = logging.getLogger(__name__)


def create_server(host: str = "0.0.0.0", port: int = 8200) -> FastMCP:
    """Создаёт FastMCP-сервер с 4 read-only tools."""
    try:
        mcp = FastMCP("pm-assistant", host=host, port=port, sse_path="/sse")
        mcp.tool(description="Гибридный поиск (векторный + FTS) по базе знаний")(tools.search)
        mcp.tool(description="Сборка контекста по теме в рамках токен-бюджета")(tools.get_context)
        mcp.tool(description="Список артефактов с фильтрами и пагинацией")(tools.list_artifacts)
        mcp.tool(description="Полный дайджест артефакта по id")(tools.get_artifact)
        logger.info("MCP-сервер создан: 4 tools зарегистрировано")
        return mcp
    except Exception:
        logger.exception("Не удалось создать MCP-сервер")
        raise
