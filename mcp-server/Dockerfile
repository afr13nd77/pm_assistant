FROM python:3.12-slim

WORKDIR /app

COPY shared/ /app/shared/
COPY mcp-server/requirements.txt /app/mcp-server/requirements.txt

RUN pip install --no-cache-dir -r /app/mcp-server/requirements.txt

COPY mcp-server/mcp_server/ /app/mcp_server/

ENV PYTHONPATH=/app
ENV VECTOR_STORE_PATH=/vector-store

EXPOSE 8200

# /sse — бесконечный стрим (curl -f зависнет), поэтому проверяем TCP-порт через python
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD python -c "import socket; socket.create_connection(('localhost', 8200), 5).close()" || exit 1

CMD ["python", "-m", "mcp_server", "sse"]
