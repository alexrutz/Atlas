"""
Text processing: simple chunking for locally-parsed text files.

For documents parsed via docling-serve (PDF, DOCX, etc.), chunks come
directly from the API and this module is NOT used.

For locally-parsed text files (TXT, MD, CSV, JSON), this module splits
the text into overlapping chunks using paragraph/line/sentence boundaries.
"""

import logging

from app.utils.file_parsers import ParsedSection, ChunkData

logger = logging.getLogger(__name__)


def chunk_text(
    text: str,
    chunk_size: int = 512,
    overlap: int = 50,
    sections: list[ParsedSection] | None = None,
) -> list[ChunkData]:
    """
    Split text into overlapping chunks.

    If sections are provided (from the parser), each section is chunked
    separately so that section headers and page numbers are preserved.

    Uses a simple recursive approach: try to split on paragraph breaks first,
    then line breaks, then sentences, then spaces.

    Args:
        text: The text to split
        chunk_size: Target chunk size in characters
        overlap: Character overlap between chunks
        sections: Optional sections from parser (preserves headers/pages)

    Returns:
        List of ChunkData
    """
    separators = ["\n\n", "\n", ". ", " "]

    # If we have sections, chunk each section separately to keep metadata
    if sections:
        chunks = []
        for section in sections:
            section_chunks = _split_with_separators(section.content, separators, chunk_size, overlap)
            for chunk in section_chunks:
                chunk.section_header = section.header
                chunk.page_number = section.page_number
            chunks.extend(section_chunks)
        return chunks

    # Otherwise just chunk the whole text
    return _split_with_separators(text, separators, chunk_size, overlap)


def _split_with_separators(
    text: str,
    separators: list[str],
    chunk_size: int,
    overlap: int,
) -> list[ChunkData]:
    """Split text using the first separator, recursing with smaller ones if needed."""
    if not text.strip():
        return []

    # Text fits in one chunk — done
    if len(text) <= chunk_size:
        return [ChunkData(text=text.strip())]

    # No separators left — fall back to fixed-size splits
    if not separators:
        return _split_fixed(text, chunk_size, overlap)

    sep = separators[0]
    parts = text.split(sep)
    chunks = []
    current_parts = []
    current_len = 0

    for part in parts:
        # If adding this part would exceed the limit, flush current buffer
        if current_len + len(part) > chunk_size and current_parts:
            combined = sep.join(current_parts)
            if combined.strip():
                # If the combined text is way too big, split with smaller separators
                if len(combined) > chunk_size * 1.5:
                    sub_chunks = _split_with_separators(combined, separators[1:], chunk_size, overlap)
                    chunks.extend(sub_chunks)
                else:
                    chunks.append(ChunkData(text=combined.strip()))
            current_parts = []
            current_len = 0

        current_parts.append(part)
        current_len += len(part) + len(sep)

    # Don't forget the last buffer
    if current_parts:
        combined = sep.join(current_parts)
        if combined.strip():
            chunks.append(ChunkData(text=combined.strip()))

    return chunks


def _split_fixed(text: str, chunk_size: int, overlap: int) -> list[ChunkData]:
    """Last resort: fixed-size character splits with overlap."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(ChunkData(text=chunk.strip()))
        start = end - overlap
    return chunks
