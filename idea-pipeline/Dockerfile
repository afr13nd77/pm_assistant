FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Install idea-pipeline dependencies
COPY idea-pipeline/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY shared/ ./shared/
COPY idea-pipeline/app/ ./idea_pipeline/
COPY idea-pipeline/pipeline.yaml ./pipeline.yaml

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD curl -f http://localhost:8100/health || exit 1

CMD ["python", "-m", "idea_pipeline", "serve"]
