"""
Database models (ORM) - Each class maps to a PostgreSQL table.

The data model:
  - User: A person who can log in and ask questions
  - Group: A group of users (e.g. "Engineering", "HR")
  - UserGroup: Links users to groups (many-to-many)
  - Collection: A set of related documents (e.g. "Technical Manuals")
  - GroupCollectionAccess: Which groups can read/write which collections
  - Document: An uploaded file (PDF, DOCX, etc.)
  - Chunk: A small piece of text from a document (used for search)
  - ChunkEmbedding: The vector representation of a chunk (for similarity search)
  - Conversation: A chat session between a user and the system
  - Message: A single message in a conversation (user question or assistant answer)
  - UserSelectedCollection: Which collections a user has selected for searching
  - SystemSetting: Key-value store for global settings (e.g. prompts, context)
"""

from datetime import datetime, timezone

from sqlalchemy import (
    String, Boolean, DateTime, ForeignKey, Integer, BigInteger, Text,
    ARRAY, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.database import Base
from app.config import settings


# =============================================================================
# Users
# =============================================================================

class User(Base):
    __tablename__ = "users"
    __table_args__ = {}

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    groups = relationship("Group", secondary="user_groups", back_populates="members")
    conversations = relationship("Conversation", back_populates="user")


# =============================================================================
# Groups and membership
# =============================================================================

class UserGroup(Base):
    __tablename__ = "user_groups"
    __table_args__ = {}

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    group_id: Mapped[int] = mapped_column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Group(Base):
    __tablename__ = "groups"
    __table_args__ = {}

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    members = relationship("User", secondary="user_groups", back_populates="groups")
    collection_access = relationship("GroupCollectionAccess", back_populates="group")


# =============================================================================
# Collections and access control
# =============================================================================

class Collection(Base):
    __tablename__ = "collections"
    __table_args__ = {}

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(nullable=True)
    context_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    documents = relationship("Document", back_populates="collection", cascade="all, delete-orphan")
    group_access = relationship("GroupCollectionAccess", back_populates="collection", cascade="all, delete-orphan")


class GroupCollectionAccess(Base):
    __tablename__ = "group_collection_access"
    __table_args__ = {}

    group_id: Mapped[int] = mapped_column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True)
    collection_id: Mapped[int] = mapped_column(Integer, ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True)
    can_read: Mapped[bool] = mapped_column(Boolean, default=True)
    can_write: Mapped[bool] = mapped_column(Boolean, default=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    granted_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)

    group = relationship("Group", back_populates="collection_access")
    collection = relationship("Collection", back_populates="group_access")


# =============================================================================
# Documents
# =============================================================================

class Document(Base):
    __tablename__ = "documents"
    __table_args__ = {}

    id: Mapped[int] = mapped_column(primary_key=True)
    collection_id: Mapped[int] = mapped_column(Integer, ForeignKey("collections.id", ondelete="CASCADE"), nullable=False)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    original_name: Mapped[str] = mapped_column(String(500), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    processing_status: Mapped[str] = mapped_column(String(20), default="pending")
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)

    uploaded_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    collection = relationship("Collection", back_populates="documents")
    chunks = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")


# =============================================================================
# Chunks and embeddings
# =============================================================================

class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    section_header: Mapped[str | None] = mapped_column(String(500), nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    document = relationship("Document", back_populates="chunks")
    embeddings = relationship("ChunkEmbedding", back_populates="chunk", cascade="all, delete-orphan")


class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"
    __table_args__ = (
        UniqueConstraint("chunk_id", "model_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chunk_id: Mapped[int] = mapped_column(Integer, ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    embedding = mapped_column(Vector(settings.vector_dimensions), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    chunk = relationship("Chunk", back_populates="embeddings")


# =============================================================================
# Conversations and messages
# =============================================================================

class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = {}

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at")


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = {}

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    used_collections = mapped_column(ARRAY(Integer), default=list)
    source_chunks = mapped_column(ARRAY(Integer), default=list)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    conversation = relationship("Conversation", back_populates="messages")


class UserSelectedCollection(Base):
    __tablename__ = "user_selected_collections"
    __table_args__ = {}

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    collection_id: Mapped[int] = mapped_column(Integer, ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True)


# =============================================================================
# System settings
# =============================================================================

class SystemSetting(Base):
    __tablename__ = "system_settings"
    __table_args__ = {}

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
