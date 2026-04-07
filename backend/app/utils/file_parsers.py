"""
Document parsers - extracts text from uploaded files.

Two parsing paths:
  1. Docling (for rich/structured formats: PDF, DOCX, XLSX, PPTX, HTML, XML, images, MD, CSV)
     - Conversion runs in docling-serve (separate Docker container with ML models)
     - Returns the full DoclingDocument JSON (layout, tables, figures, headings)
     - Chunking runs in-process using docling-core's HybridChunker
     - Tables are never split across chunks (split table chunks are merged)
     - Chunks include heading context (e.g. "Chapter 3 > Section 3.1 > ...")

  2. Local parsing (for truly plain formats: TXT, JSON)
     - File is read as text, then converted to a DoclingDocument for chunking
     - HybridChunker is still used for token-aware, structure-preserving splits

The parse_document() function automatically picks the right parser based on file type.
"""

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


# Formats converted by docling-serve (ML-powered parsing) then chunked in-process.
# Includes MD and CSV which docling handles natively with structure preservation.
DOCLING_FORMATS = {
    ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx",
    ".html", ".xml",
    ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp",
    ".md", ".csv",
}

# Formats read locally and converted to a DoclingDocument for chunking.
LOCAL_FORMATS = {".txt", ".json"}


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
        return _parse_with_docling(file_path, ext)
    elif ext in LOCAL_FORMATS:
        return _parse_locally(file_path, ext)
    else:
        raise ValueError(f"Unsupported file format: {file_type}")


# =============================================================================
# Docling: convert via docling-serve, chunk in-process with HybridChunker
# =============================================================================

_MAX_RETRIES = 2
_RETRY_DELAY = 3.0


def _parse_with_docling(file_path: str, file_type: str) -> ParsedDocument:
    """Convert a document via docling-serve, then chunk in-process.

    1. Sends the file to docling-serve's /v1/convert/file endpoint to get a
       full DoclingDocument (with layout analysis, table recognition, etc.)
    2. Chunks the DoclingDocument in-process using HybridChunker
    3. Merges any chunks where a table was split across chunk boundaries
    4. Extracts document statistics from the structured DoclingDocument
    """
    from app.core.config import settings

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    with open(path, "rb") as f:
        file_bytes = f.read()

    # --- Step 1: Convert via docling-serve ---
    dl_doc, processing_time = _convert_with_docling_serve(
        path, file_bytes, settings
    )

    # --- Step 2: Export markdown ---
    md_text = dl_doc.export_to_markdown()

    # --- Step 3: Chunk with HybridChunker ---
    tokenizer_name = settings.docling_tokenizer or "bert-base-uncased"
    chunks = _chunk_docling_document(
        dl_doc,
        tokenizer_name=tokenizer_name,
        max_tokens=settings.docling_max_tokens,
        merge_peers=settings.docling_merge_peers,
    )

    # --- Step 4: Build stats from DoclingDocument ---
    stats = _build_stats(dl_doc)

    logger.info(
        f"docling: {path.name} → {len(chunks)} chunks, "
        f"{stats.num_pages or '?'} pages "
        f"(took {processing_time:.1f}s)"
    )

    return ParsedDocument(
        text=md_text,
        sections=[],
        page_count=stats.num_pages,
        metadata={
            "parser": "docling",
            "filename": path.name,
            "file_type": file_type,
            "file_size_bytes": len(file_bytes),
            "total_time_s": round(processing_time, 2),
            "tokenizer": tokenizer_name,
            "max_tokens": settings.docling_max_tokens,
        },
        chunks=chunks,
        stats=stats,
    )


def _convert_with_docling_serve(path, file_bytes, settings):
    """Send file to docling-serve /v1/convert/file and return DoclingDocument."""
    from docling_core.types.doc import DoclingDocument

    url = f"{settings.docling_base_url}/v1/convert/file"

    form_data = {
        "to_formats": "json",
        "do_ocr": str(settings.docling_do_ocr).lower(),
        "do_table_structure": str(settings.docling_do_table_structure).lower(),
        "table_mode": settings.docling_table_mode,
        "do_code_enrichment": str(settings.docling_do_code_enrichment).lower(),
        "images_scale": str(settings.docling_images_scale),
    }
    if settings.docling_ocr_lang:
        form_data["ocr_lang"] = settings.docling_ocr_lang

    last_error = None
    response = None
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
                    raise last_error
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
        raise RuntimeError(
            f"docling-serve failed after {_MAX_RETRIES + 1} attempts: {last_error}"
        )

    result = response.json()
    processing_time = result.get("processing_time", 0)

    # The convert endpoint returns the DoclingDocument under document.json_content
    doc_data = result.get("document", {})
    json_content = doc_data.get("json_content", {})
    if not json_content:
        raise RuntimeError(
            "docling-serve returned no json_content. "
            "Ensure to_formats includes 'json'."
        )

    dl_doc = DoclingDocument.model_validate(json_content)
    return dl_doc, processing_time


