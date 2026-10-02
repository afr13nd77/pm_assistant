"""Точка входа MCP-сервера: `python -m mcp_server [sse|stdio]`."""
import logging
import sys

from .server import create_server

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    transport = sys.argv[1] if len(sys.argv) > 1 else "sse"
    try:
        server = create_server(host="0.0.0.0", port=8200)
        logger.info("MCP-сервер запускается, transport=%s", transport)
        if transport == "stdio":
            server.run(transport="stdio")
        else:
            server.run(transport="sse")
    except Exception:
        logger.exception("MCP-сервер завершился с ошибкой")
        raise


if __name__ == "__main__":
    main()
