"""API-Routen: Systemeinstellungen (z.B. globaler Kontext für Query-Anreicherung)."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.system_setting import SystemSetting

router = APIRouter()

GLOBAL_CONTEXT_KEY = "global_context"


class GlobalContextUpdate(BaseModel):
    context_text: str


class GlobalContextResponse(BaseModel):
    context_text: str


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
