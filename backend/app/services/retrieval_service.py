"""
Retrieval Service - Semantische Vektorsuche mit Reranking.

Sucht nur in Collections, auf die der Benutzer Zugriff hat.
Verwendet pgvector für semantische Ähnlichkeitssuche.
"""

import logging
import re
from collections import Counter
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.config import settings
from app.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)

# ── Keyword reranking helpers ────────────────────────────────────────────────

_SPLIT_RE = re.compile(r"[^\w]+", re.UNICODE)


def _tokenize(text_str: str) -> list[str]:
    """Lower-case unicode-aware tokenisation."""
    return [t for t in _SPLIT_RE.split(text_str.lower()) if len(t) > 1]


def _keyword_score(query_tokens: list[str], chunk_tokens: list[str]) -> float:
    """Combined Jaccard + term-frequency keyword overlap score in [0, 1]."""
    if not query_tokens or not chunk_tokens:
        return 0.0

    query_set = set(query_tokens)
    chunk_set = set(chunk_tokens)

    # Jaccard similarity
    intersection = query_set & chunk_set
    if not intersection:
        return 0.0
    jaccard = len(intersection) / len(query_set | chunk_set)

    # Term-frequency boost: fraction of query tokens that appear in chunk
    chunk_counter = Counter(chunk_tokens)
    tf_hits = sum(min(chunk_counter[t], 3) for t in query_tokens if t in chunk_counter)
    tf_score = tf_hits / (len(query_tokens) * 3)  # normalise to [0, 1]

    return 0.5 * jaccard + 0.5 * tf_score


@dataclass
class RetrievalResult:
    """Ein einzelnes Suchergebnis."""
    chunk_id: int
    document_id: int
    document_name: str
    collection_name: str
    content: str
    section_header: str | None
    page_number: int | None
    similarity_score: float


class RetrievalService:
    """Semantische Vektorsuche über Chunks mit Berechtigungsprüfung."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.embedding = EmbeddingService()
        self.config = settings.retrieval

    async def search(
        self,
        query: str,
        collection_ids: list[int],
        top_k: int | None = None,
    ) -> list[RetrievalResult]:
        """
        Führt eine semantische Vektorsuche durch.

        Args:
            query: Die Suchanfrage
            collection_ids: IDs der zu durchsuchenden Collections (bereits berechtigungsgeprüft)
            top_k: Anzahl der Ergebnisse (Standard aus Konfiguration)

        Returns:
            Liste von RetrievalResult, sortiert nach Relevanz
        """
        top_k = top_k or self.config.top_k

        if not collection_ids:
            return []

        # Query-Embedding berechnen
        logger.info(f"Retrieval: query='{query[:100]}', collections={collection_ids}, top_k={top_k}")
        query_embedding = await self.embedding.embed_query(query)
        logger.debug(f"Embedding berechnet: {len(query_embedding)} Dimensionen")

        results = await self._vector_search(query_embedding, collection_ids, top_k)

        # Optionaler Post-Query-Schwellenwert-Filter
        threshold = self.config.similarity_threshold
        if threshold > 0 and results:
            before = len(results)
            results = [r for r in results if r.similarity_score >= threshold]
            if len(results) < before:
                logger.info(f"Schwellenwert-Filter ({threshold}): {before} → {len(results)} Ergebnisse")

        if results:
            scores = [r.similarity_score for r in results]
            logger.info(f"Retrieval: {len(results)} Ergebnisse, Scores: "
                        f"max={max(scores):.3f}, min={min(scores):.3f}, avg={sum(scores)/len(scores):.3f}")
        else:
            logger.warning(f"Retrieval: 0 Ergebnisse für query='{query[:100]}'")

        # Optionales Reranking
        if self.config.rerank and len(results) > self.config.rerank_top_k:
            results = await self._rerank(query, results)
            results = results[:self.config.rerank_top_k]

        return results

    async def _vector_search(
        self,
        query_embedding: list[float],
        collection_ids: list[int],
        top_k: int,
    ) -> list[RetrievalResult]:
        """Semantische Vektorsuche mit pgvector."""
        embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

        query = text(f"""
            SELECT c.id, c.document_id, c.content, c.section_header, c.page_number,
                   d.original_name as document_name, col.name as collection_name,
                   1 - (c.embedding <=> '{embedding_str}'::vector) as similarity
            FROM chunks c
            JOIN documents d ON c.document_id = d.id
            JOIN collections col ON d.collection_id = col.id
            WHERE d.collection_id = ANY(:collection_ids)
              AND d.processing_status = 'completed'
            ORDER BY c.embedding <=> '{embedding_str}'::vector
            LIMIT :top_k
        """)

        result = await self.db.execute(query, {
            "collection_ids": collection_ids,
            "top_k": top_k,
        })

        return [
            RetrievalResult(
                chunk_id=row.id, document_id=row.document_id,
                document_name=row.document_name, collection_name=row.collection_name,
                content=row.content, section_header=row.section_header,
                page_number=row.page_number, similarity_score=float(row.similarity),
            )
            for row in result.fetchall()
        ]

    async def _rerank(self, query: str, results: list[RetrievalResult]) -> list[RetrievalResult]:
        """
        Rerank results by blending vector similarity with keyword overlap.

        Combined score = α * similarity + (1-α) * keyword_score
        where α = 0.7 (semantic weight).  This penalises chunks that match
        semantically but share no surface-level terms with the query, and
        rewards chunks that have both high semantic and lexical overlap.
        """
        if not results:
            return results

        alpha = 0.7  # weight for vector similarity
        query_tokens = _tokenize(query)

        scored: list[tuple[float, RetrievalResult]] = []
        for r in results:
            chunk_tokens = _tokenize(r.content)
            kw = _keyword_score(query_tokens, chunk_tokens)
            combined = alpha * r.similarity_score + (1 - alpha) * kw
            scored.append((combined, r))

        scored.sort(key=lambda x: x[0], reverse=True)

        if logger.isEnabledFor(logging.DEBUG):
            for rank, (score, r) in enumerate(scored, 1):
                logger.debug(
                    f"Rerank #{rank}: combined={score:.3f} "
                    f"(sim={r.similarity_score:.3f}, kw={score - alpha * r.similarity_score:.3f}) "
                    f"doc={r.document_name} chunk={r.chunk_id}"
                )

        return [r for _, r in scored]
