from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI
from fastapi.requests import Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # type: ignore[misc, assignment]

from models.config import EXAMPLE_CHIP_LABELS, EXAMPLE_QUESTIONS, RAGConfig
from services.rag_service import MutualFundRAGAssistant


APP_ROOT = Path(__file__).resolve().parent
PUBLIC_ASSETS_DIR = APP_ROOT.parent / "public" / "assets"
LOCAL_ASSETS_DIR = APP_ROOT / "static"
if load_dotenv is not None:
    env_path = APP_ROOT / ".env"
    if env_path.is_file():
        load_dotenv(env_path)


DISALLOWED_FILENAME_TERMS = ("presentation", "other funds", "rsf")
ELIGIBLE_FILENAME_TERMS = (
    "hdfc flexi cap",
    "hdfc elss",
    "hdfc top 100",
    "hdfc large cap",
    "hdfc mf factsheet",
    "riskometer",
    "investor charter",
)


class ChatRequest(BaseModel):
    question: str | None = None
    message: str | None = None


@lru_cache(maxsize=1)
def get_assistant() -> MutualFundRAGAssistant:
    return MutualFundRAGAssistant()


def _discover_pdf_paths(config: RAGConfig) -> list[Path]:
    return sorted(config.data_dir.glob("*.pdf"))


def _eligible_pdf_paths(config: RAGConfig) -> list[Path]:
    eligible_paths: list[Path] = []
    for pdf_path in _discover_pdf_paths(config):
        normalized_name = pdf_path.name.lower()
        if any(disallowed in normalized_name for disallowed in DISALLOWED_FILENAME_TERMS):
            continue
        if any(allowed in normalized_name for allowed in ELIGIBLE_FILENAME_TERMS):
            eligible_paths.append(pdf_path)
    return eligible_paths


def _read_faiss_chunk_count(index_file: Path) -> int:
    if not index_file.exists():
        return 0
    try:
        import faiss
    except ImportError:
        return 0

    try:
        index = faiss.read_index(str(index_file))
    except Exception:
        return 0
    return int(index.ntotal)


def _status_snapshot() -> dict[str, int | bool]:
    config = RAGConfig()
    index_file = config.index_dir / "index.faiss"
    return {
        "pdf_count": len(_discover_pdf_paths(config)),
        "eligible_pdf_count": len(_eligible_pdf_paths(config)),
        "index_ready": index_file.exists(),
        "vector_chunks": _read_faiss_chunk_count(index_file),
    }


def _serialize_response(response) -> dict[str, object]:
    primary_source = response.sources[0] if response.sources else None
    citation = response.primary_citation_url
    retrieved = []
    for i, src in enumerate(response.sources):
        score = src.relevance_score
        retrieved.append(
            {
                "rank": i + 1,
                "citation_url": src.citation_url or "",
                "excerpt": src.excerpt or "",
                "scheme_name": Path(src.filename).stem,
                "chunk_index": i,
                "distance": float(score) if score is not None else None,
                "source": src.filename,
            }
        )
    return {
        "answer": response.answer,
        "last_updated": response.last_updated,
        "source_text": response.short_source_text,
        "citation_url": citation,
        "source_url": citation,
        "source_count": len(response.sources),
        "source_filename": primary_source.filename if primary_source else "",
        "page_number": primary_source.page_number if primary_source else None,
        "retrieved_excerpts": retrieved,
    }


app = FastAPI(
    title="FundClear API",
    description="Facts-only HDFC Mutual Fund FAQ assistant APIs.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url=None,
)
templates = Jinja2Templates(directory=str(APP_ROOT / "templates"))
ASSETS_DIR = PUBLIC_ASSETS_DIR if PUBLIC_ASSETS_DIR.exists() else LOCAL_ASSETS_DIR
app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request,
            "app_name": "FundClear",
            "subtitle": "HDFC MF facts assistant",
            "examples": list(EXAMPLE_QUESTIONS),
            "example_chips": list(zip(EXAMPLE_QUESTIONS, EXAMPLE_CHIP_LABELS, strict=True)),
            "sources_footer_path": "data/sources/sources.csv",
        },
    )


@app.get("/api/ready")
async def ready() -> dict[str, object]:
    status = _status_snapshot()
    return {"status": "ok", "vector_chunks": status["vector_chunks"]}


@app.get("/api/corpus-status")
async def corpus_status() -> dict[str, object]:
    status = _status_snapshot()
    return {
        "status": "ok",
        "pdfs_in_downloaded_sources": status["pdf_count"],
        "eligible_official_pdfs": status["eligible_pdf_count"],
        "vector_index_ready": bool(status["index_ready"]),
        "vector_chunks": status["vector_chunks"],
    }


@app.post("/api/rebuild-index", response_model=None)
async def rebuild_index():
    assistant = get_assistant()
    try:
        assistant.build_index(force_rebuild=True)
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": str(exc)},
        )
    status = assistant.data_status()
    chunks = assistant.vector_chunk_count()
    return {
        "status": "ok",
        "pdfs_in_downloaded_sources": status["pdf_count"],
        "eligible_official_pdfs": status["eligible_pdf_count"],
        "vector_index_ready": bool(status["index_ready"]),
        "vector_chunks": chunks,
    }


@app.get("/api/health")
async def health() -> dict[str, object]:
    status = _status_snapshot()
    return {
        "ok": True,
        "indexed_files": status["eligible_pdf_count"],
        "eligible_official_pdfs": status["eligible_pdf_count"],
        "all_pdfs": status["pdf_count"],
        "pdfs_in_downloaded_sources": status["pdf_count"],
        "index_ready": bool(status["index_ready"]),
    }


@app.get("/api/config")
async def config() -> dict[str, object]:
    status = _status_snapshot()
    return {
        "app_name": "FundClear",
        "subtitle": "HDFC MF facts assistant",
        "examples": list(EXAMPLE_QUESTIONS),
        "status": {
            "indexed_files": status["eligible_pdf_count"],
            "all_pdfs": status["pdf_count"],
            "index_ready": bool(status["index_ready"]),
        },
    }


@app.post("/api/chat", response_model=None)
async def chat(payload: ChatRequest):
    question = str(payload.question or payload.message or "").strip()
    if not question:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "Please enter a question."},
        )

    assistant = get_assistant()
    response = assistant.answer_query(question)
    return {"ok": True, "question": question, "response": _serialize_response(response)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
