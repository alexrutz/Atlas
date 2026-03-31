"""
Security: JWT tokens and password hashing.

JWT (JSON Web Token) is used for authentication:
  - Access token: short-lived (default 8 hours), sent with every API request
  - Refresh token: long-lived (default 30 days), used to get a new access token

Passwords are hashed with bcrypt before storing in the database.
bcrypt automatically handles salting (random data added to prevent rainbow table attacks).
"""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings


def hash_password(password: str) -> str:
    """Hash a plaintext password for safe storage in the database."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check if a plaintext password matches the stored hash."""
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


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
