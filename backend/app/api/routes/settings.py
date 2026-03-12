"""API-Routen: Systemeinstellungen (z.B. globaler Kontext für Query-Anreicherung)."""

import logging
from pathlib import Path

import httpx
import yaml
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.system_setting import SystemSetting

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


class ModelConfigUpdate(BaseModel):
    llm_model: str | None = None
    embedding_model: str | None = None


class OllamaModel(BaseModel):
    name: str
    size: int | None = None
    parameter_size: str | None = None


class AvailableModelsResponse(BaseModel):
    models: list[OllamaModel]


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

        with open(CONFIG_PATH, "w") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        # Update the in-memory settings
        from app.core.config import settings
        if data.llm_model:
            settings.llm.model = data.llm_model
        if data.embedding_model:
            settings.embedding.model = data.embedding_model

        return ModelConfigResponse(
            llm_model=config["llm"]["model"],
            embedding_model=config["embedding"]["model"],
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
