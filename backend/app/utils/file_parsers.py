"""
Document parsers - routes documents to docling-serve or local text parsers.

Supported formats:
- Docling Serve: PDF, DOCX, XLSX, PPTX, HTML, XML, images (ML-powered parsing + chunking)
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


# Formats handled by docling-serve (ML-powered parsing)
DOCLING_FORMATS = {
    ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx",
    ".html", ".xml",
    ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp",
}

# Formats handled locally (simple text extraction)
LOCAL_FORMATS = {".txt", ".md", ".csv", ".json"}


def parse_document(file_path: str, file_type: str) -> ParsedDocument:
    """
    Parse a document, routing to docling-serve or local parser as appropriate.

    Args:
        file_path: Path to the file
        file_type: File extension (e.g. '.pdf', '.docx')

    Returns:
        ParsedDocument with extracted text, sections, chunks, and stats.
    """
    ext = file_type.lower()

    if ext in DOCLING_FORMATS:
        return _parse_with_docling_serve(file_path, ext)
    elif ext in LOCAL_FORMATS:
        return _parse_locally(file_path, ext)
    else:
        raise ValueError(f"Unsupported file format: {file_type}")


# =============================================================================
# Docling Serve (official pre-built image, ML parsing + chunking)
# =============================================================================

_MAX_RETRIES = 2
_RETRY_DELAY = 3.0


def _parse_with_docling_serve(file_path: str, file_type: str) -> ParsedDocument:
    """Parse and chunk a document via the official docling-serve API.

    Calls POST /v1/chunk/hybrid/file with include_converted_doc=true so we get
    both the chunks AND the full markdown text in one request.
    Retries on transient server errors.
    """
    from app.core.config import settings

    url = f"{settings.docling_base_url}/v1/chunk/hybrid/file"

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    with open(path, "rb") as f:
        file_bytes = f.read()

    # Build the multipart form data:
    # - "files" is the uploaded file
    # - "chunking_*" fields control the HybridChunker
    # - "include_converted_doc" gives us the full markdown text too
    tokenizer = settings.docling_tokenizer or "bert-base-uncased"
    form_data = {
        "chunking_max_tokens": str(settings.docling_max_tokens),
        "chunking_merge_peers": str(settings.docling_merge_peers).lower(),
        "chunking_tokenizer": tokenizer,
        "include_converted_doc": "true",
    }

    last_error = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            logger.info(
                f"Sending {path.name} to docling-serve at {url}"
                + (f" (retry {attempt})" if attempt > 0 else "")
            )

            files = {"files": (path.name, file_bytes, "application/octet-stream")}
            response = httpx.post(
                url,
                files=files,
                data=form_data,
                timeout=httpx.Timeout(connect=30.0, read=600.0, write=60.0, pool=30.0),
            )

            if response.status_code == 200:
                break
            else:
                last_error = RuntimeError(
                    f"docling-serve error ({response.status_code}): {response.text}"
                )
                if response.status_code < 500:
                    raise last_error  # Client error, don't retry
        except httpx.TimeoutException as e:
            last_error = e
            logger.warning(f"docling-serve timeout (attempt {attempt + 1}): {e}")
        except RuntimeError:
            raise
        except Exception as e:
            last_error = e
            logger.warning(f"docling-serve error (attempt {attempt + 1}): {e}")

        if attempt < _MAX_RETRIES:
            time.sleep(_RETRY_DELAY)
    else:
        raise RuntimeError(f"docling-serve failed after {_MAX_RETRIES + 1} attempts: {last_error}")

    result = response.json()

    # --- Extract full markdown text from the converted document ---
    md_text = ""
    documents = result.get("documents", [])
    if documents:
        content = documents[0].get("content", {})
        md_text = content.get("md_content", "") or content.get("text_content", "") or ""

    # --- Convert chunks from docling-serve format to our ChunkData format ---
    # docling-serve returns chunks with these fields:
    #   text (contextualized), raw_text, num_tokens, headings, page_numbers, etc.
    chunks = []
    for c in result.get("chunks", []):
        # "text" in docling-serve is already the contextualized text (with headings prepended)
        contextualized = c.get("text", "")
        # "raw_text" is the chunk text without heading context (only if include_raw_text was set)
        raw_text = c.get("raw_text", "") or contextualized

        # Build section header from the headings list
        headings = c.get("headings", [])
        section_header = " > ".join(headings) if headings else None

        # Page numbers come as a list; take the first one
        page_numbers = c.get("page_numbers", [])
        page_number = page_numbers[0] if page_numbers else None

        chunks.append(ChunkData(
            text=raw_text,
            section_header=section_header,
            page_number=page_number,
            contextualized_text=contextualized,
            token_count=c.get("num_tokens"),
            labels=[],
        ))

    # --- Build stats (docling-serve doesn't return stats directly, ---
    # --- so we estimate from the converted document if available)  ---
    stats = DocumentStats()
    if documents:
        timings = documents[0].get("timings", {})
        # Page count can be inferred from the chunks' page numbers
        all_pages = set()
        for c in result.get("chunks", []):
            for p in c.get("page_numbers", []):
                all_pages.add(p)
        if all_pages:
            stats.num_pages = max(all_pages)

    processing_time = result.get("processing_time", 0)

    logger.info(
        f"docling-serve: {path.name} → {len(chunks)} chunks, "
        f"{stats.num_pages or '?'} pages "
        f"(took {processing_time:.1f}s)"
    )

    return ParsedDocument(
        text=md_text,
        sections=[],  # docling-serve doesn't return sections separately
        page_count=stats.num_pages,
        metadata={
            "parser": "docling-serve",
            "filename": path.name,
            "file_type": file_type,
            "file_size_bytes": len(file_bytes),
            "total_time_s": round(processing_time, 2),
            "tokenizer": tokenizer,
            "max_tokens": settings.docling_max_tokens,
        },
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
