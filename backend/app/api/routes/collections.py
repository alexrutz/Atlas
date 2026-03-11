"""API-Routen: Collections und Zugriffsrechte."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_admin
from app.models.user import User
from app.models.collection import Collection, GroupCollectionAccess
from app.models.document import Document
from app.models.group import Group, UserGroup
from app.schemas.collection import (
    CollectionCreate, CollectionUpdate, CollectionResponse,
    CollectionWithAccess, AccessGrant, AccessInfo,
    GlossaryEntryCreate, GlossaryEntryResponse,
)
from app.models.chunk import GlossaryEntry

router = APIRouter()


@router.get("", response_model=list[CollectionWithAccess])
async def list_accessible_collections(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Alle für den Benutzer zugänglichen Collections auflisten."""
    if current_user.is_admin:
        # Admins sehen alle Collections
        result = await db.execute(select(Collection).order_by(Collection.name))
        collections = result.scalars().all()
    else:
        # Normale Benutzer: nur Collections über Gruppenzugehörigkeit
        result = await db.execute(
            select(Collection)
            .join(GroupCollectionAccess)
            .join(UserGroup, UserGroup.group_id == GroupCollectionAccess.group_id)
            .where(UserGroup.user_id == current_user.id, GroupCollectionAccess.can_read.is_(True))
            .distinct()
            .order_by(Collection.name)
        )
        collections = result.scalars().all()

    # Dokumentenanzahl pro Collection
    response = []
    for col in collections:
        count_result = await db.execute(
            select(func.count()).select_from(Document).where(Document.collection_id == col.id)
        )
        doc_count = count_result.scalar() or 0
        response.append(CollectionWithAccess(
            id=col.id, name=col.name, description=col.description,
            created_at=col.created_at, document_count=doc_count,
            can_read=True, can_write=current_user.is_admin,
        ))

    return response


