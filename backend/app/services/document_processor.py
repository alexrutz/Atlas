"""
Document Processor - Parsing and chunking of documents.

Routes documents to the Docling API (PDF, DOCX, XLSX, PPTX, HTML, XML) or
handles simple formats locally (TXT, MD, CSV, JSON).

Chunks are stored in rag.chunks, embeddings in rag.chunk_embeddings.
"""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.models.document import Document
from app.models.chunk import Chunk, ChunkEmbedding
from app.services.embedding_service import EmbeddingService
from app.utils.file_parsers import parse_document, ParsedDocument, DOCLING_FORMATS
from app.utils.text_processing import chunk_text

logger = logging.getLogger(__name__)


class DocumentProcessor:
    """Processes uploaded documents: Parsing -> Chunking -> Embedding."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.embedding = EmbeddingService()

    async def _parse(self, file_path: str, file_type: str) -> ParsedDocument:
        """Parse a document without blocking the event loop."""
        return await asyncio.to_thread(parse_document, file_path, file_type)

    async def process(self, document_id: int) -> None:
        """
        Full document processing pipeline.

        Flow:
        1. Load document from DB
        2. Parse file (Docling API for rich formats, local for text formats)
        3. Use Docling chunks if available, otherwise chunk locally
        4. Compute embedding for each chunk
        5. Store chunks + embeddings
        6. Update document status
        """
        result = await self.db.execute(select(Document).where(Document.id == document_id))
        document = result.scalar_one_or_none()
        if not document:
            logger.error(f"Document {document_id} not found")
            return

        try:
            # Parse file
            is_docling = document.file_type.lower() in DOCLING_FORMATS
            pipeline = "docling-api" if is_docling else "local"
            logger.info(f"Parsing document: {document.original_name} (pipeline={pipeline})")
            parsed = await self._parse(document.file_path, document.file_type)

            # Use Docling chunks if available, otherwise chunk locally
            if parsed.chunks:
                chunks = parsed.chunks
                chunker_type = "docling"
            else:
                chunker_type = settings.chunking.strategy
                logger.info(f"Chunking locally with strategy: {chunker_type}")
                chunks = await asyncio.to_thread(
                    chunk_text,
                    text=parsed.text,
                    strategy=settings.chunking.strategy,
                    chunk_size=settings.chunking.chunk_size,
                    overlap=settings.chunking.chunk_overlap,
                    sections=parsed.sections,
                )

            # Prepare chunks and texts for embedding
            logger.info(f"Processing {len(chunks)} chunks")
            chunk_texts = []
            chunk_objects = []

            for i, chunk_data in enumerate(chunks):
                embed_text = chunk_data.contextualized_text or chunk_data.text
                chunk_texts.append(embed_text)

                chunk_obj = Chunk(
                    document_id=document.id,
                    chunk_index=i,
                    content=chunk_data.text,
                    section_header=chunk_data.section_header,
                    page_number=chunk_data.page_number,
                    metadata_={
                        "parser": parsed.metadata.get("parser", pipeline),
                        "chunker": chunker_type,
                        **({"has_context": True} if chunk_data.contextualized_text else {}),
                    },
                )
                chunk_objects.append(chunk_obj)
                self.db.add(chunk_obj)

            await self.db.flush()

            # Compute batch embeddings
            logger.info(f"Computing embeddings for {len(chunk_texts)} chunks")
            embeddings = await self.embedding.embed_batch(chunk_texts)

            # Store embeddings
            for chunk_obj, embedding in zip(chunk_objects, embeddings):
                emb_obj = ChunkEmbedding(
                    chunk_id=chunk_obj.id,
                    model_name=settings.embedding.model,
                    embedding=embedding,
                )
                self.db.add(emb_obj)

            # Update document status
            document.processing_status = "completed"
            document.chunk_count = len(chunk_objects)
            await self.db.flush()

            logger.info(f"Document {document.original_name} processed: {len(chunk_objects)} chunks")

        except Exception as e:
            logger.error(f"Error processing document {document_id}: {e}")
            document.processing_status = "error"
            document.processing_error = str(e)
            await self.db.flush()
            raise
