"""
PostgreSQL database connection with SQLAlchemy Async.

This module sets up:
  1. An async database engine (connection pool to PostgreSQL)
  2. A session factory for creating database sessions
  3. A base class that all ORM models inherit from
  4. A FastAPI dependency that provides a DB session per request

How it works:
  - The engine manages a pool of connections to PostgreSQL.
  - async_session() creates a new session (like a "workspace" for DB operations).
  - get_db() is used as a FastAPI dependency: each API request gets its own session,
    which is automatically committed on success or rolled back on error.
"""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

# The engine holds a pool of database connections.
# pool_size = how many connections to keep open at all times.
# max_overflow = how many extra connections to allow when pool is full.
engine = create_async_engine(
    settings.db_async_url,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    echo=settings.db_echo_sql,  # if True, prints all SQL queries to the log
)

# Session factory — call async_session() to get a new database session.
# expire_on_commit=False means objects stay usable after commit (without re-querying).
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    """Base class for all ORM models. SQLAlchemy uses this to track all tables."""
    pass


async def get_db() -> AsyncSession:
    """
    FastAPI dependency that provides a database session.

    Usage in a route:
        @router.get("/items")
        async def list_items(db: AsyncSession = Depends(get_db)):
            result = await db.execute(select(Item))
            ...

    The session auto-commits when the request finishes successfully,
    or auto-rolls-back if an exception occurs.
    """
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
