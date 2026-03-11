"""
Query Enrichment Service - Reichert Suchanfragen mit Glossar-/Kontextwissen an.

Bevor eine Suchanfrage an die Retrieval-Pipeline geht, wird sie mit relevanten
Fachbegriffe, Abkürzungen und Variablennamen aus dem Glossar und den
Kontext-Beschreibungen der Dokumente angereichert.

Beispiel:
  Benutzer fragt: "Wie lang ist der Kühler?"
  Glossar enthält: "L1: Kühlerlänge"
  Angereicherte Anfrage: "Wie lang ist der Kühler, dessen Länge durch L1 beschrieben wird?"
  → Retrieval findet nun den Chunk mit "L1=1000mm"
"""

import logging

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.models.chunk import GlossaryEntry
from app.models.document import Document

logger = logging.getLogger(__name__)


class QueryEnrichmentService:
    """Reichert Suchanfragen mit Glossar- und Kontextinformationen an."""

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
        Reichert eine Suchanfrage mit Glossar- und Kontextinformationen an.

        Lädt die Glossar-Einträge und Kontext-Beschreibungen der relevanten
        Collections und lässt das LLM die Anfrage um passende Fachbegriffe erweitern.

        Args:
            query: Die ursprüngliche Suchanfrage des Benutzers
            collection_ids: IDs der zu durchsuchenden Collections

        Returns:
            Die angereicherte Suchanfrage
        """
        if not self.config.enabled:
            return query

        # Glossar- und Kontext-Informationen laden
        context = await self._load_context(collection_ids)

        if not context:
            logger.debug("Kein Glossar/Kontext für Query-Anreicherung verfügbar")
            return query

        # LLM-Prompt bauen und angereicherte Query generieren
        enriched = await self._generate_enriched_query(query, context)
        return enriched

    async def _load_context(self, collection_ids: list[int]) -> str:
        """
        Lädt Glossar-Einträge und Kontext-Beschreibungen für die angegebenen Collections.

        Returns:
            Zusammengesetzter Kontext-String für das LLM
        """
        parts = []

        # 1. Collection-Level Glossar-Einträge laden
        result = await self.db.execute(
            select(GlossaryEntry.term, GlossaryEntry.definition, GlossaryEntry.abbreviation)
            .where(GlossaryEntry.collection_id.in_(collection_ids))
        )
        glossary_entries = result.fetchall()

        if glossary_entries:
            glossary_lines = []
            for entry in glossary_entries:
                line = f"- {entry.term}: {entry.definition}"
                if entry.abbreviation:
                    line += f" (Abkürzung: {entry.abbreviation})"
                glossary_lines.append(line)
            parts.append("Glossar-Einträge:\n" + "\n".join(glossary_lines))

        # 2. Dokument-Level Glossare und Kontext-Beschreibungen laden
        result = await self.db.execute(
            select(Document.original_name, Document.context_description, Document.glossary)
            .where(
                Document.collection_id.in_(collection_ids),
                Document.processing_status == "completed",
            )
        )
        documents = result.fetchall()

        doc_context_lines = []
        doc_glossary_lines = []

        for doc in documents:
            if doc.context_description:
                doc_context_lines.append(f"- {doc.original_name}: {doc.context_description}")

            if doc.glossary:
                for term, definition in doc.glossary.items():
                    doc_glossary_lines.append(f"- {term}: {definition} (aus {doc.original_name})")

        if doc_context_lines:
            parts.append("Dokument-Beschreibungen:\n" + "\n".join(doc_context_lines))

        if doc_glossary_lines:
            parts.append("Dokument-Glossare:\n" + "\n".join(doc_glossary_lines))

        return "\n\n".join(parts)

    async def _generate_enriched_query(self, query: str, context: str) -> str:
        """
        Lässt das LLM die Suchanfrage mit dem geladenen Kontext anreichern.

        Args:
            query: Die ursprüngliche Anfrage
            context: Glossar- und Kontext-Informationen

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
