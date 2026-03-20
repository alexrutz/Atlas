"""
Atlas RAG System - FastAPI Einstiegspunkt

Lädt die zentrale Konfiguration und startet alle API-Routen.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import settings
from app.core.database import engine, Base, async_session
from app.core.security import hash_password
from app.api.routes import auth, users, groups, collections, documents, chat, docker
from app.api.routes import settings as settings_router
from app.services.llm_diagnostic import setup_diagnostic_logging

logger = logging.getLogger(__name__)

# Initialize diagnostic logging for LLM calls
setup_diagnostic_logging()


async def load_prompt_overrides():
    """Load prompt overrides from the database into the in-memory config."""
    from app.models.system_setting import SystemSetting

    prompt_keys = ["system_prompt", "enrichment_system_prompt", "free_chat_system_prompt"]
    async with async_session() as session:
        for key in prompt_keys:
            result = await session.execute(
                select(SystemSetting).where(SystemSetting.key == f"prompt_{key}")
            )
            setting = result.scalar_one_or_none()
            if setting and setting.value:
                setattr(settings.llm, key, setting.value)
                logger.info(f"Loaded prompt override for '{key}' from database.")


async def seed_admin_user():
    """Erstellt den Standard-Admin-Benutzer, falls keiner existiert."""
    from app.models.user import User

    async with async_session() as session:
        stmt = (
            pg_insert(User)
            .values(
                username=settings.auth.default_admin_username,
                email=f"{settings.auth.default_admin_username}@atlas.local",
                hashed_password=hash_password(settings.auth.default_admin_password),
                full_name="Administrator",
                is_admin=True,
                is_active=True,
            )
            .on_conflict_do_nothing()
            .returning(User.id)
        )
        result = await session.execute(stmt)
        await session.commit()
        if result.fetchone():
            logger.info(f"Admin-Benutzer '{settings.auth.default_admin_username}' wurde erstellt.")
        else:
            logger.info("Admin-Benutzer existiert bereits.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup- und Shutdown-Logik."""
    # --- Startup ---
    logger.info("Atlas RAG System startet...")
    logger.info(f"LLM: {settings.llm.model} @ {settings.llm.base_url}")
    logger.info(f"Embedding: {settings.embedding.model} @ {settings.embedding.base_url}")
    # Datenbank-Tabellen erstellen (nur bei Erststart, danach Alembic nutzen)
    # Advisory lock serialisiert parallele Worker, sodass nur einer die Tabellen anlegt.
    async with engine.begin() as conn:
        await conn.execute(text("SELECT pg_advisory_xact_lock(20250320)"))
        await conn.run_sync(Base.metadata.create_all)
        # Fehlende Spalten hinzufügen (für bestehende Datenbanken ohne Alembic)
        await conn.execute(text(
            "ALTER TABLE collections ADD COLUMN IF NOT EXISTS context_text TEXT"
        ))

    # Admin-Benutzer anlegen, falls keiner existiert
    await seed_admin_user()

    # Load prompt overrides from DB
    await load_prompt_overrides()

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
app.include_router(docker.router, prefix="/api/docker", tags=["Docker"])


@app.get("/api/health")
async def health_check():
    """Gesundheitsprüfung für Monitoring."""
    return {"status": "healthy", "version": "0.1.0"}
