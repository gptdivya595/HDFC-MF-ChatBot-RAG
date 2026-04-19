from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent.parent


DEFAULT_OFFICIAL_CITATION_FALLBACK = "https://www.hdfcfund.com/investor-services/fund-documents"


@dataclass(frozen=True)
class RAGConfig:
    data_dir: Path = APP_DIR / "data" / "sources"
    sources_catalog_csv: Path = APP_DIR / "data" / "sources" / "sources.csv"
    index_dir: Path = APP_DIR / "faiss_index"
    manifest_path: Path = APP_DIR / "faiss_index" / "manifest.json"
    chunk_size: int = 400
    chunk_overlap: int = 150
    embeddings_model: str = "text-embedding-3-small"
    top_k: int = 8
    fetch_k: int = 12
    similarity_threshold: float = 0.45
    max_answer_sentences: int = 3


EXAMPLE_QUESTIONS = (
    "What is the lock-in period of HDFC ELSS Tax Saver?",
    "What is the benchmark of HDFC Flexi Cap Fund?",
    "What is the expense ratio change in HDFC Large Cap Fund?",
    "What is the exit load for HDFC Large Cap Fund?",
)

EXAMPLE_CHIP_LABELS = (
    "ELSS lock-in",
    "Flexi Cap — benchmark",
    "Large Cap — expense ratio",
    "Large Cap — exit load",
)
