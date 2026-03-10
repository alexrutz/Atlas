"""
Atlas RAG System - FastAPI Einstiegspunkt

Lädt die zentrale Konfiguration und startet alle API-Routen.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import engine, Base
from app.api.routes import auth, users, groups, collections, documents, chat

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup- und Shutdown-Logik."""
    # --- Startup ---
    logger.info("Atlas RAG System startet...")
    logger.info(f"LLM-Modell: {settings.llm.model}")
    logger.info(f"Embedding-Modell: {settings.embedding.model}")
    logger.info(f"Context-Enrichment: {'aktiviert' if settings.context_enrichment.enabled else 'deaktiviert'}")

    # Datenbank-Tabellen erstellen (nur bei Erststart, danach Alembic nutzen)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

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


@app.get("/api/health")
async def health_check():
    """Gesundheitsprüfung für Monitoring."""
    return {"status": "healthy", "version": "0.1.0"}
