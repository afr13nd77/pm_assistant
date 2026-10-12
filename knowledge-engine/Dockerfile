FROM python:3.12-slim

WORKDIR /app

RUN apt-get update -qq && apt-get install -y -qq cron curl&& rm -rf /var/lib/apt/lists/*

COPY knowledge-engine/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ ./shared/
COPY knowledge-engine/app/ ./knowledge_engine/

HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=3 \
  CMD curl -f http://localhost:8001/api/v1/health || exit 1

CMD ["python", "-m", "knowledge_engine", "watch"]
