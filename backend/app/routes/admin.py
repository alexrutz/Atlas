"""
API routes: Admin panel - Users, Groups, Collections, Settings, Docker.

All endpoints here require admin privileges (except collection listing
and global context, which are available to all authenticated users).

Sections:
  - Users: CRUD for user accounts
  - Groups: CRUD for groups + member assignment
  - Collections: CRUD + access control (group permissions)
  - Settings: Global context, prompts, model info
  - Docker: Container/image/volume management
"""

import logging
from pathlib import Path
from typing import Any

import docker
import yaml
from docker.errors import APIError, NotFound
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.auth import get_current_user, require_admin, hash_password
from app.models import (
    User, Group, UserGroup,
    Collection, GroupCollectionAccess, Document,
    SystemSetting,
)
from app.schemas import (
    UserCreate, UserUpdate, UserResponse, UserWithGroups,
    GroupCreate, GroupUpdate, GroupResponse, GroupWithMembers, MemberAssignment,
    CollectionCreate, CollectionUpdate, CollectionResponse,
    CollectionWithAccess, AccessGrant, AccessInfo,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# Users (admin only)
# =============================================================================

@router.get("/users", response_model=list[UserResponse])
async def list_users(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """Alle Benutzer auflisten (Admin)."""
    result = await db.execute(select(User).order_by(User.username))
    return result.scalars().all()


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(data: UserCreate, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """Neuen Benutzer erstellen (Admin)."""
    existing = await db.execute(select(User).where((User.username == data.username) | (User.email == data.email)))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Benutzername oder E-Mail existiert bereits")

    user = User(
        username=data.username,
        email=data.email,
        hashed_password=hash_password(data.password),
        full_name=data.full_name,
        is_admin=data.is_admin,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@router.get("/users/{user_id}", response_model=UserWithGroups)
async def get_user(user_id: int, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """Einzelnen Benutzer mit Gruppen abrufen (Admin)."""
    result = await db.execute(select(User).options(selectinload(User.groups)).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Benutzer nicht gefunden")
    return user


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(user_id: int, data: UserUpdate, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """Benutzer bearbeiten (Admin)."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Benutzer nicht gefunden")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(user, field, value)

    await db.flush()
    await db.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: int, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """Benutzer löschen (Admin)."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Benutzer nicht gefunden")

    if user.id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Sie können sich nicht selbst löschen")

    await db.delete(user)


# =============================================================================
# Groups (admin only)
# =============================================================================

@router.get("/groups", response_model=list[GroupWithMembers])
async def list_groups(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """Alle Gruppen mit Mitgliedern auflisten (Admin)."""
    result = await db.execute(
        select(Group).options(selectinload(Group.members)).order_by(Group.name)
    )
    return result.scalars().unique().all()


@router.post("/groups", response_model=GroupResponse, status_code=status.HTTP_201_CREATED)
async def create_group(data: GroupCreate, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """Neue Gruppe erstellen (Admin)."""
    group = Group(name=data.name, description=data.description)
    db.add(group)
    await db.flush()
    await db.refresh(group)
    return group


@router.get("/groups/{group_id}", response_model=GroupWithMembers)
async def get_group(group_id: int, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """Gruppe mit Mitgliedern abrufen (Admin)."""
    result = await db.execute(select(Group).options(selectinload(Group.members)).where(Group.id == group_id))
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gruppe nicht gefunden")
    return group


@router.put("/groups/{group_id}", response_model=GroupResponse)
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


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(group_id: int, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """Gruppe löschen (Admin)."""
    result = await db.execute(select(Group).where(Group.id == group_id))
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gruppe nicht gefunden")
    await db.delete(group)


@router.post("/groups/{group_id}/members", status_code=status.HTTP_204_NO_CONTENT)
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


@router.delete("/groups/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(group_id: int, user_id: int, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """Mitglied aus Gruppe entfernen (Admin)."""
    result = await db.execute(
        select(UserGroup).where(UserGroup.user_id == user_id, UserGroup.group_id == group_id)
    )
    ug = result.scalar_one_or_none()
    if not ug:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Zuordnung nicht gefunden")
    await db.delete(ug)


# =============================================================================
# Collections
# =============================================================================

@router.get("/collections", response_model=list[CollectionWithAccess])
async def list_accessible_collections(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Alle für den Benutzer zugänglichen Collections auflisten."""
    if current_user.is_admin:
        result = await db.execute(select(Collection).order_by(Collection.name))
        collections = result.scalars().all()
    else:
        result = await db.execute(
            select(Collection)
            .join(GroupCollectionAccess)
            .join(UserGroup, UserGroup.group_id == GroupCollectionAccess.group_id)
            .where(UserGroup.user_id == current_user.id, GroupCollectionAccess.can_read.is_(True))
            .distinct()
            .order_by(Collection.name)
        )
        collections = result.scalars().all()

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


@router.post("/collections", response_model=CollectionResponse, status_code=status.HTTP_201_CREATED)
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


@router.put("/collections/{collection_id}", response_model=CollectionResponse)
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


@router.delete("/collections/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection(
    collection_id: int, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    """Collection löschen (Admin)."""
    result = await db.execute(select(Collection).where(Collection.id == collection_id))
    collection = result.scalar_one_or_none()
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection nicht gefunden")
    await db.delete(collection)


@router.post("/collections/{collection_id}/access", status_code=status.HTTP_204_NO_CONTENT)
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


@router.get("/collections/{collection_id}/access", response_model=list[AccessInfo])
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
        AccessInfo(group_id=access.group_id, group_name=group_name, can_read=access.can_read, can_write=access.can_write)
        for access, group_name in rows
    ]


@router.delete("/collections/{collection_id}/access/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_access(
    collection_id: int, group_id: int,
    admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
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


# =============================================================================
# Settings (global context, prompts, model info)
# =============================================================================

GLOBAL_CONTEXT_KEY = "global_context"
PROMPT_KEYS = {
    "system_prompt": "system_prompt",
    "enrichment_system_prompt": "enrichment_system_prompt",
    "free_chat_system_prompt": "free_chat_system_prompt",
}
CONFIG_PATH = Path("config.yaml")


class GlobalContextUpdate(BaseModel):
    context_text: str


class GlobalContextResponse(BaseModel):
    context_text: str


class ModelConfigResponse(BaseModel):
    llm_model: str
    embedding_model: str


class PromptsResponse(BaseModel):
    system_prompt: str
    enrichment_system_prompt: str
    free_chat_system_prompt: str


class PromptsUpdate(BaseModel):
    system_prompt: str
    enrichment_system_prompt: str
    free_chat_system_prompt: str


@router.get("/settings/global-context", response_model=GlobalContextResponse)
async def get_global_context(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Globalen Kontext-Text für Query-Anreicherung abrufen."""
    result = await db.execute(
        select(SystemSetting).where(SystemSetting.key == GLOBAL_CONTEXT_KEY)
    )
    setting = result.scalar_one_or_none()
    return GlobalContextResponse(context_text=setting.value if setting else "")


@router.put("/settings/global-context", response_model=GlobalContextResponse)
async def update_global_context(
    data: GlobalContextUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Globalen Kontext-Text für Query-Anreicherung setzen."""
    result = await db.execute(
        select(SystemSetting).where(SystemSetting.key == GLOBAL_CONTEXT_KEY)
    )
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = data.context_text
    else:
        db.add(SystemSetting(key=GLOBAL_CONTEXT_KEY, value=data.context_text))
    return GlobalContextResponse(context_text=data.context_text)


@router.get("/settings/models", response_model=ModelConfigResponse)
async def get_model_config(
    current_user: User = Depends(get_current_user),
):
    """Aktuelle LLM- und Embedding-Modell-Konfiguration abrufen."""
    try:
        with open(CONFIG_PATH) as f:
            config = yaml.safe_load(f)
        return ModelConfigResponse(
            llm_model=config.get("llm", {}).get("model", ""),
            embedding_model=config.get("embedding", {}).get("model", ""),
        )
    except Exception as e:
        logger.error(f"Fehler beim Lesen der Konfiguration: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/settings/prompts", response_model=PromptsResponse)
async def get_prompts(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get current prompts. Returns DB overrides if they exist, otherwise config.yaml defaults."""
    prompts = {}
    for key in PROMPT_KEYS:
        result = await db.execute(
            select(SystemSetting).where(SystemSetting.key == f"prompt_{key}")
        )
        setting = result.scalar_one_or_none()
        if setting:
            prompts[key] = setting.value
        else:
            prompts[key] = getattr(settings, f"llm_{key}", "")
    return PromptsResponse(**prompts)


@router.put("/settings/prompts", response_model=PromptsResponse)
async def update_prompts(
    data: PromptsUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update prompts. Saves to DB and updates the running config in-memory."""
    updates = {
        "system_prompt": data.system_prompt,
        "enrichment_system_prompt": data.enrichment_system_prompt,
        "free_chat_system_prompt": data.free_chat_system_prompt,
    }

    for key, value in updates.items():
        db_key = f"prompt_{key}"
        result = await db.execute(
            select(SystemSetting).where(SystemSetting.key == db_key)
        )
        setting = result.scalar_one_or_none()
        if setting:
            setting.value = value
        else:
            db.add(SystemSetting(key=db_key, value=value))

        setattr(settings, f"llm_{key}", value)

    return PromptsResponse(**updates)


# =============================================================================
# Docker management (admin only)
# =============================================================================

COMPOSE_CONTAINER_NAMES = {
    "atlas-postgres",
    "atlas-vllm-llm",
    "atlas-vllm-embed",
    "atlas-docling-serve",
    "atlas-backend",
    "atlas-llm-diagnostic",
    "atlas-frontend",
}


def get_docker_client():
    """Docker-Client erstellen."""
    try:
        return docker.from_env()
    except Exception as e:
        logger.error(f"Docker-Verbindung fehlgeschlagen: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Docker-Daemon nicht erreichbar.",
        )


class ContainerInfo(BaseModel):
    id: str
    name: str
    image: str
    status: str
    state: str
    ports: dict[str, Any] = {}
    created: str


class ImageInfo(BaseModel):
    id: str
    tags: list[str]
    size: int
    created: str


class VolumeInfo(BaseModel):
    name: str
    driver: str
    mountpoint: str
    created: str | None = None


class BulkActionRequest(BaseModel):
    ids: list[str]


class BulkActionResponse(BaseModel):
    results: list[dict[str, str]]


@router.get("/docker/containers", response_model=list[ContainerInfo])
async def list_containers(current_user: User = Depends(require_admin)):
    """Alle Docker-Container auflisten."""
    client = get_docker_client()

    containers = []
    for c in client.containers.list(all=True):
        if c.name not in COMPOSE_CONTAINER_NAMES:
            continue
        ports = {}
        if c.attrs.get("NetworkSettings", {}).get("Ports"):
            for port, bindings in c.attrs["NetworkSettings"]["Ports"].items():
                if bindings:
                    ports[port] = [{"HostIp": b.get("HostIp", ""), "HostPort": b.get("HostPort", "")} for b in bindings]

        containers.append(ContainerInfo(
            id=c.short_id,
            name=c.name,
            image=",".join(c.image.tags) if c.image.tags else c.attrs.get("Config", {}).get("Image", "unknown"),
            status=c.status,
            state=c.attrs.get("State", {}).get("Status", "unknown"),
            ports=ports,
            created=c.attrs.get("Created", ""),
        ))

    client.close()
    return containers


@router.post("/docker/containers/restart", response_model=BulkActionResponse)
async def restart_containers(
    data: BulkActionRequest,
    current_user: User = Depends(require_admin),
):
    """Einen oder mehrere Container neustarten."""
    client = get_docker_client()
    results = []

    for container_id in data.ids:
        try:
            container = client.containers.get(container_id)
            container.restart(timeout=30)
            results.append({"id": container_id, "status": "success", "message": f"{container.name} neugestartet"})
            logger.info(f"Container {container.name} neugestartet von {current_user.username}")
        except NotFound:
            results.append({"id": container_id, "status": "error", "message": "Container nicht gefunden"})
        except APIError as e:
            results.append({"id": container_id, "status": "error", "message": str(e)})

    client.close()
    return BulkActionResponse(results=results)


@router.get("/docker/images", response_model=list[ImageInfo])
async def list_images(current_user: User = Depends(require_admin)):
    """Alle Docker-Images auflisten."""
    client = get_docker_client()

    compose_image_ids = set()
    for c in client.containers.list(all=True):
        if c.name in COMPOSE_CONTAINER_NAMES:
            compose_image_ids.add(c.image.id)

    images = []
    for img in client.images.list():
        if img.id not in compose_image_ids:
            continue
        images.append(ImageInfo(
            id=img.short_id.replace("sha256:", ""),
            tags=img.tags or [],
            size=img.attrs.get("Size", 0),
            created=img.attrs.get("Created", ""),
        ))

    client.close()
    return images


@router.post("/docker/images/rebuild", response_model=BulkActionResponse)
async def rebuild_images(
    data: BulkActionRequest,
    current_user: User = Depends(require_admin),
):
    """Images neu bauen und zugehörige Container neustarten."""
    client = get_docker_client()
    results = []

    for image_id in data.ids:
        try:
            img = client.images.get(image_id)
            tag = img.tags[0] if img.tags else None

            if not tag:
                results.append({"id": image_id, "status": "error", "message": "Image hat keinen Tag"})
                continue

            related_containers = [
                c for c in client.containers.list(all=True)
                if c.image.id == img.id
            ]

            try:
                client.images.pull(tag)
                results.append({"id": image_id, "status": "success", "message": f"{tag} aktualisiert"})
            except APIError:
                results.append({"id": image_id, "status": "info", "message": f"{tag} ist ein lokales Image"})

            for container in related_containers:
                try:
                    container.restart(timeout=30)
                    logger.info(f"Container {container.name} nach Image-Rebuild neugestartet")
                except APIError as e:
                    logger.warning(f"Container {container.name} konnte nicht neugestartet werden: {e}")

        except NotFound:
            results.append({"id": image_id, "status": "error", "message": "Image nicht gefunden"})
        except APIError as e:
            results.append({"id": image_id, "status": "error", "message": str(e)})

    client.close()
    return BulkActionResponse(results=results)


@router.get("/docker/volumes", response_model=list[VolumeInfo])
async def list_volumes(current_user: User = Depends(require_admin)):
    """Alle Docker-Volumes auflisten."""
    client = get_docker_client()

    volumes = []
    for vol in client.volumes.list():
        labels = vol.attrs.get("Labels") or {}
        if "atlas" not in vol.name.lower() and labels.get("com.docker.compose.project", "") != "atlas":
            continue
        volumes.append(VolumeInfo(
            name=vol.name,
            driver=vol.attrs.get("Driver", "local"),
            mountpoint=vol.attrs.get("Mountpoint", ""),
            created=vol.attrs.get("CreatedAt"),
        ))

    client.close()
    return volumes


@router.post("/docker/volumes/delete", response_model=BulkActionResponse)
async def delete_volumes(
    data: BulkActionRequest,
    current_user: User = Depends(require_admin),
):
    """Einen oder mehrere Volumes löschen."""
    client = get_docker_client()
    results = []

    for volume_name in data.ids:
        try:
            vol = client.volumes.get(volume_name)
            vol.remove(force=True)
            results.append({"id": volume_name, "status": "success", "message": f"Volume {volume_name} gelöscht"})
            logger.info(f"Volume {volume_name} gelöscht von {current_user.username}")
        except NotFound:
            results.append({"id": volume_name, "status": "error", "message": "Volume nicht gefunden"})
        except APIError as e:
            results.append({"id": volume_name, "status": "error", "message": str(e)})

    client.close()
    return BulkActionResponse(results=results)
