"""
Query Enrichment Service - Reichert Suchanfragen mit Kontextwissen an.

Jede Query geht durch die Enrichment-Pipeline. Das Ergebnis ist immer ein Paar
aus (original_query, enriched_query). Wenn kein Kontext vorhanden ist, sind beide
identisch, aber der Workflow bleibt derselbe.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.models.collection import Collection
from app.models.system_setting import SystemSetting
from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)


class QueryEnrichmentService:
    """Reichert Suchanfragen mit Kontextinformationen an."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.config = settings.retrieval.query_enrichment
        self.llm = LLMService()

    async def enrich_query(
        self,
        query: str,
        collection_ids: list[int],
    ) -> str:
        """
        Reichert eine Suchanfrage mit Kontextinformationen an.

        Jede Query geht durch die Pipeline. Wenn kein Kontext vorhanden ist,
        wird die Original-Query unverändert zurückgegeben - der Workflow
        bleibt aber identisch (enriched_query == original_query).
        """
        context = await self._load_context(collection_ids)

        if not context:
            logger.info("Kein Kontext verfügbar - enriched_query = original_query")
            return query

        enriched = await self._generate_enriched_query(query, context)
        return enriched

    async def _load_context(self, collection_ids: list[int]) -> str:
        """Lädt den globalen Kontext und die pro-Collection Kontext-Texte."""
        parts = []

        # 1. Globalen Kontext laden
        result = await self.db.execute(
            select(SystemSetting.value).where(SystemSetting.key == "global_context")
        )
        global_context = result.scalar_one_or_none()
        if global_context:
            parts.append("Global context:\n" + global_context)

        # 2. Pro-Collection Kontext-Texte laden
        result = await self.db.execute(
            select(Collection.name, Collection.context_text)
            .where(Collection.id.in_(collection_ids))
        )
        collection_contexts = result.fetchall()

        col_context_lines = []
        for col in collection_contexts:
            if col.context_text:
                col_context_lines.append(f"- {col.name}: {col.context_text}")
        if col_context_lines:
            parts.append("Collection context:\n" + "\n".join(col_context_lines))

        return "\n\n".join(parts)

    async def _generate_enriched_query(self, query: str, context: str) -> str:
        """Lässt das LLM die Suchanfrage mit dem geladenen Kontext anreichern."""
        prompt = self.config.prompt_template.format(
            context=context,
            query=query,
        )

        try:
            enriched_query = await self.llm.generate_enrichment(prompt)

            if enriched_query:
                logger.info(
                    f"Query angereichert: '{query}' → '{enriched_query}'"
                )
                return enriched_query
            else:
                logger.warning("LLM gab leere Antwort bei Query-Anreicherung zurück")
                return query

        except Exception as e:
            logger.warning(f"Query-Anreicherung fehlgeschlagen, verwende Original-Query: {e}")
            return query
