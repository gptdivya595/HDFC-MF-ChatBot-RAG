from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SourceCitation:
    filename: str
    page_number: int
    excerpt: str
    relevance_score: float | None = None
    modified_at: int | None = None
    """Official HDFC / regulator page URL from `sources.csv` for this PDF."""
    citation_url: str = ""

    @property
    def display_name(self) -> str:
        return f"{self.filename}, page {self.page_number}"

    @property
    def short_name(self) -> str:
        stem = Path(self.filename).stem
        stem = stem.replace("_0", "")
        return stem[:42] + "..." if len(stem) > 45 else stem


@dataclass(frozen=True)
class ChatbotResponse:
    answer: str
    sources: list[SourceCitation] = field(default_factory=list)
    last_updated: str = "Based on available documents"
    # FIX: Added is_refusal flag so frontend can suppress citation UI on refusal responses.
    # Previously refusals and grounded answers were serialized identically.
    is_refusal: bool = False

    @property
    def source_text(self) -> str:
        if not self.sources:
            return "N/A"
        return "; ".join(source.display_name for source in self.sources)

    @property
    def short_source_text(self) -> str:
        if not self.sources:
            return "N/A"
        first = self.sources[0]
        more = len(self.sources) - 1
        suffix = f" +{more} more" if more > 0 else ""
        return f"{first.short_name}, p.{first.page_number}{suffix}"

    @property
    def primary_citation_url(self) -> str:
        if self.sources and self.sources[0].citation_url.strip():
            return self.sources[0].citation_url.strip()
        return ""

    @property
    def excerpts(self) -> list[tuple[str, str]]:
        return [(source.display_name, source.excerpt) for source in self.sources]


@dataclass
class ChatTurn:
    role: str
    content: str = ""
    response: ChatbotResponse | None = None