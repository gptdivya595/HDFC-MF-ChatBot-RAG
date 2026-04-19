from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass
from typing import Iterable, Sequence

import numpy as np
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import PyPDFLoader
from langchain_community.vectorstores import FAISS
from langchain_community.vectorstores.utils import maximal_marginal_relevance
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings

from models.chat import ChatbotResponse, SourceCitation
from models.config import DEFAULT_OFFICIAL_CITATION_FALLBACK, RAGConfig
from services.source_catalog import load_local_pdf_to_citation_url


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "me",
    "of",
    "on",
    "or",
    "please",
    "should",
    "tell",
    "the",
    "this",
    "to",
    "what",
    "which",
    "who",
    "with",
}

INVESTMENT_ADVICE_PATTERNS = (
    r"\bshould i invest\b",
    r"\bshould i buy\b",
    r"\bshould i redeem\b",
    r"\bwhich fund is best\b",
    r"\bwhich fund is better\b",
    r"\bwhich is better\b",
    r"\bbest fund\b",
    r"\bcompare returns\b",
    r"\bwhich should i choose\b",
    r"\bis it good\b",
    r"\bworth investing\b",
    r"\brecommend\b",
    r"\badvice\b",
    r"\bgood investment\b",
    r"\breturn(?:s)?\s+(?:comparison|calculator)\b",
    r"\bperformance\s+comparison\b",
    r"\bwill.*go up\b",
    r"\bpredict\b",
)

FUND_DOMAIN_SIGNALS = (
    "elss",
    "sip",
    "nav",
    "expense ratio",
    "exit load",
    "ter",
    "benchmark",
    "lock-in",
    "lock in",
    "riskometer",
    "mutual fund",
    "hdfc",
    "flexi cap",
    "large cap",
    "top 100",
    "tax saver",
    "factsheet",
    "kim",
    "sid",
    "amfi",
    "sebi",
    "minimum investment",
    "folio",
    "idcw",
    "growth option",
    "direct plan",
    "regular plan",
    "aaum",
    "aum",
    "fund house",
    "amc",
    "capital gains",
    "statement",
    "redemption",
    "allotment",
)

OFF_TOPIC_GREETINGS = re.compile(
    r"^\s*(?:hi|hello|hey|howdy|greetings|good\s+(?:morning|afternoon|evening|day)"
    r"|what(?:'s| is) up|sup|yo|namaste)\W*$",
    re.IGNORECASE,
)

MIN_FACTUAL_TOKENS = 4  # queries shorter than this with no domain signal are off-topic

REFUSAL_EDUCATIONAL_URL = "https://www.amfiindia.com/investor-corner/knowledge-center"
OFFSCOPE_RESPONSE = (
    "FundClear answers only factual questions about HDFC Mutual Fund schemes "
    "(expense ratio, exit load, lock-in, benchmark, minimum investment, riskometer). "
    "Please ask a specific fund fact query."
)
ADVICE_REFUSAL_RESPONSE = (
    "FundClear cannot provide investment advice, recommendations, or fund comparisons. "
    "For educational resources, visit the AMFI Investor Corner: "
    + REFUSAL_EDUCATIONAL_URL
)

PAN_PATTERN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
AADHAAR_PATTERN = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+91[\-\s]?)?[6-9]\d{9}(?!\d)")
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
WHITESPACE_PATTERN = re.compile(r"\s+")
SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+|\n+|(?:\u2022)\s*")
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
PERCENT_PATTERN = re.compile(r"\d+(?:\.\d+)?%")
# NAV / rupee amounts as printed in factsheets (avoid matching years like 2025 alone)
INR_AMOUNT_PATTERN = re.compile(
    r"(?i)(?:₹|rs\.?|inr)\s*[\d,]+(?:\.\d+)?|[\d,]+\.\d{4}\b"
)
DATE_PATTERN = re.compile(
    r"\b\d{1,2}(?:[-/]\d{1,2}(?:[-/]\d{2,4})?|"
    r"\s+[A-Za-z]+\s+\d{4}|"
    r"\s+[A-Za-z]+\s*,?\s+\d{4})\b"
)


def clean_answer(text: str) -> str:
    """Normalize whitespace. Answer length is capped in `_compose_answer` via `max_answer_sentences`."""
    return WHITESPACE_PATTERN.sub(" ", (text or "").strip())


