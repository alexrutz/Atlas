"""
Document parsers - routes documents to the Docling API or local text parsers.

Supported formats:
- Docling API: PDF, DOCX, XLSX, PPTX, HTML, XML, images (ML-powered parsing + chunking)
- Local: TXT, MD, CSV, JSON (simple text extraction, no ML needed)
"""

import csv
import logging
import time
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
    label: str | None = None


@dataclass
class ChunkData:
    """A single chunk with metadata."""
    text: str
    section_header: str | None = None
    page_number: int | None = None
    contextualized_text: str | None = None
    token_count: int | None = None
    labels: list[str] = field(default_factory=list)


@dataclass
class DocumentStats:
    """Statistics about the parsed document."""
    num_pages: int | None = None
    num_tables: int = 0
    num_figures: int = 0
    num_headings: int = 0
    num_text_elements: int = 0
    num_list_items: int = 0
    num_code_blocks: int = 0


@dataclass
class ParsedDocument:
    """Result of document parsing."""
    text: str
    sections: list[ParsedSection] = field(default_factory=list)
    page_count: int | None = None
    metadata: dict = field(default_factory=dict)
    chunks: list[ChunkData] = field(default_factory=list)
    stats: DocumentStats = field(default_factory=DocumentStats)


# Formats handled by the Docling API (ML-powered parsing)
DOCLING_FORMATS = {
    ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx",
    ".html", ".xml",
    ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp",
}

# Formats handled locally (simple text extraction)
LOCAL_FORMATS = {".txt", ".md", ".csv", ".json"}


def parse_document(file_path: str, file_type: str) -> ParsedDocument:
    """
    Parse a document, routing to Docling API or local parser as appropriate.

    Args:
        file_path: Path to the file
        file_type: File extension (e.g. '.pdf', '.docx')

    Returns:
        ParsedDocument with extracted text, sections, chunks, and stats.
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

_MAX_RETRIES = 2
_RETRY_DELAY = 3.0


def _parse_with_docling_api(file_path: str, file_type: str) -> ParsedDocument:
    """Parse a document via the Docling API service.

    Passes the configured tokenizer (docling.tokenizer in config.yaml) to the
    HybridChunker; if unset, docling-api falls back to bert-base-uncased.
    Retries on transient failures.
    """
    from app.core.config import settings

    cfg = settings.docling
    url = f"{cfg.base_url}/convert"

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    # Use explicitly configured tokenizer; if unset, let docling-api use its default
    tokenizer = cfg.tokenizer

    with open(path, "rb") as f:
        file_bytes = f.read()

    data = {
        "max_tokens": str(cfg.max_tokens),
        "merge_peers": str(cfg.merge_peers).lower(),
        "tokenizer": tokenizer,
    }

    last_error = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            logger.info(
                f"Sending {path.name} to Docling API at {url}"
                + (f" (retry {attempt})" if attempt > 0 else "")
            )

            files = {"file": (path.name, file_bytes, "application/octet-stream")}
            response = httpx.post(
                url,
                files=files,
                data=data,
                timeout=httpx.Timeout(connect=30.0, read=600.0, write=60.0, pool=30.0),
            )

            if response.status_code == 200:
                break
            else:
                last_error = RuntimeError(
                    f"Docling API error ({response.status_code}): {response.text}"
                )
                if response.status_code < 500:
                    raise last_error  # Client error, don't retry
        except httpx.TimeoutException as e:
            last_error = e
            logger.warning(f"Docling API timeout (attempt {attempt + 1}): {e}")
        except RuntimeError:
            raise
        except Exception as e:
            last_error = e
            logger.warning(f"Docling API error (attempt {attempt + 1}): {e}")

        if attempt < _MAX_RETRIES:
            import time as _time
            _time.sleep(_RETRY_DELAY)
    else:
        raise RuntimeError(f"Docling API failed after {_MAX_RETRIES + 1} attempts: {last_error}")

    result = response.json()

    # Parse sections
    sections = [
        ParsedSection(
            header=s.get("header"),
            content=s["content"],
            page_number=s.get("page_number"),
            label=s.get("label"),
        )
        for s in result.get("sections", [])
    ]

    # Parse chunks
    chunks = [
        ChunkData(
            text=c["text"],
            section_header=c.get("section_header"),
            page_number=c.get("page_number"),
            contextualized_text=c.get("contextualized_text"),
            token_count=c.get("token_count"),
            labels=c.get("labels", []),
        )
        for c in result.get("chunks", [])
    ]

    # Parse stats
    raw_stats = result.get("stats", {})
    stats = DocumentStats(
        num_pages=raw_stats.get("num_pages"),
        num_tables=raw_stats.get("num_tables", 0),
        num_figures=raw_stats.get("num_figures", 0),
        num_headings=raw_stats.get("num_headings", 0),
        num_text_elements=raw_stats.get("num_text_elements", 0),
        num_list_items=raw_stats.get("num_list_items", 0),
        num_code_blocks=raw_stats.get("num_code_blocks", 0),
    )

    logger.info(
        f"Docling API: {path.name} → {len(sections)} sections, "
        f"{len(chunks)} chunks, {stats.num_pages or '?'} pages, "
        f"{stats.num_tables} tables, {stats.num_figures} figures "
        f"(took {result.get('metadata', {}).get('total_time_s', '?')}s)"
    )

    return ParsedDocument(
        text=result.get("text", ""),
        sections=sections,
        page_count=stats.num_pages,
        metadata=result.get("metadata", {"parser": "docling"}),
        chunks=chunks,
        stats=stats,
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
