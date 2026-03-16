"""API-Routen: Systemeinstellungen (z.B. globaler Kontext für Query-Anreicherung)."""

import asyncio
import logging
import os
import subprocess
from pathlib import Path

import docker
import httpx
import yaml
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.system_setting import SystemSetting
from app.core.security import decode_token

logger = logging.getLogger(__name__)

router = APIRouter()

GLOBAL_CONTEXT_KEY = "global_context"
CONFIG_PATH = Path("config.yaml")


class GlobalContextUpdate(BaseModel):
    context_text: str


class GlobalContextResponse(BaseModel):
    context_text: str


class ModelConfigResponse(BaseModel):
    llm_model: str
    embedding_model: str
    llm_enable_thinking: bool


class ModelConfigUpdate(BaseModel):
    llm_model: str | None = None
    embedding_model: str | None = None
    llm_enable_thinking: bool | None = None


class OllamaModel(BaseModel):
    name: str
    size: int | None = None
    parameter_size: str | None = None


class AvailableModelsResponse(BaseModel):
    models: list[OllamaModel]


class DockerContainer(BaseModel):
    id: str
    name: str
    image: str
    status: str


class DockerImage(BaseModel):
    id: str
    tags: list[str]


class DockerVolume(BaseModel):
    name: str


class DockerResourcesResponse(BaseModel):
    containers: list[DockerContainer]
    images: list[DockerImage]
    volumes: list[DockerVolume]


class DockerActionRequest(BaseModel):
    container_ids: list[str] = Field(default_factory=list)
    image_ids: list[str] = Field(default_factory=list)
    volume_names: list[str] = Field(default_factory=list)
    stop_containers: bool = False
    restart_containers: bool = False
    remove_containers: bool = False
    remove_images: bool = False
    rebuild_images: bool = False
    remove_volumes: bool = False


class DockerActionResponse(BaseModel):
    messages: list[str]


class RepoUpdateResponse(BaseModel):
    started: bool
    message: str


def _get_docker_client() -> docker.DockerClient:
    try:
        return docker.from_env()
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Docker-Verbindung fehlgeschlagen: {exc}") from exc


def _ensure_admin(current_user: User):
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Nur Admins erlaubt.")


def _compose_project_path() -> Path:
    return Path(os.environ.get("ATLAS_PROJECT_PATH", "/workspace/Atlas"))


@router.get("/global-context", response_model=GlobalContextResponse)
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


@router.put("/global-context", response_model=GlobalContextResponse)
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


@router.get("/models", response_model=ModelConfigResponse)
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
            llm_enable_thinking=config.get("llm", {}).get("enable_thinking", False),
        )
    except Exception as e:
        logger.error(f"Fehler beim Lesen der Konfiguration: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.put("/models", response_model=ModelConfigResponse)
async def update_model_config(
    data: ModelConfigUpdate,
    current_user: User = Depends(get_current_user),
):
    """LLM- und/oder Embedding-Modell in config.yaml ändern. Erfordert Admin-Rechte."""
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Nur Admins können Modelle ändern.")

    try:
        with open(CONFIG_PATH) as f:
            raw_content = f.read()
            config = yaml.safe_load(raw_content)

        if data.llm_model:
            config.setdefault("llm", {})["model"] = data.llm_model
        if data.embedding_model:
            config.setdefault("embedding", {})["model"] = data.embedding_model
        if data.llm_enable_thinking is not None:
            config.setdefault("llm", {})["enable_thinking"] = data.llm_enable_thinking

        with open(CONFIG_PATH, "w") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        # Update the in-memory settings
        from app.core.config import settings
        if data.llm_model:
            settings.llm.model = data.llm_model
        if data.embedding_model:
            settings.embedding.model = data.embedding_model
        if data.llm_enable_thinking is not None:
            settings.llm.enable_thinking = data.llm_enable_thinking

        return ModelConfigResponse(
            llm_model=config["llm"]["model"],
            embedding_model=config["embedding"]["model"],
            llm_enable_thinking=config.get("llm", {}).get("enable_thinking", False),
        )
    except Exception as e:
        logger.error(f"Fehler beim Aktualisieren der Modell-Konfiguration: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/models/available", response_model=AvailableModelsResponse)
async def list_available_models(
    current_user: User = Depends(get_current_user),
):
    """Verfügbare Modelle vom Ollama-Server abrufen."""
    try:
        with open(CONFIG_PATH) as f:
            config = yaml.safe_load(f)
        ollama_url = config.get("llm", {}).get("base_url", "http://ollama:11434")

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{ollama_url}/api/tags")
            response.raise_for_status()
            data = response.json()

        models = []
        for m in data.get("models", []):
            models.append(OllamaModel(
                name=m.get("name", ""),
                size=m.get("size"),
                parameter_size=m.get("details", {}).get("parameter_size"),
            ))
        return AvailableModelsResponse(models=models)
    except httpx.ConnectError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ollama-Server nicht erreichbar.",
        )
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Ollama-Modelle: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/docker/resources", response_model=DockerResourcesResponse)
async def list_docker_resources(current_user: User = Depends(get_current_user)):
    _ensure_admin(current_user)
    client = _get_docker_client()

    containers = [
        DockerContainer(
            id=c.id,
            name=(c.name or c.id[:12]),
            image=(c.image.tags[0] if c.image.tags else c.image.short_id),
            status=c.status,
        )
        for c in client.containers.list(all=True)
    ]
    images = [
        DockerImage(id=i.id, tags=i.tags or [i.short_id])
        for i in client.images.list()
    ]
    volumes = [DockerVolume(name=v.name) for v in client.volumes.list()]
    return DockerResourcesResponse(containers=containers, images=images, volumes=volumes)


