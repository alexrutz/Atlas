"""
Document Processing - Turns uploaded files into searchable chunks.

This module handles the entire document processing pipeline:
  1. Parsing files (via docling-serve for rich formats, or locally for plain text)
  2. Chunking text (using docling-core's HybridChunker for token-aware splits)
  3. Computing embeddings for each chunk
  4. Storing chunks + embeddings in the database

Two parsing paths:
  - Docling (for PDF, DOCX, XLSX, PPTX, HTML, XML, images, MD, CSV):
    Conversion runs in docling-serve (separate Docker container with ML models).
    Chunking runs in-process using HybridChunker.
  - Local (for TXT, JSON):
    File is read as text, converted to a DoclingDocument, then chunked.

The process_document() function is the main entry point - it orchestrates
the full pipeline from file to searchable chunks in the database.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.models import Document, Chunk, ChunkEmbedding
from app.search import embed_batch

logger = logging.getLogger(__name__)


# =============================================================================
# Data types
# =============================================================================

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
DOCLING_FORMATS = {
    ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx",
    ".html", ".xml",
    ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp",
    ".md", ".csv",
}

# Formats read locally and converted to a DoclingDocument for chunking.
LOCAL_FORMATS = {".txt", ".json"}


# =============================================================================
# Main entry point: full processing pipeline
# =============================================================================

async def process_document(db: AsyncSession, document_id: int) -> None:
    """
    Full document processing pipeline.

    Flow:
    1. Load document from DB
    2. Parse file (docling-serve for rich formats, local for text formats)
    3. Use docling chunks if available, otherwise chunk locally
    4. Compute embedding for each chunk
    5. Store chunks + embeddings
    6. Store document-level metadata (stats, timings)
    7. Update document status
    """
    result = await db.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()
    if not document:
        logger.error(f"Document {document_id} not found")
        return

    try:
        # Parse file (runs in a separate thread because file I/O + HTTP calls
        # to docling-serve are blocking operations that would freeze the async loop)
        is_docling = document.file_type.lower() in DOCLING_FORMATS
        pipeline = "docling" if is_docling else "local"
        logger.info(f"Parsing document: {document.original_name} (pipeline={pipeline})")
        parsed = await asyncio.to_thread(parse_document, document.file_path, document.file_type)

        # All parsers now return chunks (via HybridChunker).
        # Fallback to chunk_text only if chunks are empty.
        if parsed.chunks:
            chunks = parsed.chunks
            chunker_type = "docling"
        else:
            chunker_type = "local-fallback"
            logger.warning("No chunks from parser, falling back to text splitter")
            chunks = await asyncio.to_thread(
                chunk_text,
                text=parsed.text,
                sections=parsed.sections,
            )

        # Prepare chunks and texts for embedding
        logger.info(f"Processing {len(chunks)} chunks")
        chunk_texts = []
        chunk_objects = []

        for i, chunk_data in enumerate(chunks):
            # Use contextualized text for embedding if available.
            # Contextualized text includes the section heading prepended to the chunk,
            # which helps the embedding model understand what the chunk is about.
            embed_text_str = chunk_data.contextualized_text or chunk_data.text
            chunk_texts.append(embed_text_str)

            chunk_meta = {
                "parser": parsed.metadata.get("parser", pipeline),
                "chunker": chunker_type,
            }
            if chunk_data.contextualized_text:
                chunk_meta["has_context"] = True
            if chunk_data.labels:
                chunk_meta["labels"] = chunk_data.labels

            chunk_obj = Chunk(
                document_id=document.id,
                chunk_index=i,
                content=chunk_data.text,
                section_header=chunk_data.section_header,
                page_number=chunk_data.page_number,
                token_count=chunk_data.token_count,
                metadata_=chunk_meta,
            )
            chunk_objects.append(chunk_obj)
            db.add(chunk_obj)

        await db.flush()

        # Compute batch embeddings
        logger.info(f"Computing embeddings for {len(chunk_texts)} chunks")
        embeddings = await embed_batch(chunk_texts)

        # Store embeddings
        for chunk_obj, embedding in zip(chunk_objects, embeddings):
            emb_obj = ChunkEmbedding(
                chunk_id=chunk_obj.id,
                model_name=settings.embedding_model,
                embedding=embedding,
            )
            db.add(emb_obj)

        # Store document-level metadata (stats, parse info)
        doc_meta = dict(parsed.metadata)
        if parsed.stats:
            doc_meta["stats"] = {
                "num_pages": parsed.stats.num_pages,
                "num_tables": parsed.stats.num_tables,
                "num_figures": parsed.stats.num_figures,
                "num_headings": parsed.stats.num_headings,
                "num_text_elements": parsed.stats.num_text_elements,
                "num_list_items": parsed.stats.num_list_items,
                "num_code_blocks": parsed.stats.num_code_blocks,
            }
        document.metadata_ = doc_meta

        # Update document status
        document.processing_status = "completed"
        document.chunk_count = len(chunk_objects)
        await db.flush()

        logger.info(
            f"Document {document.original_name} processed: "
            f"{len(chunk_objects)} chunks, pipeline={pipeline}"
        )

    except Exception as e:
        logger.error(f"Error processing document {document_id}: {e}")
        document.processing_status = "error"
        document.processing_error = str(e)
        await db.flush()
        raise


# =============================================================================
# Document parsing: route to docling or local parser
# =============================================================================

def parse_document(file_path: str, file_type: str) -> ParsedDocument:
    """
    Parse a document, routing to docling-serve or local parser as appropriate.
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
    """Convert a document via docling-serve, then chunk in-process."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    with open(path, "rb") as f:
        file_bytes = f.read()

    # Step 1: Convert via docling-serve
    dl_doc, processing_time = _convert_with_docling_serve(path, file_bytes)

    # Step 2: Export markdown
    md_text = dl_doc.export_to_markdown()

    # Step 3: Chunk with HybridChunker
    tokenizer_name = settings.docling_tokenizer or "bert-base-uncased"
    chunks = _chunk_docling_document(
        dl_doc,
        tokenizer_name=tokenizer_name,
        max_tokens=settings.docling_max_tokens,
        merge_peers=settings.docling_merge_peers,
    )

    # Step 4: Build stats from DoclingDocument
    stats = _build_stats(dl_doc)

    logger.info(
        f"docling: {path.name} -> {len(chunks)} chunks, "
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


def _convert_with_docling_serve(path, file_bytes):
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
    """Chunk a DoclingDocument using HybridChunker.

    HybridChunker handles tables natively:
    - Tables are split row-by-row via LineBasedTokenChunker
    - Table headers are repeated in each chunk
    - Table rows are serialized via TripletTableSerializer
    """
    from docling_core.transforms.chunker import HybridChunker
    from docling_core.transforms.chunker.tokenizer.huggingface import (
        HuggingFaceTokenizer,
    )
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(tokenizer_name)
    hf_tok = HuggingFaceTokenizer(tokenizer=tok, max_tokens=max_tokens)

    chunker = HybridChunker(
        tokenizer=hf_tok,
        merge_peers=merge_peers,
        repeat_table_header=True,
    )
    raw_chunks = list(chunker.chunk(dl_doc=dl_doc))

    chunks = []
    for chunk in raw_chunks:
        contextualized = chunker.contextualize(chunk)

        headings = chunk.meta.headings or []
        section_header = " > ".join(headings) if headings else None

        page_number = _extract_page_number(chunk)

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
            token_count=getattr(chunk.meta, "token_count", None),
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
# Local parsers (TXT, JSON - read as text, chunk with HybridChunker)
# =============================================================================

def _parse_locally(file_path: str, file_type: str) -> ParsedDocument:
    """Parse plain text files locally, then chunk with HybridChunker."""
    from docling_core.types.doc import DoclingDocument as DLDoc, DocItemLabel

    path = Path(file_path)
    with open(path, encoding="utf-8", errors="replace") as f:
        text_content = f.read()

    if not text_content.strip():
        return ParsedDocument(
            text=text_content,
            metadata={"parser": "local"},
        )

    # Build a DoclingDocument from plain text so HybridChunker can process it
    dl_doc = DLDoc(name=path.stem)

    paragraphs = text_content.split("\n\n")
    for para in paragraphs:
        para = para.strip()
        if para:
            dl_doc.add_text(label=DocItemLabel.TEXT, text=para)

    tokenizer_name = settings.docling_tokenizer or "bert-base-uncased"
    chunks = _chunk_docling_document(
        dl_doc,
        tokenizer_name=tokenizer_name,
        max_tokens=settings.docling_max_tokens,
        merge_peers=settings.docling_merge_peers,
    )

    logger.info(f"local: {path.name} -> {len(chunks)} chunks")

    return ParsedDocument(
        text=text_content,
        sections=[ParsedSection(header=None, content=text_content)],
        metadata={"parser": "local", "filename": path.name},
        chunks=chunks,
    )


# =============================================================================
# Fallback chunker (used only if parser returns text without chunks)
# =============================================================================

def chunk_text(
    text: str,
    chunk_size: int = 512,
    overlap: int = 50,
    sections: list[ParsedSection] | None = None,
) -> list[ChunkData]:
    """
    Split text into chunks using docling-core's HybridChunker.

    This is a fallback - normally all documents are chunked via the parsing
    functions above. This only runs if a parser returns raw text without chunks.
    """
    from docling_core.types.doc import DoclingDocument as DLDoc, DocItemLabel
    from docling_core.transforms.chunker import HybridChunker
    from docling_core.transforms.chunker.tokenizer.huggingface import (
        HuggingFaceTokenizer,
    )
    from transformers import AutoTokenizer

    if not text.strip():
        return []

    doc = DLDoc(name="local")

    if sections:
        for section in sections:
            if section.header:
                doc.add_heading(text=section.header)
            if section.content.strip():
                doc.add_text(label=DocItemLabel.TEXT, text=section.content.strip())
    else:
        for para in text.split("\n\n"):
            para = para.strip()
            if para:
                doc.add_text(label=DocItemLabel.TEXT, text=para)

    tokenizer_name = settings.docling_tokenizer or "bert-base-uncased"
    tok = AutoTokenizer.from_pretrained(tokenizer_name)
    hf_tok = HuggingFaceTokenizer(tokenizer=tok, max_tokens=settings.docling_max_tokens)
    chunker = HybridChunker(tokenizer=hf_tok, merge_peers=settings.docling_merge_peers)

    chunks = []
    for chunk in chunker.chunk(dl_doc=doc):
        contextualized = chunker.contextualize(chunk)
        headings = chunk.meta.headings or []
        section_header = " > ".join(headings) if headings else None

        chunks.append(ChunkData(
            text=chunk.text,
            section_header=section_header,
            contextualized_text=contextualized if contextualized != chunk.text else None,
        ))

    return chunks
