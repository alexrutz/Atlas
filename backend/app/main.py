"""
Atlas RAG System - FastAPI Entry Point

Loads the central configuration and starts all API routes.
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

# PostgreSQL schemas used by the application
DB_SCHEMAS = ["iam", "content", "rag", "chat", "config"]


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
    """Create the default admin user if none exists."""
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
            logger.info(f"Admin user '{settings.auth.default_admin_username}' created.")
        else:
            logger.info("Admin user already exists.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    # --- Startup ---
    logger.info("Atlas RAG System starting...")
    logger.info(f"LLM: {settings.llm.model} @ {settings.llm.base_url}")
    logger.info(f"Embedding: {settings.embedding.model} @ {settings.embedding.base_url}")
    logger.info(f"VLM-OCR: {settings.vlm_ocr.model} @ {settings.vlm_ocr.base_url}")

    # Create schemas and tables
    # Advisory lock serialises parallel workers so only one creates the tables.
    async with engine.begin() as conn:
        await conn.execute(text("SELECT pg_advisory_xact_lock(20250320)"))

        # Ensure all schemas exist
        for schema in DB_SCHEMAS:
            await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))

        # Create all tables within their respective schemas
        await conn.run_sync(Base.metadata.create_all)

    # Seed admin user
    await seed_admin_user()

    # Load prompt overrides from DB
    await load_prompt_overrides()

    logger.info("Atlas RAG System ready.")
    yield
    # --- Shutdown ---
    logger.info("Atlas RAG System shutting down...")
    await engine.dispose()


app = FastAPI(
    title="Atlas RAG System",
    description="On-premises Retrieval-Augmented Generation system for enterprise documents",
    version="0.2.0",
    lifespan=lifespan,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.server.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(users.router, prefix="/api/users", tags=["Users"])
app.include_router(groups.router, prefix="/api/groups", tags=["Groups"])
app.include_router(collections.router, prefix="/api/collections", tags=["Collections"])
app.include_router(documents.router, prefix="/api", tags=["Documents"])
app.include_router(chat.router, prefix="/api", tags=["Chat"])
app.include_router(settings_router.router, prefix="/api/settings", tags=["Settings"])
app.include_router(docker.router, prefix="/api/docker", tags=["Docker"])


@app.get("/api/health")
async def health_check():
    """Health check for monitoring."""
    return {"status": "healthy", "version": "0.2.0"}