@router.post("/docker/actions", response_model=DockerActionResponse)
async def run_docker_actions(data: DockerActionRequest, current_user: User = Depends(get_current_user)):
    _ensure_admin(current_user)
    client = _get_docker_client()
    messages: list[str] = []

    for container_id in data.container_ids:
        try:
            container = client.containers.get(container_id)
            if data.stop_containers:
                container.stop(timeout=10)
                messages.append(f"Container gestoppt: {container.name}")
            if data.restart_containers:
                container.restart(timeout=10)
                messages.append(f"Container neu gestartet: {container.name}")
            if data.remove_containers:
                container.remove(force=True)
                messages.append(f"Container entfernt: {container.name}")
        except Exception as exc:
            messages.append(f"Container-Aktion fehlgeschlagen ({container_id[:12]}): {exc}")

    for image_id in data.image_ids:
        try:
            image = client.images.get(image_id)
            tag = image.tags[0] if image.tags else image_id
            if data.remove_images:
                client.images.remove(image=image.id, force=True)
                messages.append(f"Image entfernt: {tag}")
            if data.rebuild_images and tag and ":" in tag:
                project_path = _compose_project_path()
                service_name = tag.split(":")[0].split("/")[-1].replace("atlas-", "")
                result = subprocess.run(
                    ["docker", "compose", "build", service_name],
                    cwd=project_path,
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    messages.append(f"Image neu gebaut für Service: {service_name}")
                else:
                    messages.append(f"Image-Rebuild fehlgeschlagen ({service_name}): {result.stderr.strip() or result.stdout.strip()}")
        except Exception as exc:
            messages.append(f"Image-Aktion fehlgeschlagen ({image_id[:12]}): {exc}")

    if data.remove_volumes:
        for volume_name in data.volume_names:
            try:
                volume = client.volumes.get(volume_name)
                volume.remove(force=True)
                messages.append(f"Volume entfernt: {volume_name}")
            except Exception as exc:
                messages.append(f"Volume konnte nicht entfernt werden ({volume_name}): {exc}")

    return DockerActionResponse(messages=messages or ["Keine Aktion ausgeführt."])


@router.post("/repo/update", response_model=RepoUpdateResponse)
async def trigger_repo_update(current_user: User = Depends(get_current_user)):
    _ensure_admin(current_user)

    project_path = _compose_project_path()
    parent_path = project_path.parent
    refresh_script = Path("/tmp/atlas_repo_refresh.sh")

    origin_url = ""
    try:
        origin_url = subprocess.check_output(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=project_path,
            text=True,
        ).strip()
    except Exception:
        pass

    if not origin_url:
        raise HTTPException(status_code=500, detail="Konnte remote.origin.url nicht bestimmen.")

    refresh_script.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
cd {parent_path}
rm -rf Atlas
git clone {origin_url} Atlas
cd Atlas
bash scripts/setup.sh
"""
    )
    os.chmod(refresh_script, 0o755)

    subprocess.Popen(
        ["nohup", "bash", str(refresh_script)],
        stdout=open("/tmp/atlas_repo_refresh.log", "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    return RepoUpdateResponse(started=True, message="Repo-Update gestartet. Siehe /tmp/atlas_repo_refresh.log")


@router.get("/docker/logs/stream")
async def stream_container_logs(
    container_id: str = Query(..., description="Container-ID oder Name"),
    tail: int = Query(100, ge=1, le=1000),
    token: str = Query(..., description="JWT Access Token"),
):
    try:
        payload = decode_token(token)
        if not payload.get("is_admin", False):
            raise ValueError("Kein Admin-Token")
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Ungültiger Token: {exc}") from exc

    client = _get_docker_client()

    try:
        container = client.containers.get(container_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Container nicht gefunden: {exc}") from exc

    async def event_stream():
        yield f"data: Verbunden mit Logs von {container.name}\n\n"
        loop = asyncio.get_event_loop()

        def _log_iter():
            return container.logs(stream=True, follow=True, tail=tail)

        log_iter = await loop.run_in_executor(None, _log_iter)

        for raw in log_iter:
            line = raw.decode("utf-8", errors="ignore").rstrip()
            if line:
                safe_line = line.replace("\n", " ")
                yield f"data: {safe_line}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
