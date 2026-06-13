FROM python:3.12-slim

WORKDIR /app

RUN apt-get update -qq && apt-get install -y -qq cron && rm -rf /var/lib/apt/lists/*

COPY knowledge-engine/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ ./shared/
COPY knowledge-engine/app/ ./knowledge_engine/

CMD ["python", "-m", "knowledge_engine", "watch"]
