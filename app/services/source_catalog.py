"""Map on-disk PDF filenames to official HDFC citation URLs (`sources.csv`)."""

from __future__ import annotations

import csv
from pathlib import Path


def load_local_pdf_to_citation_url(csv_path: Path) -> dict[str, str]:
    """Return `{local_pdf basename -> citation_url}` from the curated catalog."""
    if not csv_path.is_file():
        return {}
    out: dict[str, str] = {}
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pdf = (row.get("local_pdf") or "").strip()
            url = (row.get("citation_url") or "").strip()
            if pdf and url.startswith(("http://", "https://")):
                out[pdf] = url
    return out
