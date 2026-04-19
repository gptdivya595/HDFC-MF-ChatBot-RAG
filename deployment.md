# FundClear Deployment

## Recommended deployment shape

For this project, the simplest reliable deployment is:

- one Python environment
- Railway root directory / working directory set to `app/`
- Python version resolved from `.python-version` as `3.12`
- local mounted PDF corpus under `app/data/sources/` in the repo, or `data/sources/` from inside the `app/` working directory
- FastAPI app process served by Gunicorn with the Uvicorn worker
- persistent storage for `app/faiss_index/` in the repo, or `faiss_index/` from inside the `app/` working directory

This keeps `FundClear` aligned with the problem statement: facts-only answers, official-document grounding, and no advisory behavior.

## Deployment checklist

- Install Python `3.11` or `3.12`
- Set Railway root directory to `app/`
- Install the dependencies from `app/requirements.txt`
- Copy the project files to the server
- Copy the approved HDFC PDFs into `app/data/sources/`
- Ensure the process user can write to `app/faiss_index/`
- Start the Gunicorn service with the Uvicorn worker

## GitHub push checklist

- Commit `app/server.py`, `app/static/`, `app/templates/`, `app/services/`, `app/models/`, `app/requirements.txt`, `app/Procfile`, and `app/gunicorn.conf.py`
- Commit `Procfile`, `gunicorn.conf.py`, `requirements.txt`, and `.python-version`
- Do not commit `.env`
- Decide whether to commit `app/faiss_index/`

If `app/faiss_index/` is committed, the deployed app can answer immediately with the shipped index.

If `app/faiss_index/` is not committed, deploy will still succeed, but you must rebuild the index after deploy and keep storage persistent if you want it retained across restarts.

## Install on a Linux VM

```bash
python3 -m venv .venv
source .venv/bin/activate
cd app
pip install -r requirements.txt
gunicorn -k uvicorn.workers.UvicornWorker server:app --bind 0.0.0.0:8000
```

From the repo root, the equivalent command is:

```bash
gunicorn --chdir app server:app
```

## Reverse proxy example

Put Nginx or another reverse proxy in front of Gunicorn if you want:

- TLS termination
- a friendly domain
- basic auth or IP restrictions
- better process isolation

## Persistence

Persist these paths across restarts:

- `app/data/sources/`
- `app/faiss_index/`

If either path is cleared, the app may lose source files or need a full index rebuild.

## Operational guidance

- Rebuild the index whenever PDFs are updated.
- Keep the corpus limited to official HDFC/AMC/regulatory documents.
- Do not position `FundClear` as an investment-advice tool.
- Review responses and cited documents before external publishing.

## Production notes

- The recommended deployment path for this repo is the FastAPI frontend plus Gunicorn process defined in `Procfile`.
- If you later need stronger auth, APIs, or multi-user orchestration, keep the current `models/services` split and extend the HTTP layer around `app/server.py`.

## Troubleshooting

- If logs show `TypeError: FastAPI.__call__() missing 1 required positional argument: 'send'`, Gunicorn is using a WSGI worker against the ASGI app.
- Fix the start command to `gunicorn -k uvicorn.workers.UvicornWorker server:app --bind 0.0.0.0:8000`.
- On Railway, also check whether a custom start command in the dashboard is overriding the repo `Procfile`.
- If the UI loads but answers say the index is missing, either commit `app/faiss_index/` to GitHub or call `POST /api/rebuild-index` after deploy.
