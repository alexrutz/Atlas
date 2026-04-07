"""
Document Processor - Turns uploaded files into searchable chunks.

When a user uploads a document, this is what happens:
  1. The file is parsed + chunked by docling-serve via
     /v1/chunk/hybrid/file/async
  2. Each chunk is embedded (converted to a vector of numbers)
  3. Chunks + embeddings are stored in the database
  4. The document status is updated to "completed"

If anything fails, the document status is set to "error" with the error message.

Functions:
    process_document(db, document_id) - Full processing pipeline for one document
"""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.models.document import Document
from app.models.chunk import Chunk, ChunkEmbedding
from app.services.embedding_service import embed_batch
from app.utils.file_parsers import parse_document

logger = logging.getLogger(__name__)


async def process_document(db: AsyncSession, document_id: int) -> None:
    """
    Full document processing pipeline.

    Flow:
    1. Load document from DB
    2. Parse + chunk the file via docling-serve async hybrid endpoint
    3. Compute embedding for each chunk
    4. Store chunks + embeddings
    5. Store document-level metadata (stats, timings)
    6. Update document status
    """
    result = await db.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()
    if not document:
        logger.error(f"Document {document_id} not found")
        return

    try:
        logger.info(f"Parsing document via docling async hybrid endpoint: {document.original_name}")
        parsed = await asyncio.to_thread(parse_document, document.file_path, document.file_type)

        chunks = parsed.chunks
        chunker_type = "docling-hybrid-async"

        # Prepare chunks and texts for embedding
        logger.info(f"Processing {len(chunks)} chunks")
        chunk_texts = []
        chunk_objects = []

        for i, chunk_data in enumerate(chunks):
            # Use contextualized text for embedding if available.
            # Contextualized text includes the section heading prepended to the chunk,
            # which helps the embedding model understand what the chunk is about.
            embed_text = chunk_data.contextualized_text or chunk_data.text
            chunk_texts.append(embed_text)

            # Build chunk metadata
            chunk_meta = {
                "parser": parsed.metadata.get("parser", "docling-hybrid-async"),
                "chunker": chunker_type,
            }
            if chunk_data.contextualized_text:
                chunk_meta["has_context"] = True
            if chunk_data.labels:
                chunk_meta["labels"] = chunk_data.labels

            chunk_obj = Chunk(
                document_id=document.id,
                chunk_index=i,
                content=chunk_data.text,
                section_header=chunk_data.section_header,
                page_number=chunk_data.page_number,
                token_count=chunk_data.token_count,
                metadata_=chunk_meta,
            )
            chunk_objects.append(chunk_obj)
            db.add(chunk_obj)

        await db.flush()

        # Compute batch embeddings
        logger.info(f"Computing embeddings for {len(chunk_texts)} chunks")
        embeddings = await embed_batch(chunk_texts)

        # Store embeddings
        for chunk_obj, embedding in zip(chunk_objects, embeddings):
            emb_obj = ChunkEmbedding(
                chunk_id=chunk_obj.id,
                model_name=settings.embedding_model,
                embedding=embedding,
            )
            db.add(emb_obj)

        # Store document-level metadata (stats, parse info)
        doc_meta = dict(parsed.metadata)
        if parsed.stats:
            doc_meta["stats"] = {
                "num_pages": parsed.stats.num_pages,
                "num_tables": parsed.stats.num_tables,
                "num_figures": parsed.stats.num_figures,
                "num_headings": parsed.stats.num_headings,
                "num_text_elements": parsed.stats.num_text_elements,
                "num_list_items": parsed.stats.num_list_items,
                "num_code_blocks": parsed.stats.num_code_blocks,
            }
        document.metadata_ = doc_meta

        # Update document status
        document.processing_status = "completed"
        document.chunk_count = len(chunk_objects)
        await db.flush()

        logger.info(
            f"Document {document.original_name} processed: "
            f"{len(chunk_objects)} chunks, parser={parsed.metadata.get('parser', 'docling-hybrid-async')}"
        )

    except Exception as e:
        logger.error(f"Error processing document {document_id}: {e}")
        document.processing_status = "error"
        document.processing_error = str(e)
        await db.flush()
        raise