def _chunk_docling_document(
    dl_doc,
    tokenizer_name: str,
    max_tokens: int,
    merge_peers: bool,
) -> list[ChunkData]:
    """Chunk a DoclingDocument using HybridChunker, then fix split tables."""
    from docling_core.transforms.chunker import HybridChunker
    from docling_core.transforms.chunker.tokenizer.huggingface import (
        HuggingFaceTokenizer,
    )
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(tokenizer_name)
    hf_tok = HuggingFaceTokenizer(tokenizer=tok, max_tokens=max_tokens)

    chunker = HybridChunker(tokenizer=hf_tok, merge_peers=merge_peers)
    raw_chunks = list(chunker.chunk(dl_doc=dl_doc))

    # Fix table chunks: merge split tables, then re-split at row boundaries
    fixed_chunks = _fix_table_chunks(raw_chunks, tok, max_tokens)

    # Convert to ChunkData
    chunks = []
    for chunk in fixed_chunks:
        contextualized = chunker.contextualize(chunk)

        headings = chunk.meta.headings or []
        section_header = " > ".join(headings) if headings else None

        # Collect page numbers from doc_items' prov (provenance) if available
        page_number = _extract_page_number(chunk)

        # Determine labels from doc_items
        labels = list({
            item.label.value
            for item in (chunk.meta.doc_items or [])
            if hasattr(item, "label") and item.label is not None
        })

        chunks.append(ChunkData(
            text=chunk.text,
            section_header=section_header,
            page_number=page_number,
            contextualized_text=contextualized if contextualized != chunk.text else None,
            token_count=None,  # Not directly available on merged chunks
            labels=labels,
        ))

    return chunks


def _extract_page_number(chunk) -> int | None:
    """Extract first page number from a chunk's doc_items provenance."""
    for item in (chunk.meta.doc_items or []):
        if hasattr(item, "prov") and item.prov:
            for prov in item.prov:
                if hasattr(prov, "page_no"):
                    return prov.page_no
    return None


# =============================================================================
# Table chunk logic: merge split tables, then re-split at row boundaries
# =============================================================================

def _chunk_table_refs(chunk) -> set[str]:
    """Get table JSON pointer refs (e.g. '#/tables/0') from a chunk's doc_items."""
    refs = set()
    for item in (chunk.meta.doc_items or []):
        ref = item.self_ref
        if ref and "/tables/" in ref:
            refs.add(ref)
    return refs


def _fix_table_chunks(chunks: list, tokenizer, max_tokens: int) -> list:
    """Fix table chunks: merge split tables, then re-split at row boundaries.

    When HybridChunker splits a large table, rows can be cut mid-line.
    This function:
      1. Merges consecutive chunks that reference the same table into one
      2. Re-splits oversized table chunks at complete row boundaries so
         each chunk stays within max_tokens and no row is split.
    """
    if not chunks:
        return chunks

    # Step 1: Merge consecutive chunks referencing the same table
    merged = [chunks[0]]
    for chunk in chunks[1:]:
        prev_refs = _chunk_table_refs(merged[-1])
        curr_refs = _chunk_table_refs(chunk)

        if prev_refs and curr_refs and (prev_refs & curr_refs):
            merged[-1] = _merge_two_chunks(merged[-1], chunk)
        else:
            merged.append(chunk)

    # Step 2: Re-split oversized table chunks at row boundaries
    result = []
    for chunk in merged:
        table_refs = _chunk_table_refs(chunk)
        token_count = len(tokenizer.encode(chunk.text, add_special_tokens=False))

        if table_refs and token_count > max_tokens:
            sub_chunks = _split_table_chunk_by_rows(chunk, tokenizer, max_tokens)
            result.extend(sub_chunks)
            logger.info(
                f"Re-split oversized table chunk ({token_count} tokens) "
                f"into {len(sub_chunks)} chunks at row boundaries"
            )
        else:
            result.append(chunk)

    return result


