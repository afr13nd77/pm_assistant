FROM python:3.12-slim

WORKDIR /app

# Install knowledge-engine modules for reuse (vault_index, matcher, notifier, file_writer, frontmatter_utils)
COPY knowledge-engine/requirements.txt /tmp/ke-requirements.txt
RUN pip install --no-cache-dir -r /tmp/ke-requirements.txt

# Copy knowledge-engine code for Python import
COPY knowledge-engine/app/ /opt/knowledge_engine/knowledge_engine/
ENV PYTHONPATH="/opt/knowledge_engine:${PYTHONPATH}"

# Install idea-pipeline dependencies
COPY idea-pipeline/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY shared/ ./shared/
COPY idea-pipeline/app/ ./idea_pipeline/
COPY idea-pipeline/pipeline.yaml ./pipeline.yaml

CMD ["python", "-m", "idea_pipeline", "serve"]
