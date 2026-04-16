"""
API routes: Document upload, processing, download, and management.

Upload flow:
  1. User uploads a file via POST /api/collections/{id}/documents
  2. File is saved to disk, a Document record is created in the DB (status: "pending")
  3. A background task is started to process the document:
     a. Status changes to "processing"
     b. File is parsed (docling-serve for rich formats, local for text)
     c. Text is split into chunks
     d. Each chunk is embedded (converted to a vector)
     e. Chunks + embeddings are stored in the DB
     f. Status changes to "completed" (or "error" if something failed)
  4. Frontend polls GET /api/documents/{id}/status to track progress
"""

import io
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db, async_session
from app.config import settings
from app.auth import get_current_user
from app.models import User, Document, Collection
from app.schemas import DocumentResponse, DocumentStatusResponse
from app.document_processing import process_document

logger = logging.getLogger(__name__)

router = APIRouter()


async def _set_document_status(document_id: int, status_val: str, error: str | None = None) -> bool:
    """Update document processing status in its own transaction. Returns True if document was found."""
    try:
        async with async_session() as db:
            result = await db.execute(select(Document).where(Document.id == document_id))
            doc = result.scalar_one_or_none()
            if not doc:
                return False
            doc.processing_status = status_val
            if error is not None:
                doc.processing_error = error
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"Failed to set document {document_id} status to '{status_val}': {e}")
        return False


async def process_document_task(document_id: int) -> None:
    """
    Background task: process a document (parsing, chunking, embedding).

    This runs in the background after the upload response is sent.
    Uses its own database sessions because the request's session is already closed.
    """
    logger.info(f"Starting background processing for document {document_id}")

    if not await _set_document_status(document_id, "processing"):
        logger.error(f"Document {document_id} not found")
        return

    try:
        async with async_session() as db:
            await process_document(db, document_id)
            await db.commit()
            logger.info(f"Document {document_id} processed successfully")
    except Exception as e:
        logger.error(f"Error processing document {document_id}: {e}", exc_info=True)
        await _set_document_status(document_id, "error", str(e))


@router.get("/collections/{collection_id}/documents", response_model=list[DocumentResponse])
async def list_documents(
    collection_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Alle Dokumente einer Collection auflisten."""
    result = await db.execute(
        select(Document)
        .where(Document.collection_id == collection_id)
        .order_by(Document.created_at.desc())
    )
    return result.scalars().all()


@router.post("/collections/{collection_id}/documents", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    collection_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Dokument hochladen und Verarbeitung starten."""
    result = await db.execute(select(Collection).where(Collection.id == collection_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection nicht gefunden")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in settings.documents_supported_formats:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Dateiformat {suffix} wird nicht unterstützt. Erlaubt: {settings.documents_supported_formats}",
        )

    upload_dir = Path(settings.documents_temp_upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{suffix}"
    file_path = upload_dir / filename

    content = await file.read()

    if len(content) > settings.documents_max_file_size_mb * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Datei zu groß. Maximum: {settings.documents_max_file_size_mb} MB",
        )

    with open(file_path, "wb") as f:
        f.write(content)

    document = Document(
        collection_id=collection_id,
        filename=filename,
        original_name=file.filename,
        file_path=str(file_path),
        file_type=suffix,
        file_size_bytes=len(content),
        processing_status="pending",
        uploaded_by=current_user.id,
    )
    db.add(document)
    await db.flush()
    await db.refresh(document)

    background_tasks.add_task(process_document_task, document.id)

    return document


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Dokument löschen (inkl. aller Chunks und Embeddings)."""
    result = await db.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dokument nicht gefunden")

    file_path = Path(document.file_path)
    if file_path.exists():
        file_path.unlink()

    await db.delete(document)


@router.get("/documents/{document_id}/status", response_model=DocumentStatusResponse)
async def get_status(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Verarbeitungsstatus eines Dokuments abfragen."""
    result = await db.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dokument nicht gefunden")

    return DocumentStatusResponse(
        id=document.id,
        processing_status=document.processing_status,
        processing_error=document.processing_error,
        chunk_count=document.chunk_count,
        metadata_=document.metadata_,
    )


@router.get("/documents/{document_id}/download")
async def download_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Dokument-Datei herunterladen."""
    result = await db.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dokument nicht gefunden")

    file_path = Path(document.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Datei nicht gefunden")

    return FileResponse(
        path=str(file_path),
        filename=document.original_name,
        media_type="application/octet-stream",
    )


@router.get("/documents/{document_id}/page-count")
async def get_page_count(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Seitenanzahl eines PDF-Dokuments abfragen."""
    result = await db.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dokument nicht gefunden")

    if document.file_type != ".pdf":
        return {"page_count": 1, "document_id": document_id}

    try:
        from pypdf import PdfReader
        reader = PdfReader(document.file_path)
        return {"page_count": len(reader.pages), "document_id": document_id}
    except Exception:
        return {"page_count": 1, "document_id": document_id}


@router.get("/documents/{document_id}/page/{page_number}")
async def get_document_page(
    document_id: int,
    page_number: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Einzelne Seite eines PDF-Dokuments als PNG-Bild zurückgeben."""
    result = await db.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dokument nicht gefunden")

    file_path = Path(document.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Datei nicht gefunden")

    if document.file_type != ".pdf":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Seitenansicht nur für PDFs verfügbar")

    try:
        from pdf2image import convert_from_path
        images = convert_from_path(
            str(file_path),
            first_page=page_number,
            last_page=page_number,
            dpi=200,
        )
        if not images:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Seite nicht gefunden")

        buf = io.BytesIO()
        images[0].save(buf, format="PNG")
        buf.seek(0)
        return StreamingResponse(buf, media_type="image/png")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Rendern der Seite: {str(e)}",
        )
