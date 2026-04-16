"""
Authentication and authorization.

This module handles:
  1. Password hashing (bcrypt) - for safe storage in the database
  2. JWT tokens - access tokens (short-lived) and refresh tokens (long-lived)
  3. FastAPI dependencies - get_current_user and require_admin

How JWT auth works:
  1. User logs in via /api/auth/login -> gets an access token (JWT)
  2. Frontend sends the token in the "Authorization: Bearer <token>" header
  3. get_current_user() decodes the token, finds the user in the DB
  4. If the token is invalid or expired, the request is rejected (401)

Usage in a route:
    @router.get("/protected")
    async def protected_route(user: User = Depends(get_current_user)):
        # 'user' is the authenticated User object from the database
        ...
"""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.database import get_db
from app.models import User


# =============================================================================
# Password hashing
# =============================================================================

def hash_password(password: str) -> str:
    """Hash a plaintext password for safe storage in the database."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check if a plaintext password matches the stored hash."""
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


# =============================================================================
# JWT tokens
# =============================================================================

def create_access_token(user_id: int, is_admin: bool = False) -> str:
    """
    Create a short-lived JWT access token.

    The token contains:
      - sub: the user ID (as string)
      - is_admin: whether the user is an admin
      - exp: expiration timestamp
      - type: "access" (to distinguish from refresh tokens)
    """
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.auth_access_token_expire_minutes
    )
    payload = {
        "sub": str(user_id),
        "is_admin": is_admin,
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(payload, settings.auth_secret_key, algorithm=settings.auth_algorithm)


def create_refresh_token(user_id: int) -> str:
    """
    Create a long-lived JWT refresh token.
    Used to get a new access token without re-entering the password.
    """
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.auth_refresh_token_expire_days
    )
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "type": "refresh",
    }
    return jwt.encode(payload, settings.auth_secret_key, algorithm=settings.auth_algorithm)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token. Raises an exception if invalid or expired."""
    return jwt.decode(token, settings.auth_secret_key, algorithms=[settings.auth_algorithm])


# =============================================================================
# FastAPI dependencies
# =============================================================================

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
