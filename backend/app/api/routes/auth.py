"""API-Routen: Authentifizierung."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.core.database import get_db
from app.core.security import verify_password, create_access_token, create_refresh_token, decode_token, hash_password
from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.chat import LoginRequest, TokenResponse, UserBrief

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Benutzer-Login, gibt JWT-Tokens zurück."""
    result = await db.execute(select(User).where(User.username == request.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(request.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Ungültige Anmeldedaten")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Konto deaktiviert")

    return TokenResponse(
        access_token=create_access_token(user.id, user.is_admin),
        refresh_token=create_refresh_token(user.id),
        user=UserBrief(id=user.id, username=user.username, full_name=user.full_name, is_admin=user.is_admin),
    )


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(request: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Erneuert den Access Token mittels Refresh Token."""
    try:
        payload = decode_token(request.refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Ungültiger Token-Typ")
        user_id = int(payload["sub"])
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Ungültiger Refresh Token")

    result = await db.execute(select(User).where(User.id == user_id, User.is_active.is_(True)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Benutzer nicht gefunden")

    return TokenResponse(
        access_token=create_access_token(user.id, user.is_admin),
        refresh_token=create_refresh_token(user.id),
        user=UserBrief(id=user.id, username=user.username, full_name=user.full_name, is_admin=user.is_admin),
    )


@router.get("/me", response_model=UserBrief)
async def get_me(current_user: User = Depends(get_current_user)):
    """Gibt den aktuellen Benutzer zurück."""
    return UserBrief(
        id=current_user.id,
        username=current_user.username,
        full_name=current_user.full_name,
        is_admin=current_user.is_admin,
    )


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


@router.post("/change-password")
async def change_password(
    request: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Passwort ändern."""
    if not verify_password(request.old_password, current_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Altes Passwort ist falsch")

    current_user.hashed_password = hash_password(request.new_password)
    await db.flush()
    return {"message": "Passwort erfolgreich geändert"}
