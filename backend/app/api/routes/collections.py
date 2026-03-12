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
)

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
            context_text=col.context_text,
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
