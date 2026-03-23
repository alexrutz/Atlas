"""
Text-Verarbeitung: Chunking-Strategien.

Unterstützt verschiedene Strategien:
- fixed: Feste Chunk-Größe
- sentence: Satzbasiertes Chunking
- recursive: Rekursives Aufteilen nach Trennzeichen
- semantic: Semantisches Chunking (basierend auf Abschnitten)
"""

import re
import logging
from dataclasses import dataclass

from app.utils.file_parsers import ParsedSection

logger = logging.getLogger(__name__)


@dataclass
class ChunkData:
    """Ein einzelner Chunk."""
    text: str
    section_header: str | None = None
    page_number: int | None = None


def chunk_text(
    text: str,
    strategy: str = "recursive",
    chunk_size: int = 512,
    overlap: int = 50,
    sections: list[ParsedSection] | None = None,
) -> list[ChunkData]:
    """
    Teilt Text in Chunks auf.

    Args:
        text: Der zu teilende Text
        strategy: Chunking-Strategie
        chunk_size: Ziel-Chunk-Größe in Zeichen (Approximation für Tokens)
        overlap: Überlappung zwischen Chunks
        sections: Optionale Abschnitte aus dem Parser

    Returns:
        Liste von ChunkData
    """
    strategies = {
        "fixed": _chunk_fixed,
        "sentence": _chunk_sentence,
        "recursive": _chunk_recursive,
        "semantic": _chunk_semantic,
    }

    func = strategies.get(strategy, _chunk_recursive)

    if strategy == "semantic" and sections:
        return func(text, chunk_size, overlap, sections=sections)

    return func(text, chunk_size, overlap)


def _chunk_fixed(text: str, chunk_size: int, overlap: int, **kwargs) -> list[ChunkData]:
    """Feste Chunk-Größe mit Überlappung."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(ChunkData(text=chunk.strip()))
        start = end - overlap
    return chunks


def _chunk_sentence(text: str, chunk_size: int, overlap: int, **kwargs) -> list[ChunkData]:
    """Satzbasiertes Chunking."""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks = []
    current_chunk = []
    current_len = 0

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        if current_len + len(sentence) > chunk_size and current_chunk:
            chunks.append(ChunkData(text=" ".join(current_chunk)))
            # Überlappung: letzte Sätze behalten
            overlap_text = " ".join(current_chunk)
            while len(overlap_text) > overlap and current_chunk:
                current_chunk.pop(0)
                overlap_text = " ".join(current_chunk)
            current_len = len(overlap_text)
        current_chunk.append(sentence)
        current_len += len(sentence)

    if current_chunk:
        chunks.append(ChunkData(text=" ".join(current_chunk)))

    return chunks


def _chunk_recursive(text: str, chunk_size: int, overlap: int, **kwargs) -> list[ChunkData]:
    """Rekursives Chunking nach Trennzeichen-Hierarchie."""
    separators = ["\n\n", "\n", ". ", " "]
    return _recursive_split(text, separators, chunk_size, overlap)


def _recursive_split(
    text: str,
    separators: list[str],
    chunk_size: int,
    overlap: int,
) -> list[ChunkData]:
    """Hilfsfunktion für rekursives Chunking."""
    if not text.strip():
        return []

    if len(text) <= chunk_size:
        return [ChunkData(text=text.strip())]

    if not separators:
        return _chunk_fixed(text, chunk_size, overlap)

    sep = separators[0]
    parts = text.split(sep)
    chunks = []
    current = []
    current_len = 0

    for part in parts:
        if current_len + len(part) > chunk_size and current:
            chunk_text = sep.join(current)
            if chunk_text.strip():
                # Falls der Chunk immer noch zu groß ist, rekursiv weiter teilen
                if len(chunk_text) > chunk_size * 1.5:
                    sub_chunks = _recursive_split(chunk_text, separators[1:], chunk_size, overlap)
                    chunks.extend(sub_chunks)
                else:
                    chunks.append(ChunkData(text=chunk_text.strip()))
            current = []
            current_len = 0

        current.append(part)
        current_len += len(part) + len(sep)

    if current:
        chunk_text = sep.join(current)
        if chunk_text.strip():
            chunks.append(ChunkData(text=chunk_text.strip()))

    return chunks


def _chunk_semantic(
    text: str,
    chunk_size: int,
    overlap: int,
    sections: list[ParsedSection] | None = None,
    **kwargs,
) -> list[ChunkData]:
    """Semantisches Chunking basierend auf Dokumentabschnitten."""
    if not sections:
        return _chunk_recursive(text, chunk_size, overlap)

    chunks = []
    for section in sections:
        if len(section.content) <= chunk_size:
            chunks.append(ChunkData(
                text=section.content.strip(),
                section_header=section.header,
                page_number=section.page_number,
            ))
        else:
            # Abschnitt ist zu lang → rekursiv weiter teilen
            sub_chunks = _chunk_recursive(section.content, chunk_size, overlap)
            for sc in sub_chunks:
                sc.section_header = section.header
                sc.page_number = section.page_number
            chunks.extend(sub_chunks)

    return chunks
