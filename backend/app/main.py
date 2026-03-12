"""
Atlas RAG System - FastAPI Einstiegspunkt

Lädt die zentrale Konfiguration und startet alle API-Routen.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.database import engine, Base, async_session
from app.core.security import hash_password
from app.api.routes import auth, users, groups, collections, documents, chat
from app.api.routes import settings as settings_router

logger = logging.getLogger(__name__)


async def seed_admin_user():
    """Erstellt den Standard-Admin-Benutzer, falls keiner existiert."""
    from app.models.user import User

    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.username == settings.auth.default_admin_username)
        )
        if result.scalar_one_or_none():
            logger.info("Admin-Benutzer existiert bereits.")
            return

        admin = User(
            username=settings.auth.default_admin_username,
            email=f"{settings.auth.default_admin_username}@atlas.local",
            hashed_password=hash_password(settings.auth.default_admin_password),
            full_name="Administrator",
            is_admin=True,
            is_active=True,
        )
        session.add(admin)
        try:
            await session.commit()
            logger.info(f"Admin-Benutzer '{settings.auth.default_admin_username}' wurde erstellt.")
        except IntegrityError:
            await session.rollback()
            logger.info("Admin-Benutzer wurde bereits von einem anderen Worker erstellt.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup- und Shutdown-Logik."""
    # --- Startup ---
    logger.info("Atlas RAG System startet...")
    logger.info(f"LLM-Modell: {settings.llm.model}")
    logger.info(f"Embedding-Modell: {settings.embedding.model}")
    # Datenbank-Tabellen erstellen (nur bei Erststart, danach Alembic nutzen)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Fehlende Spalten hinzufügen (für bestehende Datenbanken ohne Alembic)
        await conn.execute(text(
            "ALTER TABLE collections ADD COLUMN IF NOT EXISTS context_text TEXT"
        ))

    # Admin-Benutzer anlegen, falls keiner existiert
    await seed_admin_user()

    logger.info("Atlas RAG System bereit.")
    yield
    # --- Shutdown ---
    logger.info("Atlas RAG System wird heruntergefahren...")
    await engine.dispose()


app = FastAPI(
    title="Atlas RAG System",
    description="Lokales Retrieval-Augmented Generation System für Firmendokumente",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS konfigurieren
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.server.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API-Routen registrieren
app.include_router(auth.router, prefix="/api/auth", tags=["Authentifizierung"])
app.include_router(users.router, prefix="/api/users", tags=["Benutzer"])
app.include_router(groups.router, prefix="/api/groups", tags=["Gruppen"])
app.include_router(collections.router, prefix="/api/collections", tags=["Collections"])
app.include_router(documents.router, prefix="/api", tags=["Dokumente"])
app.include_router(chat.router, prefix="/api", tags=["Chat"])
app.include_router(settings_router.router, prefix="/api/settings", tags=["Einstellungen"])


@app.get("/api/health")
async def health_check():
    """Gesundheitsprüfung für Monitoring."""
    return {"status": "healthy", "version": "0.1.0"}
