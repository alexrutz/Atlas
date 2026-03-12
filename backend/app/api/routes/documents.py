"""API-Routen: Dokument-Upload und -Verwaltung."""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.config import settings
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.document import Document
from app.models.collection import Collection
from app.schemas.document import DocumentResponse, DocumentStatusResponse
from app.core.database import async_session

router = APIRouter()


async def process_document_task(document_id: int) -> None:
    """Background-Task: Dokument verarbeiten (Parsing, Chunking, Embedding)."""
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Starte Hintergrund-Verarbeitung für Dokument {document_id}")
    from app.services.document_processor import DocumentProcessor
    async with async_session() as db:
        try:
            processor = DocumentProcessor(db)
            await processor.process(document_id)
            await db.commit()
            logger.info(f"Dokument {document_id} erfolgreich verarbeitet")
        except Exception as e:
            await db.rollback()
            logger.error(f"Fehler bei Verarbeitung von Dokument {document_id}: {e}")


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
    # Prüfe Collection
    result = await db.execute(select(Collection).where(Collection.id == collection_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection nicht gefunden")

    # Prüfe Dateiformat
    suffix = Path(file.filename).suffix.lower()
    if suffix not in settings.documents.supported_formats:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Dateiformat {suffix} wird nicht unterstützt. Erlaubt: {settings.documents.supported_formats}",
        )

    # Datei speichern
    upload_dir = Path(settings.documents.temp_upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{suffix}"
    file_path = upload_dir / filename

    content = await file.read()

    # Prüfe Dateigröße
    if len(content) > settings.documents.max_file_size_mb * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Datei zu groß. Maximum: {settings.documents.max_file_size_mb} MB",
        )

    with open(file_path, "wb") as f:
        f.write(content)

    # Dokument in DB erstellen
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

    await db.flush()

    # Hintergrund-Verarbeitung starten
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

    # Datei vom Dateisystem löschen
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
    )
