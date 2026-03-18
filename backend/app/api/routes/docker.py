"""API-Routen: Docker-Verwaltung (Container, Images, Volumes)."""

import logging
from typing import Any

import docker
from docker.errors import APIError, NotFound
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.dependencies import get_current_user
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()

# Container names defined in docker-compose.yml
COMPOSE_CONTAINER_NAMES = {
    "atlas-postgres",
    "atlas-llama-cpp",
    "atlas-llama-cpp-embed",
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


def require_admin(user: User):
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Nur Admins können Docker verwalten.",
        )


# --- Response Models ---

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


# --- Containers ---

@router.get("/containers", response_model=list[ContainerInfo])
async def list_containers(current_user: User = Depends(get_current_user)):
    """Alle Docker-Container auflisten."""
    require_admin(current_user)
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


@router.post("/containers/restart", response_model=BulkActionResponse)
async def restart_containers(
    data: BulkActionRequest,
    current_user: User = Depends(get_current_user),
):
    """Einen oder mehrere Container neustarten."""
    require_admin(current_user)
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


# --- Images ---

@router.get("/images", response_model=list[ImageInfo])
async def list_images(current_user: User = Depends(get_current_user)):
    """Alle Docker-Images auflisten."""
    require_admin(current_user)
    client = get_docker_client()

    # Collect image IDs used by compose containers
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


@router.post("/images/rebuild", response_model=BulkActionResponse)
async def rebuild_images(
    data: BulkActionRequest,
    current_user: User = Depends(get_current_user),
):
    """Images neu bauen und zugehörige Container neustarten."""
    require_admin(current_user)
    client = get_docker_client()
    results = []

    for image_id in data.ids:
        try:
            img = client.images.get(image_id)
            tag = img.tags[0] if img.tags else None

            if not tag:
                results.append({"id": image_id, "status": "error", "message": "Image hat keinen Tag"})
                continue

            # Find containers using this image and restart them
            related_containers = [
                c for c in client.containers.list(all=True)
                if c.image.id == img.id
            ]

            # Try to pull if it's a remote image, or rebuild if local
            try:
                client.images.pull(tag)
                results.append({"id": image_id, "status": "success", "message": f"{tag} aktualisiert"})
            except APIError:
                results.append({"id": image_id, "status": "info", "message": f"{tag} ist ein lokales Image"})

            # Restart related containers
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


# --- Volumes ---

@router.get("/volumes", response_model=list[VolumeInfo])
async def list_volumes(current_user: User = Depends(get_current_user)):
    """Alle Docker-Volumes auflisten."""
    require_admin(current_user)
    client = get_docker_client()

    volumes = []
    for vol in client.volumes.list():
        # Only show volumes belonging to the Atlas compose project
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


@router.post("/volumes/delete", response_model=BulkActionResponse)
async def delete_volumes(
    data: BulkActionRequest,
    current_user: User = Depends(get_current_user),
):
    """Einen oder mehrere Volumes löschen."""
    require_admin(current_user)
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
