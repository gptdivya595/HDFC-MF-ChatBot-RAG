# FundClear

`FundClear` is a facts-only mutual fund FAQ assistant built on an HDFC Mutual Fund document corpus. It uses local PDF ingestion, HuggingFace embeddings, a FAISS vector index, and a FastAPI-served web UI. The deployable application now lives inside the `app/` folder so `app/` can be used as the Railway working directory.

## What it does

- Answers objective mutual-fund questions from local official documents only.
- Retrieves from HDFC fund PDFs with FAISS and OpenAI embeddings.
- Refuses investment advice and blocks sensitive personal information.
- Shows short source-backed responses with a single official citation and source date.

## App Folder

The production app is organized under `app/`:

- `app/server.py` — FastAPI entrypoint and JSON API
- `app/templates/index.html` — app shell markup
- `app/static/styles.css` — custom FundClear UI
- `app/static/app.js` — chat interactions and API wiring
- `app/services/` — RAG ingestion, indexing, and retrieval logic
- `app/models/` — shared dataclasses and configuration

## Project structure

- `app/server.py` — FastAPI entrypoint and API routes
- `app/models/` — shared dataclasses and configuration
- `app/services/` — RAG ingestion, indexing, and retrieval logic
- `app/templates/` — HTML frontend templates
- `app/static/` — frontend CSS and JavaScript assets
- `app/data/sources/` — local source PDFs and source catalog files
- `app/rag_pipeline.py` — compatibility wrapper around the refactored RAG service

## Supported corpus

The assistant is intentionally narrow and focuses on official HDFC Mutual Fund documents such as:

- KIMs
- SIDs
- factsheets
- investor charter
- riskometer disclosures
- expense ratio notices

Known non-corpus documents like presentations and unrelated “other funds” PDFs are filtered out during ingestion.

## Guardrails

- No investment advice
- No performance recommendations
- No PAN, Aadhaar, phone number, or email sharing
- No internet/blog-based answers during chat retrieval
- Responses are concise and grounded in the approved source corpus

## Product description

`FundClear` follows the problem statement for a facts-only mutual fund FAQ assistant:

- product name: `FundClear`
- corpus: official HDFC Mutual Fund, AMC, AMFI, and SEBI-aligned documents in the local source set
- response style: short, factual, citation-backed, and non-advisory
- UI goal: minimal, readable, and support-oriented

## Run locally

See [quickstart.md](/Users/shukugup/divya/rag_chatbot/quickstart.md) for the fastest setup path.

## Deployment

See [deployment.md](/Users/shukugup/divya/rag_chatbot/deployment.md) for deployment guidance.

## Railway Ready Notes

- Python runtime is pinned with `.python-version` to `3.12`.
- The repo includes FastAPI-first Gunicorn config for Railway-safe startup.
- If you want immediate answers after deploy, push `app/faiss_index/` with the repo or mount persistent storage and rebuild the index once after deployment.
