FROM python:3.12-slim

WORKDIR /app

# System dependencies for faster-whisper / CTranslate2
RUN apt-get update && \
    apt-get install -y --no-install-recommends libsndfile1 && \
    rm -rf /var/lib/apt/lists/*

# Install pm-bot dependencies (includes faster-whisper)
COPY pm-bot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download Whisper model — cached between rebuilds via BuildKit cache mount
RUN --mount=type=cache,target=/tmp/hf-cache \
    HF_HOME=/tmp/hf-cache python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')" && \
    mkdir -p /root/.cache && \
    cp -r /tmp/hf-cache /root/.cache/huggingface

COPY shared/ ./shared/
COPY pm-bot/app/ ./app/

CMD ["python", "-m", "app.main"]
