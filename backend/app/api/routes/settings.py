"""API-Routen: Systemeinstellungen."""

import logging
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_admin
from app.core.config import settings
from app.models.user import User
from app.models.system_setting import SystemSetting

logger = logging.getLogger(__name__)

router = APIRouter()

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


# --- Prompts Management ---

class PromptsResponse(BaseModel):
    system_prompt: str
    enrichment_system_prompt: str
    free_chat_system_prompt: str


class PromptsUpdate(BaseModel):
    system_prompt: str
    enrichment_system_prompt: str
    free_chat_system_prompt: str


@router.get("/prompts", response_model=PromptsResponse)
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
            prompts[key] = getattr(settings.llm, key, "")
    return PromptsResponse(**prompts)


@router.put("/prompts", response_model=PromptsResponse)
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

        # Update in-memory config so changes take effect immediately
        setattr(settings.llm, key, value)

    return PromptsResponse(**updates)
