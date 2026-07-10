FROM python:3.12-slim

WORKDIR /app

# System dependencies for faster-whisper / CTranslate2 + WeasyPrint PDF export
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libsndfile1 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libgdk-pixbuf-2.0-0 \
        libcairo2 \
        fontconfig \
    && rm -rf /var/lib/apt/lists/*

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

# Fonts for PDF export (BL-159)
COPY pm-bot/web/vendor/fonts/inter-400.ttf /usr/share/fonts/custom/inter-400.ttf
COPY pm-bot/web/vendor/fonts/inter-500.ttf /usr/share/fonts/custom/inter-500.ttf
COPY pm-bot/web/vendor/fonts/inter-600.ttf /usr/share/fonts/custom/inter-600.ttf
COPY pm-bot/web/vendor/fonts/firacode/FiraCode-Regular.ttf /usr/share/fonts/custom/FiraCode-Regular.ttf
COPY pm-bot/web/vendor/fonts/firacode/FiraCode-Bold.ttf /usr/share/fonts/custom/FiraCode-Bold.ttf
COPY pm-bot/web/vendor/fonts/NotoEmoji-Regular.ttf /usr/share/fonts/custom/NotoEmoji-Regular.ttf
RUN fc-cache -f

CMD ["python", "-m", "app.main"]
