"""
Query Enrichment Service - Reichert Suchanfragen mit Kontextwissen an.

Bevor eine Suchanfrage an die Retrieval-Pipeline geht, wird sie mit dem
allgemeinen Kontext und den Collection-spezifischen Kontext-Texten angereichert.
"""

import logging

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.models.collection import Collection
from app.models.system_setting import SystemSetting

logger = logging.getLogger(__name__)


class QueryEnrichmentService:
    """Reichert Suchanfragen mit Kontextinformationen an."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.config = settings.retrieval.query_enrichment
        self.llm_config = settings.llm

    async def enrich_query(
        self,
        query: str,
        collection_ids: list[int],
    ) -> str:
        """
        Reichert eine Suchanfrage mit Kontextinformationen an.

        Lädt den allgemeinen Kontext und die Collection-spezifischen Kontext-Texte
        und lässt das LLM die Anfrage um passende Fachbegriffe erweitern.

        Args:
            query: Die ursprüngliche Suchanfrage des Benutzers
            collection_ids: IDs der zu durchsuchenden Collections

        Returns:
            Die angereicherte Suchanfrage
        """
        if not self.config.enabled:
            return query

        # Kontext-Informationen laden
        context = await self._load_context(collection_ids)

        if not context:
            logger.debug("Kein Kontext für Query-Anreicherung verfügbar")
            return query

        # LLM-Prompt bauen und angereicherte Query generieren
        enriched = await self._generate_enriched_query(query, context)
        return enriched

    async def _load_context(self, collection_ids: list[int]) -> str:
        """
        Lädt den globalen Kontext und die pro-Collection Kontext-Texte.

        Returns:
            Zusammengesetzter Kontext-String für das LLM
        """
        parts = []

        # 1. Globalen Kontext laden
        result = await self.db.execute(
            select(SystemSetting.value).where(SystemSetting.key == "global_context")
        )
        global_context = result.scalar_one_or_none()
        if global_context:
            parts.append("Allgemeiner Kontext:\n" + global_context)

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
            parts.append("Collection-Kontext:\n" + "\n".join(col_context_lines))

        return "\n\n".join(parts)

    async def _generate_enriched_query(self, query: str, context: str) -> str:
        """
        Lässt das LLM die Suchanfrage mit dem geladenen Kontext anreichern.

        Args:
            query: Die ursprüngliche Anfrage
            context: Kontext-Informationen

        Returns:
            Die angereicherte Anfrage
        """
        prompt = self.config.prompt_template.format(
            context=context,
            query=query,
        )

        try:
            async with httpx.AsyncClient(timeout=self.llm_config.timeout) as client:
                response = await client.post(
                    f"{self.llm_config.base_url}/api/generate",
                    json={
                        "model": self.llm_config.model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.0,
                            "num_predict": 256,
                        },
                    },
                )
                response.raise_for_status()
                enriched_query = response.json()["response"].strip()

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
