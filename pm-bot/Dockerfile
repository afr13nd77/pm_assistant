FROM python:3.12-slim

WORKDIR /app

# System dependencies for faster-whisper / CTranslate2
RUN apt-get update && \
    apt-get install -y --no-install-recommends libsndfile1 && \
    rm -rf /var/lib/apt/lists/*

# Install knowledge-engine as a package (for subprocess calls)
COPY knowledge-engine/requirements.txt /tmp/ke-requirements.txt
RUN pip install --no-cache-dir -r /tmp/ke-requirements.txt

COPY knowledge-engine/app/ /opt/knowledge_engine/knowledge_engine/

# Make it importable as knowledge_engine
ENV PYTHONPATH="/opt/knowledge_engine:${PYTHONPATH}"

# Install pm-bot dependencies (includes faster-whisper)
COPY pm-bot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download Whisper model at build time (not at first run)
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')"

COPY pm-bot/app/ ./app/

CMD ["python", "-m", "app.main"]
