# Cloud Run: `gcloud run deploy ... --source .` looks for Dockerfile at the repo root.
# Canonical build instructions: see app/Dockerfile (keep in sync).
# Build: docker build -t rag-chatbot .

FROM python:3.12-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace/app

WORKDIR /workspace/app

COPY app/requirements.txt /workspace/app/requirements.txt

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY app/ /workspace/app/
COPY public/ /workspace/public/

EXPOSE 8080
ENV PORT=8080

CMD ["gunicorn", "-c", "gunicorn.conf.py", "server:app"]
