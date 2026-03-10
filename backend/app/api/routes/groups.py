"""API-Routen: Gruppenverwaltung (Admin)."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.dependencies import require_admin
from app.models.user import User
from app.models.group import Group, UserGroup
from app.schemas.group import GroupCreate, GroupUpdate, GroupResponse, GroupWithMembers, MemberAssignment

router = APIRouter()


@router.get("", response_model=list[GroupResponse])
async def list_groups(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """Alle Gruppen auflisten (Admin)."""
    result = await db.execute(select(Group).order_by(Group.name))
    return result.scalars().all()


@router.post("", response_model=GroupResponse, status_code=status.HTTP_201_CREATED)
async def create_group(data: GroupCreate, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """Neue Gruppe erstellen (Admin)."""
    group = Group(name=data.name, description=data.description)
    db.add(group)
    await db.flush()
    await db.refresh(group)
    return group


@router.get("/{group_id}", response_model=GroupWithMembers)
async def get_group(group_id: int, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """Gruppe mit Mitgliedern abrufen (Admin)."""
    result = await db.execute(select(Group).options(selectinload(Group.members)).where(Group.id == group_id))
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gruppe nicht gefunden")
    return group


@router.put("/{group_id}", response_model=GroupResponse)
async def update_group(group_id: int, data: GroupUpdate, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """Gruppe bearbeiten (Admin)."""
    result = await db.execute(select(Group).where(Group.id == group_id))
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gruppe nicht gefunden")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(group, field, value)

    await db.flush()
    await db.refresh(group)
    return group


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(group_id: int, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """Gruppe löschen (Admin)."""
    result = await db.execute(select(Group).where(Group.id == group_id))
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gruppe nicht gefunden")
    await db.delete(group)


@router.post("/{group_id}/members", status_code=status.HTTP_204_NO_CONTENT)
async def assign_members(group_id: int, data: MemberAssignment, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """Mitglieder zu einer Gruppe zuordnen (Admin)."""
    result = await db.execute(select(Group).where(Group.id == group_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gruppe nicht gefunden")

    for user_id in data.user_ids:
        existing = await db.execute(
            select(UserGroup).where(UserGroup.user_id == user_id, UserGroup.group_id == group_id)
        )
        if not existing.scalar_one_or_none():
            db.add(UserGroup(user_id=user_id, group_id=group_id))


@router.delete("/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(group_id: int, user_id: int, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """Mitglied aus Gruppe entfernen (Admin)."""
    result = await db.execute(
        select(UserGroup).where(UserGroup.user_id == user_id, UserGroup.group_id == group_id)
    )
    ug = result.scalar_one_or_none()
    if not ug:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Zuordnung nicht gefunden")
    await db.delete(ug)
