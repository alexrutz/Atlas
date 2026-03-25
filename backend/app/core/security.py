"""
Sicherheit: JWT-Token und Passwort-Hashing.
"""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings


def hash_password(password: str) -> str:
    """Passwort hashen."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Passwort verifizieren."""
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


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
