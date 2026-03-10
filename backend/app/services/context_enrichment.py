"""
Context-Enriched Embedding Service.

KERNKOMPONENTE: Reichert Chunks mit Kontextwissen an, bevor sie embedded werden.
Dies ist entscheidend, da die Firmendokumente viele Fachbegriffe und Abkürzungen
enthalten, die ohne Kontext nicht verständlich sind.

Ablauf:
1. Dokument-Metadaten laden (Titel, Collection, Kontext-Beschreibung)
2. Relevante Glossar-Einträge für den Chunk identifizieren
3. Abschnittsüberschrift extrahieren
4. Alles nach dem konfigurierten Template zusammenbauen
5. Diesen angereicherten Text als Grundlage für das Embedding verwenden
"""

import logging
from dataclasses import dataclass

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class EnrichedChunk:
    """Ein mit Kontext angereicherter Chunk."""
    original_content: str
    enriched_content: str
    section_header: str | None
    page_number: int | None
    token_count: int | None


class ContextEnrichmentService:
    """Reichert Dokument-Chunks mit Kontextwissen an."""

    def __init__(self):
        self.config = settings.context_enrichment
        self.template = self.config.embedding_template

    def enrich_chunk(
        self,
        chunk_text: str,
        document_title: str,
        collection_name: str,
        context_description: str | None = None,
        glossary: dict[str, str] | None = None,
        section_header: str | None = None,
        page_number: int | None = None,
    ) -> EnrichedChunk:
        """
        Reichert einen einzelnen Chunk mit Kontextinformationen an.

        Args:
            chunk_text: Der originale Chunk-Text
            document_title: Titel/Name des Dokuments
            collection_name: Name der Collection (z.B. "Normen")
            context_description: Manuell eingegebene Beschreibung des Dokuments
            glossary: Dict von Fachbegriff -> Definition
            section_header: Überschrift des aktuellen Abschnitts
            page_number: Seitennummer im Originaldokument

        Returns:
            EnrichedChunk mit dem angereicherten Text für das Embedding
        """
        if not self.config.enabled:
            return EnrichedChunk(
                original_content=chunk_text,
                enriched_content=chunk_text,
                section_header=section_header,
                page_number=page_number,
                token_count=None,
            )

        # Relevante Glossar-Einträge finden (die im Chunk vorkommen)
        glossary_text = ""
        if glossary:
            relevant_terms = []
            chunk_lower = chunk_text.lower()
            for term, definition in glossary.items():
                if term.lower() in chunk_lower:
                    relevant_terms.append(f"{term}: {definition}")
            if relevant_terms:
                glossary_text = "; ".join(relevant_terms)

        # Template befüllen
        enriched = self.template.format(
            document_title=document_title or "Unbekannt",
            collection_name=collection_name or "Allgemein",
            section_header=section_header or "—",
            context_description=context_description or "—",
            glossary=glossary_text or "—",
            chunk_text=chunk_text,
        )

        return EnrichedChunk(
            original_content=chunk_text,
            enriched_content=enriched.strip(),
            section_header=section_header,
            page_number=page_number,
            token_count=None,
        )

    async def auto_extract_glossary(self, document_text: str) -> dict[str, str]:
        """
        Extrahiert automatisch Fachbegriffe und Abkürzungen aus einem Dokument
        mithilfe eines LLM.

        Args:
            document_text: Der vollständige Dokumenttext (oder ein repräsentativer Ausschnitt)

        Returns:
            Dict von Fachbegriff/Abkürzung -> Definition
        """
        if not self.config.auto_glossary_extraction:
            return {}

        prompt = f"""Analysiere den folgenden Text und extrahiere alle Fachbegriffe,
Abkürzungen und technischen Begriffe. Gib für jeden Begriff eine kurze Definition.

Antwortformat (JSON):
{{"Begriff1": "Definition1", "ABK": "Ausgeschriebener Begriff"}}

Text:
{document_text[:4000]}

Extrahierte Begriffe (JSON):"""

        try:
            async with httpx.AsyncClient(timeout=self.config.max_context_tokens) as client:
                response = await client.post(
                    f"{settings.llm.base_url}/api/generate",
                    json={
                        "model": self.config.summarization_model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": 0.1},
                    },
                    timeout=60,
                )
                response.raise_for_status()
                result = response.json()
                # Versuche JSON aus der Antwort zu parsen
                import json
                glossary_text = result.get("response", "{}")
                return json.loads(glossary_text)
        except Exception as e:
            logger.warning(f"Automatische Glossar-Extraktion fehlgeschlagen: {e}")
            return {}
