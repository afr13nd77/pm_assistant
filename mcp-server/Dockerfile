FROM python:3.12-slim

WORKDIR /app

COPY shared/ /app/shared/
COPY mcp-server/requirements.txt /app/mcp-server/requirements.txt

RUN pip install --no-cache-dir -r /app/mcp-server/requirements.txt

COPY mcp-server/mcp_server/ /app/mcp_server/

ENV PYTHONPATH=/app
ENV VECTOR_STORE_PATH=/vector-store

EXPOSE 8200

CMD ["python", "-m", "mcp_server", "sse"]
