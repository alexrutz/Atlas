"""ORM-Modell: Chunks mit Embeddings und Glossar."""

from datetime import datetime, timezone

from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.core.database import Base
from app.core.config import settings


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    enriched_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_header: Mapped[str | None] = mapped_column(String(500), nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    embedding = mapped_column(Vector(settings.vector.dimensions), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index"),
    )

    # Relationships
    document = relationship("Document", back_populates="chunks")


class GlossaryEntry(Base):
    __tablename__ = "glossary_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    collection_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("collections.id", ondelete="CASCADE"), nullable=True)
    term: Mapped[str] = mapped_column(String(200), nullable=False)
    definition: Mapped[str] = mapped_column(Text, nullable=False)
    abbreviation: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("collection_id", "term"),
    )

    # Relationships
    collection = relationship("Collection", back_populates="glossary_entries")
