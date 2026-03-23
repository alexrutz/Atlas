"""
Text processing: chunking strategies.

Primary: Docling HybridChunker (token-aware, structure-preserving).
Fallback: Legacy strategies (fixed, sentence, recursive, semantic).
"""

import logging
from dataclasses import dataclass

from app.utils.file_parsers import ParsedSection

logger = logging.getLogger(__name__)


@dataclass
class ChunkData:
    """A single chunk with metadata."""
    text: str
    section_header: str | None = None
    page_number: int | None = None
    # Enriched text with heading/caption context (from docling contextualize)
    contextualized_text: str | None = None


# =============================================================================
# Unified entry point
# =============================================================================

def chunk_document(
    text: str,
    sections: list[ParsedSection] | None = None,
    docling_document: object | None = None,
) -> list[ChunkData]:
    """
    Chunk a document using the configured strategy.

    If docling chunking is enabled and a DoclingDocument is available,
    uses HybridChunker for token-aware, structure-preserving chunks.
    Otherwise falls back to legacy chunking strategies.

    Args:
        text: Full document text
        sections: Parsed sections (for legacy semantic chunking)
        docling_document: Raw DoclingDocument from docling parsing

    Returns:
        List of ChunkData with text and metadata
    """
    from app.core.config import settings

    if (
        settings.docling.enabled
        and settings.docling.use_docling_chunker
        and docling_document is not None
    ):
        try:
            return _chunk_with_docling(docling_document)
        except Exception as e:
            logger.warning(f"Docling chunking failed, falling back to legacy: {e}")

    return chunk_text(
        text=text,
        strategy=settings.chunking.strategy,
        chunk_size=settings.chunking.chunk_size,
        overlap=settings.chunking.chunk_overlap,
        sections=sections,
    )


# =============================================================================
# Docling HybridChunker
# =============================================================================

def _chunk_with_docling(docling_document) -> list[ChunkData]:
    """Chunk a DoclingDocument using Docling's HybridChunker.

    HybridChunker combines:
    1. Hierarchical chunking (one chunk per document element)
    2. Token-aware splitting (oversized chunks split by token count)
    3. Peer merging (undersized adjacent chunks with same headings merged)

    Each chunk carries structural context (headings, captions) as metadata.
    """
    from docling_core.transforms.chunker import HybridChunker
    from app.core.config import settings

    cfg = settings.docling

    # Determine tokenizer: use configured one, or fall back to embedding model
    tokenizer_name = cfg.tokenizer or settings.embedding.model

    chunker = HybridChunker(
        tokenizer=tokenizer_name,
        max_tokens=cfg.max_tokens,
        merge_peers=cfg.merge_peers,
    )

    chunks = []
    for i, chunk in enumerate(chunker.chunk(docling_document)):
        # contextualize() produces metadata-enriched text
        # (includes parent headings and captions as prefix)
        contextualized = chunker.contextualize(chunk)

        # Extract metadata from chunk
        section_header = None
        page_number = None

        # Get heading context from chunk metadata
        meta = getattr(chunk, "meta", None)
        if meta:
            headings = getattr(meta, "headings", None)
            if headings:
                section_header = " > ".join(headings)

            # Get page number from provenance
            doc_items = getattr(meta, "doc_items", None)
            if doc_items:
                for item in doc_items:
                    prov = getattr(item, "prov", None)
                    if prov and len(prov) > 0:
                        page_no = getattr(prov[0], "page_no", None)
                        if page_no:
                            page_number = page_no
                            break

        # Use the raw chunk text as primary, contextualized for embedding
        chunk_text_raw = getattr(chunk, "text", "") or str(chunk)

        chunks.append(ChunkData(
            text=chunk_text_raw,
            section_header=section_header,
            page_number=page_number,
            contextualized_text=contextualized,
        ))

    logger.info(f"Docling HybridChunker: produced {len(chunks)} chunks")
    return chunks


# =============================================================================
# Legacy chunking strategies (fallback)
# =============================================================================

def chunk_text(
    text: str,
    strategy: str = "recursive",
    chunk_size: int = 512,
    overlap: int = 50,
    sections: list[ParsedSection] | None = None,
) -> list[ChunkData]:
    """
    Split text into chunks using legacy strategies.

    Args:
        text: The text to split
        strategy: Chunking strategy name
        chunk_size: Target chunk size in characters
        overlap: Character overlap between chunks
        sections: Optional sections from parser

    Returns:
        List of ChunkData
    """
    from app.utils.text_processing_legacy import chunk_text as legacy_chunk
    return legacy_chunk(text, strategy, chunk_size, overlap, sections)
