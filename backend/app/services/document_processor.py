"""
Document Processor - Parsing und Chunking von Dokumenten.

Unterstützt verschiedene Dateiformate und Chunking-Strategien.
Chunks werden direkt mit ihrem Originaltext embedded.
Scanned-PDF OCR nutzt Qianfan-OCR VLM mit Layout-as-thought (konfigurierbar).
"""

import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.models.document import Document
from app.models.chunk import Chunk
from app.services.embedding_service import EmbeddingService
from app.utils.file_parsers import parse_document, ParsedDocument
from app.utils.text_processing import chunk_text

logger = logging.getLogger(__name__)


class DocumentProcessor:
    """Verarbeitet hochgeladene Dokumente: Parsing → Chunking → Embedding."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.embedding = EmbeddingService()

    async def _parse_with_vlm_ocr_fallback(self, file_path: str, file_type: str) -> ParsedDocument:
        """Parst ein Dokument. Bei PDFs ohne Text wird VLM-OCR direkt async aufgerufen."""
        parsed = parse_document(file_path, file_type)

        # Wenn Text vorhanden oder kein PDF → normales Ergebnis
        if parsed.text.strip() or file_type.lower() != ".pdf":
            return parsed

        # PDF ohne Text: VLM-OCR direkt im async-Kontext aufrufen
        if not settings.documents.ocr_enabled:
            logger.warning(f"Kein Text in PDF und OCR deaktiviert: {file_path}")
            return parsed

        backend = getattr(settings.documents, "ocr_backend", "tesseract")
        if backend == "vlm" and settings.vlm_ocr.enabled:
            logger.info(f"VLM-OCR (Layout-as-thought) für: {file_path}")
            from app.services.vlm_ocr_service import VlmOcrService
            vlm = VlmOcrService()
            sections, texts = await vlm.ocr_pdf_pages(file_path)
            if texts:
                return ParsedDocument(
                    text="\n\n".join(texts),
                    sections=sections,
                    page_count=parsed.page_count,
                )
            logger.warning(f"VLM-OCR konnte keinen Text extrahieren: {file_path}")

        return parsed

    async def process(self, document_id: int) -> None:
        """
        Vollständige Verarbeitung eines Dokuments.

        Ablauf:
        1. Dokument aus DB laden
        2. Datei parsen (Text extrahieren, ggf. VLM-OCR)
        3. Text in Chunks aufteilen
        4. Embedding für jeden Chunk berechnen
        5. Chunks mit Embeddings in DB speichern
        6. Status aktualisieren
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

            # 2. Datei parsen (mit VLM-OCR Fallback für scanned PDFs)
            logger.info(f"Parse Dokument: {document.original_name}")
            parsed = await self._parse_with_vlm_ocr_fallback(
                document.file_path, document.file_type
            )

            # 3. Text in Chunks aufteilen
            logger.info(f"Chunking mit Strategie: {settings.chunking.strategy}")
            chunks = chunk_text(
                text=parsed.text,
                strategy=settings.chunking.strategy,
                chunk_size=settings.chunking.chunk_size,
                overlap=settings.chunking.chunk_overlap,
                sections=parsed.sections,
            )

            # 4. Chunks und Texte für Embedding vorbereiten
            logger.info(f"Verarbeite {len(chunks)} Chunks")
            chunk_texts = []
            chunk_objects = []

            for i, chunk_data in enumerate(chunks):
                chunk_texts.append(chunk_data.text)
                chunk_objects.append(Chunk(
                    document_id=document.id,
                    chunk_index=i,
                    content=chunk_data.text,
                    section_header=chunk_data.section_header,
                    page_number=chunk_data.page_number,
                ))

            # Batch-Embedding berechnen
            logger.info(f"Berechne Embeddings für {len(chunk_texts)} Chunks")
            embeddings = await self.embedding.embed_batch(chunk_texts)

            # 5. In DB speichern
            for chunk_obj, embedding in zip(chunk_objects, embeddings):
                chunk_obj.embedding = embedding
                self.db.add(chunk_obj)

            # 6. Status aktualisieren
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
