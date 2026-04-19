# Build from the repository root (parent of app/):
#   docker build -f app/Dockerfile -t rag-chatbot .
#
# Layout in the image matches what app/server.py expects:
#   APP_ROOT = .../app,  public assets at <repo>/public/assets
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

# gunicorn.conf.py reads PORT from the environment (Cloud Run / App Engine).
CMD ["gunicorn", "-c", "gunicorn.conf.py", "server:app"]
