# FundClear Quickstart

## Prerequisites

- Python `3.11` or `3.12`
- `pip`
- Local access to the project directory

## 1. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

## 2. Install dependencies

```bash
cd app
pip install -r requirements.txt
```

## 3. Confirm documents exist

Place the official HDFC Mutual Fund source PDFs in:

```text
app/data/sources/
```

If you are already inside the `app/` working directory, that same location is:

```text
data/sources/
```

The current app reads PDFs from that folder and stores the FAISS index in:

```text
app/faiss_index/
```

Inside `app/`, this becomes:

```text
faiss_index/
```

## 4. Start the app

```bash
cd app
uvicorn server:app --reload --host 0.0.0.0 --port 8000
```

Production-style local start:

```bash
cd app
./start.sh
```

## 5. Use FundClear

Example questions:

- `What is the lock-in period of HDFC ELSS Tax Saver?`
- `What is the benchmark of HDFC Flexi Cap Fund?`
- `What is the expense ratio change in HDFC Large Cap Fund?`
- `What is the exit load for HDFC Large Cap Fund?`

## 6. Rebuild the index

When documents change, call the rebuild endpoint from the running app or restart and trigger:

```bash
curl -X POST http://localhost:8000/api/rebuild-index
```

## Notes

- `FundClear` answers from indexed local documents only.
- Sensitive personal data is refused.
- Advisory questions are refused.
- `app/` is the intended working directory for Railway deployment.
- OpenAPI docs are available at `http://localhost:8000/docs`.
- If you see `FastAPI.__call__() missing 1 required positional argument: 'send'`, the app was started with plain Gunicorn sync workers. Use `uvicorn server:app ...` for local dev or `./start.sh` / `gunicorn -k uvicorn.workers.UvicornWorker server:app`.
- For push-based deployments, include `app/faiss_index/` if you want the first deploy to answer without rebuilding.
