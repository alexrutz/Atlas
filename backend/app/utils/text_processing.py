"""
Text processing: fallback chunking for edge cases.

In normal operation, ALL documents are chunked via docling-core's HybridChunker
inside file_parsers.py. This module exists only as a fallback if a parser
returns text without pre-made chunks (e.g. if docling-serve is unreachable
and local parsing produces raw text).

Uses HybridChunker with a DoclingDocument built from plain text.
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
    Split text into chunks using docling-core's HybridChunker.

    Creates a DoclingDocument from the text, then chunks it with
    HybridChunker for token-aware, structure-preserving splits.

    Args:
        text: The text to split
        chunk_size: Ignored (kept for API compat; max_tokens from config is used)
        overlap: Ignored (kept for API compat)
        sections: Optional sections from parser (preserved as separate doc items)

    Returns:
        List of ChunkData
    """
    from docling_core.types.doc import DoclingDocument, DocItemLabel
    from docling_core.transforms.chunker import HybridChunker
    from docling_core.transforms.chunker.tokenizer.huggingface import (
        HuggingFaceTokenizer,
    )
    from transformers import AutoTokenizer
    from app.core.config import settings

    if not text.strip():
        return []

    # Build a DoclingDocument from the text
    doc = DoclingDocument(name="local")

    if sections:
        for section in sections:
            if section.header:
                doc.add_heading(text=section.header)
            if section.content.strip():
                doc.add_text(label=DocItemLabel.TEXT, text=section.content.strip())
    else:
        # Split on double newlines to preserve paragraph structure
        for para in text.split("\n\n"):
            para = para.strip()
            if para:
                doc.add_text(label=DocItemLabel.TEXT, text=para)

    # Chunk with HybridChunker
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