@router.post("", response_model=CollectionResponse, status_code=status.HTTP_201_CREATED)
async def create_collection(
    data: CollectionCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Neue Collection erstellen (Admin)."""
    collection = Collection(name=data.name, description=data.description, created_by=admin.id)
    db.add(collection)
    await db.flush()
    await db.refresh(collection)
    return collection


@router.put("/{collection_id}", response_model=CollectionResponse)
async def update_collection(
    collection_id: int, data: CollectionUpdate,
    admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    """Collection bearbeiten (Admin)."""
    result = await db.execute(select(Collection).where(Collection.id == collection_id))
    collection = result.scalar_one_or_none()
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection nicht gefunden")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(collection, field, value)

    await db.flush()
    await db.refresh(collection)
    return collection


@router.delete("/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection(
    collection_id: int, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    """Collection löschen (Admin)."""
    result = await db.execute(select(Collection).where(Collection.id == collection_id))
    collection = result.scalar_one_or_none()
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection nicht gefunden")
    await db.delete(collection)


@router.post("/{collection_id}/access", status_code=status.HTTP_204_NO_CONTENT)
async def set_access(
    collection_id: int, data: AccessGrant,
    admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    """Gruppenzugriff auf eine Collection setzen (Admin)."""
    existing = await db.execute(
        select(GroupCollectionAccess).where(
            GroupCollectionAccess.group_id == data.group_id,
            GroupCollectionAccess.collection_id == collection_id,
        )
    )
    access = existing.scalar_one_or_none()
    if access:
        access.can_read = data.can_read
        access.can_write = data.can_write
    else:
        db.add(GroupCollectionAccess(
            group_id=data.group_id, collection_id=collection_id,
            can_read=data.can_read, can_write=data.can_write, granted_by=admin.id,
        ))


@router.get("/{collection_id}/access", response_model=list[AccessInfo])
async def list_access(
    collection_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Alle Gruppenzugriffe einer Collection auflisten (Admin)."""
    result = await db.execute(
        select(GroupCollectionAccess, Group.name)
        .join(Group, Group.id == GroupCollectionAccess.group_id)
        .where(GroupCollectionAccess.collection_id == collection_id)
        .order_by(Group.name)
    )
    rows = result.all()
    return [
        AccessInfo(
            group_id=access.group_id,
            group_name=group_name,
            can_read=access.can_read,
            can_write=access.can_write,
        )
        for access, group_name in rows
    ]


@router.delete("/{collection_id}/access/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_access(
    collection_id: int,
    group_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Gruppenzugriff auf eine Collection entfernen (Admin)."""
    result = await db.execute(
        select(GroupCollectionAccess).where(
            GroupCollectionAccess.group_id == group_id,
            GroupCollectionAccess.collection_id == collection_id,
        )
    )
    access = result.scalar_one_or_none()
    if not access:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Zugriff nicht gefunden")
    await db.delete(access)


# --- Glossar ---

@router.get("/{collection_id}/glossary", response_model=list[GlossaryEntryResponse])
async def list_glossary(
    collection_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Glossar einer Collection abrufen."""
    result = await db.execute(
        select(GlossaryEntry)
        .where(GlossaryEntry.collection_id == collection_id)
        .order_by(GlossaryEntry.term)
    )
    return result.scalars().all()


@router.post("/{collection_id}/glossary", response_model=GlossaryEntryResponse, status_code=status.HTTP_201_CREATED)
async def add_glossary_entry(
    collection_id: int, data: GlossaryEntryCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Glossar-Eintrag hinzufügen."""
    entry = GlossaryEntry(
        collection_id=collection_id, term=data.term,
        definition=data.definition, abbreviation=data.abbreviation,
        created_by=current_user.id,
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry)
    return entry


@router.put("/{collection_id}/glossary/{entry_id}", response_model=GlossaryEntryResponse)
async def update_glossary_entry(
    collection_id: int,
    entry_id: int,
    data: GlossaryEntryCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Glossar-Eintrag bearbeiten."""
    result = await db.execute(
        select(GlossaryEntry).where(
            GlossaryEntry.id == entry_id,
            GlossaryEntry.collection_id == collection_id,
        )
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Glossar-Eintrag nicht gefunden")

    entry.term = data.term
    entry.definition = data.definition
    entry.abbreviation = data.abbreviation
    await db.flush()
    await db.refresh(entry)
    return entry


@router.delete("/{collection_id}/glossary/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_glossary_entry(
    collection_id: int,
    entry_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Glossar-Eintrag löschen."""
    result = await db.execute(
        select(GlossaryEntry).where(
            GlossaryEntry.id == entry_id,
            GlossaryEntry.collection_id == collection_id,
        )
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Glossar-Eintrag nicht gefunden")
    await db.delete(entry)


@router.post("/{collection_id}/glossary/auto-extract", response_model=list[GlossaryEntryResponse])
async def auto_extract_glossary(
    collection_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Automatische Glossar-Extraktion aus allen Dokumenten einer Collection."""
    from app.services.context_enrichment import ContextEnrichmentService

    # Dokumente der Collection laden
    result = await db.execute(
        select(Document).where(
            Document.collection_id == collection_id,
            Document.processing_status == "completed",
        )
    )
    documents = result.scalars().all()
    if not documents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Keine verarbeiteten Dokumente in dieser Collection",
        )

    # Text aus allen Dokumenten sammeln (begrenzt)
    from app.utils.file_parsers import parse_document
    combined_text = ""
    for doc in documents[:5]:  # Maximal 5 Dokumente
        try:
            parsed = parse_document(doc.file_path, doc.file_type)
            combined_text += parsed.text[:2000] + "\n\n"
        except Exception:
            continue

    if not combined_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Kein Text aus Dokumenten extrahierbar",
        )

    enrichment = ContextEnrichmentService()
    extracted = await enrichment.auto_extract_glossary(combined_text)

    new_entries = []
    for term, definition in extracted.items():
        # Prüfe ob bereits existiert
        existing = await db.execute(
            select(GlossaryEntry).where(
                GlossaryEntry.collection_id == collection_id,
                GlossaryEntry.term == term,
            )
        )
        if existing.scalar_one_or_none():
            continue

        entry = GlossaryEntry(
            collection_id=collection_id,
            term=term,
            definition=definition,
            created_by=current_user.id,
        )
        db.add(entry)
        await db.flush()
        await db.refresh(entry)
        new_entries.append(entry)

    return new_entries
