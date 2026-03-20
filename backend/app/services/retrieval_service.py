"""
Retrieval Service - Semantische Vektorsuche mit Reranking.

Sucht nur in Collections, auf die der Benutzer Zugriff hat.
Verwendet pgvector für semantische Ähnlichkeitssuche.
"""

import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.config import settings
from app.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


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
        Reranking der Suchergebnisse.

        Stub: Hier kann ein Cross-Encoder oder LLM-basiertes Reranking implementiert werden.
        Aktuell wird die bestehende Sortierung beibehalten.
        """
        # TODO: Implementierung mit Cross-Encoder Modell
        # Optionen:
        # - cross-encoder/ms-marco-MiniLM-L-6-v2 (via sentence-transformers)
        # - LLM-basiertes Reranking über llama.cpp
        return sorted(results, key=lambda r: r.similarity_score, reverse=True)
