"""
FastAPI Dependencies: Authentication and authorization.

These are "dependency injection" functions used by FastAPI routes.
They run BEFORE the route handler and provide the authenticated user.

How JWT auth works:
  1. User logs in via /api/auth/login → gets an access token (JWT)
  2. Frontend sends the token in the "Authorization: Bearer <token>" header
  3. get_current_user() decodes the token, finds the user in the DB
  4. If the token is invalid or expired, the request is rejected (401)

Usage in a route:
    @router.get("/protected")
    async def protected_route(user: User = Depends(get_current_user)):
        # 'user' is the authenticated User object from the database
        ...
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import jwt

from app.core.database import get_db
from app.core.config import settings
from app.models.user import User

# HTTPBearer tells FastAPI to look for "Authorization: Bearer <token>" in the request
security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Decode the JWT token from the request and return the authenticated user.
    Raises 401 if the token is invalid, expired, or the user doesn't exist.
    """
    try:
        # Decode the JWT token and extract the user ID
        payload = jwt.decode(
            credentials.credentials,
            settings.auth_secret_key,
            algorithms=[settings.auth_algorithm],
        )
        # Make sure it's an access token (not a refresh token)
        if payload.get("type") != "access":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Ungültiger Token-Typ")
        user_id = int(payload["sub"])  # "sub" (subject) contains the user ID
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Ungültiger oder abgelaufener Token")

    # Look up the user in the database (must exist and be active)
    result = await db.execute(select(User).where(User.id == user_id, User.is_active.is_(True)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Benutzer nicht gefunden")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """
    Same as get_current_user, but also checks that the user is an admin.
    Use this for admin-only routes (e.g. user management, Docker controls).
    """
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Nur Administratoren haben Zugriff")
    return user