class MutualFundRAGAssistant:
    """Facts-only FAQ assistant grounded in local HDFC Mutual Fund documents."""

    def __init__(self, config: RAGConfig | None = None) -> None:
        self.config = config or RAGConfig()
        self.config.data_dir.mkdir(parents=True, exist_ok=True)
        self.config.index_dir.mkdir(parents=True, exist_ok=True)
        self._embeddings: OpenAIEmbeddings | None = None
        self._vector_store: FAISS | None = None
        self._text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
        )
        self._pdf_to_citation_url = load_local_pdf_to_citation_url(
            self.config.sources_catalog_csv
        )

    def _require_openai_api_key(self) -> str:
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not key:
            raise RuntimeError(
                "OPENAI_API_KEY is required for embeddings and answer synthesis in this deployment."
            )
        return key

    def _get_embeddings(self) -> OpenAIEmbeddings:
        if self._embeddings is None:
            self._embeddings = OpenAIEmbeddings(
                api_key=self._require_openai_api_key(),
                model=os.environ.get("OPENAI_EMBEDDING_MODEL", self.config.embeddings_model).strip(),
            )
        return self._embeddings

    def _citation_url_for_pdf(self, filename: str) -> str:
        mapped = self._pdf_to_citation_url.get(filename)
        if mapped:
            return mapped
        return DEFAULT_OFFICIAL_CITATION_FALLBACK

    def _filter_documents_by_scheme(self, query: str, documents: list[Document]) -> list[Document]:
        """Prefer chunks from the PDF whose filename matches the scheme named in the query."""
        q = query.lower()
        picked: list[Document] = []
        if "large cap" in q and "flexi" not in q and "large and mid" not in q:
            picked = [
                d
                for d in documents
                if "large" in d.metadata["filename"].lower()
                and "cap" in d.metadata["filename"].lower()
                and "flexi" not in d.metadata["filename"].lower()
            ]
        elif "flexi cap" in q or "flexicap" in q:
            picked = [d for d in documents if "flexi" in d.metadata["filename"].lower()]
        elif "elss" in q or "tax saver" in q or "tax-saver" in q:
            picked = [
                d
                for d in documents
                if "elss" in d.metadata["filename"].lower() or "tax saver" in d.metadata["filename"].lower()
            ]
        elif "liquid fund" in q or ("liquid" in q and "fund" in q):
            picked = [d for d in documents if "liquid" in d.metadata["filename"].lower()]
        return picked

    def _compose_answer_openai(
        self, query: str, documents: Sequence[Document]
    ) -> tuple[str, list[SourceCitation]] | None:
        """Optional LLM synthesis — mirrors rag_sample ``RAGPipeline.query`` when ``OPENAI_API_KEY`` is set."""
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not key:
            return None
        try:
            from openai import OpenAI
        except ImportError:
            return None

        max_chunks = 6
        per_chunk = 2800
        blocks: list[str] = []
        sources: list[SourceCitation] = []
        seen_pages: set[tuple[str, int]] = set()
        for i, doc in enumerate(documents[:max_chunks], 1):
            fn = str(doc.metadata["filename"])
            pg = int(doc.metadata["page_number"])
            cite = SourceCitation(
                filename=fn,
                page_number=pg,
                excerpt=doc.page_content[:280],
                relevance_score=doc.metadata.get("relevance_score"),
                modified_at=doc.metadata.get("modified_at"),
                citation_url=self._citation_url_for_pdf(fn),
            )
            tup = (fn, pg)
            if tup not in seen_pages:
                sources.append(cite)
                seen_pages.add(tup)
            body = doc.page_content[:per_chunk]
            blocks.append(f"[{i}] file={fn} page={pg}\n{body}")

        ctx = "\n\n---\n\n".join(blocks)
        model = (
            os.environ.get("OPENAI_MODEL")
            or os.environ.get("DEFAULT_MODEL")
            or "gpt-4o-mini"
        ).strip()
        client = OpenAI(api_key=key)
        system = (
            "You are a facts-only assistant for HDFC Mutual Fund official documents. "
            "Use ONLY the provided context chunks. Reply in at most 3 short sentences. "
            "Quote numbers exactly as printed. "
            "For exit load / expense ratio / lock-in / benchmark questions: answer only for what was asked—"
            "do not paste asset-allocation tables, blocks of unrelated fund names, or raw PDF headers. "
            "If the context does not clearly state the fact, say the documents retrieved do not spell it out. "
            "No investment advice."
        )
        try:
            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"Context:\n{ctx}\n\nQuestion:\n{query}"},
                ],
                temperature=0.2,
                max_tokens=450,
            )
            text = (completion.choices[0].message.content or "").strip()
        except Exception:
            return None
        if not text:
            return None
        return text, sources

    def answer_query(self, query: str, force_rebuild: bool = False) -> ChatbotResponse:
        cleaned_query = query.strip()
        if not cleaned_query:
            return ChatbotResponse(
                answer="Ask a factual question about HDFC Mutual Fund schemes.",
                is_refusal=True,
            )

        if self._contains_sensitive_information(cleaned_query):
            return ChatbotResponse(
                answer="Do not share sensitive personal information (PAN, Aadhaar, account number, OTP).",
                is_refusal=True,
            )

        if self._is_investment_advice_request(cleaned_query):
            return ChatbotResponse(
                answer=ADVICE_REFUSAL_RESPONSE,
                is_refusal=True,
                educational_url=REFUSAL_EDUCATIONAL_URL,
            )

        # Off-topic guard: must run BEFORE retrieval, not after.
        # The MMR fallback path in retrieve() bypasses similarity_threshold,
        # so without this check any query reaches _compose_answer with live chunks.
        if self._is_off_topic(cleaned_query):
            return ChatbotResponse(
                answer=OFFSCOPE_RESPONSE,
                is_refusal=True,
                educational_url=REFUSAL_EDUCATIONAL_URL,
            )

        try:
            retrieved_documents = self.retrieve(
                cleaned_query, force_rebuild=force_rebuild
            )
        except FileNotFoundError:
            return ChatbotResponse(
                answer="No indexed documents found. Rebuild the index via the status panel.",
                is_refusal=True,
            )

        if not retrieved_documents:
            return ChatbotResponse(
                answer="The indexed documents do not contain a clear answer to that query. "
                "Verify the question refers to an HDFC scheme in the corpus.",
                is_refusal=True,
            )

        scheme_filtered = self._filter_documents_by_scheme(cleaned_query, retrieved_documents)
        if scheme_filtered:
            retrieved_documents = scheme_filtered

        answer_text, supporting_sources = self._compose_answer(cleaned_query, retrieved_documents)
        if not answer_text:
            return ChatbotResponse(
                answer="The documents retrieved do not clearly state the answer. "
                "Rephrase or check the official factsheet directly.",
                is_refusal=True,
            )

        # Prefer deterministic extraction for structured factual questions.
        # This avoids optional LLM synthesis missing explicit facts already
        # present in the retrieved PDF text, such as "lock in of 3 years".
        if self._should_prefer_deterministic_answer(cleaned_query):
            return ChatbotResponse(
                answer=clean_answer(answer_text),
                sources=supporting_sources,
                last_updated=self._last_updated_from_sources(supporting_sources),
            )

        llm_result = self._compose_answer_openai(cleaned_query, retrieved_documents)
        if llm_result is not None:
            llm_answer_text, llm_supporting_sources = llm_result
            if llm_answer_text:
                return ChatbotResponse(
                    answer=clean_answer(llm_answer_text),
                    sources=llm_supporting_sources,
                    last_updated=self._last_updated_from_sources(llm_supporting_sources),
                )

        return ChatbotResponse(
            answer=clean_answer(answer_text),
            sources=supporting_sources,
            last_updated=self._last_updated_from_sources(supporting_sources),
        )

    def _should_prefer_deterministic_answer(self, query: str) -> bool:
        return self._detect_query_type(query) in {
            "lock_in",
            "benchmark",
            "expense_ratio",
            "riskometer",
            "exit_load",
            "minimum_investment",
            "nav",
            "scheme_snapshot",
        }

    def _retrieval_query(self, query: str) -> str:
        """
        Expand very short / keyword-only queries so embedding search finds factsheets
        and definitional chunks, not only section headers (see `rag_Architecture.md` retrieval notes).
        """
        q = query.strip()
        low = q.lower()
        tokens = low.split()
        if len(tokens) <= 3 and (
            low == "elss"
            or ("elss" in low and len(tokens) <= 4)
            or "tax saver" in low
            or "tax-saver" in low
        ):
            return (
                f"{q} HDFC ELSS Tax Saver Fund scheme factsheet NAV net asset value "
                "expense ratio TER lock-in benchmark portfolio"
            )
        if len(tokens) <= 2 and "flexi" in low:
            return f"{q} HDFC Flexi Cap Fund factsheet NAV expense ratio benchmark"
        if len(tokens) <= 2 and ("large cap" in low or "top 100" in low):
            return f"{q} HDFC Large Cap Fund factsheet NAV expense ratio benchmark"
        if len(tokens) <= 3 and ("nav" in low or "net asset value" in low):
            return f"{q} regular growth direct IDCW option closing NAV"
        if "exit load" in low:
            return (
                f"{q} HDFC Mutual Fund exit load redemption repurchase "
                "charge NIL percent holding period months year KIM SID factsheet"
            )
        if "expense ratio" in low or " ter " in low or low.strip() == "ter":
            return f"{q} total expense ratio TER percent direct regular growth IDCW"
        return q

    def retrieve(self, query: str, force_rebuild: bool = False) -> list[Document]:
        search_q = self._retrieval_query(query)
        vector_store = self._get_vector_store(force_rebuild=force_rebuild)
        threshold_hits = vector_store.similarity_search_with_relevance_scores(
            search_q,
            k=self.config.fetch_k,
        )

        qualified_by_id: dict[str, float] = {}
        for document, score in threshold_hits:
            if score >= self.config.similarity_threshold:
                qualified_by_id[document.metadata["chunk_id"]] = score

        retriever = vector_store.as_retriever(search_type="mmr", search_kwargs={"k": 6})
        docs = list(retriever.invoke(search_q))

        if not docs or len(docs) < 2:
            docs = vector_store.similarity_search(search_q, k=6)

        selected_documents: list[Document] = []
        seen_chunk_ids: set[str] = set()
        for document in docs:
            chunk_id = document.metadata.get("chunk_id")
            if not chunk_id or chunk_id in seen_chunk_ids:
                continue
            if chunk_id in qualified_by_id:
                document.metadata["relevance_score"] = qualified_by_id[chunk_id]
            selected_documents.append(document)
            seen_chunk_ids.add(chunk_id)

        if selected_documents:
            return selected_documents[: self.config.top_k]

        fallback_documents: list[Document] = []
        for document, score in threshold_hits:
            chunk_id = document.metadata["chunk_id"]
            if chunk_id in seen_chunk_ids or chunk_id not in qualified_by_id:
                continue
            document.metadata["relevance_score"] = score
            fallback_documents.append(document)
            seen_chunk_ids.add(chunk_id)
            if len(fallback_documents) == self.config.top_k:
                break

        return fallback_documents

    def build_index(self, force_rebuild: bool = False) -> int:
        documents = self._load_documents()
        if not documents:
            raise FileNotFoundError(
                f"No eligible PDFs were found in {self.config.data_dir}. Add the official HDFC Mutual Fund PDFs and try again."
            )

        should_rebuild = force_rebuild or self._index_is_stale()
        if not should_rebuild and self._vector_store is None:
            self._vector_store = FAISS.load_local(
                str(self.config.index_dir),
                self._get_embeddings(),
                allow_dangerous_deserialization=True,
            )
            return len(documents)

        chunks = self._chunk_documents(documents)
        self._vector_store = FAISS.from_documents(chunks, self._get_embeddings())
        self._vector_store.save_local(str(self.config.index_dir))
        self.config.manifest_path.write_text(
            json.dumps(self._manifest_payload(), indent=2),
            encoding="utf-8",
        )
        return len(documents)

    def data_status(self) -> dict[str, int]:
        pdf_count = len(self._discover_pdf_paths())
        eligible_count = len(self._eligible_pdf_paths())
        indexed = int((self.config.index_dir / "index.faiss").exists())
        return {
            "pdf_count": pdf_count,
            "eligible_pdf_count": eligible_count,
            "index_ready": indexed,
        }

    def vector_chunk_count(self) -> int:
        """Number of vectors in the FAISS index (0 if no index on disk)."""
        if not (self.config.index_dir / "index.faiss").exists():
            return 0
        try:
            store = self._get_vector_store()
            return int(store.index.ntotal)
        except Exception:
            return 0

    def _get_vector_store(self, force_rebuild: bool = False) -> FAISS:
        if self._vector_store is not None and not force_rebuild:
            return self._vector_store

        self.build_index(force_rebuild=force_rebuild)
        if self._vector_store is None:
            raise RuntimeError("Vector store could not be initialized.")
        return self._vector_store

    def _discover_pdf_paths(self) -> list[Path]:
        return sorted(self.config.data_dir.glob("*.pdf"))

    def _eligible_pdf_paths(self) -> list[Path]:
        eligible_paths: list[Path] = []
        for pdf_path in self._discover_pdf_paths():
            normalized_name = pdf_path.name.lower()
            if any(disallowed in normalized_name for disallowed in ("presentation", "other funds", "rsf")):
                continue
            if any(
                allowed in normalized_name
                for allowed in (
                    "hdfc flexi cap",
                    "hdfc elss",
                    "hdfc top 100",
                    "hdfc large cap",
                    "hdfc mf factsheet",
                    "riskometer",
                    "investor charter",
                )
            ):
                eligible_paths.append(pdf_path)
        return eligible_paths

    def _load_documents(self) -> list[Document]:
        page_documents: list[Document] = []
        for pdf_path in self._eligible_pdf_paths():
            loader = PyPDFLoader(str(pdf_path))
            for page in loader.load():
                content = self._normalize_whitespace(page.page_content)
                if not content:
                    continue
                page_number = int(page.metadata.get("page", 0)) + 1
                page_documents.append(
                    Document(
                        page_content=content,
                        metadata={
                            "filename": pdf_path.name,
                            "page_number": page_number,
                            "source": pdf_path.name,
                            "modified_at": int(pdf_path.stat().st_mtime),
                        },
                    )
                )
        return page_documents

    def _chunk_documents(self, documents: Sequence[Document]) -> list[Document]:
        split_documents = self._text_splitter.split_documents(list(documents))
        chunked_documents: list[Document] = []
        for index, document in enumerate(split_documents):
            metadata = dict(document.metadata)
            metadata["chunk_id"] = (
                f"{metadata['filename']}::page-{metadata['page_number']}::chunk-{index}"
            )
            chunked_documents.append(Document(page_content=document.page_content, metadata=metadata))
        return chunked_documents

    def _build_manifest(self) -> list[dict[str, str | int]]:
        manifest: list[dict[str, str | int]] = []
        for pdf_path in self._eligible_pdf_paths():
            stat = pdf_path.stat()
            manifest.append(
                {
                    "name": pdf_path.name,
                    "size": stat.st_size,
                    "modified": int(stat.st_mtime),
                }
            )
        return manifest

    def _manifest_payload(self) -> dict[str, object]:
        return {
            "embedding_backend": "openai",
            "embedding_model": os.environ.get("OPENAI_EMBEDDING_MODEL", self.config.embeddings_model).strip(),
            "documents": self._build_manifest(),
        }

    def _index_is_stale(self) -> bool:
        index_file = self.config.index_dir / "index.faiss"
        store_file = self.config.index_dir / "index.pkl"
        if not index_file.exists() or not store_file.exists() or not self.config.manifest_path.exists():
            return True

        try:
            current_manifest = self._manifest_payload()
            stored_manifest = json.loads(self.config.manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return True

        if not isinstance(stored_manifest, dict):
            return True
        return current_manifest != stored_manifest

    def _compose_answer(
        self,
        query: str,
        documents: Sequence[Document],
    ) -> tuple[str, list[SourceCitation]]:
        ranked_candidates: list[tuple[float, str, SourceCitation]] = []
        query_terms = self._query_terms(query)
        query_type = self._detect_query_type(query)
        seen_units: set[str] = set()

        for rank, document in enumerate(documents):
            source = SourceCitation(
                filename=document.metadata["filename"],
                page_number=int(document.metadata["page_number"]),
                excerpt=document.page_content[:280],
                relevance_score=document.metadata.get("relevance_score"),
                modified_at=document.metadata.get("modified_at"),
                citation_url=self._citation_url_for_pdf(document.metadata["filename"]),
            )

            for unit in self._extract_answer_units(document.page_content, query_type):
                concise_unit = self._summarize_answer_unit(query, unit, query_type)
                if self._is_noise_fact_unit(concise_unit, query_type):
                    continue
                if self._is_low_signal_heading(concise_unit, query_type):
                    continue
                normalized_unit = concise_unit.lower()
                if normalized_unit in seen_units:
                    continue
                score = self._score_answer_unit(
                    query_terms, concise_unit, rank, query_type=query_type
                )
                if score <= 0:
                    continue
                ranked_candidates.append((score, concise_unit, source))
                seen_units.add(normalized_unit)

        ranked_candidates.sort(key=lambda item: item[0], reverse=True)
        if not ranked_candidates:
            return "", []

        answer_sentences: list[str] = []
        sources: list[SourceCitation] = []
        seen_sources: set[tuple[str, int]] = set()

        for _, sentence, source in ranked_candidates:
            concise_sentence = self._ensure_sentence(sentence)
            if not concise_sentence:
                continue
            answer_sentences.append(concise_sentence)
            source_key = (source.filename, source.page_number)
            if source_key not in seen_sources:
                sources.append(source)
                seen_sources.add(source_key)
            if len(answer_sentences) >= self.config.max_answer_sentences:
                break

        answer = " ".join(answer_sentences[: self.config.max_answer_sentences]).strip()
        return answer, sources

    def _last_updated_from_sources(self, sources: Sequence[SourceCitation]) -> str:
        timestamps = [source.modified_at for source in sources if source.modified_at]
        if not timestamps:
            return "N/A"
        return datetime.fromtimestamp(max(timestamps)).strftime("%d %b %Y")

    def _extract_answer_units(self, content: str, query_type: str = "generic") -> list[str]:
        body = content
        if query_type == "exit_load":
            low = content.lower()
            anchor = low.find("exit load")
            if anchor == -1:
                anchor = low.find("exit-load")
            if anchor >= 0:
                start = max(0, anchor - 120)
                end = min(len(content), anchor + 900)
                body = content[start:end]

        units: list[str] = []
        for raw_unit in SENTENCE_SPLIT_PATTERN.split(body):
            cleaned = self._normalize_whitespace(raw_unit)
            if 12 <= len(cleaned) <= 280:
                units.append(cleaned)

        if units:
            return units

        cleaned_content = self._normalize_whitespace(body)
        if cleaned_content:
            cap = 320 if query_type == "exit_load" else 220
            return [cleaned_content[:cap]]
        return []

    def _summarize_answer_unit(self, query: str, answer_unit: str, query_type: str) -> str:
        cleaned_unit = self._normalize_whitespace(answer_unit)
        best_clause = self._select_best_clause(cleaned_unit, query, query_type)

        if query_type == "lock_in":
            duration = re.search(
                r"(?i)\b(\d+\s*(?:day|days|month|months|year|years))\b",
                cleaned_unit,
            )
            if duration:
                return f"Lock-in period: {duration.group(1)}"

        if query_type == "benchmark":
            benchmark = re.search(
                r"(?i)\b(?:nifty|s&p\s*bse|bse|crisil|nse)\b[^.;:,]*?(?:tri|index)\b",
                cleaned_unit,
            )
            if benchmark:
                return f"Benchmark: {self._clean_fact_value(benchmark.group(0))}"

        if query_type == "expense_ratio":
            percentages = PERCENT_PATTERN.findall(cleaned_unit)
            effective_date = DATE_PATTERN.search(cleaned_unit)
            if len(percentages) >= 2 and "from" in cleaned_unit.lower() and "to" in cleaned_unit.lower():
                answer = f"Expense ratio changed from {percentages[0]} to {percentages[1]}"
                if effective_date:
                    answer += f" effective {effective_date.group(0)}"
                return answer
            if percentages:
                answer = f"Expense ratio: {', '.join(percentages[:2])}"
                if effective_date:
                    answer += f" effective {effective_date.group(0)}"
                return answer

        if query_type == "riskometer":
            risk_level = re.search(
                r"(?i)\b(low|low to moderate|moderate|moderately high|high|very high)\b",
                cleaned_unit,
            )
            if risk_level:
                return f"Risk level: {risk_level.group(1)}"

        if query_type == "exit_load":
            low_u = cleaned_unit.lower()
            if re.search(r"(?i)\b(nil|not\s+applicable|n\.a\.)\b", low_u) and re.search(
                r"(?i)exit", low_u
            ):
                return "Exit load: Nil (per the excerpt)."
            pct_after_exit = re.search(
                r"(?i)exit\s*load\s*[:\s\-–]{0,6}[^\n.;]{0,240}?(\d+(?:\.\d+)?%)",
                cleaned_unit,
            )
            if pct_after_exit:
                return f"Exit load: {pct_after_exit.group(1)}"
            if "exit" in low_u:
                pct_line = re.search(r"(?i)\b\d+(?:\.\d+)?%\b(?:\s*[^.;]{0,40})?", cleaned_unit)
                if pct_line:
                    return f"Exit load: {self._clean_fact_value(pct_line.group(0))}"

        if query_type == "minimum_investment":
            minimum = re.search(r"(?i)\b(?:rs\.?|inr)\s*[\d,]+(?:\.\d+)?\b", cleaned_unit)
            if minimum:
                return f"Minimum investment: {self._clean_fact_value(minimum.group(0))}"

        if query_type == "nav":
            amt = INR_AMOUNT_PATTERN.search(cleaned_unit)
            date_m = DATE_PATTERN.search(cleaned_unit)
            if amt:
                line = f"NAV / pricing: {self._clean_fact_value(amt.group(0))}"
                if date_m:
                    line += f" (as stated for {date_m.group(0).strip()})"
                return line

        if query_type == "scheme_snapshot":
            snippets: list[str] = []
            amt = INR_AMOUNT_PATTERN.search(cleaned_unit)
            if amt and (
                re.search(r"(?i)\bnav\b|net asset value|pricing", cleaned_unit)
                or re.search(r"(?i)\b(?:regular|direct|growth|idcw)\s*(?:option|plan)?\b", cleaned_unit)
            ):
                snippets.append(f"NAV: {self._clean_fact_value(amt.group(0))}")
            ter = PERCENT_PATTERN.findall(cleaned_unit)
            if ter and re.search(
                r"(?i)\b(?:ter|expense|total expense|direct|regular|idcw|growth)\b",
                cleaned_unit,
            ):
                snippets.append(f"Expense ratio / TER: {ter[0]}")
            lock = re.search(
                r"(?i)(?:lock-in|lock\s+in)\s*[:\s]+[^.;]{0,55}?\b(\d+\s*(?:year|years|month|months))\b",
                cleaned_unit,
            )
            if not lock:
                lock = re.search(
                    r"(?i)\b(\d+\s*(?:year|years))\s+(?:of\s+)?(?:lock|lock-in|lock\s+in)\b",
                    cleaned_unit,
                )
            if lock:
                snippets.append(f"Lock-in: {self._clean_fact_value(lock.group(1))}")
            if snippets:
                return "; ".join(snippets)

        return best_clause

    def _select_best_clause(self, text: str, query: str, query_type: str) -> str:
        clauses = [self._normalize_whitespace(text)]
        clauses.extend(
            self._normalize_whitespace(part)
            for part in re.split(r"\s*[;|]\s*|,\s+", text)
            if self._normalize_whitespace(part)
        )

        query_terms = self._query_terms(query)
        best_clause = self._normalize_whitespace(text)
        best_score = float("-inf")

        for clause in clauses:
            score = self._score_answer_unit(
                query_terms, clause, rank=0, query_type=query_type
            )
            score -= max(0, len(clause) - 120) / 25
            if len(clause) < 8:
                score -= 5
            if score > best_score:
                best_score = score
                best_clause = clause

        return self._clean_fact_value(best_clause)

    def _detect_query_type(self, query: str) -> str:
        lowered_query = query.lower()
        if "lock-in" in lowered_query or "lock in" in lowered_query:
            return "lock_in"
        if "benchmark" in lowered_query:
            return "benchmark"
        if "expense ratio" in lowered_query:
            return "expense_ratio"
        if "riskometer" in lowered_query or "risk level" in lowered_query or "risk" in lowered_query:
            return "riskometer"
        if "exit load" in lowered_query:
            return "exit_load"
        if "minimum investment" in lowered_query or "minimum amount" in lowered_query or "min investment" in lowered_query:
            return "minimum_investment"
        if "nav" in lowered_query or "net asset value" in lowered_query:
            return "nav"
        words = lowered_query.split()
        if len(words) <= 4 and (
            "elss" in lowered_query
            or "tax saver" in lowered_query
            or "tax-saver" in lowered_query
        ):
            return "scheme_snapshot"
        return "generic"

    def _clean_fact_value(self, text: str) -> str:
        cleaned = self._normalize_whitespace(text)
        cleaned = re.sub(
            r"^(?:the scheme(?:'s)?|scheme|fund)\s+(?:has|is|shall have|offers)\s+",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\bfrom the date of allotment\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,;:.")
        return cleaned

    def _ensure_sentence(self, text: str) -> str:
        cleaned = self._clean_fact_value(text)
        if not cleaned:
            return ""
        if cleaned.endswith((".", "!", "?")):
            return cleaned
        return f"{cleaned}."

    def _looks_like_scheme_fact_line(self, answer_unit: str) -> bool:
        if PERCENT_PATTERN.search(answer_unit) or INR_AMOUNT_PATTERN.search(answer_unit):
            return True
        if re.search(r"(?i)\block(?:-in| in)\b", answer_unit) and re.search(r"\d", answer_unit):
            return True
        if re.search(r"(?i)\b(?:nifty|bse\s*sensex|benchmark)\b", answer_unit):
            return True
        return False

    def _is_noise_fact_unit(self, text: str, query_type: str) -> bool:
        """Reject PDF table dumps and continuation banners mistaken for sentences."""
        low = text.lower()
        noise_markers = (
            "contd from previous page",
            "category of scheme",
            "exit load$$",
            "scheme asset allocation",
            "portfolio composition",
        )
        if any(m in low for m in noise_markers):
            return True
        pct_n = len(PERCENT_PATTERN.findall(text))
        if query_type == "exit_load":
            if pct_n >= 6 and not re.search(r"(?i)exit", low):
                return True
            if pct_n >= 4 and len(text) > 180 and not re.search(r"(?i)exit", low):
                return True
        return False

    def _score_answer_unit(
        self,
        query_terms: set[str],
        answer_unit: str,
        rank: int,
        *,
        query_type: str = "generic",
    ) -> float:
        if query_type == "exit_load":
            pct_n = len(PERCENT_PATTERN.findall(answer_unit))
            if pct_n >= 5 and not re.search(r"(?i)exit", answer_unit.lower()):
                return 0.0
        tokens = set(TOKEN_PATTERN.findall(answer_unit.lower()))
        overlap = query_terms & tokens
        if not overlap:
            if query_type == "scheme_snapshot" and self._looks_like_scheme_fact_line(
                answer_unit
            ):
                overlap = {"_fact"}
            elif query_type == "nav" and INR_AMOUNT_PATTERN.search(answer_unit):
                overlap = {"_nav"}
            else:
                return 0.0

        numeric_overlap = {token for token in overlap if token.isdigit()}
        score = float(len(overlap)) + (2.0 * len(numeric_overlap))
        if len(overlap) == len(query_terms):
            score += 1.0
        score += max(0.0, 1.5 - (rank * 0.25))
        if any(symbol in answer_unit for symbol in ("%", "year", "years", "month", "months", "tri", "benchmark")):
            score += 0.5
        if INR_AMOUNT_PATTERN.search(answer_unit):
            score += 1.0
        if query_type == "exit_load" and re.search(r"(?i)exit\s*load", answer_unit):
            score += 3.0
        return score

    def _is_low_signal_heading(self, text: str, query_type: str) -> bool:
        """Drop factsheet titles like 'NAV as at …' that repeat no numeric facts (rag pipeline hygiene)."""
        if query_type not in ("nav", "scheme_snapshot", "generic"):
            return False
        t = text.strip()
        if len(t) > 160:
            return False
        if not re.search(r"(?i)\bnav\b", t):
            return False
        if INR_AMOUNT_PATTERN.search(t) or re.search(r"\d+\.\d{3,}", t):
            return False
        low = t.lower()
        return "as at" in low or "as on" in low or "statement as on" in low

    def _query_terms(self, query: str) -> set[str]:
        tokens = TOKEN_PATTERN.findall(query.lower())
        return {token for token in tokens if token not in STOPWORDS}

    def _contains_sensitive_information(self, query: str) -> bool:
        return any(
            pattern.search(query)
            for pattern in (PAN_PATTERN, AADHAAR_PATTERN, PHONE_PATTERN, EMAIL_PATTERN)
        )

    def _is_off_topic(self, query: str) -> bool:
        """
        Return True if query has no mutual fund domain signal and is therefore
        outside the scope of the facts-only assistant.

        Decision logic (short-circuit order):
          1. Greeting pattern match → off-topic
          2. Any fund domain signal present → in-scope
          3. Token count < MIN_FACTUAL_TOKENS → off-topic (too short / vague)
        """
        stripped = query.strip()
        if OFF_TOPIC_GREETINGS.match(stripped):
            return True
        low = stripped.lower()
        if any(sig in low for sig in FUND_DOMAIN_SIGNALS):
            return False
        tokens = re.findall(r"[a-z0-9]+", low)
        if len(tokens) < MIN_FACTUAL_TOKENS:
            return True
        return False

    def _is_investment_advice_request(self, query: str) -> bool:
        lowered_query = query.lower()
        return any(re.search(pattern, lowered_query) for pattern in INVESTMENT_ADVICE_PATTERNS)

    @staticmethod
    def _normalize_whitespace(text: str) -> str:
        return WHITESPACE_PATTERN.sub(" ", text).strip()


def mmr_rerank_query(
    query_embedding: Iterable[float],
    document_embeddings: Sequence[Sequence[float]],
    top_k: int,
) -> list[int]:
    return maximal_marginal_relevance(
        np.array(query_embedding),
        [np.array(embedding) for embedding in document_embeddings],
        k=top_k,
    )