def _split_table_chunk_by_rows(chunk, tokenizer, max_tokens: int) -> list:
    """Split a table chunk at complete row boundaries to fit max_tokens.

    Each output chunk contains only complete table rows (lines starting with |).
    The table header (first two lines: column names + separator) is repeated
    in each chunk for context.
    """
    from docling_core.transforms.chunker.doc_chunk import DocChunk, DocMeta

    lines = chunk.text.split("\n")

    # Identify the table header (column names + separator like |---|---|)
    # and separate it from data rows
    header_lines = []
    data_lines = []
    found_separator = False
    for line in lines:
        stripped = line.strip()
        if not found_separator and stripped.startswith("|"):
            header_lines.append(line)
            # Check if this is the separator line (e.g. |---|---|)
            if _is_table_separator(stripped):
                found_separator = True
        else:
            data_lines.append(line)

    header_text = "\n".join(header_lines)
    header_tokens = len(tokenizer.encode(header_text, add_special_tokens=False)) if header_lines else 0
    available_tokens = max_tokens - header_tokens

    if available_tokens < 50:
        # Header alone nearly fills the limit; skip header repetition
        header_text = ""
        header_tokens = 0
        available_tokens = max_tokens
        data_lines = lines  # Use all lines as data

    # Group data lines into chunks that fit within max_tokens
    sub_chunks = []
    current_lines = []
    current_tokens = 0

    for line in data_lines:
        line_tokens = len(tokenizer.encode(line, add_special_tokens=False))

        if current_lines and current_tokens + line_tokens > available_tokens:
            # Flush current buffer as a chunk
            chunk_text = header_text + "\n" + "\n".join(current_lines) if header_text else "\n".join(current_lines)
            sub_chunks.append(DocChunk(
                text=chunk_text.strip(),
                meta=DocMeta(
                    doc_items=list(chunk.meta.doc_items or []),
                    headings=chunk.meta.headings,
                    captions=chunk.meta.captions,
                    origin=chunk.meta.origin,
                ),
            ))
            current_lines = []
            current_tokens = 0

        current_lines.append(line)
        current_tokens += line_tokens

    # Don't forget the last buffer
    if current_lines:
        chunk_text = header_text + "\n" + "\n".join(current_lines) if header_text else "\n".join(current_lines)
        sub_chunks.append(DocChunk(
            text=chunk_text.strip(),
            meta=DocMeta(
                doc_items=list(chunk.meta.doc_items or []),
                headings=chunk.meta.headings,
                captions=chunk.meta.captions,
                origin=chunk.meta.origin,
            ),
        ))

    return sub_chunks if sub_chunks else [chunk]


def _is_table_separator(line: str) -> bool:
    """Check if a line is a markdown table separator (e.g. |---|---|)."""
    # Remove outer pipes and check if remaining cells are all dashes/colons
    inner = line.strip().strip("|")
    cells = inner.split("|")
    return all(cell.strip().replace("-", "").replace(":", "") == "" for cell in cells)


def _merge_two_chunks(a, b):
    """Merge two DocChunk objects into one, preserving metadata."""
    from docling_core.transforms.chunker.doc_chunk import DocChunk, DocMeta

    # Combine text
    merged_text = a.text + "\n" + b.text

    # Combine doc_items (deduplicate by self_ref)
    seen_refs = set()
    merged_items = []
    for item in list(a.meta.doc_items or []) + list(b.meta.doc_items or []):
        if item.self_ref not in seen_refs:
            seen_refs.add(item.self_ref)
            merged_items.append(item)

    # Keep first chunk's headings and captions
    merged_meta = DocMeta(
        doc_items=merged_items,
        headings=a.meta.headings or b.meta.headings,
        captions=a.meta.captions or b.meta.captions,
        origin=a.meta.origin,
    )

    return DocChunk(text=merged_text, meta=merged_meta)


# =============================================================================
# Document statistics from DoclingDocument structure
# =============================================================================

def _build_stats(dl_doc) -> DocumentStats:
    """Extract document statistics from a DoclingDocument."""
    from docling_core.types.doc import DocItemLabel

    stats = DocumentStats()
    stats.num_pages = dl_doc.num_pages() if dl_doc.num_pages() > 0 else None
    stats.num_tables = len(dl_doc.tables)
    stats.num_figures = len(dl_doc.pictures)

    for item, _level in dl_doc.iterate_items():
        label = getattr(item, "label", None)
        if label == DocItemLabel.SECTION_HEADER or label == DocItemLabel.TITLE:
            stats.num_headings += 1
        elif label == DocItemLabel.LIST_ITEM:
            stats.num_list_items += 1
        elif label == DocItemLabel.CODE:
            stats.num_code_blocks += 1
        elif label == DocItemLabel.TEXT or label == DocItemLabel.PARAGRAPH:
            stats.num_text_elements += 1

    return stats


# =============================================================================
# Local parsers (TXT, JSON — read as text, chunk with HybridChunker)
# =============================================================================

def _parse_locally(file_path: str, file_type: str) -> ParsedDocument:
    """Parse plain text files locally, then chunk with HybridChunker."""
    from app.core.config import settings
    from docling_core.types.doc import DoclingDocument, DocItemLabel

    path = Path(file_path)
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()

    if not text.strip():
        return ParsedDocument(
            text=text,
            metadata={"parser": "local"},
        )

    # Build a DoclingDocument from plain text so HybridChunker can process it
    dl_doc = DoclingDocument(name=path.stem)

    # Split on double newlines to preserve paragraph structure
    paragraphs = text.split("\n\n")
    for para in paragraphs:
        para = para.strip()
        if para:
            dl_doc.add_text(label=DocItemLabel.TEXT, text=para)

    # Chunk using HybridChunker (same as docling path)
    tokenizer_name = settings.docling_tokenizer or "bert-base-uncased"
    chunks = _chunk_docling_document(
        dl_doc,
        tokenizer_name=tokenizer_name,
        max_tokens=settings.docling_max_tokens,
        merge_peers=settings.docling_merge_peers,
    )

    logger.info(f"local: {path.name} → {len(chunks)} chunks")

    return ParsedDocument(
        text=text,
        sections=[ParsedSection(header=None, content=text)],
        metadata={"parser": "local", "filename": path.name},
        chunks=chunks,
    )
