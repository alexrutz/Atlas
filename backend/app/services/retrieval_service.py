"""
Retrieval Service - Hybrid-Suche (Vektor + Volltext) mit Reranking.

Sucht nur in Collections, auf die der Benutzer Zugriff hat.
Verwendet pgvector für Vektorsuche und pg_trgm für Volltextsuche.
"""

import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, func

from app.core.config import settings
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.collection import Collection
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
    """Hybrid-Suche über Chunks mit Berechtigungsprüfung."""

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
        Führt eine Hybrid-Suche durch.

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
        logger.info(f"Retrieval: query='{query[:100]}', collections={collection_ids}, top_k={top_k}, "
                     f"hybrid={self.config.hybrid_search}, threshold={self.config.similarity_threshold}")
        query_embedding = await self.embedding.embed_query(query)
        logger.debug(f"Embedding berechnet: {len(query_embedding)} Dimensionen")

        if self.config.hybrid_search:
            results = await self._hybrid_search(query, query_embedding, collection_ids, top_k)
        else:
            results = await self._vector_search(query_embedding, collection_ids, top_k)

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
        """Reine Vektorsuche mit pgvector."""
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
              AND 1 - (c.embedding <=> '{embedding_str}'::vector) > :threshold
            ORDER BY c.embedding <=> '{embedding_str}'::vector
            LIMIT :top_k
        """)

        result = await self.db.execute(query, {
            "collection_ids": collection_ids,
            "threshold": self.config.similarity_threshold,
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

    async def _hybrid_search(
        self,
        query_text: str,
        query_embedding: list[float],
        collection_ids: list[int],
        top_k: int,
    ) -> list[RetrievalResult]:
        """
        Hybrid-Suche: Kombination aus Vektor- und Volltextsuche.
        hybrid_alpha steuert die Gewichtung (1.0 = nur Vektor, 0.0 = nur Volltext).
        """
        alpha = self.config.hybrid_alpha
        embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

        query = text(f"""
            WITH vector_results AS (
                SELECT c.id, c.document_id, c.content, c.section_header, c.page_number,
                       d.original_name as document_name, col.name as collection_name,
                       1 - (c.embedding <=> '{embedding_str}'::vector) as vector_score
                FROM chunks c
                JOIN documents d ON c.document_id = d.id
                JOIN collections col ON d.collection_id = col.id
                WHERE d.collection_id = ANY(:collection_ids)
                  AND d.processing_status = 'completed'
                  AND 1 - (c.embedding <=> '{embedding_str}'::vector) > :threshold
                ORDER BY c.embedding <=> '{embedding_str}'::vector
                LIMIT :top_k * 2
            ),
            text_results AS (
                SELECT c.id,
                       similarity(c.content, :query_text) as text_score
                FROM chunks c
                JOIN documents d ON c.document_id = d.id
                WHERE d.collection_id = ANY(:collection_ids)
                  AND d.processing_status = 'completed'
                  AND c.content % :query_text
            )
            SELECT vr.*,
                   COALESCE(tr.text_score, 0) as text_score,
                   (:alpha * vr.vector_score + (1.0 - :alpha) * COALESCE(tr.text_score, 0)) as combined_score
            FROM vector_results vr
            LEFT JOIN text_results tr ON vr.id = tr.id
            ORDER BY combined_score DESC
            LIMIT :top_k
        """)

        result = await self.db.execute(query, {
            "query_text": query_text,
            "collection_ids": collection_ids,
            "alpha": alpha,
            "threshold": self.config.similarity_threshold,
            "top_k": top_k,
        })

        return [
            RetrievalResult(
                chunk_id=row.id, document_id=row.document_id,
                document_name=row.document_name, collection_name=row.collection_name,
                content=row.content, section_header=row.section_header,
                page_number=row.page_number, similarity_score=float(row.combined_score),
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
        # - LLM-basiertes Reranking über Ollama
        return sorted(results, key=lambda r: r.similarity_score, reverse=True)
