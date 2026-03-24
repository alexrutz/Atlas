"""
Document parsers - routes documents to the Docling API or local text parsers.

Supported formats:
- Docling API: PDF, DOCX, XLSX, PPTX, HTML, XML (ML-powered parsing + chunking)
- Local: TXT, MD, CSV, JSON (simple text extraction, no ML needed)
"""

import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


@dataclass
class ParsedSection:
    """A section from a parsed document."""
    header: str | None
    content: str
    page_number: int | None = None


@dataclass
class ChunkData:
    """A single chunk with metadata."""
    text: str
    section_header: str | None = None
    page_number: int | None = None
    contextualized_text: str | None = None


@dataclass
class ParsedDocument:
    """Result of document parsing."""
    text: str
    sections: list[ParsedSection] = field(default_factory=list)
    page_count: int | None = None
    metadata: dict = field(default_factory=dict)
    chunks: list[ChunkData] = field(default_factory=list)


# Formats handled by the Docling API (ML-powered parsing)
DOCLING_FORMATS = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".html", ".xml"}

# Formats handled locally (simple text extraction)
LOCAL_FORMATS = {".txt", ".md", ".csv", ".json"}


def parse_document(file_path: str, file_type: str) -> ParsedDocument:
    """
    Parse a document, routing to Docling API or local parser as appropriate.

    Args:
        file_path: Path to the file
        file_type: File extension (e.g. '.pdf', '.docx')

    Returns:
        ParsedDocument with extracted text, sections, and chunks.
    """
    ext = file_type.lower()

    if ext in DOCLING_FORMATS:
        return _parse_with_docling_api(file_path, ext)
    elif ext in LOCAL_FORMATS:
        return _parse_locally(file_path, ext)
    else:
        raise ValueError(f"Unsupported file format: {file_type}")


# =============================================================================
# Docling API (remote ML parsing + chunking)
# =============================================================================

def _parse_with_docling_api(file_path: str, file_type: str) -> ParsedDocument:
    """Parse a document via the Docling API service."""
    from app.core.config import settings

    cfg = settings.docling
    url = f"{cfg.base_url}/convert"

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    with open(path, "rb") as f:
        files = {"file": (path.name, f, "application/octet-stream")}
        data = {
            "max_tokens": str(cfg.max_tokens),
            "merge_peers": str(cfg.merge_peers).lower(),
            "tokenizer": cfg.tokenizer,
        }

        logger.info(f"Sending {path.name} to Docling API at {url}")

        response = httpx.post(
            url,
            files=files,
            data=data,
            timeout=httpx.Timeout(connect=30.0, read=600.0, write=30.0, pool=30.0),
        )

    if response.status_code != 200:
        raise RuntimeError(f"Docling API error ({response.status_code}): {response.text}")

    result = response.json()

    sections = [
        ParsedSection(
            header=s.get("header"),
            content=s["content"],
            page_number=s.get("page_number"),
        )
        for s in result.get("sections", [])
    ]

    chunks = [
        ChunkData(
            text=c["text"],
            section_header=c.get("section_header"),
            page_number=c.get("page_number"),
            contextualized_text=c.get("contextualized_text"),
        )
        for c in result.get("chunks", [])
    ]

    logger.info(
        f"Docling API: {path.name} → {len(sections)} sections, "
        f"{len(chunks)} chunks, {result.get('page_count', '?')} pages"
    )

    return ParsedDocument(
        text=result.get("text", ""),
        sections=sections,
        page_count=result.get("page_count"),
        metadata=result.get("metadata", {"parser": "docling"}),
        chunks=chunks,
    )


# =============================================================================
# Local parsers (simple text-based formats)
# =============================================================================

def _parse_locally(file_path: str, file_type: str) -> ParsedDocument:
    """Parse simple text-based formats locally."""
    parsers = {
        ".txt": _parse_text,
        ".md": _parse_text,
        ".csv": _parse_csv,
        ".json": _parse_text,
    }

    parser = parsers.get(file_type)
    if not parser:
        raise ValueError(f"No local parser for: {file_type}")

    return parser(file_path)


def _parse_text(file_path: str) -> ParsedDocument:
    """Parse a plain text file."""
    with open(file_path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    return ParsedDocument(
        text=text,
        sections=[ParsedSection(header=None, content=text)],
        metadata={"parser": "local"},
    )


def _parse_csv(file_path: str) -> ParsedDocument:
    """Parse a CSV file."""
    rows = []
    with open(file_path, encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        for row in reader:
            rows.append(" | ".join(row))

    text = "\n".join(rows)
    return ParsedDocument(
        text=text,
        sections=[ParsedSection(header=None, content=text)],
        metadata={"parser": "local"},
    )
