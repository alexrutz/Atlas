"""
Document Processor - Parsing und Chunking von Dokumenten.

Unterstützt verschiedene Dateiformate und Chunking-Strategien.
Nutzt den ContextEnrichmentService für kontextangereichertes Embedding.
"""

import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.models.document import Document
from app.models.chunk import Chunk, GlossaryEntry
from app.models.collection import Collection
from app.services.context_enrichment import ContextEnrichmentService
from app.services.embedding_service import EmbeddingService
from app.utils.file_parsers import parse_document
from app.utils.text_processing import chunk_text

logger = logging.getLogger(__name__)


class DocumentProcessor:
    """Verarbeitet hochgeladene Dokumente: Parsing → Chunking → Enrichment → Embedding."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.enrichment = ContextEnrichmentService()
        self.embedding = EmbeddingService()

    async def process(self, document_id: int) -> None:
        """
        Vollständige Verarbeitung eines Dokuments.

        Ablauf:
        1. Dokument aus DB laden
        2. Datei parsen (Text extrahieren)
        3. Text in Chunks aufteilen
        4. Kontext-Beschreibung und Glossar laden
        5. Jeden Chunk mit Kontext anreichern
        6. Embedding für jeden angereicherten Chunk berechnen
        7. Chunks mit Embeddings in DB speichern
        8. Status aktualisieren
        """
        # 1. Dokument laden
        result = await self.db.execute(select(Document).where(Document.id == document_id))
        document = result.scalar_one_or_none()
        if not document:
            logger.error(f"Dokument {document_id} nicht gefunden")
            return

        try:
            document.processing_status = "processing"
            await self.db.flush()

            # Collection laden
            col_result = await self.db.execute(select(Collection).where(Collection.id == document.collection_id))
            collection = col_result.scalar_one()

            # Collection-Glossar laden
            glossary_result = await self.db.execute(
                select(GlossaryEntry).where(GlossaryEntry.collection_id == collection.id)
            )
            collection_glossary = {
                entry.term: entry.definition
                for entry in glossary_result.scalars().all()
            }

            # Dokument-spezifisches Glossar mit Collection-Glossar zusammenführen
            combined_glossary = {**collection_glossary, **(document.glossary or {})}

            # 2. Datei parsen
            logger.info(f"Parse Dokument: {document.original_name}")
            parsed = parse_document(document.file_path, document.file_type)

            # 3. Text in Chunks aufteilen
            logger.info(f"Chunking mit Strategie: {settings.chunking.strategy}")
            chunks = chunk_text(
                text=parsed.text,
                strategy=settings.chunking.strategy,
                chunk_size=settings.chunking.chunk_size,
                overlap=settings.chunking.chunk_overlap,
                sections=parsed.sections,
            )

            # Optionale automatische Glossar-Extraktion
            if settings.context_enrichment.auto_glossary_extraction and not document.glossary:
                auto_glossary = await self.enrichment.auto_extract_glossary(parsed.text)
                if auto_glossary:
                    combined_glossary.update(auto_glossary)
                    document.glossary = auto_glossary

            # 4-6. Enrichment und Embedding für jeden Chunk
            logger.info(f"Verarbeite {len(chunks)} Chunks mit Context Enrichment")
            enriched_texts = []
            chunk_objects = []

            for i, chunk_data in enumerate(chunks):
                # Kontext-Anreicherung
                enriched = self.enrichment.enrich_chunk(
                    chunk_text=chunk_data.text,
                    document_title=document.original_name,
                    collection_name=collection.name,
                    context_description=document.context_description,
                    glossary=combined_glossary,
                    section_header=chunk_data.section_header,
                    page_number=chunk_data.page_number,
                )

                enriched_texts.append(enriched.enriched_content)
                chunk_objects.append(Chunk(
                    document_id=document.id,
                    chunk_index=i,
                    content=chunk_data.text,
                    enriched_content=enriched.enriched_content,
                    section_header=enriched.section_header,
                    page_number=enriched.page_number,
                ))

            # Batch-Embedding berechnen
            logger.info(f"Berechne Embeddings für {len(enriched_texts)} angereicherte Chunks")
            embeddings = await self.embedding.embed_batch(enriched_texts)

            # 7. In DB speichern
            for chunk_obj, embedding in zip(chunk_objects, embeddings):
                chunk_obj.embedding = embedding
                self.db.add(chunk_obj)

            # 8. Status aktualisieren
            document.processing_status = "completed"
            document.chunk_count = len(chunk_objects)
            await self.db.flush()

            logger.info(f"Dokument {document.original_name} erfolgreich verarbeitet: {len(chunk_objects)} Chunks")

        except Exception as e:
            logger.error(f"Fehler bei Verarbeitung von Dokument {document_id}: {e}")
            document.processing_status = "error"
            document.processing_error = str(e)
            await self.db.flush()
            raise
