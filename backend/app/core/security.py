"""
Sicherheit: JWT-Token und Passwort-Hashing.
"""

from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Passwort hashen."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Passwort verifizieren."""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(user_id: int, is_admin: bool = False) -> str:
    """Erstellt einen JWT Access Token."""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.auth.access_token_expire_minutes
    )
    payload = {
        "sub": str(user_id),
        "is_admin": is_admin,
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(payload, settings.auth.secret_key, algorithm=settings.auth.algorithm)


def create_refresh_token(user_id: int) -> str:
    """Erstellt einen JWT Refresh Token."""
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.auth.refresh_token_expire_days
    )
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "type": "refresh",
    }
    return jwt.encode(payload, settings.auth.secret_key, algorithm=settings.auth.algorithm)


def decode_token(token: str) -> dict:
    """Dekodiert und validiert einen JWT Token."""
    return jwt.decode(token, settings.auth.secret_key, algorithms=[settings.auth.algorithm])
